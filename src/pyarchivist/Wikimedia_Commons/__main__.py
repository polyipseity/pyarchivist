"""Entry point for the `Wikimedia_Commons` subcommand.

This module is executed when `python -m pyarchivist.Wikimedia_Commons` is run.
It constructs the subcommand parser and invokes the selected action.
"""

from asyncio import run as _run
from logging import INFO, basicConfig
from sys import argv as _argv

from .main import parser as _parser

__all__ = ()

if __name__ == "__main__":
    basicConfig(level=INFO)
    entry = _parser().parse_args(_argv[1:])
    _run(entry.invoke(entry))
