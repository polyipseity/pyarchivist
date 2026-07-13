"""CLI entry point for the `Wikimedia_Commons` subcommand.

This module contains the CLI binding: argument parser, the `main(args)`
translation function that converts ``ArchiveResult`` → ``ExitCode``, and
the ``__main__()`` entry point that calls ``exit()``.
"""

from argparse import ONE_OR_MORE, ArgumentParser
from collections.abc import Callable
from functools import wraps
from logging import INFO, basicConfig
from sys import argv, exit
from typing import Protocol

from anyio import Path
from asyncer import runnify

from pyarchivist.meta import VERSION
from pyarchivist.types import ArchiveResult, Args, ExitCode

from .main import archive

"""Public symbols exported by this module."""
__all__ = ("main", "parser")


async def main(args: Args) -> ExitCode:
    """Run the archival flow and return an ``ExitCode``.

    Calls :func:`archive` with the given *args* and translates the
    returned :class:`ArchiveResult` into an :class:`ExitCode` for CLI use.
    Does **not** call ``exit()``.
    """
    result = await archive(args)
    return _archive_result_to_exit_code(result)


def _archive_result_to_exit_code(result: ArchiveResult) -> ExitCode:
    """Translate an ``ArchiveResult`` into a combined ``ExitCode``."""
    ec = ExitCode(0)
    for error in result.errors:
        if error.phase == "query":
            ec |= ExitCode.QUERY_ERROR_PARTIAL
        elif error.phase == "fetch":
            ec |= ExitCode.FETCH_ERROR_PARTIAL
        elif error.phase == "index":
            ec |= ExitCode.INDEX_ERROR
        else:
            ec |= ExitCode.GENERIC_ERROR
    if result.errors:
        ec |= ExitCode.GENERIC_ERROR
    if result.downloaded == 0 and not ec:
        ec |= ExitCode.GENERIC_ERROR
    return ec


class _ParserNamespace(Protocol):
    """Typed namespace returned by the Wikimedia subparser."""

    dest: Path
    index: Path | None
    inputs: list[str]
    ignore_individual_errors: bool


def parser(parent: Callable[..., ArgumentParser] | None = None):
    """Return an argparse parser configured for the Wikimedia Commons subcommand.

    When embedded, *parent* can be a callable that produces an ``ArgumentParser``.
    """

    prog = __package__ or __name__

    parser = (ArgumentParser if parent is None else parent)(
        prog=f"python -m {prog}",
        description="archive data from Wikimedia Commons",
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
    parser.add_argument(
        "-d",
        "--dest",
        action="store",
        type=Path,
        required=True,
        help="destination directory",
    )
    parser.add_argument(
        "-i",
        "--index",
        action="store",
        type=Path,
        help="Markdown-based index file",
    )
    parser.add_argument(
        "--ignore-individual-errors",
        action="store_true",
        default=False,
        help="ignore errors from individual files",
        dest="ignore_individual_errors",
    )
    parser.add_argument(
        "inputs",
        action="store",
        nargs=ONE_OR_MORE,
        type=str,
        help="sequence of input(s) to read",
    )

    @wraps(main)
    async def invoke(args: _ParserNamespace) -> ExitCode:
        """Adapter converting an argparse namespace into ``Args`` and calling
        :func:`main`."""
        return await main(
            Args(
                inputs=tuple(args.inputs),
                dest=args.dest,
                index=args.index,
                ignore_individual_errors=args.ignore_individual_errors,
            )
        )

    parser.set_defaults(invoke=invoke)
    return parser


async def _cli_entry() -> None:
    """Internal CLI entry — parse ``argv``, run, and exit."""
    basicConfig(level=INFO)
    entry = parser().parse_args(argv[1:])
    ec = await entry.invoke(entry)
    exit(ec)


def __main__() -> None:
    """Synchronous command-line entrypoint exposed by the package."""
    runnify(_cli_entry, backend_options={"use_uvloop": True})()


if __name__ == "__main__":
    __main__()
