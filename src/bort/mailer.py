"""Zip-Export per Gmail-SMTP verschicken; App-Passwort liegt im System-Schlüsselbund."""

from __future__ import annotations

import re
import smtplib
import ssl
import subprocess
from email.message import EmailMessage
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_TIMEOUT = 30
# secret-tool (libsecret) spricht den Secret Service an -> landet unter KDE in KWallet.
_SECRET_ATTRS = ("service", "bort-gmail", "account")
_ADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # Gmail-Limit


class MailError(Exception):
    """Fehler beim Speichern des Passworts oder beim Versand."""


def is_valid_address(value: str) -> bool:
    return bool(_ADDRESS_RE.fullmatch(value.strip()))


def store_app_password(sender: str, password: str) -> None:
    """Legt das Gmail-App-Passwort im System-Schlüsselbund ab (nie in der Config)."""
    if not is_valid_address(sender):
        raise MailError("Ungültige Absender-Adresse.")
    if not password.strip():
        raise MailError("Leeres App-Passwort.")
    try:
        result = subprocess.run(
            ["secret-tool", "store", "--label", "BoRT Gmail App-Passwort",
             *_SECRET_ATTRS[:2], _SECRET_ATTRS[2], sender.strip()],
            input=password.encode("utf-8"),
            capture_output=True,
            timeout=SMTP_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise MailError("secret-tool ist nicht installiert (libsecret).") from exc
    except subprocess.TimeoutExpired as exc:
        raise MailError("Schlüsselbund antwortet nicht.") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise MailError(f"Passwort konnte nicht gespeichert werden: {detail}")


def load_app_password(sender: str) -> str | None:
    """Liest das App-Passwort aus dem Schlüsselbund; None wenn keines hinterlegt ist."""
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", *_SECRET_ATTRS[:2], _SECRET_ATTRS[2], sender.strip()],
            capture_output=True,
            timeout=SMTP_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    password = result.stdout.decode("utf-8", errors="replace").strip()
    return password or None


def send_zip(sender: str, password: str, recipient: str, zip_path: Path) -> None:
    """Verschickt das Zip als Anhang über Gmail-SMTP (STARTTLS)."""
    sender = sender.strip()
    recipient = recipient.strip()
    if not is_valid_address(sender):
        raise MailError("Ungültige Absender-Adresse.")
    if not is_valid_address(recipient):
        raise MailError("Ungültige Empfänger-Adresse.")
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise MailError("Zip-Datei nicht gefunden.")
    if zip_path.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise MailError("Zip ist größer als 25 MB (Gmail-Anhang-Limit).")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"BoR Minutes: {zip_path.name}"
    message.set_content("Transkript-Export aus BoRT, siehe Anhang.")
    message.add_attachment(
        zip_path.read_bytes(),
        maintype="application",
        subtype="zip",
        filename=zip_path.name,
    )
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
            # Ohne context prüft smtplib das Serverzertifikat nicht
            # (check_hostname=False, CERT_NONE) – verschlüsselt, aber
            # gegen MITM offen. Nicht abschaltbar machen.
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(sender, password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "Gmail-Anmeldung fehlgeschlagen — App-Passwort prüfen (2FA nötig)."
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Versand fehlgeschlagen: {exc}") from exc
