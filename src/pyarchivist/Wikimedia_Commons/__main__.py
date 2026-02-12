"""Entry point for the `Wikimedia_Commons` subcommand.

This module is executed when `python -m pyarchivist.Wikimedia_Commons` is run.
It constructs the subcommand parser and invokes the selected action.
"""

from asyncio import run
from logging import INFO, basicConfig
from sys import argv

from .main import parser

__all__ = ("main",)


def main() -> None:
    """Main entry point for the Wikimedia_Commons subcommand.

    This function is called when the module is executed as a script. It sets up
    logging, parses command-line arguments, and runs the selected action.
    """
    basicConfig(level=INFO)
    entry = parser().parse_args(argv[1:])
    run(entry.invoke(entry))


if __name__ == "__main__":
    main()
