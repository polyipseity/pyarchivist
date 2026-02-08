from logging import getLogger as _getLogger
from sys import version as _ver
from typing import Literal as _Lit
from typing import TypedDict as _TDict
from typing import final as _fin


@_fin
class _OpenOptions(_TDict):
    encoding: str
    errors: _Lit[
        "strict",
        "ignore",
        "replace",
        "surrogateescape",
        "xmlcharrefreplace",
        "backslashreplace",
        "namereplace",
    ]
    newline: None | _Lit["", "\n", "\r", "\r\n"]


# update `pyproject.toml`
AUTHORS = (
    {
        "name": "William So",
        "email": "polyipseity@gmail.com",
    },
)
NAME = "pyarchivist"
VERSION = "2.0.1"

LOGGER = _getLogger(NAME)
OPEN_TEXT_OPTIONS: _OpenOptions = {
    "encoding": "UTF-8",
    "errors": "strict",
    "newline": None,
}
USER_AGENT = f"{NAME}/{VERSION} ({AUTHORS[0]['email']}) Python/{_ver}"
