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
TOOLS = [READ_TOOL]


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

  return data.decode("utf-8", errors="replace")


def dispatch(name, args):
  """Run a tool that is passed in as an argument.
  Returns unknown tool error if tool not found.
  """
  if name == "read":
    path = args.get("path")
    if not isinstance(path, str):
      return f"Path must be a string; got {path}"

    return read_file(args.get("path"))

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
    "You have one tool: read(path) returns the UTF-8 contents of \n "
    "a text file. Use it to inspect files before answering questions \n"
    "about them."
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
