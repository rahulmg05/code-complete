# Tool output lands in the transcript and is resent every turn, so cap it.
import os
import subprocess

MAX_READ_CHARS = 20000
MAX_SHELL_CHARS = 10000
WORKDIR = os.getcwd()
WORKROOT = os.path.realpath(WORKDIR)
_read_paths = set()


def abspath(path):
  """Return the absolute path to a file."""
  return os.path.realpath(os.path.join(WORKROOT, path))


def in_workspace(full):
  """Return True if the path is in a workspace."""
  return WORKROOT == full or full.startswith(WORKROOT + os.sep)


def read_file(path):
  """Read a UTF-8 text file and return its contents.
  Refuse binaries; decode leniently; no line numbers.
  """
  try:
    with open(path, "rb") as f:
      data = f.read()
  except FileNotFoundError:
    return f"File not found {path}"
  except OSError:
    return f"Error: File {path} cannot be read"

  if b"\x00" in data:
    return f"{path} is a binary file; refusing to read"

  _read_paths.add(abspath(path))
  text = data.decode("utf-8", errors="replace")
  if len(text) > MAX_READ_CHARS:
    return (
      f"{text[:MAX_READ_CHARS]}\n\n"
      f"[truncated: showed the first {MAX_READ_CHARS} of {len(text)} characters. "
      f"Read a specific range with shell: sed -n 'START,ENDp' {path}]"
    )
  return text


def run_shell(command, timeout=30):
  """Run a shell command and return its output."""
  try:
    proc = subprocess.run(
      ["bash", "--norc", "--noprofile", "-c", command],
      cwd=WORKDIR,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True,
      timeout=min(timeout, 600),
    )
  except subprocess.TimeoutExpired:
    return f"timed out after {timeout}s"
  return f"exit {proc.returncode}\n{proc.stdout[:MAX_SHELL_CHARS]}"


def write_file(path, content):
  """Create and/or write a UTF-8 text file."""
  full = abspath(path)
  if not in_workspace(full):
    return f"refused: cannot write to files {path} outside of the working directory"
  if os.path.exists(full) and full not in _read_paths:
    return f"refused: {full} already exists; please read before overwriting"
  os.makedirs(os.path.dirname(full), exist_ok=True)
  with open(full, "w", encoding="utf-8") as f:
    f.write(content)
  _read_paths.add(full)

  return f"successfully wrote to {path}; bytes written {len(content)}"


def edit_file(path, old, new):
  """Edit a UTF-8 text file. Replace the old content with new"""
  full = abspath(path)
  if full not in _read_paths:
    return f"refused: please read before editing {path}"
  if not os.path.exists(full):
    return f"refused: {full} does not exist"
  with open(full, encoding="utf-8") as f:
    text = f.read()
  n = text.count(old)

  if n == 0:
    return "refused: no match found to edit the file"
  if n > 1:
    return (
      f"refused: found {n} matches - add surrounding context so that match is unique"
    )

  new_text = text.replace(old, new)
  with open(full, "w", encoding="utf-8") as f:
    f.write(new_text)

  return f"successfully edited {path}; bytes written {len(new_text)}"
