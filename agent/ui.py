import os
import pathlib
import time
from contextlib import contextmanager

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.processors import (
  Processor,
  Transformation,
  explode_text_fragments,
)
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape

console = Console()

AGENT_NAME = "code-complete"
USER_NAME = "keyboard-gremlin"

AGENT_STYLE = "cyan"
USER_STYLE = "green"
TOOL_STYLE = "yellow"
OK_STYLE = "green"
ERROR_STYLE = "red"
DIM = "grey50"

MAX_ARG_CHARS = 90
MAX_RESULT_LINES = 8

# seconds the block stays on, then off; we draw it ourselves so the terminal's
# own cursor-blink setting (which many emulators refuse to hand over) can't win
BLINK_SECONDS = 0.5

# the tool arg worth showing inline; everything else stays folded away
PRIMARY_ARG = {"read": "path", "write": "path", "edit": "path", "shell": "command"}

_history_path = pathlib.Path.home() / ".code-complete" / "history"
_history_path.parent.mkdir(parents=True, exist_ok=True)
_history = FileHistory(str(_history_path))

_kb = KeyBindings()


@_kb.add("c-c")
def _interrupt(event):
  event.app.exit(exception=KeyboardInterrupt)


@_kb.add("c-d")
def _eof(event):
  event.app.exit(exception=EOFError)


class _BlinkingBlock(Processor):
  """Paint our own cursor: a reverse-video block that toggles on a timer."""

  def apply_transformation(self, ti):
    fragments = explode_text_fragments(ti.fragments)
    lit = int(time.monotonic() / BLINK_SECONDS) % 2 == 0
    if lit and ti.lineno == ti.document.cursor_position_row:
      col = ti.document.cursor_position_col
      if col < len(fragments):
        style, text = fragments[col][0], fragments[col][1]
        fragments[col] = (f"{style} reverse", text)
      else:
        fragments.append(("reverse", " "))  # cursor sits past the last character
    return Transformation(fragments)


def print_banner():
  console.print()
  console.print(
    f"  [bold {AGENT_STYLE}]{AGENT_NAME}[/]  [{DIM}]{escape(os.getcwd())}[/]"
  )
  console.print(f"  [{DIM}]ctrl-c or ctrl-d to quit[/]")


def get_input():
  """Name on its own line, input on the next — mirrors the agent's output."""
  console.print(f"\n[bold {USER_STYLE}]{USER_NAME}[/]")

  def accept(buff):
    app.exit(result=buff.text)
    return True  # keep_text: leave what was typed visible in the scrollback

  buf = Buffer(history=_history, accept_handler=accept, multiline=False)
  app = Application(
    layout=Layout(
      Window(
        BufferControl(buffer=buf, input_processors=[_BlinkingBlock()]),
        always_hide_cursor=True,  # the real cursor is replaced by ours
        wrap_lines=True,
      )
    ),
    key_bindings=_kb,
    refresh_interval=BLINK_SECONDS / 2,  # redraw often enough to see the toggle
    full_screen=False,
  )
  return app.run()


def _clip_chars(value, limit=MAX_ARG_CHARS):
  """Keep an arg to one line — file contents and diffs can be enormous."""
  text = " ".join(str(value).split())
  if len(text) <= limit:
    return escape(text)
  return f"{escape(text[:limit])}[{DIM}]… +{len(text) - limit} chars[/]"


def _call_summary(name, args):
  """Show only the arg that identifies the call; the result line says the rest."""
  key = PRIMARY_ARG.get(name)
  if key in args:
    return _clip_chars(args[key])
  return ", ".join(f"{escape(k)}={_clip_chars(v, 40)}" for k, v in args.items())


def print_tool_call(name, args):
  summary = _call_summary(name, args)
  console.print(f"\n[{TOOL_STYLE}]●[/] [bold]{escape(name)}[/] [{DIM}]{summary}[/]")


def _result_failed(result):
  text = str(result)
  if text.startswith("refused") or text.startswith("Error"):
    return True
  # shell results lead with "exit N" — anything but 0 is a failure
  first = text.split("\n", 1)[0]
  return first.startswith("exit ") and first != "exit 0"


def print_tool_result(result, elapsed=None):
  """Indented under its call, with a tree elbow instead of a border."""
  failed = _result_failed(result)
  style = ERROR_STYLE if failed else DIM
  lines = str(result).splitlines() or [""]
  hidden = max(len(lines) - MAX_RESULT_LINES, 0)
  shown = lines[:MAX_RESULT_LINES]

  # sub-100ms timings are noise on file ops; they only matter for shell/builds
  show_time = elapsed is not None and elapsed >= 0.1
  stamp = f"  [{DIM}]{elapsed:.1f}s[/]" if show_time else ""

  for i, line in enumerate(shown):
    elbow = "  ⎿ " if i == 0 else "    "
    suffix = stamp if i == 0 else ""
    console.print(f"[{DIM}]{elbow}[/][{style}]{escape(line)}[/]{suffix}")
  if hidden:
    console.print(f"[{DIM}]    … +{hidden} more lines[/]")


def print_agent_message(text):
  """Labelled like the user prompt, then plain markdown so prose reads as prose."""
  console.print(f"\n[bold {AGENT_STYLE}]{AGENT_NAME}[/]")
  if not text:
    console.print(f"[{DIM}](no answer)[/]")
    return
  console.print(Markdown(text))


def print_note(note):
  console.print(f"[{DIM} italic]{escape(str(note))}[/]")


@contextmanager
def thinking(label="thinking..."):
  with console.status(f"[{DIM}]{label}[/]", spinner="dots"):
    yield
