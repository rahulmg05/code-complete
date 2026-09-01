# Tool schemas sent to the model on every turn. Descriptions are the only
# instructions the model gets about a tool, so they state the preconditions
# the handlers enforce (read-before-write, unique match, truncation limits).
TOOL_SCHEMAS = [
  {
    "type": "function",
    "function": {
      "name": "read_file",
      "description": (
        "Read a UTF-8 text file and return its full contents. Use this before "
        "editing or overwriting a file. Only text files and source code can be "
        "read; binary files are refused. Long files are truncated, and the "
        "truncation notice says how to read a specific line range with the shell "
        "tool. Returns an error message if the file is missing or unreadable."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string",
            "description": (
              "Path to the file, absolute or relative to the working directory."
            ),
          }
        },
        "required": ["path"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "write_file",
      "description": (
        "Create a new text file, or replace an existing one with the given "
        "content in full. This overwrites; it never appends, so include the "
        "entire intended file content. Prefer the edit tool for changing part of "
        "an existing file. Writes outside the working directory are refused, and "
        "overwriting an existing file is refused unless it was read first. "
        "Returns a success message with the number of bytes written, or an error."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string",
            "description": (
              "Path to the file, absolute or relative to the working directory. "
              "Parent directories are created if needed."
            ),
          },
          "content": {
            "type": "string",
            "description": "The complete new content of the file.",
          },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "edit_file",
      "description": (
        "Replace one exact substring in a file that has already been read with "
        "this session's read tool. The old content must appear exactly once in "
        "the file; if it is missing or appears more than once, the edit is "
        "refused and nothing is changed, so include enough surrounding lines to "
        "make the match unique. Returns a success message with the resulting "
        "file size, or an error."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string",
            "description": (
              "Path to the file, absolute or relative to the working directory."
            ),
          },
          "old_content": {
            "type": "string",
            "description": (
              "The exact text to replace, copied verbatim from the file "
              "including indentation and newlines. Must occur exactly once."
            ),
          },
          "new_content": {
            "type": "string",
            "description": (
              "The replacement text. Use an empty string to delete the matched text."
            ),
          },
        },
        "required": ["path", "old_content", "new_content"],
        "additionalProperties": False,
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "run_shell_command",
      "description": (
        "Run a one-shot bash command from the working directory and return its "
        "exit code together with the combined stdout and stderr. No state "
        "persists between calls, so a cd or an exported variable is forgotten on "
        "the next call; chain such steps in a single command instead. Long "
        "output is truncated. Use this for searching, listing, running tests and "
        "git, and for reading a line range with sed -n 'START,ENDp' FILE."
      ),
      "parameters": {
        "type": "object",
        "properties": {
          "command": {
            "type": "string",
            "description": "The bash command to execute.",
          },
          "timeout": {
            "type": "integer",
            "description": (
              "Seconds before the command is killed. Defaults to 30, capped at 600."
            ),
          },
        },
        "required": ["command"],
        "additionalProperties": False,
      },
    },
  },
]
