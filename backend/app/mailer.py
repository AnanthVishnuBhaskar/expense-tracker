"""Sending email through Resend, Brevo or plain SMTP, whichever is configured."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import httpx

from app.config import Settings

log = logging.getLogger(__name__)


class EmailError(Exception):
    """The email couldn't be handed to the provider."""


def send_email(settings: Settings, to: str, subject: str, text: str, html: str) -> None:
    name, address = parseaddr(settings.email_from)
    if settings.email_console:
        log.warning(
            "EMAIL_CONSOLE is on, so this email was printed, not sent.\nTo: %s\nSubject: %s\n\n%s",
            to,
            subject,
            text,
        )
        return
    try:
        if settings.resend_api_key:
            resp = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": formataddr((name, address)),
                    "to": [to],
                    "subject": subject,
                    "text": text,
                    "html": html,
                },
                timeout=15,
            )
            resp.raise_for_status()
        elif settings.brevo_api_key:
            resp = httpx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
                json={
                    "sender": {"name": name or address, "email": address},
                    "to": [{"email": to}],
                    "subject": subject,
                    "textContent": text,
                    "htmlContent": html,
                },
                timeout=15,
            )
            resp.raise_for_status()
        elif settings.smtp_host:
            msg = EmailMessage()
            msg["From"] = formataddr((name, address))
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(text)
            msg.add_alternative(html, subtype="html")
            context = ssl.create_default_context()
            if settings.smtp_port == 465:
                server = smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port, timeout=15, context=context
                )
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
                server.starttls(context=context)
            with server:
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
        else:
            raise EmailError("No way to send email is configured")
    except httpx.HTTPStatusError as e:
        # The provider's reply says why (unverified sender, bad key...), never the key itself.
        log.error("email to %s failed: %s %s", to, e.response.status_code, e.response.text[:300])
        raise EmailError(str(e)) from e
    except (httpx.HTTPError, smtplib.SMTPException, OSError) as e:
        log.error("email to %s failed: %s", to, e)
        raise EmailError(str(e)) from e
