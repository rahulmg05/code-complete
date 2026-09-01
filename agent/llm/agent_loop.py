"""The agentic loop: drives a conversation with the model until it stops.

The model is stateless, so the whole conversation is re-sent on every request.
`AgentLoop.messages` is that conversation, and it only ever grows: a user turn,
then alternating assistant messages and tool results until the model answers
without asking for another tool.

Talks to OpenRouter's chat-completions endpoint, which is OpenAI-compatible.
"""

import inspect
import json
import os
from collections.abc import Callable
from typing import NamedTuple

import requests
from dotenv import load_dotenv

from agent.llm.prompts import SYSTEM_PROMPT
from agent.tools.handlers import TOOLS_REGISTRY, ToolError
from agent.tools.schemas import TOOL_SCHEMAS

load_dotenv()
API_KEY = (os.getenv("OPENROUTER_API_KEY") or "").strip()
URL = "https://openrouter.ai/api/v1/chat/completions"
HEADERS = {
  "Authorization": f"Bearer {API_KEY}",
  "Content-Type": "application/json",
}
TEMPERATURE = 0.1
REQUESTS_TIMEOUT = 90


class InvalidToolCall(Exception):
  """The model sent a tool call that cannot be executed.

  The message is sent back to the model verbatim, so it should say what was
  wrong in terms the model can act on.
  """


class ToolCall(NamedTuple):
  """A tool call that is ready to invoke: the handler and its keyword args."""

  fn: Callable
  args: dict


def _valid_tool_call(tool_call):
  """Return a runnable ToolCall, or raise InvalidToolCall explaining why not."""
  if not tool_call.get("function"):
    raise InvalidToolCall(f"tool calls can be functions only: {tool_call}")

  name = tool_call.get("function").get("name")
  raw_args = tool_call.get("function").get("arguments") or "{}"
  if not name:
    raise InvalidToolCall(f"empty function name: {tool_call}")

  fn = TOOLS_REGISTRY.get(name)
  if not fn:
    raise InvalidToolCall(f"this tool does not exist: {name}")

  try:
    fn_args = json.loads(raw_args)
  except json.JSONDecodeError as e:
    raise InvalidToolCall(
      f"invalid args - {raw_args} must be a valid json string"
    ) from e

  if not isinstance(fn_args, dict):
    raise InvalidToolCall(
      f"arguments - {raw_args} must be a valid json object, "
      f"got {type(fn_args).__name__}"
    )

  try:
    inspect.signature(fn).bind(**fn_args)
  except TypeError as e:
    raise InvalidToolCall(f"invalid args {fn_args} for tool {name}: {e}") from e

  return ToolCall(fn=fn, args=fn_args)


def _get_choice(response):
  """Return the first choice of a completion, guaranteed to have a message.

  Returns the whole choice rather than just the message, because
  `finish_reason` is a sibling of `message` on the choice, not a field inside
  it. Raises RuntimeError on a malformed response: that is an infrastructure
  failure the model cannot fix, so it must not be fed back into the
  conversation.
  """
  choices = response.get("choices") or []
  if not choices:
    raise RuntimeError(f"response message is invalid, has no choices: {response}")
  choice = choices[0]
  if not choice.get("message"):
    raise RuntimeError(f"response message is invalid, has no choice: {response}")

  return choice


class AgentLoop:
  """One conversation with the model, including its tool calls.

  An instance holds the conversation for a whole session: `run` is called once
  per user turn and appends to the same `messages` list, so the model sees
  everything that came before. `tokens_used` accumulates `total_tokens` across
  every request, which counts the re-sent history each time and so tracks
  billed spend rather than conversation size.
  """

  def __init__(self, model, max_iterations=100):
    self.model = model or os.getenv("CODE_COMPLETE_MODEL")
    self.max_iterations = max_iterations
    self.tokens_used = 0
    self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if not API_KEY:
      raise RuntimeError("OPENROUTER_API_KEY is required (add it to .env)")
    if not self.model:
      raise RuntimeError("error: model is empty, pass it or set it in .env")

  def run(self, user_prompt):
    """Run one user turn to completion and return the model's reply as text.

    Each iteration is one request: the model either answers, which ends the
    turn, or asks for tools, which are run and their results appended before
    going round again. A failing tool is not an error here -- the failure is
    reported back as the tool's result so the model can adapt.

    Always returns a string, including for the give-up cases (truncated
    response, content filter, iteration limit). Raises only when the request
    itself fails, which `repl` reports to the user.
    """
    self.messages.append({"role": "user", "content": user_prompt})

    for _ in range(self.max_iterations):
      response = self._call_llm()

      self.tokens_used += (response.get("usage") or {}).get("total_tokens", 0)
      choice = _get_choice(response)

      finish_reason = choice.get("finish_reason")
      if finish_reason == "length":
        return "response truncated: the model ran out of output space"
      if finish_reason == "content_filter":
        return "response blocked by the provider's content filter"

      message = choice["message"]
      tool_calls = message.get("tool_calls")
      content = message.get("content")

      self.messages.append(message)
      if not tool_calls:
        return content or "(no response)"

      for tool_call in tool_calls:
        try:
          call = _valid_tool_call(tool_call)
        except InvalidToolCall as e:
          self._add_tool_result(tool_call.get("id"), f"invalid tool call: {e}")
          continue

        try:
          tool_response = str(call.fn(**call.args))
          self._add_tool_result(tool_call.get("id"), tool_response)
        except ToolError as e:
          # An expected failure the tool phrased for the model: pass it through
          # as the result, not as an exception.
          self._add_tool_result(tool_call.get("id"), str(e))
        except Exception as e:
          self._add_tool_result(
            tool_call.get("id"), f"error running tool call, exception: {e}"
          )

    return f"iteration limit: {self.max_iterations} reached"

  def _call_llm(self):
    """Send the conversation and return the parsed completion payload.

    OpenRouter reports rate limits and upstream provider failures as an
    `error` object in the body of an HTTP 200, so checking the status code
    alone is not enough. Raises RuntimeError for every failure; the caller
    gets a usable payload or nothing.
    """
    response = requests.post(
      url=URL,
      headers=HEADERS,
      json={
        "model": self.model,
        "messages": self.messages,
        "tools": TOOL_SCHEMAS,
        "temperature": TEMPERATURE,
      },
      timeout=REQUESTS_TIMEOUT,
    )

    if response.status_code != 200:
      raise RuntimeError(f"{response.status_code}: {response.text}")

    try:
      payload = response.json()
    except ValueError:
      raise RuntimeError("response is not a a valid json")

    if "error" in payload:
      raise RuntimeError(f"error: call to openrouter failed: {payload.get('error')}")

    return payload

  def _add_tool_result(self, tool_call_id, content):
    self.messages.append(
      {"role": "tool", "content": content, "tool_call_id": tool_call_id}
    )
