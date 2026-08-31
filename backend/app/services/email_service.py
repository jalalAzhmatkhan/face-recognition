"""Outbound email via stdlib `smtplib` (BE-03 follow-up, forgot-password flow).

Deliberately stdlib-only, no third-party mail library — same "no dependency
for something the standard library already does" philosophy as
`scripts/device_simulator.py`. Dev/test points `SMTP_HOST`/`SMTP_PORT` at
MailHog (docker-compose.dev.yml's `mailhog` service), which accepts any
message without real delivery and exposes a web UI at
http://localhost:8025 to inspect what was "sent".
"""

import smtplib
from email.message import EmailMessage

from app.core.config import Settings, get_settings


def send_password_reset_email(
    *, to_address: str, reset_url: str, settings: Settings | None = None
) -> None:
    settings = settings or get_settings()

    message = EmailMessage()
    message["Subject"] = "Reset Password FRAC Console"
    message["From"] = settings.smtp_from_address
    message["To"] = to_address
    message.set_content(
        "Kami menerima permintaan reset password untuk akun kamu.\n\n"
        f"Klik tautan berikut untuk membuat password baru (berlaku "
        f"{settings.password_reset_token_expire_minutes} menit):\n\n"
        f"{reset_url}\n\n"
        "Jika kamu tidak meminta reset password, abaikan email ini — "
        "password akun kamu tidak akan berubah."
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        if settings.smtp_use_tls:
            client.starttls()
        client.send_message(message)
