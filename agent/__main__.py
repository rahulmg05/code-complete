import os
import subprocess

from agent.llm import complete

READ_TOOL = {
  "type": "function",
  "function": {
    "name": "read",
    "description": "Read a UTF-8 text file and return its contents",
    "parameters": {
      "type": "object",
      "properties": {"path": {"type": "string"}},
      "required": ["path"],
    },
  },
}

WRITE_TOOL = {
  "type": "function",
  "function": {
    "name": "write",
    "description": "Create or overwrite a UTF-8 text file",
    "parameters": {
      "type": "object",
      "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
      "required": ["path", "content"],
    },
  },
}

SHELL_TOOL = {
  "type": "function",
  "function": {
    "name": "shell",
    "description": (
      "Run a one-shot bash command from the working directory and return its "
      "combined stdout+stderr and exit code. No state persists between calls."
    ),
    "parameters": {
      "type": "object",
      "properties": {
        "command": {"type": "string"},
        "timeout": {
          "type": "integer",
          "description": "Seconds before the command is killed (default 30, max 600).",
        },
      },
      "required": ["command"],
    },
  },
}

EDIT_TOOL = {
  "type": "function",
  "function": {
    "name": "edit",
    "description": "Replace one exact, unique substring in a file you've already read.",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {"type": "string"},
        "old": {
          "type": "string",
          "description": "Exact text to find, whitespace included; must occur exactly once.",
        },
        "new": {
          "type": "string",
          "description": "Replacement text",
        },
      },
      "required": ["path", "old", "new"],
    },
  },
}

TOOLS = [READ_TOOL, WRITE_TOOL, SHELL_TOOL, EDIT_TOOL]
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
  return data.decode("utf-8", errors="replace")


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
  return f"exit {proc.returncode}\n{proc.stdout[:10000]}"


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


def dispatch(name, args):
  """Run a tool that is passed in as an argument.
  Returns unknown tool error if tool not found.
  """
  if name == "read":
    path = args.get("path")
    if not isinstance(path, str):
      return f"Path must be a string; got {path}"

    return read_file(path)
  elif name == "write":
    path, content = args.get("path"), args.get("content")
    if not isinstance(path, str) or not isinstance(content, str):
      return "write requires string path and content"

    return write_file(path, content)
  elif name == "shell":
    command = args.get("command")
    if not isinstance(command, str):
      return "shell requires a string 'command'"
    try:
      timeout = int(args.get("timeout", 30))
    except TypeError, ValueError:
      return "shell 'timeout' must be a number of seconds"

    return run_shell(command, timeout)
  elif name == "edit":
    path, old, new = args.get("path"), args.get("old"), args.get("new")
    if (
      not isinstance(path, str) or not isinstance(old, str) or not isinstance(new, str)
    ):
      return "edit requires string path and string old and string new"
    return edit_file(path, old, new)

  return f"Error: Tool name {name} not found"


def run_turn(messages, system_prompt):
  while True:
    turn = complete(messages, system_prompt, TOOLS)
    messages.append(turn.message)
    if turn.note:
      print(f"{turn.note}")

    if not turn.tool_calls:
      return turn.message["content"]

    for tool_call in turn.tool_calls:
      if tool_call.parse_error:
        result = f"Error: {tool_call.parse_error}"
      else:
        result = dispatch(tool_call.name, tool_call.args)

      messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})


def main():
  system_prompt = (
    "You are a coding agent working in the current directory. \n"
    "You have these tools:\n"
    "read(path) returns the UTF-8 contents of \n "
    "a text file. Use it to inspect files before answering questions about them.\n"
    "write(path, content) creates or overwrites a file; you must read an \n"
    "existing file before overwriting it.\n"
    "shell(command, timeout=30) runs a single bash command from the working \n"
    "directory; it is one-shot, so no cwd, environment, or virtualenv \n"
    "persists between calls — chain dependent steps in one command with &&.\n"
    "Use it to explore and navigate the project (ls, grep -rn, find, cat) \n"
    "rather than expecting dedicated search tools. Raise the timeout for slow\n"
    "operations like builds, tests, or docker, which may produce no output until\n"
    "they finish."
  )
  messages = []
  print("agent ready (ctrl-c or ctrl-d to quit)")
  while True:
    try:
      line = input("you> ").strip()
    except EOFError, KeyboardInterrupt:
      print()
      break

    if not line:
      continue

    messages.append({"role": "user", "content": line})
    answer = run_turn(messages, system_prompt)
    print(
      f"code-complete>\n{answer}"
      if answer
      else "\ncode-complete> Agent did not return anything"
    )


if __name__ == "__main__":
  main()
