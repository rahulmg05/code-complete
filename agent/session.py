import enum
import json
import pathlib
import time
from dataclasses import dataclass

SESSIONS_DIR = pathlib.Path.home() / ".code-complete" / "sessions"
_current = SESSIONS_DIR / f"{time.time_ns()}.jsonl"


class Resume(enum.Enum):
  LATEST = enum.auto()


@dataclass
class SessionInfo:
  path: pathlib.Path
  mtime: float
  count: int
  preview: str


def current():
  """The session file we're currently appending to."""
  return _current


def use(existing):
  """Point the logger at an existing session file. Used by --resume."""
  global _current
  _current = pathlib.Path(existing)


def log_message(message):
  """Append one message dict as a single JSON line."""
  _current.parent.mkdir(parents=True, exist_ok=True)
  with open(_current, "a", encoding="utf-8") as f:
    f.write(json.dumps(message) + "\n")


def add(messages, msg):
  """Append to the in-memory list AND the on-disk log. Always use this."""
  messages.append(msg)
  log_message(msg)
  return msg


def latest():
  """Path of the most recently written session, or None if there are none."""
  files = list(SESSIONS_DIR.glob("*.jsonl"))
  if not files:
    return None
  return max(files, key=lambda p: p.stat().st_mtime)


def load(path):
  """Read a session file back into a list of message dicts."""
  messages = []
  lines = path.read_text(encoding="utf-8").splitlines()
  for i, line in enumerate(lines):
    if not line.strip():
      continue
    try:
      messages.append(json.loads(line))
    except json.JSONDecodeError as e:
      raise SystemExit(f"corrupt session {path}, line {i + 1}: {e}")
  return messages


def summarize(path):
  """Cheap description of a session: how many messages, and how it started.

  Tolerates corrupt lines instead of raising like load() — a damaged session is
  the one you most want to see in the menu.
  """
  # errors="replace" is insurance, not a live fix: log_message uses json.dumps
  # defaults, so ensure_ascii=True escapes non-ASCII and sessions are pure ASCII.
  # Drop that default and a torn line can split a character, raising
  # UnicodeDecodeError here — which is not a JSONDecodeError and would not be
  # caught below.
  lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
  count = sum(1 for line in lines if line.strip())

  preview = ""
  for line in lines:
    if not line.strip():
      continue
    try:
      msg = json.loads(line)
    except json.JSONDecodeError:
      continue
    if isinstance(msg, dict) and msg.get("role") == "user":
      preview = msg.get("content") or ""  # content is legitimately None elsewhere
      break

  return SessionInfo(path, path.stat().st_mtime, count, preview)


def listing():
  """Every session, newest first — same mtime ordering as latest(), so that
  row 1 and a bare --resume can never disagree.
  """
  if not SESSIONS_DIR.exists():
    return []
  paths = sorted(
    SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
  )
  return [summarize(p) for p in paths]
