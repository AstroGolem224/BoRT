"""Regressionstest: Ordner-Dialoge dürfen KEINEN Datei-Filter bekommen.

Ein '*.*'-Filter auf einem GTK SELECT_FOLDER-Dialog führt dazu, dass
get_filenames() leer zurückkommt, solange der Nutzer nicht explizit einen
Unterordner anklickt -> der aktuell geöffnete Ordner ist nicht wählbar
(Bug 2026-07: 'nur den übergeordneten Ordner wählbar'). Datei-Dialoge
behalten ihre Filter.
"""

from bort.app import Bridge


class _RecordingWindow:
    def __init__(self):
        self.file_types = None

    def create_file_dialog(self, dialog_type, directory, allow_multiple, file_types):
        self.file_types = file_types
        # gültiger Rückgabewert (Ordner bzw. Datei)
        return (directory,)


def _bridge(tmp_path, window):
    b = Bridge()
    b.window = window
    b._paths = {k: tmp_path for k in ("audio", "marker", "output", "model", "watch")}
    return b


def test_folder_dialog_has_no_file_filter(tmp_path):
    win = _RecordingWindow()
    b = _bridge(tmp_path, win)
    b.pick_output()
    assert win.file_types == (), f"Ordner-Dialog bekam Filter: {win.file_types}"


def test_watch_dir_dialog_has_no_file_filter(tmp_path):
    win = _RecordingWindow()
    b = _bridge(tmp_path, win)
    b.pick_watch_dir()
    assert win.file_types == (), f"Ordner-Dialog bekam Filter: {win.file_types}"


def test_file_dialog_keeps_filters(tmp_path):
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"")
    win = _RecordingWindow()
    b = _bridge(tmp_path, win)
    # Datei muss existieren, damit _record_path ok ist; Rückgabe = directory (tmp_path)
    b._paths["audio"] = audio
    b.pick_audio()
    assert win.file_types and len(win.file_types) >= 1
    assert any("mp3" in f or "m4a" in f for f in win.file_types)
