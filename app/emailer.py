from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
import smtplib

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
class RenderedDigest:
    subject: str
    text: str
    html: str


def render_digest(listings: list[Listing], public_url: str = "") -> RenderedDigest:
    jobs = present_listings(listings, highest_fit_first=True)
    count = len(jobs)
    subject = f"{count} new role{'s' if count != 1 else ''} for Spring 2027"
    context = {
        "jobs": jobs,
        "public_url": public_url.rstrip("/"),
        "subject": subject,
    }
    return RenderedDigest(
        subject=subject,
        text=template_environment.get_template("email/digest.txt").render(context).strip() + "\n",
        html=template_environment.get_template("email/digest.html").render(context),
    )


def send_new_jobs_digest(listings: list[Listing], config: Settings = settings) -> bool:
    if not listings or not all((config.smtp_host, config.smtp_from, config.alert_recipient)):
        return False

    digest = render_digest(listings, config.public_url)
    message = EmailMessage()
    message["Subject"] = digest.subject
    message["From"] = config.smtp_from
    message["To"] = config.alert_recipient
    message.set_content(digest.text)
    message.add_alternative(digest.html, subtype="html")

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
        if config.smtp_use_tls:
            smtp.starttls()
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password)
        smtp.send_message(message)
    return True
