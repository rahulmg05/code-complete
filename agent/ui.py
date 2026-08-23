import json
import pathlib
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.processors import (
  BeforeInput,
  Processor,
  Transformation,
  explode_text_fragments,
)
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.markup import escape
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

AGENT_NAME = "code-complete"
USER_NAME = "keyboard-gremlin"

# One place to restyle the whole surface. Every call site below uses these names
# rather than raw colours, so a light-terminal variant is a second dict, not a
# sweep through the file. "dim" is deliberately not a key here — it is a builtin
# rich attribute and a theme entry of that name would shadow it everywhere.
THEME = Theme(
  {
    "agent": "#22d3ee",
    "user": "#a3e635",
    "tool": "#fbbf24",
    "ok": "#4ade80",
    "error": "#f87171",
    "muted": "grey50",
    "faint": "grey37",
    "rule": "#3f3f46",
  }
)
console = Console(theme=THEME)

AGENT_STYLE = "agent"
USER_STYLE = "user"
TOOL_STYLE = "tool"
OK_STYLE = "ok"
ERROR_STYLE = "error"
DIM = "muted"

MAX_ARG_CHARS = 90
MAX_RESULT_LINES = 8

# how long a call has to run before the spinner starts showing a clock
SPINNER_QUIET = 1.0

# The two turns are told apart by *shape*, not colour: a user turn is boxed, an
# agent turn hangs off a marker at column zero with its body indented under it.
# That reads at a glance in a scrollback, survives a monochrome terminal, and
# survives colour-blindness.
AGENT_MARK = "✻"
BODY_INDENT = 2

# what you type against, before the line is redrawn as its box
PROMPT = "❯ "
_PROMPT_STYLE = Style.from_dict({"prompt": "#a3e635 bold"})

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


WORDMARK = r"""
  ___         _         ___                _     _
 / __|___  __| |___ ___/ __|___ _ __  _ __| |___| |_ ___
| (__/ _ \/ _` / -_)___ (__/ _ \ '  \| '_ \ / -_)  _/ -_)
 \___\___/\__,_\___|   \___\___/_|_|_| .__/_\___|\__\___|
                                     |_|
"""

# the ramp the wordmark is painted with, left edge to right edge
GRADIENT_FROM = (0x22, 0xD3, 0xEE)
GRADIENT_TO = (0xA7, 0x8B, 0xFA)

# below this the panel wraps and the wordmark breaks apart, so we drop to a line
MIN_BANNER_WIDTH = 66


def _gradient(block, start=GRADIENT_FROM, end=GRADIENT_TO):
  """Paint a text block with a horizontal ramp.

  Colour is a function of *column*, not of position in the string, so the ramp
  stays vertically aligned and the five rows read as one object.
  """
  lines = block.strip("\n").splitlines()
  width = max((len(line) for line in lines), default=1)
  out = Text()
  for i, line in enumerate(lines):
    for col, char in enumerate(line):
      r, g, b = (
        round(a + (b_ - a) * col / max(width - 1, 1)) for a, b_ in zip(start, end)
      )
      out.append(char, style=f"#{r:02x}{g:02x}{b:02x}")
    if i < len(lines) - 1:
      out.append("\n")
  return out


def _short_cwd():
  """$HOME collapsed to ~ — an absolute path is mostly noise you already know."""
  cwd = pathlib.Path.cwd()
  try:
    return f"~/{cwd.relative_to(pathlib.Path.home())}"
  except ValueError:
    return str(cwd)


def _branch():
  """Read .git/HEAD directly; a subprocess is too much for one banner line."""
  head = pathlib.Path(".git") / "HEAD"
  try:
    ref = head.read_text(encoding="utf-8").strip()
  except OSError:
    return None
  if ref.startswith("ref: refs/heads/"):
    return ref.removeprefix("ref: refs/heads/")
  return ref[:7] or None  # detached HEAD: show the short sha


def _meta_rows():
  """The facts worth confirming at a glance: which model, where, which branch."""
  from agent.llm import MODEL  # imported late: agent.llm builds a client on import

  rows = [("model", MODEL), ("cwd", _short_cwd())]
  branch = _branch()
  if branch:
    rows.append(("branch", branch))

  out = Text()
  for i, (label, value) in enumerate(rows):
    out.append(f"{label:<7}", style="faint")
    out.append(value, style="muted")
    if i < len(rows) - 1:
      out.append("\n")
  return out


