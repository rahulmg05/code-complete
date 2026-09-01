from prompt_toolkit import PromptSession
from rich.console import Console

from agent.ui.repl import run

session = PromptSession(multiline=True, prompt_continuation="")
console = Console()

OCEAN_BLUE = "#0077be"

# Solid block-letter banner, generated once via:
#   pyfiglet.figlet_format("code - complete", font="ansi_shadow", width=200)
# and pasted here as a plain string, so the agent has no runtime
# dependency on pyfiglet.
BANNER = r"""
 ██████╗ ██████╗ ██████╗ ███████╗           ██████╗ ██████╗ ███╗   ███╗██████╗ ██╗     ███████╗████████╗███████╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝          ██╔════╝██╔═══██╗████╗ ████║██╔══██╗██║     ██╔════╝╚══██╔══╝██╔════╝
██║     ██║   ██║██║  ██║█████╗    █████╗  ██║     ██║   ██║██╔████╔██║██████╔╝██║     █████╗     ██║   █████╗  
██║     ██║   ██║██║  ██║██╔══╝    ╚════╝  ██║     ██║   ██║██║╚██╔╝██║██╔═══╝ ██║     ██╔══╝     ██║   ██╔══╝  
╚██████╗╚██████╔╝██████╔╝███████╗          ╚██████╗╚██████╔╝██║ ╚═╝ ██║██║     ███████╗███████╗   ██║   ███████╗
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝           ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝   ╚═╝   ╚══════╝
"""  # noqa: E501

if __name__ == "__main__":
  run()
