import argparse
import pathlib

from agent import session, ui
from agent.loop import run_turn
from agent.prompts import SYSTEM_PROMPT


def args_parse():
  p = argparse.ArgumentParser(prog="agent")
  g = p.add_mutually_exclusive_group()
  g.add_argument(
    "--resume",
    nargs="?",
    const=session.Resume.LATEST,
    default=None,
    metavar="PATH",
    help="resume a session; latest if none is provided",
  )
  g.add_argument(
    "--list-sessions",
    action="store_true",
    help="pick a session to resume from a list",
  )

  return p.parse_args()


def resolve_session(args):
  """Which session to resume, if any — the three entry paths converge here so
  main() keeps exactly one load/use block.
  """
  if args.list_sessions:
    records = session.listing()
    if not records:
      raise SystemExit("no sessions yet")
    ui.print_sessions(records)
    choice = ui.ask_session(len(records))
    if choice is None:
      raise SystemExit(0)  # backing out is not an error, and must start nothing
    return records[choice].path

  if args.resume is None:
    return None

  if args.resume == session.Resume.LATEST:
    resumed = session.latest()
    if resumed is None:
      raise SystemExit("Latest session not found")
    return resumed

  resumed = pathlib.Path(args.resume).expanduser()
  if not resumed.exists():
    raise SystemExit(f"session {resumed} not found")
  return resumed


def main():
  args = args_parse()

  messages = []
  resumed = resolve_session(args)
  if resumed:
    messages = session.load(resumed)
    session.use(resumed)

  ui.print_banner()
  if resumed:
    ui.print_note(f"resumed {resumed.name} — {len(messages)} messages")
    ui.print_transcript(messages)

  while True:
    try:
      line = ui.get_input().strip()
    except EOFError, KeyboardInterrupt:
      print()
      break

    if not line:
      continue

    session.add(messages, {"role": "user", "content": line})
    answer = run_turn(messages, SYSTEM_PROMPT)
    ui.print_agent_message(answer)


if __name__ == "__main__":
  main()
