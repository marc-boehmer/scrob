import asyncio
import html as html_lib
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from core.config import settings

logger = logging.getLogger(__name__)

SMTP_TIMEOUT = 15


def _html_to_text(html: str) -> str:
    # Keep link targets, since the buttons are the whole point of these mails
    text = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2: \1", html, flags=re.S)
    text = re.sub(r"<(script|style)\b.*?</\1>", "", text, flags=re.S)
    text = re.sub(r"</(p|div|h\d|a)>|<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


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


async def send_email(to: str, subject: str, html: str) -> None:
    await asyncio.to_thread(_send_sync, to, subject, html)


async def send_activation_email(to: str, token: str, *, email_change: bool = False) -> None:
    link = f"{settings.server_url}/auth/activate/{token}"
    if email_change:
        link += "?email_change=true"
    heading = "Confirm your new email" if email_change else "Confirm your email"
    message = (
        "Click the button below to confirm this address for your Scrob account."
        if email_change
        else "Thanks for registering on Scrob. Click the button below to activate your account."
    )
    button = "Confirm email" if email_change else "Activate account"
    subject = "Confirm your Scrob email address" if email_change else "Activate your Scrob account"
    ignore_message = (
        "If you didn't request this change, you can safely ignore this email."
        if email_change
        else "If you didn't create an account, you can safely ignore this email."
    )
    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: sans-serif; background: #18181b; color: #f4f4f5; padding: 40px;">
      <div style="max-width: 480px; margin: 0 auto; background: #27272a; border: 1px solid #3f3f46; border-radius: 12px; padding: 32px;">
        <h1 style="font-size: 24px; font-weight: 700; margin-bottom: 8px;">{heading}</h1>
        <p style="color: #a1a1aa; margin-bottom: 24px;">
          {message}
          This link expires in <strong style="color: #f4f4f5;">24 hours</strong>.
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
    await send_email(to, subject, html)


async def send_password_reset_email(to: str, token: str) -> None:
    link = f"{settings.server_url}/reset-password/{token}"
    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: sans-serif; background: #18181b; color: #f4f4f5; padding: 40px;">
      <div style="max-width: 480px; margin: 0 auto; background: #27272a; border: 1px solid #3f3f46; border-radius: 12px; padding: 32px;">
        <h1 style="font-size: 24px; font-weight: 700; margin-bottom: 8px;">Reset your password</h1>
        <p style="color: #a1a1aa; margin-bottom: 24px;">
          We received a request to reset your Scrob password. Click the button below to choose a new one.
          This link expires in <strong style="color: #f4f4f5;">1 hour</strong>.
        </p>
        <a href="{link}"
           style="display: inline-block; background: #f4f4f5; color: #09090b; font-weight: 700;
                  padding: 12px 24px; border-radius: 8px; text-decoration: none;">
          Reset password
        </a>
        <p style="color: #71717a; font-size: 12px; margin-top: 24px;">
          If you didn't request a password reset, you can safely ignore this email.
        </p>
      </div>
    </body>
    </html>
    """
    await send_email(to, "Reset your Scrob password", html)


def email_enabled() -> bool:
    return bool(settings.smtp_address)


def _card(heading: str, body_html: str, button: str | None = None) -> str:
    link = settings.server_url
    btn = (
        f'''<a href="{link}" style="display: inline-block; background: #f4f4f5; color: #09090b; font-weight: 700;
                  padding: 12px 24px; border-radius: 8px; text-decoration: none;">{button}</a>'''
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


async def send_friend_request_email(to: str, requester_name: str) -> None:
    name = html_lib.escape(requester_name)
    html = _card(
        "New friend request",
        f"<p><strong style=\"color: #f4f4f5;\">{name}</strong> sent you a friend request on Scrob.</p>",
        "View request",
    )
    await send_email(to, f"{requester_name} sent you a friend request on Scrob", html)


async def send_rating_digest_email(to: str, items: list[tuple[str, str, float | None]]) -> None:
    """`items` are (actor name, media title, rating) tuples."""
    rows = "".join(
        f"<li><strong style=\"color: #f4f4f5;\">{html_lib.escape(actor)}</strong> rated "
        f"{html_lib.escape(title)}" + (f" {rating:g}" if rating is not None else "") + "</li>"
        for actor, title, rating in items
    )
    count = len(items)
    html = _card(
        "Your daily rating digest",
        f"<p>{count} new rating{'s' if count != 1 else ''} from your friends:</p><ul>{rows}</ul>",
        "Open Scrob",
    )
    await send_email(to, f"{count} new rating{'s' if count != 1 else ''} from your friends on Scrob", html)
