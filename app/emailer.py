from email.message import EmailMessage
from html import escape
import smtplib

from app.config import Settings, settings
from app.models import Listing


def send_new_jobs_digest(listings: list[Listing], config: Settings = settings) -> bool:
    if not listings or not all((config.smtp_host, config.smtp_from, config.alert_recipient)):
        return False
    lines = [f"{job.company} — {job.title} ({job.location or 'Location not listed'})\n{job.application_url}" for job in listings]
    html_rows = "".join(
        f'<li><a href="{escape(job.application_url, quote=True)}">{escape(job.company)} — {escape(job.title)}</a>'
        f' <small>{escape(job.location or "Location not listed")}</small></li>' for job in listings
    )
    message = EmailMessage()
    message["Subject"] = f"{len(listings)} new new-grad SWE job{'s' if len(listings) != 1 else ''}"
    message["From"] = config.smtp_from
    message["To"] = config.alert_recipient
    message.set_content("New roles found:\n\n" + "\n\n".join(lines))
    message.add_alternative(f"<h2>New new-grad SWE roles</h2><ul>{html_rows}</ul>", subtype="html")
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
        if config.smtp_use_tls:
            smtp.starttls()
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password)
        smtp.send_message(message)
    return True
