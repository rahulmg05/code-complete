import enum
import json
import pathlib
import time

SESSIONS_DIR = pathlib.Path.home() / ".code-complete" / "sessions"
_current = SESSIONS_DIR / f"{time.time_ns()}.jsonl"


class Resume(enum.Enum):
  LATEST = enum.auto()


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
      if i == len(lines) - 1:
        break  # torn last line: a crash mid-write. Drop it and carry on.
      raise SystemExit(f"corrupt session {path}, line {i + 1}: {e}")
  return messages
