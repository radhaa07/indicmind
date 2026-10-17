import os

# Load torch FIRST (before sklearn/stanza below): its OpenMP DLL loses any
# load-order race, which otherwise breaks Argos offline translation.
try:
    import torch  # noqa: F401
except Exception:
    pass

import sqlite3
import uuid
import json
import socket
from functools import wraps
from pathlib import Path
import random
import string
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for, send_file
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from gtts import gTTS
import tempfile
import re

try:
    # .env early: ARGOS_PACKAGE_DIR must exist before argos resolves its data dir.
    from dotenv import load_dotenv as _ld
    _ld(Path(__file__).resolve().parent / ".env")
except Exception:
    pass
try:
    # Load Argos BEFORE rag/sklearn: ctranslate2 pulls torch, whose DLLs only
    # win if nothing (numpy/MKL) claimed OpenMP first. Lazy import later = WinError 1114.
    import argostranslate.translate  # noqa: F401
except Exception:
    pass

from rag import DocumentRAG, _llm_call, extract_text, translate_to_english, compare_documents

MEMORY_TARGET_NAMES = {
    "hi": "hindi", "mr": "marathi", "bn": "bengali", "gu": "gujarati",
    "ta": "tamil india", "kn": "kannada", "te": "telugu", "ml": "malayalam",
    "pa": "punjabi", "ur": "urdu", "or": "odia", "as": "assamese",
    "fr": "french", "es": "spanish", "de": "german", "ar": "arabic",
    "zh": "chinese", "ja": "japanese", "ko": "korean", "pt": "portuguese", "ru": "russian",
}
INDIC_CODES = {"hi", "mr", "bn", "gu", "ta", "kn", "te", "ml", "pa", "ur", "or", "as"}
_INDIC_RANGES = [(0x0900, 0x097F), (0x0980, 0x09FF), (0x0A80, 0x0AFF),
                 (0x0B80, 0x0BFF), (0x0C00, 0x0C7F), (0x0C80, 0x0CFF), (0x0D00, 0x0D7F)]
INDIC_RE = "[" + "".join(chr(a) + "-" + chr(b) for a, b in _INDIC_RANGES) + "]"


def _chain_translator(target_code: str):
    """Google web first, MyMemory second (Google rate-limits with TooManyRequests).

    Returned object has .translate(text); failures raise only if both backends fail.
    """
    from deep_translator import GoogleTranslator
    name = MEMORY_TARGET_NAMES.get(target_code)
    mem = None
    if name:
        try:
            from deep_translator import MyMemoryTranslator
            mem = MyMemoryTranslator(source="english", target=name)
        except Exception:
            mem = None

    class _Chain:
        def translate(self, text):
            try:
                return GoogleTranslator(source="en", target=target_code).translate(text)
            except Exception as e:
                if mem is None:
                    raise
                import time as _t
                _t.sleep(0.5)
                return mem.translate(text)
    return _Chain()


def _restore_report_breaks(translated: str, source: str) -> str:
    """Translation backends (Google/MyMemory/LLM chunks) often flatten newlines,
    which renders as one giant paragraph. If the translated report lost most
    line breaks vs the source, re-split into readable blocks."""
    import re as _rx
    if not translated or not source:
        return translated
    if source.count("\n") < 6 or translated.count("\n") >= source.count("\n") * 0.5:
        return translated
    flat = _rx.sub(r"\s+", " ", translated).strip()
    sents = _rx.split(
        r"\s+(?=#{1,3}\s)"          # markdown headings
        r"|(?<=[.!?])\s+(?=[A-Z0-9#\-*\"'(])"  # sentence ends
        r"|\s+(?=[-*]\s+[A-Za-z0-9])"          # bullets
        r"|\s+(?=\d+\.\s+[A-Z])",              # numbered clauses
        flat)
    blocks, cur = [], ""
    for s in sents:
        s = s.strip()
        if not s:
            continue
        if _rx.match(r"(#{1,3}\s|[-*]\s|\d+\.\s+[A-Z])", s) or len(cur) > 600:
            if cur:
                blocks.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        blocks.append(cur)
    return "\n\n".join(blocks) if blocks else translated


def _looks_translated_indic(text: str) -> bool:
    """A real Indic translation carries script characters — plain English means the backends failed."""
    import re as _re
    return len(_re.findall(INDIC_RE, text or "")) >= 10


