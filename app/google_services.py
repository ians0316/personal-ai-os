"""Google Calendar + Gmail: read your schedule and mail, write drafts (never sends).

Setup (once, by you):
  1. Create an OAuth client in Google Cloud (type "Web application") with the
     redirect URI http://localhost:8000/api/google/callback, and enable the
     Google Calendar API and Gmail API.
  2. Paste the client JSON in the Connections tab (saved to data/google_client.json).
  3. Click "Connect Google" and approve. The token is saved to data/google_token.json.

Permissions asked for: read calendars, read mail, and compose (create drafts).
There is deliberately no permission to send mail or change your calendar.
"""

import base64
import html
import json
import os
import re
import threading
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from pathlib import Path

from . import db

# oauthlib refuses plain http unless told otherwise; this app only runs on localhost.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
DATA_DIR = db.DB_PATH.parent
CLIENT_PATH = DATA_DIR / "google_client.json"
TOKEN_PATH = DATA_DIR / "google_token.json"
REDIRECT_URI = os.environ.get("AIOS_GOOGLE_REDIRECT", "http://localhost:8000/api/google/callback")

_lock = threading.Lock()
_pending_flows: dict = {}   # OAuth state -> Flow (holds the PKCE verifier between the two steps)
_services: dict = {}
_email_cache: dict = {}


class NotConnected(Exception):
    pass


# ---------- setup + sign-in ----------

def save_client_config(raw: str) -> None:
    cfg = json.loads(raw)
    inner = cfg.get("web") or cfg.get("installed")
    if not inner or not inner.get("client_id") or not inner.get("client_secret"):
        raise ValueError('That doesn\'t look like a Google OAuth client file (needs "web" or "installed" with client_id and client_secret).')
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_PATH.write_text(json.dumps(cfg))
    os.chmod(CLIENT_PATH, 0o600)


def has_client() -> bool:
    return CLIENT_PATH.exists()


def begin_auth() -> str:
    """Return the Google consent URL to send the user to."""
    if not has_client():
        raise NotConnected("Add your Google OAuth client first.")
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(json.loads(CLIENT_PATH.read_text()), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    with _lock:
        _pending_flows[state] = flow
    return url


def finish_auth(state: str, code: str) -> str:
    """Exchange the code Google sent back for a token. Returns the account email."""
    with _lock:
        flow = _pending_flows.pop(state, None)
    if flow is None:
        raise ValueError("Sign-in expired or was started elsewhere. Please click Connect again.")
    flow.fetch_token(code=code)
    _save_token(flow.credentials)
    _services.clear()
    _email_cache.clear()
    return account_email() or "your Google account"


def _save_token(creds) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    os.chmod(TOKEN_PATH, 0o600)


def _credentials():
    if not TOKEN_PATH.exists():
        raise NotConnected("Google isn't connected. Connect it in the Connections tab.")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                raise NotConnected(f"Google sign-in expired ({e}). Please reconnect in the Connections tab.")
            _save_token(creds)
        else:
            raise NotConnected("Google sign-in expired. Please reconnect in the Connections tab.")
    return creds


def _build(api: str, version: str):
    """Build (and cache) a Google API client. Tests replace this function."""
    key = (api, version)
    if key not in _services:
        from googleapiclient.discovery import build
        _services[key] = build(api, version, credentials=_credentials(), cache_discovery=False)
    return _services[key]


def connected() -> bool:
    return TOKEN_PATH.exists()


def account_email() -> str | None:
    if "email" not in _email_cache:
        try:
            _email_cache["email"] = _build("gmail", "v1").users().getProfile(userId="me").execute().get("emailAddress")
        except Exception:
            return None
    return _email_cache["email"]


def disconnect() -> None:
    """Forget the token locally and ask Google to revoke it."""
    if TOKEN_PATH.exists():
        try:
            import urllib.parse, urllib.request
            token = json.loads(TOKEN_PATH.read_text()).get("refresh_token") or json.loads(TOKEN_PATH.read_text()).get("token")
            if token:
                urllib.request.urlopen(urllib.request.Request(
                    "https://oauth2.googleapis.com/revoke",
                    data=urllib.parse.urlencode({"token": token}).encode(), method="POST"), timeout=10)
        except Exception:
            pass  # still remove it locally
        TOKEN_PATH.unlink()
    _services.clear()
    _email_cache.clear()


def status() -> dict:
    return {"client": has_client(), "connected": connected(),
            "email": account_email() if connected() else None, "redirect_uri": REDIRECT_URI}


# ---------- calendar ----------

def list_events(days_ahead: int = 7, days_back: int = 0, max_results: int = 50) -> list[dict]:
    now = datetime.now().astimezone()
    start = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0) if days_back else now
    end = now + timedelta(days=days_ahead)
    cal = _build("calendar", "v3")
    calendars = [c for c in cal.calendarList().list().execute().get("items", []) if c.get("selected", True)]
    events = []
    for c in calendars or [{"id": "primary", "summary": "Calendar"}]:
        items = cal.events().list(calendarId=c["id"], timeMin=start.isoformat(), timeMax=end.isoformat(),
                                  singleEvents=True, orderBy="startTime", maxResults=max_results).execute().get("items", [])
        for e in items:
            if e.get("status") == "cancelled":
                continue
            s, en = e.get("start", {}), e.get("end", {})
            events.append({
                "title": e.get("summary", "(no title)"),
                "start": s.get("dateTime") or s.get("date"),
                "end": en.get("dateTime") or en.get("date"),
                "all_day": "date" in s,
                "location": e.get("location"),
                "calendar": c.get("summary"),
                "attendees": len(e.get("attendees", [])),
                "link": e.get("htmlLink"),
            })
    events.sort(key=lambda e: e["start"] or "")
    return events[:max_results]


