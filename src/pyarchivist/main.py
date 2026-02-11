"""CLI utilities for pyarchivist.

This module provides the top-level CLI `ArgumentParser` factory and wires
in subcommands from subpackages.
"""

from argparse import ArgumentParser
from functools import partial
from typing import Callable

from pyarchivist.meta import VERSION

from .Wikimedia_Commons import __name__ as Wikimedia_Commons_name
from .Wikimedia_Commons import __package__ as Wikimedia_Commons_package
from .Wikimedia_Commons.main import parser as Wikimedia_Commons_parser

__all__ = ("parser",)


def parser(parent: Callable[..., ArgumentParser] | None = None):
    """Return an ArgumentParser configured for the package CLI.

    If a `parent` callable is provided it will be used to construct the
    parser (useful when the command is embedded within another parser).
    """

    prog = __package__ or __name__

    parser = (ArgumentParser if parent is None else parent)(
        prog=f"python -m {prog}",
        description="archive data",
        add_help=True,
        allow_abbrev=False,
        exit_on_error=False,
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"{prog} v{VERSION}",
        help="print version and exit",
    )
    subparsers = parser.add_subparsers(
        required=True,
    )
    Wikimedia_Commons_parser(
        partial(
            subparsers.add_parser,
            (Wikimedia_Commons_package or Wikimedia_Commons_name).replace(
                f"{prog}.", ""
            ),
        )
    )
    return parser
