"""
Write a Repl class that takes user input and writes the agent output
The repl class is composed of Agent object which holds the conversation
Repl uses console to print the messages and uses prompt toolkit to accept
user messages
"""

from agent.llm.agent_loop import AgentLoop
from agent.ui.console import console, session


def run():
  agent_loop = AgentLoop()
  while True:
    try:
      text = session.prompt("keyboard-gremlin >>> ")
      response = agent_loop.run(text)
      console.print(f"code-complete >>> {response}")
    except KeyboardInterrupt:
      break
    except EOFError:
      console.print("\n[dim]Goodbye[/dim] \N{WAVING HAND SIGN}")
      break
    except Exception as e:
      console.print(f"\nError: {e}")