def print_banner():
  console.print()
  if console.width < MIN_BANNER_WIDTH:
    # narrow terminal: same facts, cropped rather than wrapped — a path that
    # spills onto a second ragged line looks broken, an elided one does not
    head = Text("  ", style="")
    head.append(AGENT_NAME, style="bold agent")
    head.append("  ")
    head.append(_short_cwd(), style="muted")
    console.print(head, no_wrap=True, overflow="ellipsis")
    console.print("  [faint]ctrl-c or ctrl-d to quit[/]")
    return

  console.print(
    Panel(
      Group(_gradient(WORDMARK), Text(), _meta_rows()),
      box=box.ROUNDED,
      border_style="rule",
      padding=(1, 3),
      subtitle="[faint]ctrl-c or ctrl-d to quit[/]",
      subtitle_align="right",
      expand=False,
    )
  )


def get_input():
  """Type against a plain chevron; on submit the line is erased and redrawn as
  the same panel print_user_message() replays.

  prompt-toolkit cannot draw rich's rounded border, and reimplementing it as a
  nested layout would leave two box definitions to keep in sync. Erasing and
  redrawing costs one repaint and guarantees live scrollback and a resumed
  transcript are the same bytes.
  """

  def accept(buff):
    app.exit(result=buff.text)
    return False  # erase it; the panel below replaces it

  buf = Buffer(history=_history, accept_handler=accept, multiline=False)
  app = Application(
    layout=Layout(
      Window(
        BufferControl(
          buffer=buf,
          # order matters: the block reads cursor_position_col against the raw
          # fragments, so the prefix has to be prepended after it has painted
          input_processors=[_BlinkingBlock(), BeforeInput(PROMPT, "class:prompt")],
        ),
        always_hide_cursor=True,  # the real cursor is replaced by ours
        wrap_lines=True,
      )
    ),
    key_bindings=_kb,
    style=_PROMPT_STYLE,
    refresh_interval=BLINK_SECONDS / 2,  # redraw often enough to see the toggle
    full_screen=False,
  )
  text = app.run()
  if text.strip():  # a blank line is discarded by the caller, so don't box it
    print_user_message(text)
  return text


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


def _highlight(text, path):
  """A read result is source, so render it as source. background_color="default"
  keeps the terminal's own background instead of stamping a dark block into the
  scrollback, which is what makes it sit under the elbow rather than fight it.
  """
  return Padding(
    Syntax(
      text,
      Syntax.guess_lexer(path, code=text),
      theme="ansi_dark",
      background_color="default",
      word_wrap=True,
    ),
    (0, 0, 0, 4),
  )


def print_tool_result(result, elapsed=None, name=None, args=None):
  """Indented under its call, with a tree elbow instead of a border.

  `name`/`args` are optional: the generic text rendering below is always correct,
  and knowing the tool only ever buys a nicer shape (highlighted source, a single
  acknowledgement line). Callers that don't have them still get sane output.
  """
  failed = _result_failed(result)
  style = ERROR_STYLE if failed else DIM
  lines = str(result).splitlines() or [""]

  # sub-100ms timings are noise on file ops; they only matter for shell/builds
  show_time = elapsed is not None and elapsed >= 0.1
  stamp = f"  [faint]{elapsed:.1f}s[/]" if show_time else ""

  if not failed:
    # a write/edit result is one sentence of confirmation; a body would be filler
    if name in ("write", "edit"):
      console.print(f"[{DIM}]  ⎿ [/][{OK_STYLE}]{escape(lines[0])}[/]{stamp}")
      return

    path = (args or {}).get("path")
    if name == "read" and isinstance(path, str):
      shown = lines[:MAX_RESULT_LINES]
      hidden = len(lines) - len(shown)
      console.print(f"[{DIM}]  ⎿ read {len(lines)} lines from {escape(path)}[/]{stamp}")
      console.print(_highlight("\n".join(shown), path))
      if hidden:
        console.print(f"[{DIM}]    … +{hidden} more lines[/]")
      return

  hidden = max(len(lines) - MAX_RESULT_LINES, 0)
  shown = lines[:MAX_RESULT_LINES]
  for i, line in enumerate(shown):
    elbow = "  ⎿ " if i == 0 else "    "
    suffix = stamp if i == 0 else ""
    console.print(f"[{DIM}]{elbow}[/][{style}]{escape(line)}[/]{suffix}")
  if hidden:
    console.print(f"[{DIM}]    … +{hidden} more lines[/]")


def print_user_message(text):
  """A user turn, boxed. Text() rather than a markup string: a transcript is
  history, and a message containing [brackets] must not be parsed as markup.

  The leading blank lives here, not in get_input(), so a replayed turn is spaced
  exactly like a live one instead of losing it.
  """
  console.print()
  console.print(
    Panel(
      Text(str(text)),
      box=box.ROUNDED,
      border_style=USER_STYLE,
      padding=(0, 1),
      title=f"[bold {USER_STYLE}]{USER_NAME}[/]",
      title_align="left",
      expand=False,
    )
  )