# ---------- gmail ----------

def _header(headers: list, name: str) -> str:
    return next((h["value"] for h in headers if h["name"].lower() == name.lower()), "")


def search_emails(query: str = "", max_results: int = 15) -> list[dict]:
    """Gmail search syntax works, e.g. "is:unread newer_than:1d" or "from:teacher"."""
    gm = _build("gmail", "v1")
    ids = gm.users().messages().list(userId="me", q=query or "in:inbox", maxResults=max_results).execute().get("messages", [])
    out = []
    for m in ids:
        msg = gm.users().messages().get(userId="me", id=m["id"], format="metadata",
                                        metadataHeaders=["From", "To", "Subject", "Date"]).execute()
        h = msg.get("payload", {}).get("headers", [])
        out.append({
            "id": msg["id"], "thread_id": msg.get("threadId"),
            "from": _header(h, "From"), "subject": _header(h, "Subject") or "(no subject)",
            "date": _header(h, "Date"), "snippet": html.unescape(msg.get("snippet", "")),
            "unread": "UNREAD" in msg.get("labelIds", []),
        })
    return out


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def _body_text(payload: dict) -> str:
    plain, rich = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_html_to_text(_decode(data)))
        for p in part.get("parts", []) or []:
            walk(p)

    walk(payload)
    return ("\n".join(plain) or "\n".join(rich)).strip()


def read_email(message_id: str, max_chars: int = 8000) -> dict:
    gm = _build("gmail", "v1")
    msg = gm.users().messages().get(userId="me", id=message_id, format="full").execute()
    p = msg.get("payload", {})
    h = p.get("headers", [])
    body = _body_text(p)
    out = {
        "id": msg["id"], "thread_id": msg.get("threadId"),
        "from": _header(h, "From"), "to": _header(h, "To"), "cc": _header(h, "Cc"),
        "subject": _header(h, "Subject"), "date": _header(h, "Date"),
        "body": body[:max_chars],
    }
    if len(body) > max_chars:
        out["truncated"] = True
    return out


def create_draft(to: str, subject: str, body: str, reply_to_id: str | None = None) -> dict:
    """Save a draft in Gmail. It is NOT sent; the user reviews and sends it from Gmail."""
    addrs = [a for _, a in getaddresses([to]) if "@" in a]
    if not addrs:
        raise ValueError(f"No valid email address in {to!r}")
    gm = _build("gmail", "v1")
    msg = EmailMessage()
    msg["To"] = ", ".join(addrs)
    msg["Subject"] = subject
    thread_id = None
    if reply_to_id:
        orig = gm.users().messages().get(userId="me", id=reply_to_id, format="metadata",
                                         metadataHeaders=["Message-ID", "References", "Subject"]).execute()
        oh = orig.get("payload", {}).get("headers", [])
        mid = _header(oh, "Message-ID")
        if mid:
            msg["In-Reply-To"] = mid
            msg["References"] = (_header(oh, "References") + " " + mid).strip()
        thread_id = orig.get("threadId")
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload = {"message": {"raw": raw, **({"threadId": thread_id} if thread_id else {})}}
    draft = gm.users().drafts().create(userId="me", body=payload).execute()
    return {"draft_id": draft["id"], "to": msg["To"], "subject": subject,
            "open_in_gmail": "https://mail.google.com/mail/u/0/#drafts", "sent": False}


def sender_name(from_header: str) -> str:
    name, addr = parseaddr(from_header)
    return name or addr
