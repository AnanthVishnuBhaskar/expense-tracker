import httpx
import pytest

from app.config import Settings
from app.mailer import EmailError, send_email


def capture(monkeypatch, status=200):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json})
        return httpx.Response(status, request=httpx.Request("POST", url), text="denied")

    monkeypatch.setattr("app.mailer.httpx.post", fake_post)
    return calls


def test_resend(monkeypatch):
    calls = capture(monkeypatch)
    s = Settings(email_from="Receipts <r@abc.example>", resend_api_key="rk")
    send_email(s, "xyz@example.com", "Hi", "text", "<p>html</p>")
    assert calls[0]["url"] == "https://api.resend.com/emails"
    assert calls[0]["headers"]["Authorization"] == "Bearer rk"
    assert calls[0]["json"]["from"] == "Receipts <r@abc.example>"
    assert calls[0]["json"]["to"] == ["xyz@example.com"]


def test_brevo(monkeypatch):
    calls = capture(monkeypatch)
    s = Settings(email_from="Receipts <r@abc.example>", brevo_api_key="bk")
    send_email(s, "xyz@example.com", "Hi", "text", "<p>html</p>")
    assert calls[0]["url"] == "https://api.brevo.com/v3/smtp/email"
    assert calls[0]["json"]["sender"] == {"name": "Receipts", "email": "r@abc.example"}


def test_provider_errors_become_email_errors(monkeypatch):
    capture(monkeypatch, status=403)
    s = Settings(email_from="r@abc.example", resend_api_key="rk")
    with pytest.raises(EmailError):
        send_email(s, "xyz@example.com", "Hi", "text", "html")


def test_email_is_off_without_a_sender():
    assert not Settings().email_enabled
    assert not Settings(resend_api_key="rk").email_enabled
    assert Settings(email_from="r@abc.example", smtp_host="smtp.gmail.com").email_enabled
