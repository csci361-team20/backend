import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


Attachment = tuple[str, bytes, str]  # (filename, content, MIME type)


def send_email(
    to: str, subject: str, body: str, attachments: list[Attachment] | None = None
) -> None:
    """Send a plain-text email. Failures are logged, never raised.

    Runs synchronously; call it through FastAPI ``BackgroundTasks`` so the
    request does not wait for the SMTP server.
    """
    if not settings.EMAIL_ENABLED:
        logger.info(
            "Email disabled; would send to %s: %s (%d attachments)\n%s",
            to,
            subject,
            len(attachments or []),
            body,
        )
        return

    message = EmailMessage()
    message["From"] = settings.EMAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    for filename, content, mime_type in attachments or []:
        maintype, _, subtype = mime_type.partition("/")
        message.add_attachment(
            content, maintype=maintype, subtype=subtype, filename=filename
        )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Failed to send email to %s (%s)", to, subject)
