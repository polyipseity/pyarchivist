"""Module entry-point for command-line invocation.

This module is executed when the package is run with `python -m pyarchivist`.
It configures basic logging and executes the selected CLI subcommand.
"""

from asyncio import run
from logging import INFO, basicConfig
from sys import argv

from .main import parser

__all__ = ("main",)


def main() -> None:
    """Main entry point for the pyarchivist command-line interface.

    This function is called when the module is executed as a script. It sets up
    logging, parses command-line arguments, and runs the selected action.
    """
    basicConfig(level=INFO)
    entry = parser().parse_args(argv[1:])
    run(entry.invoke(entry))


if __name__ == "__main__":
    main()
