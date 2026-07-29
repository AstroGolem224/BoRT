"""Mailer: Adress-Validierung, Schlüsselbund-Zugriff (gemockt), SMTP-Versand (gemockt)."""

import smtplib
import subprocess
from pathlib import Path

import pytest

from bort import mailer
from bort.mailer import MailError, is_valid_address, send_zip, store_app_password


def test_address_validation():
    assert is_valid_address("a@b.de")
    assert not is_valid_address("kaputt@")
    assert not is_valid_address("ohne-at.de")
    assert not is_valid_address(" a b@c.de ")


def test_store_password_rejects_bad_input():
    with pytest.raises(MailError):
        store_app_password("kein-mail", "pw")
    with pytest.raises(MailError):
        store_app_password("a@b.de", "   ")


def test_store_password_missing_secret_tool(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError("secret-tool")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(MailError, match="secret-tool"):
        store_app_password("a@b.de", "pw")


class _FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None):
        assert host == "smtp.gmail.com" and port == 587

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        if password == "falsch":
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, message):
        _FakeSMTP.sent.append(message)


@pytest.fixture
def zip_file(tmp_path) -> Path:
    path = tmp_path / "export.zip"
    path.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    return path


def test_send_zip_success(monkeypatch, zip_file):
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.sent = []
    send_zip("me@gmail.com", "pw", "du@example.com", zip_file)
    assert len(_FakeSMTP.sent) == 1
    message = _FakeSMTP.sent[0]
    assert message["To"] == "du@example.com"
    assert "export.zip" in message["Subject"]


def test_send_zip_auth_error(monkeypatch, zip_file):
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    with pytest.raises(MailError, match="App-Passwort"):
        send_zip("me@gmail.com", "falsch", "du@example.com", zip_file)


def test_send_zip_rejects_oversize(monkeypatch, zip_file, tmp_path):
    monkeypatch.setattr(mailer, "MAX_ATTACHMENT_BYTES", 2)
    with pytest.raises(MailError, match="25 MB"):
        send_zip("me@gmail.com", "pw", "du@example.com", zip_file)


def test_bridge_export_and_send_paths(tmp_path, monkeypatch):
    from bort.app import Bridge
    from bort.config import Config

    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    assert bridge.export_and_send(["x"], "kaputt", "a@b.de")["ok"] is False

    # Kein Passwort hinterlegt -> needs_password.
    monkeypatch.setattr("bort.app.load_app_password", lambda _s: None)
    result = bridge.export_and_send(["x"], "du@example.com", "me@gmail.com")
    assert result["ok"] is False and result.get("needs_password") is True
