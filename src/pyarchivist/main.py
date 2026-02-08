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


def parser(parent: _Call[..., _ArgParser] | None = None):
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
