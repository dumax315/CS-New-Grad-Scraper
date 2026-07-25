from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
import smtplib
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import Settings, settings
from app.models import Listing
from app.presentation import present_listings


template_environment = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(("html", "xml")),
    keep_trailing_newline=True,
)


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


RenderedDigest = RenderedEmail


@dataclass(frozen=True, slots=True)
class DigestRecipient:
    address: str
    unsubscribe_url: str


def render_digest(
    listings: list[Listing],
    public_url: str = "",
    unsubscribe_url: str = "",
) -> RenderedDigest:
    jobs = present_listings(listings, highest_fit_first=True)
    count = len(jobs)
    subject = f"{count} new role{'s' if count != 1 else ''} for Spring 2027"
    context = {
        "jobs": jobs,
        "public_url": public_url.rstrip("/"),
        "subject": subject,
        "unsubscribe_url": unsubscribe_url,
    }
    return RenderedDigest(
        subject=subject,
        text=template_environment.get_template("email/digest.txt").render(context).strip() + "\n",
        html=template_environment.get_template("email/digest.html").render(context),
    )


def render_confirmation(confirmation_url: str) -> RenderedEmail:
    subject = "Confirm your New Grad SWE Jobs alerts"
    context = {"confirmation_url": confirmation_url, "subject": subject}
    return RenderedEmail(
        subject=subject,
        text=template_environment.get_template("email/confirmation.txt").render(context).strip() + "\n",
        html=template_environment.get_template("email/confirmation.html").render(context),
    )


def build_message(
    rendered: RenderedEmail,
    recipient: str,
    config: Settings,
    *,
    unsubscribe_url: str = "",
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = rendered.subject
    message["From"] = config.smtp_from
    message["To"] = recipient
    if unsubscribe_url:
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")
    return message


def send_messages(messages: Iterable[EmailMessage], config: Settings = settings) -> int:
    pending = list(messages)
    if not pending or not all((config.smtp_host, config.smtp_from)):
        return 0

    sent = 0
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
        if config.smtp_use_tls:
            smtp.starttls()
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password)
        for message in pending:
            try:
                smtp.send_message(message)
                sent += 1
            except smtplib.SMTPRecipientsRefused:
                continue
    return sent


def send_confirmation_email(
    recipient: str,
    confirmation_url: str,
    config: Settings = settings,
) -> bool:
    rendered = render_confirmation(confirmation_url)
    return send_messages([build_message(rendered, recipient, config)], config) == 1


def send_new_jobs_digest(
    listings: list[Listing],
    config: Settings = settings,
    recipients: Iterable[DigestRecipient] = (),
) -> bool:
    if not listings:
        return False

    recipients_by_address = {
        recipient.address.strip().lower(): recipient
        for recipient in recipients
        if recipient.address.strip()
    }
    if config.alert_recipient:
        admin_address = config.alert_recipient.strip()
        recipients_by_address.setdefault(
            admin_address.lower(),
            DigestRecipient(admin_address, ""),
        )
    if not recipients_by_address:
        return False

    messages = []
    for recipient in recipients_by_address.values():
        digest = render_digest(listings, config.public_url, recipient.unsubscribe_url)
        messages.append(build_message(
            digest,
            recipient.address,
            config,
            unsubscribe_url=recipient.unsubscribe_url,
        ))
    return send_messages(messages, config) > 0
