"""Unit tests for app/services/email_service.py (BE-03 follow-up).

Monkeypatches `smtplib.SMTP` so no real socket/MailHog connection is needed.
"""

from app.core.config import Settings
from app.services import email_service


class FakeSmtpClient:
    sent_messages: list[object] = []
    tls_started = False

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self) -> "FakeSmtpClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def starttls(self) -> None:
        FakeSmtpClient.tls_started = True

    def send_message(self, message: object) -> None:
        FakeSmtpClient.sent_messages.append(message)


def _settings(**overrides: object) -> Settings:
    fields: dict[str, object] = {
        "smtp_host": "mailhog",
        "smtp_port": 1025,
        "smtp_from_address": "noreply@frac.local",
        "smtp_use_tls": False,
        "password_reset_token_expire_minutes": 30,
    }
    fields.update(overrides)
    return Settings(**fields)  # type: ignore[arg-type]


def test_send_password_reset_email_sends_via_smtp(monkeypatch) -> None:
    FakeSmtpClient.sent_messages = []
    FakeSmtpClient.tls_started = False
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSmtpClient)

    email_service.send_password_reset_email(
        to_address="admin@example.com",
        reset_url="http://localhost:5173/reset-password?token=abc.def",
        settings=_settings(),
    )

    assert len(FakeSmtpClient.sent_messages) == 1
    message = FakeSmtpClient.sent_messages[0]
    assert message["To"] == "admin@example.com"
    assert message["From"] == "noreply@frac.local"
    assert "http://localhost:5173/reset-password?token=abc.def" in message.get_content()
    assert FakeSmtpClient.tls_started is False


def test_send_password_reset_email_starts_tls_when_configured(monkeypatch) -> None:
    FakeSmtpClient.sent_messages = []
    FakeSmtpClient.tls_started = False
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSmtpClient)

    email_service.send_password_reset_email(
        to_address="admin@example.com",
        reset_url="http://localhost:5173/reset-password?token=abc.def",
        settings=_settings(smtp_use_tls=True),
    )

    assert FakeSmtpClient.tls_started is True
