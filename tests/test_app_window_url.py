"""main() muss die Seite als file://-URI laden: mit blankem Pfad serviert
pywebview über seinen internen HTTP-Server, und eine http-Seite darf keine
file://-Audio-URLs laden (Player komplett tot, MEDIA_ERR_SRC_NOT_SUPPORTED)."""

from unittest.mock import patch

import bort.app as app


def test_main_passes_file_uri_to_create_window() -> None:
    with (
        patch.object(app.webview, "create_window") as create_window,
        patch.object(app.webview, "start"),
        patch.object(app.Bridge, "attach_window"),
    ):
        app.main()
    url = create_window.call_args.kwargs.get("url") or create_window.call_args.args[1]
    assert url.startswith("file://"), url
    assert url.endswith("/index.html"), url