def _offline_translate_html_preserve(html: str, target_code: str) -> str | None:
    """Translate HTML preserving tags — batched text-node translation to avoid 429."""
    try:
        from deep_translator import GoogleTranslator
        import re, time
        if len(html) > 30000:
            html = html[:30000]
        tr = _chain_translator(target_code)
        parts = re.split(r'(<[^>]+>)', html)
        LABEL_RE = re.compile(r'^\s*(DATE|TIME|PERSON|NORP|ORG|GPE|LOC|FAC|MONEY|PERCENT|LAW|EVENT|PRODUCT|WORK_OF_ART)\s*$')
        # Collect indices of translatable text nodes
        text_idxs = []
        for i, p in enumerate(parts):
            if not p or p.startswith('<'):
                continue
            if LABEL_RE.match(p):
                continue
            if not p.strip():
                continue
            text_idxs.append(i)
        if not text_idxs:
            return html
        SEP = " __SEG__ "
        # Batch translate: group text nodes until ~3200 chars to keep 1-3 API calls total
        out_parts = parts[:]  # copy
        batch_indices = []
        batch_texts = []
        batch_len = 0
        from concurrent.futures import ThreadPoolExecutor as _HPool

        def _one_node(item):
            bi, orig = item
            try:
                return bi, tr.translate(orig)
            except Exception:
                return bi, orig

        def _nodes_parallel(pairs):
            if not pairs:
                return
            with _HPool(max_workers=min(4, len(pairs))) as _hp:
                for bi, trans in _hp.map(_one_node, pairs):
                    out_parts[bi] = trans

        def _flush_batch():
            if not batch_texts:
                return
            joined = SEP.join(batch_texts)
            try:
                translated_joined = tr.translate(joined)
                split_pat = re.compile(r'\s*__SEG__\s*')
                translated_splits = split_pat.split(translated_joined)
                if len(translated_splits) != len(batch_texts):
                    _nodes_parallel(list(zip(batch_indices, batch_texts)))
                else:
                    for bi, trans in zip(batch_indices, translated_splits):
                        out_parts[bi] = trans
            except Exception:
                # Batch failed (e.g. TranslationNotFound due to SEP), fallback per-node in parallel
                _nodes_parallel(list(zip(batch_indices, batch_texts)))
        for idx in text_idxs:
            txt = parts[idx]
            # very long node -> translate alone
            if len(txt) > 3500:
                _flush_batch()
                batch_indices = []
                batch_texts = []
                batch_len = 0
                # split long node into 3500 chunks at space boundary
                chunks = []
                remaining = txt
                while len(remaining) > 3500:
                    cut = remaining.rfind(" ", 0, 3500)
                    if cut == -1:
                        cut = 3500
                    chunks.append(remaining[:cut])
                    remaining = remaining[cut:].lstrip()
                chunks.append(remaining)
                with _HPool(max_workers=min(4, len(chunks))) as _hp:
                    translated_chunks = list(_hp.map(
                        lambda ch: _one_node((0, ch))[1], chunks))
                out_parts[idx] = "".join(translated_chunks)
                continue
            # try batching
            add_len = len(txt) + len(SEP)
            if batch_len + add_len > 3200 and batch_texts:
                _flush_batch()
                batch_indices = [idx]
                batch_texts = [txt]
                batch_len = len(txt)
            else:
                batch_indices.append(idx)
                batch_texts.append(txt)
                batch_len += add_len
        _flush_batch()
        result = "".join(out_parts)
        if "About India" in result[:800] and target_code in ('mr','hi','ta','kn','te','ml','bn','gu'):
            try:
                plain = re.sub(r'<[^>]+>', ' ', html)
                plain = re.sub(r'\s+', ' ', plain).strip()
                if plain:
                    trans_plain = tr.translate(plain[:3900])
                    if trans_plain and trans_plain != plain:
                        return f'<div style="background:#fff;border:1px solid #E6EFE9;border-radius:12px;padding:18px;line-height:1.8;font-size:14px;color:#122C2A">{trans_plain}</div>'
            except Exception:
                pass
        return result
    except Exception:
        return None

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
UPLOAD_DIR = BASE_DIR / "uploads"
DATABASE = BASE_DIR / "documentlens.db"
TTS_CACHE_DIR = BASE_DIR / "tts_cache"
UPLOAD_DIR.mkdir(exist_ok=True)
TTS_CACHE_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["TEMPLATES_AUTO_RELOAD"] = True  # Auto-reload templates in development
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-before-production")
oauth = OAuth(app)
if os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
    oauth.register(
        name="google",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

documents: dict[str, DocumentRAG] = {}
user_documents: dict[int, set[str]] = {}  # Track user's document IDs


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    with sqlite3.connect(DATABASE) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            original_text TEXT NOT NULL,
            analysis_json TEXT,
            report_markdown TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS magic_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT 'login',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS otp_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS report_translations (
            document_id TEXT NOT NULL,
            language TEXT NOT NULL,
            report_hash TEXT NOT NULL,
            translated_markdown TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (document_id, language)
        )""")


def preload_argos():
    """Warm the Argos offline engine in background at boot: the first import
    costs ~13s (stanza/onnx init) and must win any DLL-order race, so do it
    once here instead of inside a user request."""
    try:
        from argostranslate.translate import get_installed_languages
        codes = sorted({l.code for l in get_installed_languages()})
        print(f"[Boot] Argos offline ready: {codes}")
    except Exception as e:
        print(f"[Boot] Argos preload skipped: {e}")


import threading as _th
_th.Thread(target=preload_argos, daemon=True).start()


def warm_ollama():
    """Load the local model into memory at boot so the first question does
    not pay a ~25s cold-load penalty (qwen3:4b runs ~6 tok/s on CPU here)."""
    try:
        import requests as _rq
        _rq.post(os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/") + "/api/chat",
                 json={"model": os.getenv("OLLAMA_MODEL", "qwen3:4b"), "stream": False,
                       "think": False, "keep_alive": "30m",
                       "options": {"num_predict": 4},
                       "messages": [{"role": "user", "content": "ok"}]},
                 timeout=150)
        print("[Boot] Ollama model warm")
    except Exception as e:
        print(f"[Boot] Ollama warm skipped: {e}")


_th.Thread(target=warm_ollama, daemon=True).start()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            # API callers expect JSON, not a redirect to HTML login page (which breaks response.json())
            if request.path.startswith("/api/"):
                return jsonify(error="Session expired. Please sign in again."), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def generate_otp():
    """Generate a 6-digit OTP code."""
    return ''.join(random.choices(string.digits, k=6))


def _name_from_email(email: str) -> str:
    """Display name derived from the email local-part (editable later in Settings)."""
    local = (email or "").split("@", 1)[0]
    name = re.sub(r"[._\-+]+", " ", local).strip().title()
    return name or "Member"


def send_otp_email(email, otp_code):
    """Send a 6-digit code email (light branded theme)."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("FROM_EMAIL", smtp_user)

    if not smtp_user or not smtp_password:
        raise ValueError("Email configuration missing. Set SMTP_USER and SMTP_PASSWORD in .env")

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = email
    msg['Subject'] = "Your login code - IndicMind"

    body = f"""
    <html>
        <body style="margin:0;padding:0;background-color:#F7F9FD;font-family:'Plus Jakarta Sans',Arial,sans-serif;line-height:1.6;color:#0B1526;">
            <div style="max-width:600px;margin:0 auto;padding:24px 16px;">
                <div style="background-color:#0B1526;border-radius:16px 16px 0 0;padding:22px 28px;text-align:center;">
                    <div style="font-size:20px;font-weight:800;letter-spacing:-0.5px;color:#FFFFFF;">IndicMind</div>
                    <div style="font-size:10px;font-weight:700;letter-spacing:2px;color:#C3CAD6;">INDIAN LANGUAGES NER</div>
                </div>
                <div style="background-color:#FFFFFF;border:1px solid #E6EAF2;border-top:none;border-radius:0 0 16px 16px;padding:28px;">
                    <h2 style="margin:0 0 8px;font-size:22px;color:#0A1628;">Your login code</h2>
                    <p style="margin:0 0 16px;font-size:14px;color:#475569;">Hello,<br>Your one-time code for signing in to IndicMind document analysis is:</p>
                    <div style="background-color:#EEEAFF;border:1px solid #C9C0FF;border-radius:12px;padding:20px;text-align:center;margin:20px 0;">
                        <div style="font-size:36px;font-weight:800;letter-spacing:10px;margin:0;color:#3B32B0;">{otp_code}</div>
                    </div>
                    <p style="margin:0 0 6px;font-size:13px;color:#475569;">This code expires in <strong>10 minutes</strong>.</p>
                    <p style="margin:0;font-size:13px;color:#475569;">Didn&apos;t request this code? Just ignore this email.</p>
                    <hr style="border:none;border-top:1px solid #E6EAF2;margin:22px 0 14px;">
                    <p style="margin:0;font-size:11px;color:#94A3B8;text-align:center;">IndicMind for Indian Languages &middot; Zero-retention privacy</p>
                </div>
            </div>
        </body>
    </html>
    """

    msg.attach(MIMEText(body, 'html'))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True
    except Exception as e:
        app.logger.error(f"Failed to send OTP email: {e}")
        raise


def send_magic_link_email(email, name, link, mode):
    """Send a sign-in link email (light branded theme)."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("FROM_EMAIL", smtp_user)

    if not smtp_user or not smtp_password:
        raise ValueError("Email configuration missing. Set SMTP_USER and SMTP_PASSWORD in .env")

    heading = "Your sign-in link" if mode == "login" else "Confirm your email"
    intro = ("Click the button below to sign in to IndicMind document analysis."
             if mode == "login" else
             "Click the button below to verify this email and create your IndicMind account.")

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = email
    msg['Subject'] = f"{heading} - IndicMind"

    body = f"""
    <html>
        <body style="margin:0;padding:0;background-color:#F7F9FD;font-family:'Plus Jakarta Sans',Arial,sans-serif;line-height:1.6;color:#0B1526;">
            <div style="max-width:600px;margin:0 auto;padding:24px 16px;">
                <div style="background-color:#0B1526;border-radius:16px 16px 0 0;padding:22px 28px;text-align:center;">
                    <div style="font-size:20px;font-weight:800;letter-spacing:-0.5px;color:#FFFFFF;">IndicMind</div>
                    <div style="font-size:10px;font-weight:700;letter-spacing:2px;color:#C3CAD6;">INDIAN LANGUAGES NER</div>
                </div>
                <div style="background-color:#FFFFFF;border:1px solid #E6EAF2;border-top:none;border-radius:0 0 16px 16px;padding:28px;">
                    <h2 style="margin:0 0 8px;font-size:22px;color:#0A1628;">{heading}</h2>
                    <p style="margin:0 0 16px;font-size:14px;color:#475569;">Hello {name},<br>{intro}</p>
                    <div style="text-align:center;margin:22px 0;">
                        <a href="{link}" style="display:inline-block;background-color:#6C5CFF;color:#FFFFFF;font-size:16px;font-weight:800;text-decoration:none;padding:14px 36px;border-radius:12px;">Open my workspace &rarr;</a>
                    </div>
                    <p style="margin:0 0 6px;font-size:13px;color:#475569;">This link expires in <strong>15 minutes</strong> and works only once.</p>
                    <p style="margin:0;font-size:13px;color:#475569;">Didn&apos;t request this? Just ignore this email.</p>
                    <hr style="border:none;border-top:1px solid #E6EAF2;margin:22px 0 14px;">
                    <p style="margin:0;font-size:11px;color:#94A3B8;text-align:center;">IndicMind for Indian Languages &middot; Zero-retention privacy</p>
                </div>
            </div>
        </body>
    </html>
    """

    msg.attach(MIMEText(body, 'html'))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True
    except Exception as e:
        app.logger.error(f"Failed to send magic-link email: {e}")
        raise


_cached_lan_ip = {"ip": None}


def _server_lan_ip():
    """This machine's LAN IP (what ipconfig shows) — cached. Phones on the
    same Wi-Fi reach the app through it; 127.0.0.1 would be dead on mobile."""
    if _cached_lan_ip["ip"]:
        return _cached_lan_ip["ip"]
    try:
        import socket as _s
        sk = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        sk.connect(("8.8.8.8", 80))
        _cached_lan_ip["ip"] = sk.getsockname()[0]
        sk.close()
    except Exception:
        _cached_lan_ip["ip"] = None
    return _cached_lan_ip["ip"]


def _is_loopback(addr):
    return (addr or "") in ("127.0.0.1", "::1", "localhost")


def send_magic_link(email, name, mode):
    """Create a single-use login link and email it. Invalidates older links."""
    import hashlib
    import secrets
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    db = get_db()
    db.execute("UPDATE magic_links SET used = 1 WHERE email = ? AND used = 0", (email,))
    expires_at = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
    db.execute(
        "INSERT INTO magic_links (email, token_hash, name, mode, expires_at) VALUES (?, ?, ?, ?, ?)",
        (email, digest, name, mode, expires_at)
    )
    db.commit()
    # Link host auto-pick by client (explicit APP_BASE_URL only rules the
    # public-internet case):
    # - same-machine browser -> APP_BASE_URL, else its own request host
    # - phone / LAN device   -> http://<server-LAN-ip>:<port> (127.0.0.1 is
    #                           dead on mobile; works for any same-Wi-Fi device)
    # - public internet      -> APP_BASE_URL, else its own request host
    base = None
    remote = request.remote_addr or ""
    try:
        import ipaddress as _ipa
        _rip = _ipa.ip_address(remote)
        _is_private = _rip.is_private and not _rip.is_loopback
    except Exception:
        _is_private = False
    if _is_private:
        lan_ip = _server_lan_ip()
        if lan_ip:
            port = (request.host or "").rsplit(":", 1)
            port = port[1] if len(port) == 2 and port[1].isdigit() else "5000"
            base = f"http://{lan_ip}:{port}"
    if not base:
        base = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/") or None
    if base:
        link = f"{base}/auth/magic?token={token}"
    else:
        link = url_for("magic_auth", token=token, _external=True)
    print(f"[Auth] Magic link for {email}: {link}")
    send_magic_link_email(email, name, link, mode)
    return True


def store_otp(email, otp_code):
    """Store OTP in database with expiration."""
    db = get_db()
    expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    
    # Invalidate old OTPs for this email
    db.execute("UPDATE otp_codes SET used = 1 WHERE email = ? AND used = 0", (email,))
    
    # Store new OTP
    db.execute(
        "INSERT INTO otp_codes (email, otp_code, expires_at) VALUES (?, ?, ?)",
        (email, otp_code, expires_at)
    )
    db.commit()


def verify_otp(email, otp_code):
    """Verify OTP code for email."""
    db = get_db()
    now = datetime.utcnow().isoformat()
    
    row = db.execute(
        "SELECT * FROM otp_codes WHERE email = ? AND otp_code = ? AND used = 0 AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
        (email, otp_code, now)
    ).fetchone()
    
    if row:
        # Mark OTP as used
        db.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
        db.commit()
        return True
    
    return False


# --- PAGE ROUTES ---

@app.get("/")
def index():
    if "user_id" in session:
        return redirect(url_for("app_workspace"))
    return render_template("landing.html")


@app.get("/landing")
def landing():
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:4b")
    return render_template("landing.html", ollama_model=ollama_model)


@app.get("/app")
@login_required
def app_workspace():
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:4b")
    return render_template("index.html", ollama_model=ollama_model)


@app.get("/documents")
@login_required
def documents_page():
    return render_template("documents.html")


@app.get("/compare")
@login_required
def compare_page():
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:4b")
    return render_template("compare.html", ollama_model=ollama_model)


@app.get("/settings")
@login_required
def settings_page():
    return render_template("settings.html")


@app.get("/security")
def security_page():
    return render_template("security.html", section="security")


@app.get("/privacy")
def privacy_page():
    return render_template("security.html", section="privacy")


@app.get("/terms")
def terms_page():
    return render_template("security.html", section="terms")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        action = request.form.get("action", "send_link")
        email = request.form.get("email", "").strip().lower()

        if not email or "@" not in email:
            flash("Please enter a valid email address.", "error")
            return render_template("auth.html", mode="login")

        if action == "send_otp":
            try:
                user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if not user:
                    flash("No account found with this email. Please create an account first.", "error")
                    return render_template("auth.html", mode="login")
                otp_code = generate_otp()
                send_otp_email(email, otp_code)
                store_otp(email, otp_code)
                return render_template("auth.html", mode="login", otp_sent=True, email=email)
            except Exception as e:
                app.logger.error(f"OTP send failed: {e}")
                flash("Could not send the code. Please check your email configuration and retry.", "error")
                return render_template("auth.html", mode="login")

        if action == "verify_otp":
            otp_code = request.form.get("otp", "").strip()
            if not otp_code:
                flash("Please enter the 6-digit code.", "error")
                return render_template("auth.html", mode="login", otp_sent=True, email=email)
            if verify_otp(email, otp_code):
                user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if user:
                    session.clear()
                    session["user_id"] = user["id"]
                    session["user_name"] = user["name"]
                    return redirect(url_for("index"))
                flash("Account not found.", "error")
            else:
                flash("Invalid or expired code. Please try again.", "error")
                return render_template("auth.html", mode="login", otp_sent=True, email=email)

        try:
            user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not user:
                flash("No account found with this email. Please create an account first.", "error")
                return render_template("auth.html", mode="login")

            send_magic_link(email, name=user["name"], mode="login")
            return render_template("auth.html", mode="login", link_sent=True, email=email)
        except Exception as e:
            app.logger.error(f"Magic-link send failed: {e}")
            flash("Could not send the login link. Please check your email configuration and retry.", "error")
            return render_template("auth.html", mode="login")

    return render_template("auth.html", mode="login")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        action = request.form.get("action", "send_link")
        email = request.form.get("email", "").strip().lower()

        if not email or "@" not in email:
            flash("Please enter a valid email address.", "error")
            return render_template("auth.html", mode="register")

        if action == "send_otp":
            try:
                existing = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if existing:
                    flash("An account already exists for that email. Try signing in.", "error")
                    return render_template("auth.html", mode="register")
                otp_code = generate_otp()
                send_otp_email(email, otp_code)
                store_otp(email, otp_code)
                return render_template("auth.html", mode="register", otp_sent=True, email=email)
            except Exception as e:
                app.logger.error(f"OTP send failed: {e}")
                flash("Could not send the code. Please check your email configuration and retry.", "error")
                return render_template("auth.html", mode="register")

        if action == "verify_otp":
            otp_code = request.form.get("otp", "").strip()
            if not otp_code:
                flash("Please enter the 6-digit code.", "error")
                return render_template("auth.html", mode="register", otp_sent=True, email=email)
            if verify_otp(email, otp_code):
                try:
                    name = _name_from_email(email)
                    db = get_db()
                    cursor = db.execute(
                        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                        (name, email, generate_password_hash(uuid.uuid4().hex))
                    )
                    db.commit()
                    session.clear()
                    session["user_id"] = cursor.lastrowid
                    session["user_name"] = name
                    return redirect(url_for("index"))
                except sqlite3.IntegrityError:
                    flash("An account already exists for that email. Try signing in.", "error")
            else:
                flash("Invalid or expired code. Please try again.", "error")
                return render_template("auth.html", mode="register", otp_sent=True, email=email)

        try:
            existing_user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if existing_user:
                flash("An account already exists for that email. Try signing in.", "error")
                return render_template("auth.html", mode="register")

            send_magic_link(email, name=_name_from_email(email), mode="register")
            return render_template("auth.html", mode="register", link_sent=True, email=email)
        except Exception as e:
            app.logger.error(f"Magic-link send failed: {e}")
            flash("Could not send the sign-in link. Please check your email configuration and retry.", "error")
            return render_template("auth.html", mode="register")

    return render_template("auth.html", mode="register")


@app.get("/auth/magic")
def magic_auth():
    """Verify a single-use sign-in link and start the session."""
    import hashlib
    token = (request.args.get("token") or "").strip()
    if not token:
        flash("That sign-in link is invalid. Please request a fresh one.", "error")
        return redirect(url_for("login"))
    digest = hashlib.sha256(token.encode()).hexdigest()
    db = get_db()
    row = db.execute(
        "SELECT * FROM magic_links WHERE token_hash = ? AND used = 0 AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
        (digest, datetime.utcnow().isoformat())
    ).fetchone()
    if not row:
        flash("That sign-in link is invalid or expired. Please request a fresh one.", "error")
        return redirect(url_for("login"))
    db.execute("UPDATE magic_links SET used = 1 WHERE id = ?", (row["id"],))
    db.commit()

    email = row["email"]
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        if (row["mode"] or "login") != "register":
            flash("No account found with this email. Please create an account first.", "error")
            return redirect(url_for("login"))
        try:
            name = row["name"] or _name_from_email(email)
            cursor = db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(uuid.uuid4().hex))
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        except sqlite3.IntegrityError:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        flash("Account not found.", "error")
        return redirect(url_for("login"))
    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("index"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/auth/google")
def google_login():
    if not hasattr(oauth, "google"):
        flash("Google Sign-In needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your local .env file.", "error")
        return redirect(url_for("login"))
    return oauth.google.authorize_redirect(url_for("google_callback", _external=True))


@app.get("/auth/google/callback")
def google_callback():
    if request.args.get("error"):
        reason = request.args.get("error", "unknown_error")
        flash(f"Google Sign-In was cancelled or blocked ({reason}).", "error")
        return redirect(url_for("login"))
    try:
        token = oauth.google.authorize_access_token()
        profile = oauth.google.userinfo(token=token)
        email = (profile.get("email") or "").strip().lower()
        if not email or not profile.get("email_verified", True):
            raise ValueError("Google did not provide a verified email address.")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            name = profile.get("name") or profile.get("given_name") or email.split("@", 1)[0]
            cursor = db.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                                (name, email, generate_password_hash(uuid.uuid4().hex)))
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        return redirect(url_for("index"))
    except OAuthError as exc:
        app.logger.warning("Google OAuth error: %s", exc.error)
        flash(f"Google rejected the sign-in request ({exc.error}). Check the callback URL and OAuth client type.", "error")
        return redirect(url_for("login"))
    except Exception:
        app.logger.exception("Google Sign-In callback failed")
        flash("Google Sign-In could not be completed. Confirm the redirect URL and OAuth credentials, then try again.", "error")
        return redirect(url_for("login"))


@app.get("/auth/<provider>")
def sso_placeholder(provider):
    if provider != "microsoft":
        return redirect(url_for("login"))
    flash("Microsoft SSO is ready in the interface. Add its OAuth client ID and secret to enable it.", "info")
    return redirect(url_for("login"))


# --- DOCUMENTS MANAGEMENT APIs ---

@app.get("/api/documents")
@login_required
def list_documents():
    db = get_db()
    rows = db.execute(
        "SELECT id, filename, file_type, analysis_json, created_at FROM documents WHERE user_id = ? ORDER BY created_at DESC",
        (session["user_id"],)
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if item.get("analysis_json"):
            try:
                analysis = json.loads(item["analysis_json"])
                meta = analysis.get("metadata", {})
                item["agreement_type"] = meta.get("agreement_type", "Agreement")
                item["risk_level"] = meta.get("overall_risk_level", "Medium")
                item["parties"] = meta.get("parties", [])
                item["language"] = meta.get("original_language", "English")
            except Exception:
                item["risk_level"] = "Medium"
        else:
            item["risk_level"] = "Medium"
        result.append(item)
    return jsonify(result)


@app.get("/api/stats")
@login_required
def user_stats():
    """Aggregate statistics for user's documents dashboard."""
    db = get_db()
    rows = db.execute(
        "SELECT analysis_json, file_type, created_at FROM documents WHERE user_id = ?",
        (session["user_id"],)
    ).fetchall()
    total = len(rows)
    high_risk = 0
    med_risk = 0
    low_risk = 0
    languages = set()
    file_types = {}
    
    for r in rows:
        ft = (r["file_type"] or "txt").upper()
        file_types[ft] = file_types.get(ft, 0) + 1
        if r["analysis_json"]:
            try:
                a = json.loads(r["analysis_json"])
                risk = a.get("metadata", {}).get("overall_risk_level", "Medium")
                lang = a.get("metadata", {}).get("original_language", "English")
                if lang:
                    languages.add(lang)
                if risk == "High":
                    high_risk += 1
                elif risk == "Low":
                    low_risk += 1
                else:
                    med_risk += 1
            except Exception:
                med_risk += 1
        else:
            med_risk += 1
            
    return jsonify(
        total_documents=total,
        high_risk=high_risk,
        medium_risk=med_risk,
        low_risk=low_risk,
        languages_count=len(languages) if languages else 1,
        file_types=file_types
    )


@app.post("/api/documents/compare")
@login_required
def api_compare_documents():
    """Side-by-side document comparison endpoint."""
    file_a = request.files.get("document_a")
    file_b = request.files.get("document_b")
    id_a = request.form.get("document_id_a")
    id_b = request.form.get("document_id_b")
    provider = request.form.get("provider", "auto")

    text_a, name_a = "", ""
    text_b, name_b = "", ""
    db = get_db()

    # Load Document A
    if id_a:
        row = db.execute("SELECT * FROM documents WHERE id = ? AND user_id = ?", (id_a, session["user_id"])).fetchone()
        if row:
            text_a, name_a = row["original_text"], row["filename"]
    if not text_a and file_a and file_a.filename:
        suffix = Path(file_a.filename).suffix.lower()
        if suffix in {".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            temp_path = UPLOAD_DIR / f"temp_comp_a_{uuid.uuid4()}{suffix}"
            file_a.save(temp_path)
            try:
                text_a = extract_text(temp_path)
                name_a = file_a.filename
            finally:
                temp_path.unlink(missing_ok=True)

    # Load Document B
    if id_b:
        row = db.execute("SELECT * FROM documents WHERE id = ? AND user_id = ?", (id_b, session["user_id"])).fetchone()
        if row:
            text_b, name_b = row["original_text"], row["filename"]
    if not text_b and file_b and file_b.filename:
        suffix = Path(file_b.filename).suffix.lower()
        if suffix in {".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            temp_path = UPLOAD_DIR / f"temp_comp_b_{uuid.uuid4()}{suffix}"
            file_b.save(temp_path)
            try:
                text_b = extract_text(temp_path)
                name_b = file_b.filename
            finally:
                temp_path.unlink(missing_ok=True)

    if not text_a or not text_b:
        return jsonify(error="Please provide two valid documents to compare."), 400

    try:
        eng_a, _ = translate_to_english(text_a, provider=provider)
        eng_b, _ = translate_to_english(text_b, provider=provider)

        rag_a = DocumentRAG(text=eng_a, filename=name_a, provider=provider)
        rag_b = DocumentRAG(text=eng_b, filename=name_b, provider=provider)

        comparison_results = compare_documents(rag_a, rag_b, provider=provider)
        return jsonify(comparison_results)
    except Exception as e:
        app.logger.error(f"Document comparison error: {e}")
        return jsonify(error=f"Comparison failed: {str(e)}"), 500


@app.get("/api/settings/diagnostics")
@login_required
def api_diagnostics():
    """Diagnostic check for connected AI models and integrations."""
    gemini_key = bool(os.getenv("GEMINI_API_KEY"))
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    ollama_ready = False
    try:
        host_port = ollama_host.split("://", 1)[-1].split("/", 1)[0]
        host, port = host_port.rsplit(":", 1)
        with socket.create_connection((host, int(port)), timeout=0.8):
            ollama_ready = True
    except (OSError, ValueError):
        ollama_ready = False
    
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:4b")
    return jsonify(
        gemini_configured=gemini_key,
        gemini_model=gemini_model,
        ollama_host=ollama_host,
        ollama_model=ollama_model,
        ollama_ready=ollama_ready,
        smtp_configured=bool(os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD")),
        google_oauth_configured=bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))
    )


@app.get("/api/providers")
@login_required
def provider_status():
    """Expose safe, non-secret provider readiness information to the upload UI."""
    ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:4b")
    try:
        host_port = ollama_host.split("://", 1)[-1].split("/", 1)[0]
        host, port = host_port.rsplit(":", 1)
        with socket.create_connection((host, int(port)), timeout=0.8):
            ollama_ready = True
    except (OSError, ValueError):
        ollama_ready = False
    return jsonify(gemini_configured=bool(os.getenv("GEMINI_API_KEY")), gemini_valid=gemini_key_valid(),
                   ollama_ready=ollama_ready, ollama_model=ollama_model)


_gemini_valid_cache = {"ts": 0.0, "ok": None}


def gemini_key_valid():
    """Cheap live check: list models (no generation cost). Cached 10 min.
    Returns True/False, or None when offline/unknown (never cry invalid)."""
    import time as _t
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    if _t.time() - _gemini_valid_cache["ts"] < 600 and _gemini_valid_cache["ok"] is not None:
        return _gemini_valid_cache["ok"]
    try:
        import requests as _rq
        r = _rq.get("https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": key}, timeout=5)
        ok = r.status_code == 200
    except Exception:
        return None
    _gemini_valid_cache["ts"] = _t.time()
    _gemini_valid_cache["ok"] = ok
    return ok


@app.get("/api/documents/<document_id>")
@login_required
def get_document(document_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM documents WHERE id = ? AND user_id = ?",
        (document_id, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify(error="Document not found."), 404
        
    if document_id not in documents:
        rag = DocumentRAG(text=row["original_text"], filename=row["filename"])
        documents[document_id] = rag
        
    analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else {}
    # Self-heal stale analyses: rows baked before the entity-correction rules
    # show raw/mislabelled marks AND stale entity grids. Current template is
    # stamped <!--mner-ner-v2-->; anything with marks but no stamp regenerates
    # once (fast, local) and the fix is saved back.
    _ner = (analysis.get("ner_highlighted_html") or "")
    _stale_marks = ("mner-ner-v2" not in _ner) and (
        "<mark" in _ner or "border-radius:4px" in _ner
        or "border-radius:3px" in _ner or "font-size:9px" in _ner
        or "What is NER?" not in _ner)
    if _stale_marks:
        try:
            _rag = documents.get(document_id)
            if _rag is None:
                _rag = DocumentRAG(text=row["original_text"], filename=row["filename"])
                documents[document_id] = _rag
            _healed = False
            _fresh = _rag.get_ner_highlighted_html()
            if _fresh and "mner-ner-v2" in _fresh:
                analysis["ner_highlighted_html"] = _fresh
                _healed = True
            try:
                _fresh_ents = _rag.entity_scan()
                # Replace only on non-empty (very old rows may store
                # source-language text that scans poorly — keep those).
                if _fresh_ents and any(e.get("values") for e in _fresh_ents):
                    analysis["entities"] = _fresh_ents
                    _healed = True
            except Exception:
                pass
            if _healed:
                db.execute("UPDATE documents SET analysis_json = ? WHERE id = ? AND user_id = ?",
                           (json.dumps(analysis), document_id, session["user_id"]))
                db.commit()
        except Exception as e:
            app.logger.error(f"NER self-heal failed: {e}")
    return jsonify(
        id=row["id"],
        filename=row["filename"],
        file_type=row["file_type"],
        created_at=row["created_at"],
        analysis=analysis,
        report=row["report_markdown"]
    )


@app.post("/api/documents/<document_id>/reanalyze")
@login_required
def reanalyze_document(document_id):
    """Refresh a saved document using the current extraction and audit rules."""
    db = get_db()
    row = db.execute(
        "SELECT * FROM documents WHERE id = ? AND user_id = ?",
        (document_id, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify(error="Document not found."), 404

    provider = (request.json or {}).get("provider", "auto")
    # Older saved multilingual uploads may contain their original language.
    # Translate and verify again before refreshing their RAG index.
    english_text, detected_language = translate_to_english(row["original_text"], provider=provider)
    rag = DocumentRAG(text=english_text, filename=row["filename"])
    documents[document_id] = rag
    analysis, report = _build_entity_result(rag, row["filename"], detected_language)
    previous = json.loads(row["analysis_json"]) if row["analysis_json"] else {}
    if analysis["metadata"].get("original_language") == "English":
        analysis["metadata"]["original_language"] = previous.get("metadata", {}).get("original_language", "English")
    db.execute(
        "UPDATE documents SET original_text = ?, analysis_json = ?, report_markdown = ? WHERE id = ? AND user_id = ?",
        (english_text, json.dumps(analysis), report, document_id, session["user_id"])
    )
    db.commit()
    return jsonify(id=document_id, filename=row["filename"], analysis=analysis, report=report)


# Cache of translated reports: (doc_id, language, mode) -> {"report_hash":..., "resp": {...}}
_TRANSLATE_CACHE = {}


@app.post("/api/documents/<document_id>/translate-report")
@login_required
def translate_report(document_id):
    """Translate the completed plain-language report without changing its analysis."""
    target_language = (request.json or {}).get("language", "").strip()
    provider = (request.json or {}).get("provider", "gemini")
    if not target_language or len(target_language) > 60:
        return jsonify(error="Enter a valid language name, for example Tamil, Hindi, French, or Arabic."), 400
    db = get_db()
    row = db.execute(
        "SELECT report_markdown, analysis_json, original_text, filename FROM documents WHERE id = ? AND user_id = ?",
        (document_id, session["user_id"])
    ).fetchone()
    if not row or not row["report_markdown"]:
        return jsonify(error="The report is not available. Analyze the document first."), 404
    # Repeat clicks are instant: validated cache keyed on report content hash.
    import hashlib as _hl
    _rep_hash = _hl.md5(row["report_markdown"].encode("utf-8")).hexdigest()
    _ckey = (document_id, target_language.lower().strip(),
             os.getenv("TRANSLATION_PROVIDER", "auto").lower())
    _hit = _TRANSLATE_CACHE.get(_ckey)
    if _hit and _hit.get("report_hash") == _rep_hash:
        return jsonify(_hit["resp"])
    # Persistent cache: repeats stay instant across server restarts.
    try:
        _dbhit = db.execute(
            "SELECT translated_markdown FROM report_translations WHERE document_id = ? AND language = ? AND report_hash = ?",
            (document_id, target_language.lower().strip(), _rep_hash)).fetchone()
        if _dbhit and _dbhit["translated_markdown"]:
            _resp_db = {"report": _dbhit["translated_markdown"], "language": target_language, "provider": "cache"}
            _TRANSLATE_CACHE[_ckey] = {"report_hash": _rep_hash, "resp": _resp_db}
            return jsonify(_resp_db)
    except Exception:
        pass
    system = (
        f"Translate this document report into {target_language}. Preserve every fact, number, date, amount, clause reference, "
        "Markdown heading, bullet, and bold marker. Do not summarize, omit information, or add commentary. "
        "Return only the translated Markdown report."
    )
    # OFFLINE-FIRST when TRANSLATION_PROVIDER=offline — save Gemini tokens, no 429 retries
    offline_mode = os.getenv("TRANSLATION_PROVIDER", "auto").lower() == "offline"
    translated = None
    used_provider = "offline" if offline_mode else provider
    if offline_mode:
        try:
            _lm = {"hindi":"hi","tamil":"ta","kannada":"kn","telugu":"te","malayalam":"ml","bengali":"bn","marathi":"mr","gujarati":"gu","punjabi":"pa","urdu":"ur","oriya":"or","odia":"or","assamese":"as","french":"fr","spanish":"es","german":"de","arabic":"ar","chinese":"zh","japanese":"ja","korean":"ko","portuguese":"pt","russian":"ru"}
            _code = _lm.get(target_language.lower().strip(), target_language[:2].lower())
            from deep_translator import GoogleTranslator
            # Chunk by paragraphs to preserve word/heading boundaries and avoid concatenated Marathi like "एकाष्टीक्षेपातदस्तऐवज"
            _text = row["report_markdown"]
            def _chunk_by_paragraph(t, lim=3400):
                paras = t.split("\n")
                cur = ""
                for p in paras:
                    if len(cur) + len(p) + 1 <= lim:
                        cur += ("\n" if cur else "") + p
                    else:
                        if cur:
                            yield cur
                        # long single para: hard split at space boundary
                        while len(p) > lim:
                            cut = p.rfind(" ", 0, lim)
                            if cut == -1:
                                cut = lim
                            yield p[:cut]
                            p = p[cut:].lstrip()
                        cur = p
                if cur:
                    yield cur
            _chunks = list(_chunk_by_paragraph(_text))
            from concurrent.futures import ThreadPoolExecutor as _Pool
            _tr = _chain_translator(_code)

            def _one(_ch):
                try:
                    return _tr.translate(_ch)
                except Exception:
                    # Heading-only chunks like '## Document at a glance' raise TranslationNotFound; retry without markdown symbols
                    try:
                        cleaned = re.sub(r'^#+\s*', '', _ch, flags=re.M)
                        cleaned = re.sub(r'\*\*', '', cleaned)
                        if cleaned.strip() and cleaned != _ch:
                            return _tr.translate(cleaned)
                    except Exception:
                        pass
                    return _ch

            # Independent chunks in parallel (~4x faster than one-by-one)
            with _Pool(max_workers=min(4, len(_chunks) or 1)) as _pool:
                _out = list(_pool.map(_one, _chunks))
            _maybe = "\n".join(_out)
            # Honesty guard: English text is NOT a Kannada/Hindi/... translation —
            # both backends failed, so fall through instead of faking success.
            if _maybe and len(_maybe.strip()) > 20 and (
                    _code not in INDIC_CODES or _looks_translated_indic(_maybe)):
                translated = _maybe
                used_provider = "offline"
        except Exception:
            pass
    if not translated:
        # Try LLM (Gemini/Ollama) only if not offline
        try:
            translated, used_provider = _llm_call(system, row["report_markdown"], provider)
        except ValueError:
            pass
        if not translated and provider != "auto" and not offline_mode:
            try:
                translated, used_provider = _llm_call(system, row["report_markdown"], "auto")
            except ValueError:
                pass
        # Final offline fallback if LLM still failed
        if not translated:
            try:
                _lm2 = {"hindi":"hi","tamil":"ta","kannada":"kn","telugu":"te","malayalam":"ml","bengali":"bn","marathi":"mr","gujarati":"gu","punjabi":"pa","urdu":"ur","oriya":"or","odia":"or","assamese":"as","french":"fr","spanish":"es","german":"de","arabic":"ar","chinese":"zh","japanese":"ja","korean":"ko","portuguese":"pt","russian":"ru"}
                _code2 = _lm2.get(target_language.lower().strip(), target_language[:2].lower())
                from deep_translator import GoogleTranslator as _GT2
                _text2 = row["report_markdown"]
                def _chunk_by_paragraph2(t, lim=3400):
                    paras = t.split("\n")
                    cur = ""
                    for p in paras:
                        if len(cur) + len(p) + 1 <= lim:
                            cur += ("\n" if cur else "") + p
                        else:
                            if cur:
                                yield cur
                            while len(p) > lim:
                                cut = p.rfind(" ", 0, lim)
                                if cut == -1:
                                    cut = lim
                                yield p[:cut]
                                p = p[cut:].lstrip()
                            cur = p
                    if cur:
                        yield cur
                _chunks2 = list(_chunk_by_paragraph2(_text2))
                from concurrent.futures import ThreadPoolExecutor as _Pool2
                _tr2 = _chain_translator(_code2)

                def _one2(_ch):
                    try:
                        return _tr2.translate(_ch)
                    except Exception:
                        try:
                            cleaned2 = re.sub(r'^#+\s*', '', _ch, flags=re.M)
                            cleaned2 = re.sub(r'\*\*', '', cleaned2)
                            if cleaned2.strip() and cleaned2 != _ch:
                                return _tr2.translate(cleaned2)
                        except Exception:
                            pass
                        return _ch

                with _Pool2(max_workers=min(4, len(_chunks2) or 1)) as _pool2:
                    _out2 = list(_pool2.map(_one2, _chunks2))
                _maybe2 = "\n".join(_out2)
                if _maybe2 and len(_maybe2.strip()) > 20 and (
                        _code2 not in INDIC_CODES or _looks_translated_indic(_maybe2)):
                    translated = _maybe2
                    used_provider = "offline"
            except Exception:
                pass
    if not translated:
        # Last resort: local Ollama — no quota, no rate limits. Chunked with
        # generous timeouts: one shot times out on big reports (60s per call).
        try:
            import requests as _rq
            _oh = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
            _om2 = os.getenv("OLLAMA_MODEL", "qwen3:4b")
            _chunks_o, _cur_o = [], ""
            for _para in row["report_markdown"].split("\n"):
                if len(_cur_o) + len(_para) + 1 <= 1200:
                    _cur_o += ("\n" if _cur_o else "") + _para
                else:
                    if _cur_o:
                        _chunks_o.append(_cur_o)
                    _cur_o = _para
            if _cur_o:
                _chunks_o.append(_cur_o)
            _out_o, _ok_o = [], True
            import time as _tt2
            _ollama_until = _tt2.time() + 240  # overall cap for this fallback
            for _ch in _chunks_o:
                if _tt2.time() > _ollama_until:
                    app.logger.error("Ollama fallback translation timed out, giving up")
                    _ok_o = False
                    break
                _r = _rq.post(_oh + "/api/chat", json={
                    "model": _om2, "stream": False, "think": False,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": _ch}]}, timeout=120)
                _r.raise_for_status()
                _txt = (_r.json().get("message") or {}).get("content", "")
                if not _txt.strip():
                    _ok_o = False
                    break
                _out_o.append(_txt)
            _maybe_o = "\n".join(_out_o)
            _indic_names = {"hindi", "tamil", "kannada", "telugu", "malayalam", "bengali",
                            "marathi", "gujarati", "punjabi", "urdu", "odia", "oriya", "assamese"}
            if _ok_o and _maybe_o and len(_maybe_o.strip()) > 20 and (
                    target_language.lower().strip() not in _indic_names
                    or _looks_translated_indic(_maybe_o)):
                translated = _maybe_o
                used_provider = "ollama"
        except Exception as e:
            app.logger.error(f"Ollama fallback translation failed: {e}")
    if not translated:
        _om = os.getenv("OLLAMA_MODEL", "qwen3:4b")
        return jsonify(error=f"Report translation is unavailable. Gemini quota hit and offline fallback failed. Try again or pick Ollama Local ({_om}) which runs on this machine."), 503
    # Also translate NER highlighted view (3rd-image pattern) so it doesn't stay English
    ner_translated = None
    if offline_mode:
        try:
            rag2 = documents.get(document_id)
            if not rag2:
                rag2 = DocumentRAG(text=row["original_text"], filename=row["filename"] or "document")
            ner_html2 = rag2.get_ner_highlighted_html()
            if ner_html2:
                _lm3 = {"hindi":"hi","tamil":"ta","kannada":"kn","telugu":"te","malayalam":"ml","bengali":"bn","marathi":"mr","gujarati":"gu","punjabi":"pa","urdu":"ur","oriya":"or","odia":"or","assamese":"as","french":"fr","spanish":"es","german":"de","arabic":"ar","chinese":"zh","japanese":"ja","korean":"ko","portuguese":"pt","russian":"ru"}
                _code3 = _lm3.get(target_language.lower().strip(), target_language[:2].lower())
                ner_translated = _offline_translate_html_preserve(ner_html2, _code3)
                if not ner_translated:
                    # no direct HTML fallback — would corrupt tags; keep English view instead
                    ner_translated = None
        except Exception:
            ner_translated = None
    else:
        try:
            rag = documents.get(document_id)
            if not rag:
                rag = DocumentRAG(text=row["original_text"], filename=row["filename"] or "document")
            ner_html = rag.get_ner_highlighted_html()
            if ner_html:
                # Prefer offline batched (3 calls, no 429) — reliable for large NER HTML
                _lm3b = {"hindi":"hi","tamil":"ta","kannada":"kn","telugu":"te","malayalam":"ml","bengali":"bn","marathi":"mr","gujarati":"gu","punjabi":"pa","urdu":"ur","oriya":"or","odia":"or","assamese":"as","french":"fr","spanish":"es","german":"de","arabic":"ar","chinese":"zh","japanese":"ja","korean":"ko","portuguese":"pt","russian":"ru"}
                _code3b = _lm3b.get(target_language.lower().strip(), target_language[:2].lower())
                try:
                    ner_translated = _offline_translate_html_preserve(ner_html, _code3b)
                except Exception:
                    ner_translated = None
                # Verify offline actually translated (Indic script present); if not, try LLM
                _is_indic = _code3b in ('hi','mr','bn','gu','ta','kn','te','ml','pa','ur','or','as')
                _looks_ok = False
                if ner_translated:
                    if _is_indic:
                        _looks_ok = bool(re.search(r'[\u0900-\u097F\u0980-\u09FF\u0A80-\u0AFF\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F\u0D80-\u0DFF]', ner_translated))
                    else:
                        _looks_ok = "What is NER?" not in ner_translated
                if not _looks_ok:
                    ner_system = (
                        f"Translate the visible text of this HTML NER view into {target_language}. "
                        "Keep all HTML tags (<mark>, <small>, <div>, <span>, <br>), style attributes, and entity labels (DATE, PERSON, ORG, GPE, LOC, FAC, PERCENT, etc.) EXACTLY as they are. "
                        "Only translate the human-readable text inside the spans. Do not add or remove entities. Return only the translated HTML."
                    )
                    llm_res, _ = _llm_call(ner_system, ner_html, provider)
                    if llm_res:
                        # verify LLM also translated
                        _llm_ok = False
                        if _is_indic:
                            _llm_ok = bool(re.search(r'[\u0900-\u097F\u0980-\u09FF\u0A80-\u0AFF\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F\u0D80-\u0DFF]', llm_res))
                        else:
                            _llm_ok = "What is NER?" not in llm_res
                        if _llm_ok:
                            ner_translated = llm_res
                        elif not ner_translated:
                            ner_translated = llm_res
                    if not ner_translated and provider != "auto":
                        llm2, _ = _llm_call(ner_system, ner_html, "auto")
                        if llm2:
                            ner_translated = llm2
        except Exception:
            ner_translated = None
    # Translate UI kicker/title too so DOCUMENT ANALYSIS → MULTILINGUAL NER follows target language
    if offline_mode:
        try:
            _lm4 = {"hindi":"hi","tamil":"ta","kannada":"kn","telugu":"te","malayalam":"ml","bengali":"bn","marathi":"mr","gujarati":"gu","punjabi":"pa","urdu":"ur","oriya":"or","odia":"or","assamese":"as","french":"fr","spanish":"es","german":"de","arabic":"ar","chinese":"zh","japanese":"ja","korean":"ko","portuguese":"pt","russian":"ru"}
            _code4 = _lm4.get(target_language.lower().strip(), target_language[:2].lower())
            _GT4k = _chain_translator(_code4)
            try:
                kicker_trans = _GT4k.translate("DOCUMENT ANALYSIS → MULTILINGUAL NER")
            except Exception:
                kicker_trans = None
            _GT4t = _chain_translator(_code4)
            try:
                title_trans = _GT4t.translate("Semantic NER Analysis")
            except Exception:
                title_trans = None
        except Exception:
            kicker_trans = None
            title_trans = None
    else:
        try:
            kicker_sys = f"Translate 'DOCUMENT ANALYSIS → MULTILINGUAL NER' into {target_language}. Keep the arrow → exactly. Return only the translated line."
            kicker_trans, _ = _llm_call(kicker_sys, "DOCUMENT ANALYSIS → MULTILINGUAL NER", provider)
            if not kicker_trans and provider != "auto":
                kicker_trans, _ = _llm_call(kicker_sys, "DOCUMENT ANALYSIS → MULTILINGUAL NER", "auto")
            if not kicker_trans:
                try:
                    _lm4b = {"hindi":"hi","tamil":"ta","kannada":"kn","telugu":"te","malayalam":"ml","bengali":"bn","marathi":"mr","gujarati":"gu","punjabi":"pa","urdu":"ur","oriya":"or","odia":"or","assamese":"as","french":"fr","spanish":"es","german":"de","arabic":"ar","chinese":"zh","japanese":"ja","korean":"ko","portuguese":"pt","russian":"ru"}
                    _code4b = _lm4b.get(target_language.lower().strip(), target_language[:2].lower())
                    from deep_translator import GoogleTranslator as _GT4b
                    kicker_trans = _GT4b(source='en', target=_code4b).translate("DOCUMENT ANALYSIS → MULTILINGUAL NER")
                except Exception:
                    pass
        except Exception:
            kicker_trans = None
        try:
            title_sys = f"Translate 'Semantic NER Analysis' into {target_language}. Return only the translated title."
            title_trans, _ = _llm_call(title_sys, "Semantic NER Analysis", provider)
            if not title_trans and provider != "auto":
                title_trans, _ = _llm_call(title_sys, "Semantic NER Analysis", "auto")
            if not title_trans:
                try:
                    _lm5 = {"hindi":"hi","tamil":"ta","kannada":"kn","telugu":"te","malayalam":"ml","bengali":"bn","marathi":"mr","gujarati":"gu","punjabi":"pa","urdu":"ur","oriya":"or","odia":"or","assamese":"as","french":"fr","spanish":"es","german":"de","arabic":"ar","chinese":"zh","japanese":"ja","korean":"ko","portuguese":"pt","russian":"ru"}
                    _code5 = _lm5.get(target_language.lower().strip(), target_language[:2].lower())
                    from deep_translator import GoogleTranslator as _GT5
                    title_trans = _GT5(source='en', target=_code5).translate("Semantic NER Analysis")
                except Exception:
                    pass
        except Exception:
            title_trans = None
    resp = {"report": _restore_report_breaks(translated, row["report_markdown"]), "language": target_language, "provider": used_provider or provider}
    if ner_translated:
        resp["ner_highlighted_html"] = ner_translated
    if kicker_trans:
        resp["kicker"] = kicker_trans.strip()
    if title_trans:
        resp["title"] = title_trans.strip()
    if len(_TRANSLATE_CACHE) > 200:
        _TRANSLATE_CACHE.clear()
    _TRANSLATE_CACHE[_ckey] = {"report_hash": _rep_hash, "resp": resp}
    try:
        db.execute(
            "INSERT OR REPLACE INTO report_translations (document_id, language, report_hash, translated_markdown) VALUES (?, ?, ?, ?)",
            (document_id, target_language.lower().strip(), _rep_hash, resp["report"]))
        db.commit()
    except Exception:
        pass
    return jsonify(resp)


@app.delete("/api/documents/<document_id>")
@login_required
def delete_document(document_id):
    db = get_db()
    db.execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (document_id, session["user_id"]))
    db.commit()
    documents.pop(document_id, None)
    return jsonify(success=True)


# --- Alias routes for legacy /api/contracts frontend calls (frontend still uses contracts) ---
@app.get("/api/contracts")
@login_required
def list_contracts_alias():
    return list_documents()


@app.post("/api/contracts")
@login_required
def upload_contract_alias():
    return upload_document()


@app.get("/api/contracts/<document_id>")
@login_required
def get_contract_alias(document_id):
    return get_document(document_id)


@app.delete("/api/contracts/<document_id>")
@login_required
def delete_contract_alias2(document_id):
    return delete_document(document_id)


@app.post("/api/contracts/<document_id>/reanalyze")
@login_required
def reanalyze_contract_alias_forward(document_id):
    return reanalyze_document(document_id)


@app.post("/api/contracts/<document_id>/translate-report")
@login_required
def translate_contract_alias_forward(document_id):
    return translate_report(document_id)


def _code_for_tts_lang(name: str) -> str:
    base = (name or "").split("(")[0].strip().lower()
    _m = {"hindi": "hi", "tamil": "ta", "kannada": "kn", "telugu": "te", "malayalam": "ml", "bengali": "bn", "marathi": "mr", "gujarati": "gu", "punjabi": "pa", "urdu": "ur", "oriya": "or", "odia": "or", "assamese": "as", "nepali": "ne", "french": "fr", "spanish": "es", "german": "de", "arabic": "ar", "chinese": "zh-cn", "japanese": "ja", "korean": "ko", "portuguese": "pt", "russian": "ru", "sanskrit": "sa"}
    return _m.get(base, base[:2])


def _argos_values(values, from_code: str, to_code: str):
    """Fully-offline value translation via installed Argos packs.
    Only Hindi pairs are safe here (Bengali stanza resources don't exist).
    Returns translated list or None."""
    if from_code != "en" or to_code != "hi":
        return None
    try:
        from argostranslate.translate import get_installed_languages
        installed = get_installed_languages()
        src = next((l for l in installed if l.code == from_code), None)
        dst = next((l for l in installed if l.code == to_code), None)
        if not src or not dst:
            return None
        trans = src.get_translation(dst)
        if not trans:
            return None
        return [trans.translate(v) if v and v.strip() else v for v in values]
    except Exception as e:
        print(f"[Values] Argos en->hi unavailable: {e}")
        return None


def _translate_values_to_source(entity_buckets, target_code, timeout_s: int = 150):
    """Back-translate entity values en->source language for display.
    Returns {type: [values]} aligned 1:1; falls back to English per item.
    Single batched Ollama call after a fast web probe - no per-value waits."""
    flat = [(t, v) for t, vals in (entity_buckets or {}).items() for v in (vals or [])]
    if not flat or not target_code or target_code == "en":
        return {t: list(vals) for t, vals in (entity_buckets or {}).items()}

    def _do():
        try:
            argos_out = _argos_values([v for _, v in flat], "en", target_code)
            if argos_out and len(argos_out) == len(flat):
                print("[Values] Argos offline en->hi used")
                return argos_out
        except Exception:
            pass
        try:
            tr = _chain_translator("zh" if target_code == "zh-cn" else target_code)
            probe = tr.translate(flat[0][1])
            if probe and probe.strip() and probe.strip() != flat[0][1]:
                out = [probe.strip()]
                for _, v in flat[1:]:
                    try:
                        tv = tr.translate(v)
                        out.append(tv.strip() if tv and tv.strip() else v)
                    except Exception:
                        out.append(v)
                return out
        except Exception:
            pass
        import json as _js
        import requests as _rq
        oh = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        om = os.getenv("OLLAMA_MODEL", "qwen3:4b")
        names = {"hi": "Hindi", "ta": "Tamil", "kn": "Kannada", "te": "Telugu", "ml": "Malayalam", "bn": "Bengali", "mr": "Marathi", "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu", "or": "Odia", "as": "Assamese"}
        payload = _js.dumps([v for _, v in flat], ensure_ascii=False)
        r = _rq.post(oh + "/api/chat", json={
            "model": om, "stream": False, "think": False,
            "messages": [
                {"role": "system", "content": "Translate each English line into " + names.get(target_code, target_code) + ". Return ONLY a JSON array of translated strings, same order and same length, no commentary."},
                {"role": "user", "content": payload}]}, timeout=timeout_s)
        r.raise_for_status()
        content = ((r.json().get("message") or {}).get("content", "") or "").strip()
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        start, end = content.find("["), content.rfind("]")
        arr = _js.loads(content[start:end + 1]) if start != -1 and end != -1 else None
        if isinstance(arr, list) and len(arr) == len(flat):
            return [str(x).strip() or v for x, (_, v) in zip(arr, flat)]
        return [v for _, v in flat]

    from concurrent.futures import ThreadPoolExecutor as _VPool
    try:
        try:
            from rag import _seconds_left as _sl
            timeout_s = max(10, min(timeout_s, int(_sl(timeout_s))))
        except Exception:
            pass
        # Never outlive the request deadline: the future cap is tight so a
        # slow Ollama batch cannot push the whole upload past 30s.
        with _VPool(max_workers=1) as _vp:
            got = _vp.submit(_do).result(timeout=timeout_s + 5)
    except Exception as e:
        app.logger.error("Value back-translation failed, keeping English: %s", e)
        got = [v for _, v in flat]
    rebuilt, k = {}, 0
    for t, vals in (entity_buckets or {}).items():
        rebuilt[t] = []
        for _ in (vals or []):
            rebuilt[t].append(got[k] if k < len(got) else "")
            k += 1
    return rebuilt


def _quick_entity_report(display_buckets, filename, detected_lang) -> str:
    total = sum(len(v) for v in (display_buckets or {}).values())
    head = "# Quick entities - " + filename
    sub = "Found **" + str(total) + "** entities"
    if detected_lang and detected_lang != "English":
        sub += " (shown in " + detected_lang + ")"
    lines = [head, "", sub + ".", ""]
    for t, vals in (display_buckets or {}).items():
        if not vals:
            continue
        lines.append("## " + t + " (" + str(len(vals)) + ")")
        lines.extend("- " + v for v in vals)
        lines.append("")
    lines.append("Tip: open IndicMind Q&A below to ask questions grounded in this document.")
    return "\n".join(lines).strip()


def _build_entity_result(rag, filename, detected_lang):
    """The one and only analysis flow: translate -> entities -> display.
    No audit/report LLM calls (those were slow and non-essential).
    RAG lives on purely for Q&A over the stored English text."""
    local = rag._local_audit()
    en_buckets = {e.get("type", "Other"): list(e.get("values", []))
                  for e in rag.entity_scan()}
    src_code = _code_for_tts_lang(detected_lang)
    # Back-translation is a nicety, not the result: skip it when the
    # request budget is nearly spent so the flow stays fast.
    try:
        from rag import _seconds_left as _sl2
        _remaining = _sl2(999)
    except Exception:
        _remaining = 999
    if src_code != "en" and _remaining >= 12:
        shown = _translate_values_to_source(en_buckets, src_code)
    else:
        shown = en_buckets
    analysis_results = dict(local)
    analysis_results["metadata"] = dict(local.get("metadata", {}))
    analysis_results["metadata"]["original_language"] = detected_lang
    analysis_results["entities"] = [{"type": t, "values": vals} for t, vals in shown.items()]
    try:
        analysis_results["ner_highlighted_html"] = rag.get_ner_highlighted_html()
    except Exception:
        analysis_results["ner_highlighted_html"] = ""
    report_markdown = _quick_entity_report(shown, filename, detected_lang)
    return analysis_results, report_markdown


# --- Async upload jobs: POST returns instantly (202 + job_id) while the heavy
# extract -> translate -> analyze pipeline runs in a worker thread with live
# stage progress the frontend polls. Users see movement in ~1s, never a stall.
_jobs = {}
_jobs_lock = _th.Lock()


def _job_update(job_id, **fields):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)


def _run_upload_job(job_id, saved_path, filename, suffix, provider, user_id):
    from rag import set_request_deadline, clear_request_deadline
    # Background worker: generous budget (checkpoints still bail hopeless steps).
    set_request_deadline(420)
    document_id = str(uuid.uuid4())
    try:
        with app.app_context():
            _job_update(job_id, status="working", stage="Reading document…", pct=8)
            # Extraction (esp. scanned-PDF OCR) runs under its own cap so it
            # cannot eat the whole worker budget.
            from concurrent.futures import ThreadPoolExecutor as _EPool, TimeoutError as _FutureTimeout
            try:
                with _EPool(max_workers=1) as _ep:
                    text = _ep.submit(extract_text, saved_path).result(timeout=60)
            except _FutureTimeout as _ex:
                raise ValueError("Text extraction took too long. Try a text-based PDF, DOCX, or TXT file.") from _ex
            # Voice notes are short by nature — 40 chars is enough to scan.
            _min_len = 40 if (filename or "").startswith("voice-note-") else 100
            if len(text.strip()) < _min_len:
                if _min_len == 40:
                    raise ValueError("The voice note is too short. Speak at least 10 words, then analyze again.")
                raise ValueError("The document has too little readable text. Try a clearer image, text-based PDF, or TXT/DOCX file.")

            _job_update(job_id, stage="Translating…", pct=30)
            # Entities-only flow (RAG is used purely for Q&A): translate to
            # English, extract entities, show them back in the uploaded language.
            english_text, detected_lang = translate_to_english(text, provider=provider, fast=True)

            _job_update(job_id, stage="Extracting entities…", pct=62)
            rag = DocumentRAG(text=english_text, filename=filename)
            documents[document_id] = rag

            _job_update(job_id, stage="Building report…", pct=85)
            analysis_results, report_markdown = _build_entity_result(rag, filename, detected_lang)

            # Save to database
            db = get_db()
            db.execute(
                "INSERT INTO documents (id, user_id, filename, file_type, original_text, analysis_json, report_markdown) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (document_id, user_id, filename, suffix[1:], english_text, json.dumps(analysis_results), report_markdown)
            )
            db.commit()

            # Clear physical file to protect privacy
            saved_path.unlink(missing_ok=True)

            clear_request_deadline()
            _job_update(job_id, status="done", stage="Done", pct=100, result={
                "id": document_id,
                "filename": filename,
                "chunks": len(rag.chunks),
                "analysis": analysis_results,
                "report": report_markdown,
            })
    except Exception as exc:
        try:
            clear_request_deadline()
        except Exception:
            pass
        try:
            saved_path.unlink(missing_ok=True)
        except Exception:
            pass
        message = str(exc)
        if "time budget exceeded" in message.lower():
            message = "Translators are too slow right now. Wait a minute and retry."
        _job_update(job_id, status="error", stage="Failed", pct=100, error=message)
    finally:
        try:
            from flask import g as _flask_g
            _db = _flask_g.pop("db", None)
            if _db is not None:
                _db.close()
        except Exception:
            pass


@app.get("/api/jobs/<job_id>")
@login_required
def upload_job_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job.get("user_id") != session.get("user_id"):
        return jsonify(error="Upload job not found."), 404
    out = {"status": job["status"], "stage": job.get("stage", ""), "pct": job.get("pct", 0)}
    if job["status"] == "done":
        out["result"] = job.get("result")
    if job["status"] == "error":
        out["error"] = job.get("error", "Analysis failed.")
    return jsonify(out)


@app.post("/api/documents")
@login_required
def upload_document():
    # frontend sends field "contract" (index.html) while documents page sends "document" — accept both
    file = request.files.get("document") or request.files.get("contract")
    if not file or not file.filename:
        return jsonify(error="Choose a PDF, DOCX, TXT, or Image document first."), 400

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        return jsonify(error="Supported formats are PDF, DOCX, TXT, JPG, and PNG."), 400

    job_id = str(uuid.uuid4())
    saved_path = UPLOAD_DIR / f"{job_id}{suffix}"
    file.save(saved_path)
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "stage": "Queued…", "pct": 3, "user_id": session["user_id"]}
        while len(_jobs) > 60:  # evict oldest finished jobs
            old = next((k for k, v in _jobs.items() if v.get("status") in ("done", "error")), None)
            if old is None:
                break
            del _jobs[old]
    _th.Thread(
        target=_run_upload_job,
        args=(job_id, saved_path, file.filename, suffix, request.form.get("provider", "auto"), session["user_id"]),
        daemon=True,
    ).start()
    return jsonify(job_id=job_id), 202


@app.post("/api/contracts/<contract_id>/ask")
@login_required
def ask_contract(contract_id):
    return ask_document_alias(contract_id)


@app.post("/api/documents/<document_id>/ask")
@login_required
def ask_document_alias(document_id):
    rag = documents.get(document_id)
    if not rag:
        db = get_db()
        row = db.execute(
            "SELECT * FROM documents WHERE id = ? AND user_id = ?",
            (document_id, session["user_id"])
        ).fetchone()
        if row:
            rag = DocumentRAG(text=row["original_text"], filename=row["filename"])
            documents[document_id] = rag
        else:
            return jsonify(error="That document session has expired or does not exist. Upload it again."), 404
            
    question = (request.json or {}).get("question", "").strip()
    if not question:
        return jsonify(error="Ask a question about the document."), 400
    provider = (request.json or {}).get("provider", "auto")
    return jsonify(rag.answer(question, provider))


# --- TEXT-TO-SPEECH APIs ---

def clean_text_for_tts(text: str) -> str:
    """Clean markdown and special characters for better TTS pronunciation."""
    # Remove markdown headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove markdown bold/italic
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    # Remove markdown links but keep text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Remove emojis and special symbols
    text = re.sub(r'[🔴🟡🟢📋📝💼💰⏰🚪⚖️🔒🎯⚠️🏛️🚨✅📊🎉✓❌⭐🔧]', '', text)
    # Remove clause citations like [Clause 1]
    text = re.sub(r'\[Clause \d+\]', '', text)
    # Clean up extra spaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


@app.post("/api/tts/generate")
@login_required
def generate_tts():
    """Generate TTS audio from text."""
    data = request.json or {}
    text = data.get("text", "").strip()
    language = data.get("language", "en").strip()
    section = data.get("section", "summary").strip()
    
    if not text:
        return jsonify(error="No text provided for TTS generation."), 400
    
    # Limit text length (gTTS has limits, and we want reasonable audio length)
    max_chars = 5000
    if len(text) > max_chars:
        text = text[:max_chars] + "... The full text exceeds the audio length limit."
    
    # Clean text for better pronunciation
    clean_text = clean_text_for_tts(text)
    
    if not clean_text:
        return jsonify(error="No readable text after cleaning."), 400
    
    try:
        # Generate unique filename based on content hash
        import hashlib
        text_hash = hashlib.md5(clean_text.encode()).hexdigest()
        audio_filename = f"tts_{section}_{text_hash[:12]}.mp3"
        audio_path = TTS_CACHE_DIR / audio_filename
        
        # Check if already cached
        if not audio_path.exists():
            # Generate TTS
            tts = gTTS(text=clean_text, lang=language, slow=False)
            tts.save(str(audio_path))
        
        return jsonify(
            success=True,
            audio_url=f"/api/tts/audio/{audio_filename}",
            duration_estimate=len(clean_text) // 15  # Rough estimate: 15 chars per second
        )
        
    except Exception as e:
        app.logger.error(f"TTS generation failed: {e}")
        return jsonify(error=f"TTS generation failed: {str(e)}"), 500


@app.get("/api/tts/audio/<filename>")
@login_required  
def serve_tts_audio(filename):
    """Serve generated TTS audio file."""
    # Security: Only allow alphanumeric, underscore, dash, and .mp3
    if not re.match(r'^tts_[\w\-]+\.mp3$', filename):
        return jsonify(error="Invalid filename."), 400
    
    audio_path = TTS_CACHE_DIR / filename
    if not audio_path.exists():
        return jsonify(error="Audio file not found."), 404
    
    return send_file(audio_path, mimetype='audio/mpeg')


@app.post("/api/contracts/<contract_id>/tts/summary")
@login_required
def generate_summary_tts(contract_id):
    return generate_summary_tts_alias(contract_id)


@app.post("/api/documents/<document_id>/tts/summary")
@login_required
def generate_summary_tts_alias(document_id):
    """Generate TTS for executive summary."""
    db = get_db()
    row = db.execute(
        "SELECT report_markdown FROM documents WHERE id = ? AND user_id = ?",
        (document_id, session["user_id"])
    ).fetchone()
    
    if not row or not row["report_markdown"]:
        return jsonify(error="Executive summary not available."), 404
    
    # Extract just the key sections for TTS (avoid overwhelming with too much audio)
    report = row["report_markdown"]
    req_lang = ((request.json or {}).get("language", "") or "").strip()
    tts_code = "en"
    _lm_tts = {"hindi":"hi","tamil":"ta","kannada":"kn","telugu":"te","malayalam":"ml","bengali":"bn","marathi":"mr","gujarati":"gu","punjabi":"pa","urdu":"ur","oriya":"or","odia":"or","assamese":"as","nepali":"ne","french":"fr","spanish":"es","german":"de","arabic":"ar","chinese":"zh-cn","japanese":"ja","korean":"ko","portuguese":"pt","russian":"ru","sanskrit":"sa"}
    if req_lang and req_lang.lower() not in ("en", "english"):
        tts_code = _lm_tts.get(req_lang.lower().strip(), req_lang[:2].lower())
        if tts_code not in ("hi","ta","kn","te","ml","bn","mr","gu","pa","ur","or","as","ne","sa","fr","es","de","ar","zh-cn","ja","ko","pt","ru"):
            return jsonify(error=f"Audio is not supported for '{req_lang}'."), 400

    # Zero-call fast path: the user just translated this exact report (the
    # Translate button caches it), so slice the summary from the cached
    # translation instead of burning more rate-limited web calls.
    already_translated = False
    if req_lang and req_lang.lower() not in ("en", "english"):
        import hashlib as _hl2
        _rep_hash2 = _hl2.md5(row["report_markdown"].encode("utf-8")).hexdigest()
        _ckey2 = (document_id, req_lang.lower().strip(),
                  os.getenv("TRANSLATION_PROVIDER", "auto").lower())
        try:
            _hit2 = _TRANSLATE_CACHE.get(_ckey2)
        except Exception:
            _hit2 = None
        if _hit2 and _hit2.get("report_hash") == _rep_hash2 and (_hit2.get("resp") or {}).get("report"):
            report = _hit2["resp"]["report"]
            already_translated = True
    
    # Get first few sections (Quick Facts, What This Agreement Does, Key Risks)
    sections_to_read = []
    lines = report.split('\n')
    current_section = []
    section_count = 0
    max_sections = 5  # Read first 5 sections
    
    for line in lines:
        if line.startswith('## ') or line.startswith('# '):
            if current_section and section_count < max_sections:
                sections_to_read.extend(current_section)
                section_count += 1
            current_section = [line]
            if section_count >= max_sections:
                break
        else:
            current_section.append(line)
    
    if current_section and section_count < max_sections:
        sections_to_read.extend(current_section)
    
    summary_text = '\n'.join(sections_to_read)

    # Speak the report's current language: frontend sends the translated
    # language name ("Marathi") when the report view is translated.
    # (req_lang/tts_code already resolved above; cache hit sets already_translated.)
    if req_lang and req_lang.lower() not in ("en", "english") and not already_translated:
        try:
            tr = _chain_translator("zh" if tts_code == "zh-cn" else tts_code)
            # Small chunks: MyMemory (the rate-limit fallback) caps at 500 chars.
            parts, cur = [], ""
            for para in summary_text.split("\n"):
                for sent in para.split(". "):
                    piece = sent if sent.endswith(".") or not sent else sent + "."
                    if len(cur) + len(piece) + 1 <= 450:
                        cur += ("\n" if cur else "") + piece
                    else:
                        if cur:
                            parts.append(cur)
                        while len(piece) > 450:
                            cut = piece.rfind(" ", 0, 450)
                            if cut == -1:
                                cut = 450
                            parts.append(piece[:cut])
                            piece = piece[cut:].lstrip()
                        cur = piece
            if cur:
                parts.append(cur)
            summary_text = "\n".join(tr.translate(p) for p in parts if p.strip())
        except Exception as e:
            app.logger.error(f"Summary translation for TTS failed: {e}")
            return jsonify(error="Could not translate the summary for audio. Wait a minute and retry."), 502

    # Generate TTS
    clean_text = clean_text_for_tts(summary_text)

    if not clean_text:
        return jsonify(error="No readable content in summary."), 400

    try:
        import hashlib
        text_hash = hashlib.md5((tts_code + clean_text).encode()).hexdigest()
        audio_filename = f"tts_summary_{document_id}_{tts_code}_{text_hash[:12]}.mp3"
        audio_path = TTS_CACHE_DIR / audio_filename

        if not audio_path.exists():
            tts = gTTS(text=clean_text, lang=tts_code, slow=False)
            tts.save(str(audio_path))
        
        return jsonify(
            success=True,
            audio_url=f"/api/tts/audio/{audio_filename}",
            duration_estimate=len(clean_text) // 15
        )
        
    except Exception as e:
        app.logger.error(f"Summary TTS generation failed: {e}")
        return jsonify(error=f"TTS generation failed: {str(e)}"), 500


@app.delete("/api/tts/cache")
@login_required
def clear_tts_cache():
    """Clear TTS cache (admin/user cleanup)."""
    try:
        import shutil
        for file in TTS_CACHE_DIR.glob("tts_*.mp3"):
            file.unlink()
        return jsonify(success=True, message="TTS cache cleared.")
    except Exception as e:
        return jsonify(error=f"Failed to clear cache: {str(e)}"), 500


@app.errorhandler(413)
def file_too_large(_):
    return jsonify(error="File is too large. The limit is 16 MB."), 413


if __name__ == "__main__":
    init_db()
    # use_reloader=False: the reloader forks a 2nd process that re-imports
    # torch/stanza/spacy (~1GB+), which OOMs on low-RAM machines.
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
