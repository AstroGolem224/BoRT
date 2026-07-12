"""Regressionstest gegen den Datei-Dialog-Deadlock (2026-07).

pywebviews window.create_file_dialog marshalt sich intern auf die GTK-Mainloop
und blockt den AUFRUFER-Thread. Wird es zusätzlich über GLib.idle_add auf die
Mainloop marshallt (das frühere _run_on_gtk), blockt der Main-Thread in der
internen Semaphore und der Dialog kann nie laufen -> Deadlock, Dialog öffnet
nicht, App friert. Die Bridge MUSS create_file_dialog direkt aus dem
js_api-Worker-Thread aufrufen.
"""

import threading

from bort.app import Bridge


class _FakeWindow:
    """Simuliert pywebviews synchrones create_file_dialog (kein GLib nötig)."""

    def __init__(self, result):
        self._result = result
        self.called_in_thread: str | None = None

    def create_file_dialog(self, *_args, **_kwargs):
        # Muss synchron im aufrufenden (Worker-)Thread laufen, ohne dass die
        # Bridge selbst noch einen idle_add-Umweg baut.
        self.called_in_thread = threading.current_thread().name
        return (self._result,)


def _make_bridge(tmp_path, window):
    bridge = Bridge()
    bridge.window = window
    # Startordner-Lookup soll nicht auf reale Pfade zugreifen.
    bridge._paths = {k: None for k in ("audio", "marker", "output", "model", "watch")}
    return bridge


def test_pick_file_calls_dialog_directly_in_worker_thread(tmp_path):
    target = tmp_path / "audio.m4a"
    target.write_bytes(b"")
    window = _FakeWindow(str(target))
    bridge = _make_bridge(tmp_path, window)

    done = {}

    def worker():
        done["result"] = bridge.pick_audio()

    t = threading.Thread(target=worker, name="bort-web-bridge-test")
    t.start()
    t.join(timeout=5)

    assert not t.is_alive(), "pick_audio hing -> Dialog-Deadlock wieder da"
    assert done["result"] == {"ok": True, "path": str(target)}
    # Der Dialog lief direkt im Worker-Thread (kein Main-Loop-Umweg).
    assert window.called_in_thread == "bort-web-bridge-test"
