"""Entry point for the `Wikimedia_Commons` subcommand.

This module is executed when `python -m pyarchivist.Wikimedia_Commons` is run.
It constructs the subcommand parser and invokes the selected action.
"""

from asyncio import run
from logging import INFO, basicConfig
from sys import argv

from .main import parser

__all__ = ()

if __name__ == "__main__":
    basicConfig(level=INFO)
    entry = parser().parse_args(argv[1:])
    run(entry.invoke(entry))
