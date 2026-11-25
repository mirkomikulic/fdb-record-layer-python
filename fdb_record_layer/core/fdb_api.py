"""Single place that selects the FoundationDB API version.

FDB only allows one API version per process, so every module in this package
calls :func:`ensure_api_version` instead of calling ``fdb.api_version`` itself.
If the application already selected a version, that choice is kept.
"""

from __future__ import annotations

import fdb

#: API version used by this package. Requires the FDB client library 7.4 or newer.
FDB_API_VERSION = 740


def ensure_api_version(version: int = FDB_API_VERSION) -> int:
    """Select the FDB API version unless one is already selected.

    Returns the API version that is active after the call.
    """
    if fdb.is_api_version_selected():
        return int(fdb.get_api_version())
    fdb.api_version(version)
    return version
