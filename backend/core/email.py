import asyncio
import html as html_lib
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from core.config import settings
from core.email_translations import email_text, normalize_email_language

logger = logging.getLogger(__name__)

SMTP_TIMEOUT = 15


def _html_to_text(html: str) -> str:
    # Keep link targets, since the buttons are the whole point of these mails
    text = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2: \1", html, flags=re.S)
    text = re.sub(r"<(script|style)\b.*?</\1>", "", text, flags=re.S)
    text = re.sub(r"</(p|div|h\d|a)>|<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return html_lib.unescape("\n".join(ln for ln in lines if ln))


def _log_result(to: str, refused: dict) -> None:
    if refused:
        logger.error("SMTP relay refused recipient %s: %s", to, refused)
    else:
        logger.info("Email accepted by SMTP relay for %s", to)


def _send_sync(to: str, subject: str, html: str) -> None:
    from_addr = settings.from_email or settings.smtp_username or "noreply@scrob"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.rsplit("@", 1)[-1] or None)
    msg.attach(MIMEText(_html_to_text(html), "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    enc = (settings.smtp_encryption or "tls").lower()

    if enc == "ssl":
        with smtplib.SMTP_SSL(settings.smtp_address, settings.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            refused = smtp.sendmail(from_addr, to, msg.as_string())
            _log_result(to, refused)
    elif enc == "tls":
        with smtplib.SMTP(settings.smtp_address, settings.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
            smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            refused = smtp.sendmail(from_addr, to, msg.as_string())
            _log_result(to, refused)
    else:  # none
        with smtplib.SMTP(settings.smtp_address, settings.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            refused = smtp.sendmail(from_addr, to, msg.as_string())
            _log_result(to, refused)


async def send_email(to: str, subject: str, html: str, *, language: str | None = None) -> None:
    await asyncio.to_thread(_send_sync, to, subject, html)


async def send_activation_email(
    to: str, token: str, *, email_change: bool = False, language: str | None = None
) -> None:
    link = html_lib.escape(f"{settings.server_url}/auth/activate/{token}", quote=True)
    if email_change:
        link += "?email_change=true"
    email_type = "activation_change" if email_change else "activation"
    heading = email_text(language, f"{email_type}_heading")
    message = email_text(language, f"{email_type}_message")
    button = email_text(language, f"{email_type}_button")
    subject = email_text(language, f"{email_type}_subject")
    ignore_message = email_text(language, f"{email_type}_ignore")
    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: sans-serif; background: #18181b; color: #f4f4f5; padding: 40px;">
      <div style="max-width: 480px; margin: 0 auto; background: #27272a; border: 1px solid #3f3f46; border-radius: 12px; padding: 32px;">
        <h1 style="font-size: 24px; font-weight: 700; margin-bottom: 8px;">{heading}</h1>
        <p style="color: #a1a1aa; margin-bottom: 24px;">
          {message}
          {email_text(language, "expires_24_hours")}
        </p>
        <a href="{link}"
           style="display: inline-block; background: #f4f4f5; color: #09090b; font-weight: 700;
                  padding: 12px 24px; border-radius: 8px; text-decoration: none;">
          {button}
        </a>
        <p style="color: #71717a; font-size: 12px; margin-top: 24px;">
          {ignore_message}
        </p>
      </div>
    </body>
    </html>
    """
    await send_email(to, subject, html, language=language)


async def send_email_change_email(to: str, token: str, *, language: str | None = None) -> None:
    link = html_lib.escape(f"{settings.server_url}/auth/activate/{token}", quote=True)
    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: sans-serif; background: #18181b; color: #f4f4f5; padding: 40px;">
      <div style="max-width: 480px; margin: 0 auto; background: #27272a; border: 1px solid #3f3f46; border-radius: 12px; padding: 32px;">
        <h1 style="font-size: 24px; font-weight: 700; margin-bottom: 8px;">{email_text(language, "email_change_heading")}</h1>
        <p style="color: #a1a1aa; margin-bottom: 24px;">
          {email_text(language, "email_change_message")}
          {email_text(language, "expires_24_hours")}
        </p>
        <a href="{link}"
           style="display: inline-block; background: #f4f4f5; color: #09090b; font-weight: 700;
                  padding: 12px 24px; border-radius: 8px; text-decoration: none;">
          {email_text(language, "email_change_button")}
        </a>
        <p style="color: #71717a; font-size: 12px; margin-top: 24px;">
          {email_text(language, "email_change_ignore")}
        </p>
      </div>
    </body>
    </html>
    """
    await send_email(to, email_text(language, "email_change_subject"), html, language=language)


async def send_password_reset_email(to: str, token: str, *, language: str | None = None) -> None:
    link = html_lib.escape(f"{settings.server_url}/reset-password/{token}", quote=True)
    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: sans-serif; background: #18181b; color: #f4f4f5; padding: 40px;">
      <div style="max-width: 480px; margin: 0 auto; background: #27272a; border: 1px solid #3f3f46; border-radius: 12px; padding: 32px;">
        <h1 style="font-size: 24px; font-weight: 700; margin-bottom: 8px;">{email_text(language, "password_heading")}</h1>
        <p style="color: #a1a1aa; margin-bottom: 24px;">
          {email_text(language, "password_message")}
          {email_text(language, "expires_1_hour")}
        </p>
        <a href="{link}"
           style="display: inline-block; background: #f4f4f5; color: #09090b; font-weight: 700;
                  padding: 12px 24px; border-radius: 8px; text-decoration: none;">
          {email_text(language, "password_button")}
        </a>
        <p style="color: #71717a; font-size: 12px; margin-top: 24px;">
          {email_text(language, "password_ignore")}
        </p>
      </div>
    </body>
    </html>
    """
    await send_email(to, email_text(language, "password_subject"), html, language=language)


def email_enabled() -> bool:
    return bool(settings.smtp_address)


def _base_url() -> str:
    base = (settings.server_url or "").strip().rstrip("/")
    if base and not re.match(r"^https?://", base, re.I):
        base = f"https://{base}"
    if not base:
        logger.warning("SERVER_URL is empty: links in emails will be relative and unusable. Set SERVER_URL to your public URL.")
    return base


def _card(
    heading: str,
    body_html: str,
    button: str | None = None,
    button_url: str | None = None,
    *,
    language: str | None = None,
) -> str:
    link = button_url or html_lib.escape(_base_url(), quote=True)
    escaped_button = html_lib.escape(button) if button else None
    btn = (
        f'''<table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>
          <td bgcolor="#f4f4f5" style="border-radius: 8px;">
            <a href="{link}" target="_blank" rel="noopener noreferrer"
               style="display: inline-block; color: #09090b; font-weight: 700; padding: 12px 24px;
                      border-radius: 8px; text-decoration: none;">{escaped_button}</a>
          </td></tr></table>
        <p style="color: #71717a; font-size: 12px; margin-top: 16px; word-break: break-all;">
          {email_text(language, "fallback_link")} <a href="{link}" style="color: #a1a1aa;">{link}</a>
        </p>'''
        if button else ""
    )
    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: sans-serif; background: #18181b; color: #f4f4f5; padding: 40px;">
      <div style="max-width: 480px; margin: 0 auto; background: #27272a; border: 1px solid #3f3f46; border-radius: 12px; padding: 32px;">
        <h1 style="font-size: 24px; font-weight: 700; margin-bottom: 8px;">{heading}</h1>
        <div style="color: #a1a1aa; margin-bottom: 24px;">{body_html}</div>
        {btn}
      </div>
    </body>
    </html>
    """


def _format_rating(rating: float, language: str | None) -> str:
    value = f"{rating:g}"
    return value.replace(".", ",") if normalize_email_language(language) != "en" else value


async def send_friend_request_email(
    to: str, requester_name: str, *, language: str | None = None
) -> None:
    name = html_lib.escape(requester_name)
    subject_name = requester_name
    html = _card(
        email_text(language, "friend_request_heading"),
        email_text(language, "friend_request_message").format(name=name),
        email_text(language, "friend_request_button"),
        language=language,
    )
    await send_email(
        to, email_text(language, "friend_request_subject").format(name=subject_name), html,
        language=language,
    )


async def send_friend_media_share_email(
    to: str, sender_name: str, title: str, link: str, rating: float | None = None,
    comment: str | None = None, *, language: str | None = None,
) -> None:
    name = html_lib.escape(sender_name)
    escaped_title = html_lib.escape(title)
    url = html_lib.escape(f"{_base_url()}{link}", quote=True)
    rating_html = (
        email_text(language, "share_rated").format(name=name, rating=_format_rating(rating, language))
        if rating is not None else ""
    )
    if comment:
        rating_html += (
            "<blockquote style=\"margin: 16px 0; padding-left: 12px; border-left: 3px solid #52525b; "
            f"color: #d4d4d8; white-space: pre-wrap;\">{html_lib.escape(comment)}</blockquote>"
        )
    html = _card(
        email_text(language, "share_heading"),
        email_text(language, "share_message").format(name=name, title=escaped_title) + rating_html,
        email_text(language, "share_button"),
        button_url=url,
        language=language,
    )
    await send_email(to, email_text(language, "share_subject"), html, language=language)


async def send_rating_digest_email(
    to: str, items: list[tuple[str, str, float | None]], *, language: str | None = None
) -> None:
    """`items` are (actor name, media title, rating) tuples."""
    rows = "".join(
        email_text(language, "digest_row").format(
            actor=html_lib.escape(actor),
            title=html_lib.escape(title),
            rating=(email_text(language, "digest_rating").format(rating=_format_rating(rating, language))
                    if rating is not None else ""),
        )
        for actor, title, rating in items
    )
    count = len(items)
    html = _card(
        email_text(language, "digest_heading"),
        f"<p>{email_text(language, 'digest_one' if count == 1 else 'digest_many').format(count=count)}</p><ul>{rows}</ul>",
        email_text(language, "digest_button"),
        language=language,
    )
    subject_key = "digest_subject_one" if count == 1 else "digest_subject_many"
    subject = email_text(language, subject_key).format(count=count)
    await send_email(to, subject, html, language=language)


async def send_watchlist_alert_email(
    to: str, title: str, link: str, events: list[str], *, language: str | None = None
) -> None:
    escaped_title = html_lib.escape(title)
    url = html_lib.escape(f"{_base_url()}{link}", quote=True)
    event_rows = "".join(f"<li>{html_lib.escape(event)}</li>" for event in events)
    html = _card(
        email_text(language, "watchlist_heading"),
        email_text(language, "watchlist_message").format(title=escaped_title, events=event_rows),
        email_text(language, "watchlist_button"),
        button_url=url,
        language=language,
    )
    await send_email(to, email_text(language, "watchlist_subject"), html, language=language)
