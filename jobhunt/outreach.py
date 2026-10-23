"""Write a short, personalised email per contact and save it as a Gmail DRAFT.

Nothing is ever sent automatically: you review each draft in Gmail and click Send.
If Gmail isn't set up, drafts are written as .eml files you can open in any mail app.
"""
import base64
import mimetypes
import re
from email.message import EmailMessage
from pathlib import Path

from pydantic import BaseModel

from . import llm
from .models import Contact, Job

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class Email(BaseModel):
    subject: str
    body: str


SYSTEM = """You write cold outreach emails from a job seeker to a recruiter or hiring \
manager about a specific open role.

Style: plain text, 90-140 words, warm and specific, no flattery, no buzzwords, no \
emojis, no "I hope this email finds you well". Mention the exact role, one or two \
concrete, relevant facts from the candidate's background (only facts present in the \
resume below), and a low-friction ask (a quick chat, or pointing to the right person). \
Say the tailored resume is attached. Sign off with the candidate's name, phone and \
LinkedIn. Subject line under 9 words, includes the role title.

CANDIDATE RESUME (YAML):
{master}
"""


def write(job: Job, contact: Contact, master_yaml: str, cfg: dict) -> Email:
    prompt = (f"Recipient: {contact.name}, {contact.title} at {contact.company}\n"
              f"Role: {job.title} ({job.location})\nJob link: {job.apply_url or job.url}\n\n"
              f"Job description:\n{job.description[:6000]}")
    return llm.structured(cfg, SYSTEM.format(master=master_yaml), prompt, Email, max_tokens=4000)


def build_message(to: str, sender: str, email: Email, attachment: Path | None) -> EmailMessage:
    msg = EmailMessage()
    msg["To"], msg["From"], msg["Subject"] = to, sender, email.subject
    msg.set_content(email.body)
    if attachment and attachment.exists():
        ctype = mimetypes.guess_type(attachment.name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(attachment.read_bytes(), maintype=maintype, subtype=subtype,
                           filename=attachment.name)
    return msg


def _gmail(cfg: dict):
    creds_path, token_path = cfg["paths"]["gmail_credentials"], cfg["paths"]["gmail_token"]
    if not creds_path.exists():
        return None
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES) if token_path.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES).run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def save_draft(msg: EmailMessage, cfg: dict, out_dir: Path) -> str:
    """Create a Gmail draft (preferred) or write an .eml file. Returns an id or path."""
    service = _gmail(cfg)
    if service is not None:
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return f"gmail:{draft['id']}"
    safe = re.sub(r"[^A-Za-z0-9]+", "_", f"{msg['To']}_{msg['Subject']}")[:90]
    path = out_dir / "emails" / f"{safe}.eml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(msg.as_bytes())
    return str(path)
