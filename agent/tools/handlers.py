"""File and shell tools the model can call.

Every handler returns a string that goes into the transcript verbatim, so
failures are phrased for the model, not for a log. Expected failures raise
ToolError, which the loop turns into that string; anything else is a bug and
propagates.
"""

import subprocess
from pathlib import Path

MAX_READ_CHARS = 20_000
MAX_OUTPUT_CHARS = 20_000
MAX_TIMEOUT = 300
WORKROOT = Path.cwd()

# Paths whose contents the model has seen this session. Overwrites and edits
# are refused for anything not in here, so it cannot destroy what it never read.
_read_paths = set()


class ToolError(Exception):
  """A failure the model should see as the tool's result."""


def _resolve(path):
  """Return the absolute path, refusing anything outside the working directory."""
  if not isinstance(path, str):
    raise ToolError(
      f"refused: the file path {path} is not a string, it is {type(path).__name__}"
    )

  full = (WORKROOT / path).resolve()
  if not full.is_relative_to(WORKROOT):
    raise ToolError(
      f"refused: file path {path} is outside the working directory {WORKROOT}."
    )
  return full


def _read_text(full, path):
  """Return the file's contents as text, or raise a ToolError saying why not."""
  try:
    return full.read_text(encoding="utf-8")
  except FileNotFoundError:
    raise ToolError(f"error: file {path} does not exist")
  except IsADirectoryError:
    raise ToolError(f"error: file {path} is a directory")
  except PermissionError:
    raise ToolError(f"error: no permission to read file {path}")
  except UnicodeDecodeError as e:
    raise ToolError(f"error: file {path} is not utf-8 encoded, error {e}")
  except OSError as e:
    raise ToolError(f"error: file {path} cannot be read, error: {e}")


def read_file(path):
  """Read a UTF-8 text file and return its contents.

  Refuses paths outside the working directory and files that aren't valid
  UTF-8 text.
  """
  full = _resolve(path)
  text = _read_text(full, path)
  _read_paths.add(full)

  if not text:
    return f"file {path} is empty"

  if len(text) > MAX_READ_CHARS:
    return (
      f"{text[:MAX_READ_CHARS]}\n\n"
      f"[truncated: showed the first {MAX_READ_CHARS} of {len(text)} characters. "
      f"Read a specific range with the shell tool: sed -n 'START,ENDp' {path}]"
    )

  return text


def write_file(path, content):
  """Create a file, or replace an existing one in full.

  Overwriting is refused unless the file was read first this session, so the
  model cannot destroy content it has never seen.
  """
  if not isinstance(content, str):
    raise ToolError(
      f"refused: the content for file {path} is not a string, "
      f"it is {type(content).__name__}"
    )

  full = _resolve(path)
  if full.exists() and full not in _read_paths:
    raise ToolError(f"error: file {path} must be read before overwriting")

  try:
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
  except IsADirectoryError:
    raise ToolError(f"error: file {path} is a directory")
  except PermissionError:
    raise ToolError(f"error: no permission to write file {path}")
  except OSError as e:
    raise ToolError(f"error: file {path} cannot be written, error: {e}")

  # The model has now seen this content, so a later edit is allowed.
  _read_paths.add(full)

  return f"success: file {path} written"


def edit_file(path, old_content, new_content):
  """Replace one exact, unique substring in a file that was read first."""
  if not isinstance(old_content, str) or not isinstance(new_content, str):
    raise ToolError(
      f"refused: the content for file {path} is not a string, "
      f"new content type {type(new_content).__name__}, "
      f"old content type {type(old_content).__name__}"
    )

  if not old_content:
    raise ToolError("refused: old_content is empty; give the exact text to replace")

  if new_content == old_content:
    raise ToolError(
      "refused: old and new content that must replace the old one is the same"
    )

  full = _resolve(path)
  if full not in _read_paths:
    raise ToolError(f"refused: file {path} is not read; please read before editing.")

  # Read fresh: the file may have changed since, and the match count has to
  # describe what is about to be overwritten.
  text = _read_text(full, path)

  count = text.count(old_content)
  if count == 0:
    raise ToolError(f"refused: old content not found in {path}")
  if count > 1:
    raise ToolError(
      "there is more than one occurrence of the content to be replaced;"
      "add surrounding text so that match is unique"
    )

  updated = text.replace(old_content, new_content)
  try:
    full.write_text(updated, encoding="utf-8")
  except OSError as e:
    raise ToolError(f"error: {path} cannot be written: {e}")

  return (
    f"success: file {path} edited with new content, "
    f"bytes written {len(updated.encode('utf-8'))} bytes"
  )


