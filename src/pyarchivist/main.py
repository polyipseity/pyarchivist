"""CLI utilities for pyarchivist.

This module provides the top-level CLI `ArgumentParser` factory and wires
in subcommands from subpackages.
"""

from argparse import ArgumentParser as _ArgParser
from functools import partial as _part
from typing import Callable as _Call

from . import VERSION as _VER
from .Wikimedia_Commons import (
    __name__ as _wm_c_name,
)
from .Wikimedia_Commons import (
    __package__ as _wm_c_package,
)
from .Wikimedia_Commons import (
    main as _wm_c_main,
)

__all__ = ("parser",)


def parser(parent: _Call[..., _ArgParser] | None = None):
    """Return an ArgumentParser configured for the package CLI.

    If a `parent` callable is provided it will be used to construct the
    parser (useful when the command is embedded within another parser).
    """

    prog = __package__ or __name__

    parser = (_ArgParser if parent is None else parent)(
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
        version=f"{prog} v{_VER}",
        help="print version and exit",
    )
    subparsers = parser.add_subparsers(
        required=True,
    )
    _wm_c_main.parser(
        _part(
            subparsers.add_parser, (_wm_c_package or _wm_c_name).replace(f"{prog}.", "")
        )
    )
    return parser
