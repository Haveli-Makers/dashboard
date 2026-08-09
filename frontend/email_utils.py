import datetime
import io
import re
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd

from CONFIG import (
    SMTP_FROM_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USERNAME,
)
from CONFIG import SAMPLES_EMAIL_BODY_TEMPLATE as SAMPLES_EMAIL_BODY_TEMPLATE
from CONFIG import SAMPLES_EMAIL_SUBJECT_TEMPLATE as SAMPLES_EMAIL_SUBJECT_TEMPLATE
from CONFIG import SPREAD_EMAIL_BODY_TEMPLATE as SPREAD_EMAIL_BODY_TEMPLATE
from CONFIG import SPREAD_EMAIL_SUBJECT_TEMPLATE as SPREAD_EMAIL_SUBJECT_TEMPLATE

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_template(template: str, context: dict) -> str:
    """Render a {var}-style template, leaving unknown placeholders untouched."""
    return template.format_map(_SafeDict(context))


def build_spread_email_context(
    connectors: list[str],
    pairs: list[str],
    window_hours,
    row_count: int,
    failed_count: int,
) -> dict:
    """Build the variable context used to render the spread report email template."""
    now = datetime.datetime.now()
    return {
        "connectors": ", ".join(connectors) if connectors else "-",
        "pairs": ", ".join(pairs) if pairs else "All Pairs",
        "window_hours": window_hours,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "row_count": row_count,
        "failed_count": failed_count,
    }


def build_samples_email_context(
    connectors: list[str],
    pairs: list[str],
    row_count: int,
) -> dict:
    """Build the variable context used to render the spread samples email template."""
    now = datetime.datetime.now()
    return {
        "connectors": ", ".join(connectors) if connectors else "-",
        "pairs": ", ".join(pairs) if pairs else "-",
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "row_count": row_count,
    }


def parse_recipients(raw: str) -> list[str]:
    """Split a comma/semicolon/whitespace separated string into a list of validated emails."""
    if not raw:
        return []
    candidates = re.split(r"[,;\s]+", raw.strip())
    return [c for c in candidates if c and EMAIL_RE.match(c)]


def dataframes_to_xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """Build an in-memory .xlsx file from a dict of {sheet_name: DataFrame}."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31] or "Sheet1"
            df.to_excel(writer, sheet_name=safe_name, index=False)
    buffer.seek(0)
    return buffer.read()


def is_smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD)


def send_email_with_xlsx(
    to_emails: list[str],
    subject: str,
    body: str,
    attachment_bytes: bytes,
    attachment_filename: str,
) -> None:
    """Send an email with an .xlsx attachment via SMTP. Raises on failure."""
    if not is_smtp_configured():
        raise RuntimeError(
            "SMTP is not configured. Set SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD in the .env file."
        )
    if not to_emails:
        raise ValueError("No valid recipient email addresses were provided.")

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM_EMAIL or SMTP_USERNAME
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    part = MIMEApplication(
        attachment_bytes,
        _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    part.add_header("Content-Disposition", "attachment", filename=attachment_filename)
    msg.attach(part)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL or SMTP_USERNAME, to_emails, msg.as_string())
