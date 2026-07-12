"""Regressionstest: alle Datei-Dialog-Filter müssen pywebviews strengem
parse_file_type genügen. Bindestriche in der Beschreibung (z.B.
'Audio-Dateien') werden von dessen Regex [\\w ]+ abgelehnt -> ValueError
beim create_file_dialog -> Dialog öffnet nicht (Bug 2026-07).
"""

import pytest
from webview.util import parse_file_type

from bort import app

FILTERS = [
    app.AUDIO_FILTER,
    app.JSON_FILTER,
    app.REVIEW_FILTER,
    app.GGML_FILTER,
    app.ALL_FILES_FILTER,
]


@pytest.mark.parametrize("file_filter", FILTERS)
def test_filter_is_accepted_by_pywebview(file_filter: str) -> None:
    # Wirft ValueError, wenn das Format ungültig ist.
    description, extensions = parse_file_type(file_filter)
    assert description
    assert extensions
