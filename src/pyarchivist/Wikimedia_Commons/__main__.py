"""Entry point for the `Wikimedia_Commons` subcommand.

This module is executed when `python -m pyarchivist.Wikimedia_Commons` is run.
It constructs the subcommand parser and invokes the selected action.
"""

from logging import INFO, basicConfig
from sys import argv

from asyncer import runnify

from .main import parser

__all__ = ("main",)


async def main() -> None:
    """Internal async entry point for the Wikimedia_Commons subcommand."""
    """Main entry point for the Wikimedia_Commons subcommand.

    This function is called when the module is executed as a script. It sets up
    logging, parses command-line arguments, and runs the selected action.

    This function is wrapped by the synchronous `main` function to allow
    asynchronous execution without requiring callers to use `anyio.run` directly."""
    basicConfig(level=INFO)
    entry = parser().parse_args(argv[1:])
    await entry.invoke(entry)


def __main__() -> None:
    """Synchronous command-line entrypoint exposed by the package."""
    runnify(main, backend_options={"use_uvloop": True})()


if __name__ == "__main__":
    __main__()