def print_agent_message(text):
  """Marker at column zero, prose indented beneath it — the inverse silhouette of
  a user turn, and the same shape tool calls already use.
  """
  console.print()
  console.print(f"[{AGENT_STYLE}]{AGENT_MARK}[/] [bold {AGENT_STYLE}]{AGENT_NAME}[/]")
  if not text:
    console.print(f"  [{DIM}](no answer)[/]")
    return
  console.print(Padding(Markdown(text), (0, 0, 0, BODY_INDENT)))


def print_note(note):
  console.print(f"[{DIM} italic]{escape(str(note))}[/]")


def _when(mtime):
  """Timestamps you scan rather than parse: today and yesterday get named."""
  dt = datetime.fromtimestamp(mtime)
  days = (date.today() - dt.date()).days
  if days == 0:
    return f"today {dt:%H:%M}"
  if days == 1:
    return f"yesterday {dt:%H:%M}"
  return f"{dt:%b %d %H:%M}"


def print_sessions(records):
  """One row per session, newest first. Previews are untrusted text, so they go
  through _clip_chars — it escapes markup and flattens newlines in one call.
  """
  table = Table(box=None, pad_edge=False)
  table.add_column("#", style=DIM, justify="right")
  table.add_column("when", style=DIM)
  table.add_column("msgs", justify="right")
  table.add_column("first message")

  for i, r in enumerate(records, 1):
    if r.preview:
      preview = _clip_chars(r.preview, 60)
    else:
      # a session can hold messages and still have no user line to quote, so
      # "empty" and "nothing to preview" are different things worth saying
      preview = f"[{DIM}]({'empty' if r.count == 0 else 'no preview'})[/]"
    table.add_row(str(i), _when(r.mtime), str(r.count), preview)

  console.print()
  console.print(table)


def ask_session(count):
  """Pick a row. Returns a 0-based index, or None if the user backed out."""
  while True:
    try:
      raw = console.input(
        f"\n  [{DIM}]which session? (1-{count}, blank to cancel)[/] "
      ).strip()
    except KeyboardInterrupt, EOFError:
      print()
      return None

    if not raw:
      return None
    try:
      n = int(raw)
    except ValueError:
      print_note("  enter a number")
      continue
    if 1 <= n <= count:
      return n - 1
    print_note(f"  pick between 1 and {count}")


def _replay_args(raw):
  """Tool args reach disk as a JSON string (llm.py:57), not a dict — turn them
  back so _call_summary can pick out the primary arg. Unparseable args still
  render rather than raising: a transcript is history, not input to validate.
  """
  if isinstance(raw, dict):
    return raw
  try:
    args = json.loads(raw or "{}")
  except (json.JSONDecodeError, TypeError):
    return {"arguments": raw}
  return args if isinstance(args, dict) else {"arguments": raw}


def print_transcript(messages):
  """Re-render a loaded session so a resume reads like the scrollback it replaces.

  Results are re-paired with their calls by tool_call_id: on the wire one
  assistant message declares every call and each result is a separate message,
  but run_turn printed them interleaved, one call and its result at a time.
  """
  results = {
    m.get("tool_call_id"): m.get("content") or ""
    for m in messages
    if m.get("role") == "tool" and m.get("tool_call_id")
  }
  shown = set()

  for msg in messages:
    role = msg.get("role")
    if role == "user":
      print_user_message(msg.get("content") or "")
    elif role == "assistant":
      # usually None on tool-call turns, and run_turn never printed it live;
      # show it when it is there rather than silently dropping real output
      if msg.get("content"):
        print_agent_message(msg["content"])
      for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        name = fn.get("name") or "?"
        args = _replay_args(fn.get("arguments"))
        print_tool_call(name, args)
        tid = tc.get("id")
        if tid in results:
          print_tool_result(results[tid], name=name, args=args)
          shown.add(tid)
        else:
          # no result on disk: the crash landed mid-dispatch (sub-step 4)
          print_note("  ⎿ interrupted — no result recorded")
    elif role == "tool":
      # only reached by a result whose call is missing or already consumed
      if msg.get("tool_call_id") not in shown:
        print_tool_result(msg.get("content") or "")


@contextmanager
def thinking(label="thinking..."):
  """Spinner that starts counting once the wait stops feeling instant.

  A bare spinner looks the same at two seconds and at ninety; the counter is
  what separates "working" from "hung". It only appears after SPINNER_QUIET so
  fast tool calls don't flash a number on their way past.
  """
  started = time.monotonic()
  done = threading.Event()

  with console.status(f"[{DIM}]{label}[/]", spinner="dots") as status:

    def tick():
      while not done.wait(0.2):
        seconds = time.monotonic() - started
        if seconds >= SPINNER_QUIET:
          status.update(f"[{DIM}]{label}[/] [faint]{seconds:.0f}s[/]")

    ticker = threading.Thread(target=tick, daemon=True)
    ticker.start()
    try:
      yield
    finally:
      done.set()
      ticker.join(timeout=1)
