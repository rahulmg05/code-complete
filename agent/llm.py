import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=os.getenv("OPENROUTER_API_KEY"),
)
# Step 11 promotes this to models.json; a module-level constant is the first move.
MODEL = os.getenv("CODE_COMPLETE_MODEL", "anthropic/claude-sonnet-4.5")
MAX_TOKENS = 16384


@dataclass
class ToolCall:
  id: str
  name: str
  args: dict
  parse_error: str | None = None


@dataclass
class Turn:
  finish_reason: str
  message: dict
  tool_calls: list[ToolCall]
  note: str | None = None


def complete(messages, system_prompt=None, tools=None):
  wire = messages
  if system_prompt:
    wire = [{"role": "system", "content": system_prompt}] + messages

  response = client.chat.completions.create(
    model=MODEL,
    messages=wire,
    tools=tools or [],
    max_tokens=MAX_TOKENS,
  )

  choice = response.choices[0]
  msg = choice.message
  finish_reason = choice.finish_reason

  assistant = {"role": "assistant", "content": msg.content}
  if msg.tool_calls:
    assistant["tool_calls"] = [
      {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
      }
      for tc in msg.tool_calls
    ]

  if finish_reason in ("length", "content_filter"):
    note = (
      "Response truncated (hit max tokens); skipping tool calls if any"
      if finish_reason == "length"
      else "Response blocked by content filter"
    )
    return Turn(finish_reason, assistant, [], note)

  parsed_tool_calls = []
  for tc in msg.tool_calls or []:
    try:
      args = json.loads(tc.function.arguments)
    except json.decoder.JSONDecodeError as e:
      parsed_tool_calls.append(
        ToolCall(
          id=tc.id, name=tc.function.name, args={}, parse_error=f"invalid json args {e}"
        )
      )
      continue

    if isinstance(args, dict):
      parsed_tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))
    else:
      parsed_tool_calls.append(
        ToolCall(
          id=tc.id,
          name=tc.function.name,
          args={},
          parse_error=f"args not a dict {args}",
        )
      )

  return Turn(finish_reason, assistant, parsed_tool_calls, None)
