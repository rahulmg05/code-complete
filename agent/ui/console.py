from prompt_toolkit import PromptSession
from rich.console import Console

session = PromptSession(multiline=True, prompt_continuation="")
console = Console()
