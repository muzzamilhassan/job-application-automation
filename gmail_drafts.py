#!/usr/bin/env python3
"""Stage 4a - Gmail DRAFTS. This module can never send mail; it only creates drafts.

One-time setup (see README section "Gmail drafts setup"):
  1. Google Cloud Console -> new project -> enable Gmail API
  2. OAuth consent screen (External, add yourself as test user)
  3. Credentials -> Create OAuth client ID -> Desktop app -> download credentials.json
     into this folder
  4. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
  5. python gmail_drafts.py --auth        (opens browser once, stores token.json)

Usage:
  python gmail_drafts.py --to a@b.com --subject "..." --body-file note.txt --attach cv.pdf
"""
import argparse
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOKEN = ROOT / "token.json"
CREDS = ROOT / "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]  # drafts only, no send


def get_service():
    try:
        from googleapiclient.discovery import build
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        sys.exit("Google libs missing. Run:\n  pip install google-api-python-client "
                 "google-auth-httplib2 google-auth-oauthlib")
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS.exists():
                sys.exit("credentials.json not found - see README 'Gmail drafts setup'.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
            # open_browser=False prints the auth URL instead: the CLI relays it
            # as a clickable link, which is more reliable than auto-opening.
            creds = flow.run_local_server(port=8068, open_browser=False)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)


def create_draft(to: str, subject: str, body: str, attachment=None, attachments=None) -> str:
    """Create a draft. attachment = single path (back-compat) or attachments = list."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication

    paths = []
    if attachment:
        paths.append(Path(attachment))
    for a in (attachments or []):
        paths.append(Path(a))

    msg = MIMEMultipart()
    msg["to"] = to
    msg["subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    for p in paths:
        if p.exists():
            part = MIMEApplication(p.read_bytes(), Name=p.name)
            part["Content-Disposition"] = f'attachment; filename="{p.name}"'
            msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = get_service().users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return draft["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", action="store_true", help="run one-time OAuth and exit")
    ap.add_argument("--to")
    ap.add_argument("--subject")
    ap.add_argument("--body-file")
    ap.add_argument("--attach")
    args = ap.parse_args()
    if args.auth:
        get_service()
        print("OAuth complete - token.json saved. Drafts can now be created.")
        return
    if not (args.to and args.subject and args.body_file):
        ap.error("need --to, --subject, --body-file (or use --auth first)")
    draft_id = create_draft(args.to, args.subject,
                            Path(args.body_file).read_text(encoding="utf-8"),
                            Path(args.attach) if args.attach else None)
    print(f"Draft created (id={draft_id}) - NOT sent. Review it in Gmail.")


if __name__ == "__main__":
    main()
