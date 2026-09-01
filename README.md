# Code Complete

A simple coding agent with just four tools.

Code Complete reads and understands your codebase, fixes bugs, writes new
features, and scaffolds new projects that can be grown into production-ready
code — all from a terminal REPL.

## Why four tools

The whole agent is a loop. The model gets a system prompt, four tools, and a
running transcript; everything else it composes out of them. There is no
dedicated search tool, no test runner, no git integration — the model reaches
for `shell` and writes the `grep`, `pytest`, or `git` invocation itself.

That keeps the codebase learning-sized: this is an agent you can read end to
end in an afternoon, not a framework.

## The four tools

| Tool    | What it does                                                    | Guardrails                                                                                     |
| ------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `read`  | Returns the full UTF-8 contents of a text file                    | Refuses binaries; truncates past 20k characters so one huge file cannot crowd out the transcript, and points the model at `sed -n` for reading a specific line range instead |
| `write` | Creates a file, or replaces an existing one in full               | Refuses paths outside the working directory; refuses to overwrite a file it has not read first, so it cannot clobber contents it only assumed |
| `edit`  | Replaces one exact substring in a file                            | The match must be unique — an ambiguous or missing match is refused and the file left untouched, rather than landing as a silent wrong edit |
| `shell` | Runs a one-shot bash command, returns exit code + stdout/stderr   | No state persists between calls, so a `cd` or an export must be chained into the same command; 30s default timeout capped at 600s; output truncated at 10k characters |

## Getting started

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Create a `.env` in the project root:

```
OPENROUTER_API_KEY=your-key-here
CODE_COMPLETE_MODEL=anthropic/claude-sonnet-4.5   # optional, this is the default
```

Requests go to [OpenRouter](https://openrouter.ai/) over its OpenAI-compatible
API, so any model OpenRouter serves with tool-calling support will work.

Then start the agent from the directory you want it to work in:

```bash
uv run python -m agent
```

## A note on safety

`shell` runs real commands on your machine, with no sandbox and no confirmation
prompt. File writes are confined to the working directory; shell commands are
not.

Run Code Complete in a directory you are happy for it to change, and ideally
one that is under version control with nothing uncommitted you would miss.