def _truncate(stream, name):
  """Return the stream's text, capped, with a notice when it was cut."""
  if len(stream) <= MAX_OUTPUT_CHARS:
    return stream
  return (
    f"{stream[:MAX_OUTPUT_CHARS]}\n"
    f"[truncated: showed the first {MAX_OUTPUT_CHARS} of {len(stream)} "
    f"characters of {name}]"
  )


def _decoded(raw):
  """Return a stream as text.

  TimeoutExpired carries the raw buffer undecoded even when the call asked for
  text mode, so what it hands back is bytes, unlike CompletedProcess.
  """
  if isinstance(raw, bytes):
    return raw.decode("utf-8", errors="replace")
  return raw or ""


def _format_result(returncode, stdout, stderr):
  """Render a finished command as the string the model sees."""
  parts = [f"exit code: {returncode}"]
  if stdout:
    parts.append(f"stdout:\n{_truncate(stdout, 'stdout')}")
  if stderr:
    parts.append(f"stderr:\n{_truncate(stderr, 'stderr')}")

  # A silent success is still a result. Returning "" would reach the model as
  # an empty tool message, which reads like a broken tool.
  if not stdout and not stderr:
    parts.append("(no output)")

  return "\n\n".join(parts)


def run_shell_command(command, timeout=30):
  """Run a shell command in the working directory and report what it did.

  A non-zero exit code is not an error here: the command ran, and the code is
  part of the answer. ToolError is reserved for commands that could not run at
  all, or that had to be killed.
  """
  if not isinstance(command, str):
    raise ToolError(
      f"refused: the command is not a string, it is {type(command).__name__}"
    )

  if not command.strip():
    raise ToolError("refused: the command is empty")

  # bool is a subclass of int, so True would otherwise pass as one second.
  if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
    raise ToolError(f"refused: timeout must be a positive whole number, got {timeout}")

  # Clamped rather than refused: refusing costs a round trip to learn a limit
  # the model cannot see.
  timeout = min(timeout, MAX_TIMEOUT)

  try:
    result = subprocess.run(
      command,
      # The model writes shell syntax -- pipes, redirects, globs, && -- so the
      # string goes to a shell rather than being split into an argv list.
      shell=True,
      cwd=WORKROOT,
      capture_output=True,
      # The command already ran, so decoding must never be what fails:
      # undecodable bytes are replaced instead of raising.
      text=True,
      encoding="utf-8",
      errors="replace",
      # Nothing will ever type at this process. Without DEVNULL an editor or a
      # bare `cat` blocks until the timeout instead of exiting at once.
      stdin=subprocess.DEVNULL,
      timeout=timeout,
    )
  except subprocess.TimeoutExpired as e:
    # Whatever was printed before the kill is often the diagnosis, so it is
    # reported rather than dropped.
    partial = _format_result("killed", _decoded(e.stdout), _decoded(e.stderr))
    raise ToolError(
      f"error: command timed out after {timeout} seconds and was killed\n\n{partial}"
    )
  except OSError as e:
    raise ToolError(f"error: command could not be started, error: {e}")

  return _format_result(result.returncode, result.stdout, result.stderr)


TOOLS_REGISTRY = {
  "read_file": read_file,
  "edit_file": edit_file,
  "write_file": write_file,
  "run_shell_command": run_shell_command,
}
