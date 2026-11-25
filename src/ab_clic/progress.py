"""Progress stages for preparing a CLIC import."""

from collections.abc import Callable
from enum import IntEnum


class PreparationStep(IntEnum):
    REQUEST_EXPORT = 1
    WAIT_FOR_EXPORT = 2
    DOWNLOAD_PACKAGE = 3
    READ_DESCRIPTIONS = 4
    CHECK_PACKAGE = 5
    MATCH_TECHNOSPHERE = 6
    MATCH_BIOSPHERE = 7
    CHECK_LINKS = 8


ProgressCallback = Callable[[PreparationStep, str], None]


def ignore_progress(step: PreparationStep, message: str) -> None:
    """Allow callers to prepare an import without a progress display."""
