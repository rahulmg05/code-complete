import time

from agent import session, ui
from agent.llm import complete
from agent.tools.handlers import edit_file, read_file, run_shell, write_file
from agent.tools.schemas import TOOLS


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
    with ui.thinking("thinking..."):
      turn = complete(messages, system_prompt, TOOLS)
    session.add(messages, turn.message)
    if turn.note:
      ui.print_note(turn.note)

    if not turn.tool_calls:
      return turn.message["content"]

    for tool_call in turn.tool_calls:
      if tool_call.parse_error:
        result = f"Error: {tool_call.parse_error}"
      else:
        ui.print_tool_call(tool_call.name, tool_call.args)
        started = time.monotonic()
        with ui.thinking(f"running {tool_call.name}..."):
          result = dispatch(tool_call.name, tool_call.args)
        ui.print_tool_result(
          result,
          elapsed=time.monotonic() - started,
          name=tool_call.name,
          args=tool_call.args,
        )

      session.add(
        messages, {"role": "tool", "tool_call_id": tool_call.id, "content": result}
      )
