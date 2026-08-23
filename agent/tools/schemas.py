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
