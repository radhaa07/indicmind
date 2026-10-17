import os
import re
import json
import threading
import time as _time
from pathlib import Path
from urllib.parse import quote

import requests

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# --- Request time budgets: every upload must answer within ~30s. ---
# Flask serves threads; a thread-local deadline lets each LLM/web/Ollama step
# bail out early so slow backends degrade instead of hanging the user.
_request_state = threading.local()
_OLLAMA_LOCK = threading.Lock()


def set_request_deadline(seconds: float) -> None:
    """Call at request start; all timed steps below respect it."""
    _request_state.deadline = _time.time() + seconds


def clear_request_deadline() -> None:
    _request_state.deadline = None


def _seconds_left(default: float) -> float:
    dl = getattr(_request_state, "deadline", None)
    if dl is None:
        return default
    return max(0.0, dl - _time.time())


def _check_deadline(label: str = "") -> None:
    if _seconds_left(0) <= 0 and getattr(_request_state, "deadline", None) is not None:
        raise ValueError(f"Time budget exceeded{(' — ' + label) if label else ''}.")


def extract_text(path: Path) -> str:
    try:
        if path.suffix.lower() == ".txt":
            return path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".docx":
            doc = Document(path)
            # Documents frequently put parties, fees, dates, and schedules in tables.
            # Walk the document body in order so that those details are not silently lost.
            blocks = []
            for child in doc.element.body.iterchildren():
                if isinstance(child, CT_P):
                    value = Paragraph(child, doc).text.strip()
                    if value:
                        blocks.append(value)
                elif isinstance(child, CT_Tbl):
                    table = Table(child, doc)
                    for row in table.rows:
                        values = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                        if any(values):
                            blocks.append(" | ".join(values))
            return "\n".join(blocks)
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            # A scan often has an empty text layer. OCR only those PDFs, keeping
            # normal digital PDFs fast and their original text intact.
            if len(re.sub(r"\s+", "", text)) < 80:
                text = _ocr_scanned_pdf(path)
            return text
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            return _ocr_image(path)
        raise ValueError(f"Unsupported file type: {path.suffix}")
    except Exception as e:
        raise ValueError(f"Failed to extract text from {path.name}: {str(e)}")


def _ocr_image(path: Path) -> str:
    """Read document images (JPG, JPEG, PNG, etc.) with Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image

        image = Image.open(path)
        text = pytesseract.image_to_string(image, config="--oem 3 --psm 6")
        if not text.strip():
            text = pytesseract.image_to_string(image)
        if text.strip():
            return text.strip()
        raise ValueError("OCR could not detect readable text from this image.")
    except Exception as exc:
        raise ValueError(
            "Could not read text from image. "
            "Please ensure Tesseract OCR is installed and the image contains clear text. Details: " + str(exc)
        ) from exc


def _ocr_scanned_pdf(path: Path) -> str:
    """Read image-only PDFs with Tesseract, preserving page boundaries."""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        from io import BytesIO

        document = fitz.open(path)
        pages = []
        for page_number, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            page_text = pytesseract.image_to_string(image, config="--oem 3 --psm 6")
            if page_text.strip():
                pages.append(f"[Page {page_number}]\n{page_text.strip()}")
        if pages:
            return "\n\n".join(pages)
        raise ValueError("OCR could not read text from this PDF.")
    except Exception as exc:
        raise ValueError(
            "This PDF appears to be a scan and has no readable text layer. "
            "Install Tesseract OCR, then upload it again. Details: " + str(exc)
        ) from exc


def _clean_indic_spacing(text: str) -> str:
    """Join PDF-split Indic characters e.g. 'ભા રત' -> 'ભારત' to avoid garbage dots."""
    for pat in [r'([\u0A80-\u0AFF])\s+(?=[\u0A80-\u0AFF])', r'([\u0900-\u097F])\s+(?=[\u0900-\u097F])', r'([\u0B80-\u0BFF])\s+(?=[\u0B80-\u0BFF])', r'([\u0C00-\u0C7F])\s+(?=[\u0C00-\u0C7F])', r'([\u0C80-\u0CFF])\s+(?=[\u0C80-\u0CFF])', r'([\u0D00-\u0D7F])\s+(?=[\u0D00-\u0D7F])', r'([\u0980-\u09FF])\s+(?=[\u0980-\u09FF])']:
        text = re.sub(pat, r'\1', text)
    text = re.sub(r'\s+([.,;:!?\)])', r'\1', text)
    text = re.sub(r'\(\s+', '(', text)
    return text


def split_document(text: str, size: int = 900, overlap: int = 180) -> list[str]:
    if not text or not text.strip():
        return [""]
    
    text = _clean_indic_spacing(text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    
    sections = re.split(r"(?=\n\s*(?:\d+(?:\.\d+)*[.)]|[A-Z][A-Z ]{3,}:))", text)
    # Keep numbered clauses separate even in short agreements. This gives every
    # screen a useful source excerpt and makes Q&A citations meaningful.
    meaningful_sections = [section.strip() for section in sections if section.strip()]
    numbered = [section for section in meaningful_sections if re.match(r"^(?:\d+(?:\.\d+)*[.)]|[A-Z][A-Z ]{3,}:)", section)]
    if numbered:
        preamble = meaningful_sections[0] if meaningful_sections and meaningful_sections[0] not in numbered else ""
        return ([preamble] if preamble else []) + numbered
    if len(text) <= size:
        return [text]
    chunks, buffer = [], ""
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(buffer) + len(section) <= size:
            buffer += ("\n" if buffer else "") + section
        else:
            if buffer:
                chunks.append(buffer)
            buffer = section
            while len(buffer) > size:
                split_at = buffer.rfind(". ", 0, size)
                if split_at == -1 or split_at < size // 2:
                    split_at = size
                else:
                    split_at = split_at + 1
                chunks.append(buffer[:split_at].strip())
                buffer = buffer[max(0, split_at - overlap):].strip()
    if buffer:
        chunks.append(buffer)
    return chunks if chunks else [text]


RISK_RULES = {
    "Auto-renewal": ["auto renew", "automatically renew", "automatic renewal"],
    "Broad indemnity": ["indemnify", "hold harmless", "defend and indemnify"],
    "Liability cap": ["limitation of liability", "liability shall not exceed", "aggregate liability"],
    "Termination": ["termination", "terminate for convenience", "notice of termination"],
    "Data & privacy": ["personal data", "data protection", "confidential information", "privacy"],
    "Governing law": ["governing law", "laws of", "jurisdiction"],
    "Non-compete": ["non-compete", "non compete", "not compete"],
}

LEGAL_TERMS = ["confidentiality", "indemnity", "limitation of liability", "termination", "intellectual property", "governing law", "force majeure", "payment", "warranty", "data protection", "dispute resolution", "non-solicitation"]


def parse_json_markdown(text: str) -> dict:
    if not text:
        return {}
    # Try finding markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    # Try parsing direct JSON
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    # Fallback to manual curly braces extraction
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
    except Exception:
        pass
    return {}


def _llm_call(system: str, prompt: str, provider: str = "auto", _retry: int = 2,
             _timeout: float | None = None, _options: dict | None = None,
             _prefill: str | None = None) -> tuple[str | None, str | None]:
    import time
    chosen = provider.lower() if provider else "auto"
    if chosen not in {"auto", "gemini", "ollama"}:
        chosen = "auto"
    gemini_failed = False
    if chosen in {"auto", "gemini"} and os.getenv("GEMINI_API_KEY"):
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        for attempt in range(_retry):
            try:
                _check_deadline("gemini")
                response = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent",
                    params={"key": os.environ["GEMINI_API_KEY"]},
                    json={"system_instruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                          # Bounded response length (2048 max tokens) for fast response generation.
                          "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}},
                    timeout=max(3, min(15, _seconds_left(15))))
                if response.status_code == 429:
                    if attempt >= 1:
                        raise ValueError(
                            "Gemini rate limit or API quota reached. Wait a few minutes, check your Gemini API quota, "
                            "or use a running local Ollama model."
                        )
                    print(f"Gemini 429 rate-limit hit — retrying in 1s (attempt {attempt+1}/{_retry})")
                    time.sleep(1)
                    continue
                response.raise_for_status()
                return response.json()["candidates"][0]["content"]["parts"][0]["text"], "gemini"
            except requests.exceptions.HTTPError as e:
                if response.status_code in {500, 502, 503} and attempt < _retry - 1:
                    print(f"Gemini server error {response.status_code} — retrying in 1s")
                    time.sleep(1)
                    continue
                # Bad key / 400 / quota: fall through to local Ollama instead of
                # dying, so questions still get a proper LLM answer.
                print("Gemini LLM call failed. Trying local fallback.")
                gemini_failed = True
                break
            except ValueError:
                raise
            except Exception as e:
                print("Gemini LLM call failed. Fallback engine active.")
                gemini_failed = True
                break
    elif chosen == "gemini":
        # Explicit Gemini choice but no key at all — still try local Ollama.
        gemini_failed = True
    if chosen in {"auto", "ollama"} or gemini_failed:
        try:
            _check_deadline("ollama")
            # Single-flight: Ollama serves one request at a time — never queue
            # behind another generation, or every caller times out in a jam.
            if not _OLLAMA_LOCK.acquire(blocking=False):
                print("Ollama busy with another request — skipping local fallback")
                return None, None
            try:
                _model = os.getenv("OLLAMA_MODEL", "qwen3:4b")
                _messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
                if _prefill:
                    # Assistant prefill: the model continues in answer voice
                    # instead of opening with "Okay, the user asked…".
                    _messages.append({"role": "assistant", "content": _prefill})
                _payload = {"model": _model, "stream": False, "think": False,
                          "keep_alive": "30m", "messages": _messages}
                _merged_options = {"temperature": 0.2}
                if _options:
                    _merged_options.update(_options)
                _payload["options"] = _merged_options
                _ollama_timeout = _timeout if _timeout else max(3, min(20, _seconds_left(20)))
                response = requests.post(
                    f"{os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')}/api/chat",
                    json=_payload,
                    timeout=_ollama_timeout)
                response.raise_for_status()
                res_content = response.json()["message"]["content"]
                if "</think>" in res_content:
                    res_content = res_content.split("</think>")[-1].strip()
                return res_content, "ollama"
            finally:
                _OLLAMA_LOCK.release()
        except requests.exceptions.ConnectionError:
            print("Ollama not running — skipping local fallback")
            return None, None
        except Exception as e:
            print(f"Ollama LLM call failed: {e}")
            return None, None
    return None, None


_SPACY_NLP = None
_SPACY_TRIED = False


def _get_spacy_nlp():
    """Load en_core_web_sm once per process — spacy.load costs seconds per call."""
    global _SPACY_NLP, _SPACY_TRIED
    if _SPACY_NLP is not None or _SPACY_TRIED:
        return _SPACY_NLP
    _SPACY_TRIED = True
    try:
        try:
            import spacy
        except Exception:
            # Windows torch DLL broken (common) — mock torch so spaCy CNN model still works
            import sys, unittest.mock
            sys.modules.setdefault('torch', unittest.mock.MagicMock())
            sys.modules.setdefault('torch.cuda', unittest.mock.MagicMock())
            import spacy  # type: ignore
        _SPACY_NLP = spacy.load("en_core_web_sm")
    except OSError:
        _SPACY_NLP = None
    return _SPACY_NLP


SCRIPT_LANGUAGE_HINTS = [
    (r"[\u0B80-\u0BFF]", "ta"), (r"[\u0C80-\u0CFF]", "kn"),
    (r"[\u0A80-\u0AFF]", "gu"), (r"[\u0C00-\u0C7F]", "te"),
    (r"[\u0D00-\u0D7F]", "ml"), (r"[\u0980-\u09FF]", "bn"),
    (r"[\u0900-\u097F]", "mr"),  # Marathi before Hindi (both Devanagari)
    (r"[\u0900-\u097F]", "hi"),
]


# Indian states/UTs/major cities the small spaCy model often mislabels
# (Chennai→ORG, Tamil Nadu→PERSON). Matched case-insensitively.
_INDIAN_PLACES = frozenset({
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
    "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram",
    "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu",
    "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal",
    "delhi", "new delhi", "jammu and kashmir", "ladakh", "puducherry",
    "chandigarh", "andaman and nicobar islands", "lakshadweep",
    "dadra and nagar haveli and daman and diu",
    "mumbai", "chennai", "kolkata", "bengaluru", "bangalore", "hyderabad",
    "ahmedabad", "pune", "jaipur", "lucknow", "kanpur", "nagpur", "indore",
    "thane", "bhopal", "visakhapatnam", "patna", "vadodara", "surat", "agra",
    "coimbatore", "madurai", "kochi", "thiruvananthapuram", "gurgaon",
    "gurugram", "noida", "ghaziabad", "faridabad", "rajkot", "jabalpur",
    "mysuru", "mysore", "salem", "tiruchirappalli", "varanasi", "prayagraj",
    "allahabad", "meerut", "jodhpur", "ranchi", "guwahati", "bhubaneswar",
    "dehradun", "shimla", "amritsar", "ludhiana", "udaipur", "kota",
    "aurangabad", "nashik", "tirunelveli", "erode", "vellore", "india",
    "bharat", "amravati", "kolhapur", "solapur", "jammu", "srinagar",
    "thanjavur", "madurai", "kochi", "thrissur", "mysore",
})

# Generic legal boilerplate spaCy sometimes tags as entities — never entities.
_GENERIC_ENTITY_PHRASES = frozenset({
    "due date", "scope of services", "scope of service", "scope", "period",
    "agreement", "schedule", "annexure", "annex", "exhibit", "clause",
    "section", "article", "term", "fees", "fee", "payment", "sample document",
    "service agreement", "effective date", "governing law",
    "this agreement", "this agreement party", "agreement party",
    "party", "party a", "party b", "mg",
})


def _correct_indian_entity(text: str) -> str:
    """Fix small-model NER mistakes. Returns 'GPE' (force location),
    'DROP' (not an entity), or 'KEEP'."""
    low = (text or "").strip().lower()
    if not low:
        return "DROP"
    if low in _GENERIC_ENTITY_PHRASES:
        return "DROP"
    if low in _INDIAN_PLACES:
        return "GPE"
    return "KEEP"


def _self_introduced_names(text: str) -> list[str]:
    """Names from self-introductions ('my name is Gaurav', 'I am Priya') —
    the small model tags these ORG/NORP; they are always PERSON."""
    non_names = {"from", "doing", "here", "there", "going", "working", "looking",
                 "trying", "currently", "now", "today", "very", "so", "really",
                 "just", "also", "an", "the", "a", "my", "am", "is", "are",
                 "was", "were", "be", "been", "have", "has", "had", "do",
                 "does", "did", "will", "would", "can", "could", "should",
                 "not", "no", "and", "or", "but", "if", "in", "on", "at",
                 "to", "for", "of", "with", "as", "by", "that", "this",
                 "it", "he", "she", "we", "they", "you", "i",
                 "glad", "happy", "sorry", "ready"}
    names = []
    for pat in (r"\bmy name is\s+([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)",
                r"\bi am\s+([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)",
                r"\bthis is\s+([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)",
                r"\bmyself\s+([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)?)"):
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            words = m.group(1).split()
            if not words or words[0].lower() in non_names:
                continue
            # A trailing stopword ("Gaurav and...") means only the first word
            # is the name — keep it instead of dropping the whole match.
            if len(words) > 1 and words[1].lower() in non_names:
                words = words[:1]
            name = " ".join(w.capitalize() for w in words)
            if name and name not in names:
                names.append(name)
    return names


def _force_persons_bucket(buckets: dict, names: list[str]) -> dict:
    for name in names:
        low = name.lower()
        for key in list(buckets.keys()):
            if key == "Persons":
                continue
            buckets[key] = [v for v in buckets[key] if v.lower() != low]
        persons = buckets.setdefault("Persons", [])
        if low not in {v.lower() for v in persons} and len(persons) < 8:
            persons.append(name)
    return buckets


def _is_verified_english(text: str) -> bool:
    """Reject untranslated responses before they reach RAG."""
    if len(re.findall(r"[A-Za-z]", text)) < 30:
        return False
    source_script_chars = sum(len(re.findall(pattern, text)) for pattern, _ in SCRIPT_LANGUAGE_HINTS)
    return source_script_chars / max(len(re.findall(r"\w", text, re.UNICODE)), 1) < 0.02


def translate_to_english(text: str, provider: str = "auto", fast: bool = False) -> tuple[str, str]:
    from langdetect import detect, LangDetectException
    
    if not text or not text.strip():
        return text, "Unknown"
    
    try:
        lang = detect(text)
    except LangDetectException:
        lang = "en"

    # A document with an English title can confuse language detection. Prefer
    # a dominant regional script, so Tamil/Kannada documents are translated.
    document_letters = max(len(re.findall(r"\w", text, re.UNICODE)), 1)
    for pattern, language_code in SCRIPT_LANGUAGE_HINTS:
        if len(re.findall(pattern, text)) / document_letters > 0.08:
            lang = language_code
            break

    lang_names = {
        # ── Global languages ────────────────────────────────────────
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
        "ru": "Russian",
        "zh-cn": "Chinese (Simplified)",
        "zh-tw": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "ar": "Arabic",
        # ── Indian languages ─────────────────────────────────────────
        "hi": "Hindi (हिन्दी)",
        "bn": "Bengali (বাংলা)",
        "te": "Telugu (తెలుగు)",
        "mr": "Marathi (मराठी)",
        "ta": "Tamil (தமிழ்)",
        "ur": "Urdu (اردو)",
        "gu": "Gujarati (ગુજરાતી)",
        "kn": "Kannada (ಕನ್ನಡ)",
        "ml": "Malayalam (മലയാളം)",
        "pa": "Punjabi (ਪੰਜਾਬੀ)",
        "or": "Odia (ଓଡ଼ିଆ)",
        "as": "Assamese (অসমীয়া)",
        "ne": "Nepali (नेपाली)",
        "si": "Sinhala (සිංහල)",
        "sa": "Sanskrit (संस्कृतम्)",
        "mai": "Maithili (मैथिली)",
    }
    lang_name = lang_names.get(lang.lower(), f"Unknown ({lang.upper()})")

    if lang.lower() == "en":
        return text, "English"

    # Check if offline-only translation is requested
    translation_provider = os.getenv("TRANSLATION_PROVIDER", "auto").lower()
    if translation_provider == "offline":
        print(f"Offline-only translation mode enabled for {lang}...")
        try:
            from offline_translator import offline_translate
            offline_result = offline_translate(text, lang, SCRIPT_LANGUAGE_HINTS, allow_ollama=not fast)
            if offline_result:
                print("Offline translation successful")
                return offline_result, f"{lang_name} (offline translation)"
            else:
                raise ValueError(
                    f"Offline translation failed for {lang_name} (code '{lang}'). "
                    f"Only Hindi/Bengali/Urdu have offline Argos packs, and the web fallbacks "
                    f"(Google/MyMemory) were rate-limited or unreachable. "
                    f"Wait 2 minutes and retry, or use Gemini Cloud: set TRANSLATION_PROVIDER=auto and add a valid GEMINI_API_KEY."
                )
        except ImportError:
            raise ValueError(
                "Offline translation not available. Install with: pip install argostranslate"
            )

    # Split text into translation chunks of ~6000 chars
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""
    for p in paragraphs:
        if len(current_chunk) + len(p) + 1 < 6000:
            current_chunk += p + "\n"
        else:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = p + "\n"
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    if not chunks:
        return text, lang_name

    translated_parts = []
    system_prompt = (
        "You are a certified legal translator. Translate every word of the contract segment into accurate legal English.\n"
        "Do not summarize, omit, simplify, add commentary, or answer questions. Preserve all clause numbers, headings, "
        "names, currency amounts, dates, percentages, tables represented as lines, and legal conditions exactly.\n"
        "Output ONLY the complete translated English document text."
    )

    import time
    from concurrent.futures import ThreadPoolExecutor

    def _translate_chunk(item):
        i, chunk = item
        prompt = f"Document segment to translate ({i+1} of {len(chunks)}):\n\n{chunk}"
        # A translation must be complete, so retry a transient provider failure
        # once before rejecting the document rather than passing native text on.
        # Quota/config errors (ValueError) skip the sleep loop — the offline
        # fallback below covers those chunks without dead waiting.
        for _ in range(2):
            try:
                translated_part, _ = _llm_call(system_prompt, prompt, provider)
            except ValueError:
                break
            if translated_part and _is_verified_english(translated_part):
                return i, translated_part.strip(), None
            time.sleep(0.5)
        return i, None, chunk  # failed chunk, for targeted offline fallback

    translated_parts: list = [None] * len(chunks)
    failed_chunks = []
    used_offline = False
    # Chunks are independent — translate concurrently (~3-4x faster), restore order after.
    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
        for i, part, failed in pool.map(_translate_chunk, enumerate(chunks)):
            if part:
                translated_parts[i] = part
            else:
                failed_chunks.append((i, failed))

    if failed_chunks:
        # Offline fallback covers only the failed chunks — not the whole document.
        try:
            from offline_translator import offline_translate
            for i, chunk in failed_chunks:
                print(f"LLM translation failed for chunk {i+1}. Attempting offline translation for {lang}...")
                offline_result = offline_translate(chunk, lang, SCRIPT_LANGUAGE_HINTS, allow_ollama=not fast)
                if offline_result:
                    translated_parts[i] = offline_result
                    used_offline = True
                    print(f"Offline translation successful for chunk {i+1}")
                else:
                    print("Offline translation unavailable or failed")
        except ImportError:
            print("Offline translation not available. Install with: pip install argostranslate deep-translator")
        except Exception as e:
            print(f"Offline translation error: {e}")

    if any(p is None for p in translated_parts):
        raise ValueError(
            f"Could not complete a verified English translation of this {lang_name} (detected '{lang}') document. "
            f"Try: (1) set GEMINI_API_KEY and use provider='gemini' for cloud translation, or "
            f"(2) offline: pip install argostranslate deep-translator && argospm update && argospm install translate-{lang}_en "
            f"(note: some pairs like gu->en have no Argos pack — the built-in Google/MyMemory web fallbacks then apply). "
            "The document was not sent to analysis."
        )

    label = f"{lang_name} (offline translation)" if used_offline else lang_name
    return "\n\n".join(translated_parts), label


def _get_embedding_single(text: str, provider: str = "auto") -> list[float] | None:
    """Retrieve semantic embedding vector for a single text using Gemini or Ollama."""
    chosen = provider.lower() if provider else "auto"
    if not text or not text.strip():
        return None
    # 1. Try Gemini text-embedding-004
    if chosen in {"auto", "gemini"} and os.getenv("GEMINI_API_KEY"):
        api_key = os.environ["GEMINI_API_KEY"]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={api_key}"
        try:
            res = requests.post(url, json={"model": "models/text-embedding-004", "content": {"parts": [{"text": text[:2048]}]}}, timeout=8)
            if res.status_code == 200:
                values = res.json().get("embedding", {}).get("values")
                if values and isinstance(values, list):
                    return values
        except Exception:
            pass
    # 2. Try Ollama embeddings
    if chosen in {"auto", "ollama"}:
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        model = os.getenv("OLLAMA_EMBED_MODEL", os.getenv("OLLAMA_MODEL", "llama3.2"))
        try:
            res = requests.post(f"{host}/api/embeddings", json={"model": model, "prompt": text[:2048]}, timeout=4)
            if res.status_code == 200:
                values = res.json().get("embedding")
                if values and isinstance(values, list):
                    return values
        except Exception:
            pass
    return None


def _get_embeddings_batch(texts: list[str], provider: str = "auto") -> list[list[float]] | None:
    """Batch retrieve semantic embeddings for a list of text chunks."""
    if not texts:
        return []
    chosen = provider.lower() if provider else "auto"
    # 1. Try Gemini batchEmbedContents
    if chosen in {"auto", "gemini"} and os.getenv("GEMINI_API_KEY"):
        api_key = os.environ["GEMINI_API_KEY"]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents?key={api_key}"
        reqs = [{"model": "models/text-embedding-004", "content": {"parts": [{"text": t[:2048]}]}} for t in texts[:100]]
        try:
            res = requests.post(url, json={"requests": reqs}, timeout=15)
            if res.status_code == 200:
                raw = res.json().get("embeddings", [])
                embeddings = [item.get("values") for item in raw if item.get("values")]
                if len(embeddings) == len(reqs):
                    return embeddings
        except Exception:
            pass
    # Fallback to individual embeddings
    results = []
    for t in texts:
        emb = _get_embedding_single(t, provider=provider)
        if emb is None:
            return None
        results.append(emb)
    return results


_NER_HTML_VERSION = "<!--mner-ner-v2-->"


class DocumentRAG:
    def __init__(self, text: str, filename: str, provider: str = "auto"):
        self.filename = filename
        if not text or not text.strip():
            text = "Empty document"
        self.text = text
        self.chunks = split_document(text)
        # Ensure we have at least one chunk
        if not self.chunks or all(not c.strip() for c in self.chunks):
            self.chunks = ["Empty document"]
        # Character n-grams make retrieval more forgiving of legal word forms
        # such as "terminate", "termination", and "terminating".
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform(self.chunks)
        self.provider = provider
        # Fetch embeddings in background so __init__ returns instantly.
        # retrieve() checks self._emb_future when first called.
        self.embeddings = None
        self._emb_future = None
        try:
            from concurrent.futures import ThreadPoolExecutor as _EPool
            _ep = _EPool(max_workers=1)
            self._emb_future = _ep.submit(_get_embeddings_batch, self.chunks, provider)
            _ep.shutdown(wait=False)
        except Exception:
            pass

    def _resolve_embeddings(self):
        """Resolve background embedding future if not already done."""
        if self.embeddings is None and self._emb_future is not None:
            try:
                self.embeddings = self._emb_future.result(timeout=4)
            except Exception:
                self.embeddings = None
            self._emb_future = None

    def retrieve(self, question: str, k: int = 4):
        if not question or not question.strip():
            return []

        self._resolve_embeddings()

        # Compute Lexical (TF-IDF) Scores
        tfidf_scores = cosine_similarity(self.vectorizer.transform([question]), self.matrix).flatten()

        # Compute Semantic (Embedding) Scores if available
        q_emb = None
        if self.embeddings and len(self.embeddings) == len(self.chunks):
            try:
                q_emb = _get_embedding_single(question, provider=self.provider)
            except Exception:
                q_emb = None
        
        if q_emb is not None and self.embeddings:
            try:
                import numpy as np
                q_arr = np.array([q_emb])
                doc_arr = np.array(self.embeddings)
                semantic_scores = cosine_similarity(q_arr, doc_arr).flatten()
                
                # Hybrid Blend: 70% Semantic Meaning + 30% Lexical Exact Terms
                max_s = max(semantic_scores) if max(semantic_scores) > 0 else 1.0
                max_t = max(tfidf_scores) if max(tfidf_scores) > 0 else 1.0
                norm_s = semantic_scores / max_s
                norm_t = tfidf_scores / max_t
                
                combined_scores = 0.7 * norm_s + 0.3 * norm_t
                order = combined_scores.argsort()[::-1][:k]
                return [(int(i), self.chunks[i], float(combined_scores[i])) for i in order if combined_scores[i] > 0]
            except Exception as e:
                print(f"Hybrid retrieval calculation fallback: {e}")
        
        order = tfidf_scores.argsort()[::-1][:k]
        return [(int(i), self.chunks[i], float(tfidf_scores[i])) for i in order if tfidf_scores[i] > 0]

    def risk_scan(self):
        joined = " ".join(self.chunks).lower()
        found = []
        for name, phrases in RISK_RULES.items():
            if any(phrase in joined for phrase in phrases):
                found.append(name)
        return {
            "flags": found,
            "message": f"Found {len(found)} document areas worth reviewing." if found else "No common risk terms were detected automatically.",
        }

    def _normalize_text_for_ner(self, text: str) -> str:
        """Normalize text to prevent translation artifacts from causing NER issues."""
        # Replace multiple newlines with single space
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        # Replace single newlines with space (but keep paragraph breaks)
        text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
        # Replace multiple spaces with single space
        text = re.sub(r'[ \t]+', ' ', text)
        # Remove zero-width spaces and other invisible chars
        text = re.sub(r'[\u200b-\u200f\ufeff]', '', text)
        return text.strip()

    def entity_scan(self):
        """Extract document entities using spaCy NER (+ regex for legal specifics)."""
        text = self._normalize_text_for_ner(" ".join(self.chunks))
        entities: list[dict] = []
        buckets: dict[str, list[str]] = {}

        # 1) spaCy NER — primary, multilingual-aware via English-translated text
        try:
            nlp = _get_spacy_nlp()
            if nlp is None:
                raise OSError("spaCy model unavailable")
            if nlp is not None:
                # spaCy works best on sentences; limit to avoid OOM on huge docs
                doc = nlp(text[:80000])
                # Map spaCy labels to user-facing buckets
                label_map = {
                    "PERSON": "Persons",
                    "NORP": "Groups",
                    "ORG": "Organizations",
                    "GPE": "Locations",
                    "LOC": "Locations",
                    "FAC": "Facilities",
                    "DATE": "Dates",
                    "TIME": "Dates",
                    "MONEY": "Amounts",
                    "QUANTITY": "Amounts",
                    "PERCENT": "Amounts",
                    "LAW": "Legal References",
                    "PRODUCT": "Organizations",
                    "EVENT": "Events",
                    "WORK_OF_ART": "Works",
                    "LANGUAGE": "Languages",
                }
                for ent in doc.ents:
                    orig_label = ent.label_
                    bucket = label_map.get(orig_label)
                    if not bucket:
                        continue
                    # Special-case NORP: person names like "Priya Sharma" vs locations like "Maharashtra"
                    if orig_label == "NORP":
                        if " " in ent.text and ent.text.strip().istitle() and len(ent.text.strip().split()) == 2:
                            bucket = "Persons"
                        else:
                            bucket = "Locations"
                    val = ent.text.strip(" ,.;\"'").replace("\n", " ")
                    if len(val) < 2 or len(val) > 120:
                        continue
                    low2 = val.lower()
                    GENERIC_SUBS = ("machine learning","history & fundamentals","history and fundamentals","support vector","random forest","artificial intelligence","what is machine","why it was created","how it evolved","where it is used","table of contents","inventors")
                    if low2 in ("ai",) and orig_label == "GPE":
                        continue
                    if low2 == "ml" and orig_label == "ORG":
                        continue
                    if any(s in low2 for s in GENERIC_SUBS):
                        if orig_label in ("PERSON","ORG","GPE","PRODUCT","WORK_OF_ART","NORP"):
                            continue
                    if "founded" in low2 and orig_label == "PERSON":
                        val = re.sub(r'\s+founded\s*$', '', val, flags=re.I).strip()
                        if len(val) < 3:
                            continue
                        low2 = val.lower()
                    if re.match(r'^(page\s*\d+|p\.\s*\d+)$', low2):
                        continue
                    if low2.startswith("page ") and orig_label in ("ORG","PERSON","GPE"):
                        continue
                    # Fix common spaCy mislabels: INR/$ amounts tagged as ORG/NORP
                    if re.match(r'^(?:USD|INR|EUR|GBP|\$|₹|€|£)\s?[\d,]', val):
                        bucket = "Amounts"
                    # Gazetteer + boilerplate correction for Indian documents
                    # (Chennai→Locations not ORG, Tamil Nadu→Locations not Persons,
                    # "Due Date"/"Scope of Services" are not entities at all)
                    _corr = _correct_indian_entity(val)
                    if _corr == "DROP":
                        continue
                    if _corr == "GPE":
                        bucket = "Locations"
                    # de-duplicate case-insensitive, keep first 8 per bucket
                    lst = buckets.setdefault(bucket, [])
                    if val.lower() not in {v.lower() for v in lst} and len(lst) < 8:
                        lst.append(val)
                # --- Strong Indian corrections (festivals, currency, monuments) ---
                FESTIVAL_SET = {"diwali","दिवाळी","divali","holi","होळी","navratri","नवरात्री","eid","ईद","christmas","ख्रिसमस","pongal","पोंगल","onam","ओणम","baisakhi","बैसाखी","ganesh chaturthi","गणेश चतुर्थी","republic day","प्रजासत्ताक दिन","independence day","स्वातंत्र्य दिन","dussehra","दसरा","durga puja","दुर्गा पूजा","independence","swatantrya","republic"}
                CURRENCY_SET = {"भारतीय रुपया","indian rupee","bharatiya rupya","रुपया"}
                MONUMENT_SET = {"ताजमहल","taj mahal","कुतुबमिनार","qutub minar","gateway of india","गेटवे ऑफ इंडिया","qutub minar (delhi)","india gate"}
                for src_bucket in list(buckets.keys()):
                    for val in list(buckets[src_bucket]):
                        low = val.lower().strip()
                        # Festival -> Events
                        if any(f in low for f in FESTIVAL_SET if len(f) > 2):
                            if src_bucket != "Events":
                                try: buckets[src_bucket].remove(val)
                                except: pass
                                if low not in {v.lower() for v in buckets.get("Events", [])} and len(buckets.get("Events", [])) < 8:
                                    buckets.setdefault("Events", []).append(val)
                                continue
                        # Currency -> Amounts
                        if low in CURRENCY_SET or "रुपया" in low or "rupee" in low:
                            if src_bucket != "Amounts":
                                try: buckets[src_bucket].remove(val)
                                except: pass
                                if low not in {v.lower() for v in buckets.get("Amounts", [])}:
                                    buckets.setdefault("Amounts", []).append(val)
                                continue
                        # Monuments/backwaters/mountains -> Locations/Facilities
                        if any(m in low for m in MONUMENT_SET) or "बॅकवॉटर" in low or "backwater" in low or "पर्वतमाला" in low or "mountain" in low:
                            target = "Facilities" if any(m in low for m in MONUMENT_SET) else "Locations"
                            if src_bucket != target:
                                try: buckets[src_bucket].remove(val)
                                except: pass
                                if low not in {v.lower() for v in buckets.get(target, [])}:
                                    buckets.setdefault(target, []).append(val)
                # Fast local rule engine for Indian script entity normalization (instant, 0ms)
                pass
                # Self-introductions always win ("my name is Gaurav" → Persons)
                _force_persons_bucket(buckets, _self_introduced_names(text))
        except Exception as e:
            print(f"spaCy entity_scan fallback: {e}")

        # 2) Regex augmentation — legal-specific patterns spaCy often misses
        #    (e.g., "between X and Y", "governing law of ...", INR amounts)
        # Indian months for strong date recognition (English + Gujarati/Hindi/Marathi/Tamil/Telugu/Kannada/Malayalam/Bengali)
        _indian_months = r"[\u0900-\u0AFF\u0B80-\u0CFF\u0C00-\u0C7F\u0D00-\u0D7F]{2,15}"  # Generic Indic month
        _en_months = r"January|February|March|April|May|June|July|August|September|October|November|December"
        _all_months = _en_months + "|" + _indian_months
        regex_patterns = {
            "Parties": r"(?:between|by and between)\s+([A-Z][A-Za-z0-9&.,' -]{2,70}?)\s+and\s+([A-Z][A-Za-z0-9&.,' -]{2,70}?)(?:\s+(?:on|dated)|[.,;(])",
            "Dates": rf"\b(?:\d{{1,2}}\s+(?:{_all_months})\s+\d{{4}}|(?:{_all_months})\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}})\b",
            "Amounts": r"(?:USD|INR|EUR|GBP|\$|₹|€|£)\s?[\d,]+(?:\.\d{2})?",
            "Jurisdictions": r"(?:governed by (?:the )?laws of|courts? of|jurisdiction of)\s+([A-Z][A-Za-z ]{2,45}?)(?:\s+(?:and|which|subject)|[.,;]|$)",
        }
        for label, pattern in regex_patterns.items():
            values: list[str] = []
            for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                vals = list(m.groups()) if label == "Parties" else [m.group(1) if m.lastindex else m.group(0)]
                for v in vals:
                    v = v.strip(" ,.;")
                    if v and v.lower() not in {x.lower() for x in values}:
                        values.append(v)
                if len(values) >= 4:
                    break
            if values:
                # merge into spaCy buckets (or create new) without duplicates
                lst = buckets.setdefault(label, [])
                for v in values:
                    if v.lower() not in {x.lower() for x in lst} and len(lst) < 8:
                        lst.append(v)

        # 3) Legal topics keyword scan (always useful)
        terms = [t.title() for t in LEGAL_TERMS if t in text.lower()]
        if terms:
            buckets["Key topics"] = terms[:6]

        # 4) Convert to expected list[dict] shape
        for typ, vals in buckets.items():
            if vals:
                entities.append({"type": typ, "values": vals})

        # Fallback empty guard
        return entities

    def _regex_highlight_fallback(self, text: str) -> str:
        """Highlight entity_scan values with regex when spaCy yields nothing —
        guarantees the NER view never renders as an unmarked wall of text."""
        import html as html_lib
        try:
            buckets = {}
            for e in (self.entity_scan() or []):
                vals = [v for v in (e.get("values") or []) if v and len(v.strip()) >= 2]
                if vals:
                    buckets[e.get("type", "Other")] = vals
        except Exception:
            buckets = {}
        if not buckets:
            return ""
        bg_map = {"Persons": "#FFDAB9", "Organizations": "#A0E0E0", "Locations": "#FFDC8A",
                  "Dates": "#A8D8EA", "Amounts": "#FFB6B6", "Facilities": "#FCEEB0",
                  "Events": "#FFEC8B", "Jurisdictions": "#C1F0C1", "Parties": "#E0E0E0",
                  "Legal References": "#FFC0CB", "Key topics": "#FFE4B5"}
        label_map = {"Persons": "PERSON", "Organizations": "ORG", "Locations": "GPE",
                     "Dates": "DATE", "Amounts": "MONEY", "Facilities": "FAC",
                     "Events": "EVENT", "Jurisdictions": "GPE", "Parties": "ORG",
                     "Legal References": "LAW", "Key topics": "TOPIC"}
        # Longest-first so "Anna Salai" wins over "Anna"; skip values inside larger matches.
        items = sorted(((v, t) for t, vals in buckets.items() for v in vals),
                       key=lambda x: -len(x[0]))
        spans = []
        used = []
        for val, typ in items:
            try:
                pat = re.compile(re.escape(val), re.IGNORECASE)
            except Exception:
                continue
            for m in pat.finditer(text):
                s, e = m.start(), m.end()
                if any(s < u1 and e > u0 for u0, u1 in used):
                    continue
                used.append((s, e))
                spans.append((s, e, typ, text[s:e]))
                break  # first occurrence per value keeps the view clean
        if not spans:
            return ""
        spans.sort(key=lambda x: x[0])
        parts, last = [], 0
        for s, e, typ, txt in spans:
            if s < last:
                continue
            bg = bg_map.get(typ, "#E0E0E0")
            lab = label_map.get(typ, typ[:4].upper())
            parts.append(html_lib.escape(text[last:s]).replace("\n", "<br>"))
            parts.append(
                f'<mark style="background:{bg};padding:1px 6px 2px;border-radius:8px;border:1px solid rgba(0,0,0,.06);margin:0 2px;line-height:2.2;white-space:nowrap">'
                f'<span style="color:#0E2E2B">{html_lib.escape(txt)}</span> '
                f'<small style="font-size:12px;font-weight:800;letter-spacing:.04em;background:rgba(0,0,0,.08);padding:1px 4px;border-radius:8px;margin-left:4px;vertical-align:middle">{lab}</small>'
                f'</mark>'
            )
            last = e
        parts.append(html_lib.escape(text[last:]).replace("\n", "<br>"))
        body = "".join(parts)
        header = (
            '<div style="background:#FFFEFA;border:1px solid #E0D9B8;border-radius:10px;padding:14px 16px;margin-bottom:16px;font-size:13px;line-height:1.6;color:#0E2E2B">'
            '<strong style="color:#0E2E2B">What is NER?</strong> Named Entity Recognition detects and classifies key entities — '
            '<em>persons, organizations, locations, dates, amounts</em> — turning unstructured text into structured data.'
            '</div>'
        )
        return _NER_HTML_VERSION + header + '<div style="background:#fff;border:1px solid #E6EFE9;border-radius:10px;padding:18px;line-height:2.1;font-size:14px;color:#0E2E2B;max-height:520px;overflow:auto">' + body + '</div>'

    def get_ner_highlighted_html(self) -> str:
        """Return document text with spaCy entities highlighted like displaCy — for the 3rd-image pattern."""
        import html as html_lib
        text = self._normalize_text_for_ner(self.text[:80000])
        # PDF extractors often join words ("PrivateLimited", "Meridianlogistics").
        # Split CamelCase joins for display so highlighted text reads properly.
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
        text = re.sub(r"\s*\|\s*", "  |  ", text)
        lines = text.split("\n")
        while lines and re.match(r'^\s*(•|-|\*|–|—|\d+|[·•])\s*$', lines[-1]):
            lines.pop()
        cleaned_lines = []
        for ln in lines:
            if re.match(r'^\s*•\s*$', ln):
                continue
            if re.match(r'^\s*\d+\s*$', ln) and len(cleaned_lines) > 5:
                continue
            cleaned_lines.append(ln)
        text = "\n".join(cleaned_lines).strip()
        text = re.sub(r'\s+•\s*$', '', text)
        text = re.sub(r'\n\s*•\s*\n', '\n', text)
        color_map = {
            "DATE": "#A8D8EA", "TIME": "#A8D8EA",
            "PERSON": "#FFDAB9", "NORP": "#FFE4B5",
            "ORG": "#A0E0E0", "PRODUCT": "#E0E0E0",
            "GPE": "#FFDC8A", "LOC": "#C1F0C1", "FAC": "#FCEEB0",
            "MONEY": "#FFB6B6", "PERCENT": "#D8BFD8", "QUANTITY": "#FFB6B6",
            "LAW": "#FFC0CB", "EVENT": "#FFEC8B", "WORK_OF_ART": "#E6E6FA",
        }
        try:
            nlp = _get_spacy_nlp()
            if nlp is None:
                return self._regex_highlight_fallback(text) or (
                    "<p>Entity highlighting is unavailable for this document.</p>")
            doc = nlp(text)
            spans: list[tuple[int,int,str,str]] = []
            # --- Filter false positives for technical / generic headings / TOC ---
            # Use substring check (not just start) because spaCy often merges heading fragments like
            # "Machine Learning — History & Fundamentals" or "Page 1 MACHINE LEARNING History Inventors"
            GENERIC_SUBSTRINGS = ("machine learning","history & fundamentals","history and fundamentals","support vector","random forest","artificial intelligence","what is machine","why it was created","how it evolved","where it is used","table of contents","inventors")
            for ent in doc.ents:
                if ent.label_ not in color_map:
                    continue
                txt = ent.text.strip()
                low = txt.lower()
                # Fix "Claude Shannon Founded" -> trim verb
                if 'founded' in low and ent.label_ == 'PERSON':
                    txt = re.sub(r'\s+founded\s*$', '', txt, flags=re.I).strip()
                    if not txt or len(txt) < 3:
                        continue
                    low = txt.lower()
                # AI alone is not GPE (common spaCy error: AI -> GPE)
                if low == 'ai' and ent.label_ == 'GPE':
                    continue
                # Standalone "ML" tagged ORG is not useful in a generic ML doc — skip
                if low == 'ml' and ent.label_ == 'ORG':
                    continue
                # Generic headings / TOC fragments should not be PERSON/ORG/GPE/PRODUCT
                if any(sub in low for sub in GENERIC_SUBSTRINGS):
                    if ent.label_ in ('PERSON','NORP','ORG','PRODUCT','GPE','WORK_OF_ART'):
                        continue
                # Page/TOC markers
                if re.match(r'^(page\s*\d+|p\.\s*\d+)$', low):
                    continue
                if low.startswith("page ") and ent.label_ in ("ORG","PERSON","GPE"):
                    continue
                # Gazetteer + boilerplate: Indian places forced to GPE,
                # generic headers ("Due Date") dropped entirely.
                _corr = _correct_indian_entity(txt)
                if _corr == "DROP":
                    continue
                _disp_label = "GPE" if _corr == "GPE" else ent.label_
                spans.append((ent.start_char, ent.end_char, _disp_label, txt))
            try:
                _ind_m = r"[\u0900-\u0AFF\u0B80-\u0CFF\u0C00-\u0C7F\u0D00-\u0D7F]{2,15}"  # Generic Indic month — matches Marathi जान्युारी even with PDF splits
                _en_m = r"January|February|March|April|May|June|July|August|September|October|November|December"
                _date_pat = rf"\b\d{{1,2}}\s+(?:{_en_m}|{_ind_m})\s+\d{{4}}\b"
                for m in re.finditer(_date_pat, text):
                    s, e = m.start(), m.end()
                    if any(s < es_end and e > es_start for es_start, es_end, _, _ in spans):
                        continue
                    spans.append((s, e, "DATE", m.group(0)))
            except Exception:
                pass
            # Self-introduced names are always PERSON, even if spaCy missed
            # them or tagged them ORG/NORP ("my name is Gaurav").
            for _nm in _self_introduced_names(text):
                try:
                    for _m in re.finditer(re.escape(_nm), text, flags=re.IGNORECASE):
                        _s, _e = _m.start(), _m.end()
                        _ovs = [(a, b) for a, b, c, d in spans if _s < b and _e > a]
                        if any((b - a) > (_e - _s) for a, b in _ovs):
                            continue  # a bigger span owns this range; keep it
                        spans = [(a, b, c, d) for a, b, c, d in spans
                                 if not (_s <= a and _e >= b)]
                        spans.append((_s, _e, "PERSON", text[_s:_e]))
                        break
                except Exception:
                    pass
            spans.sort(key=lambda x: x[0])
            if not spans:
                # spaCy saw nothing (garbled MT/PDF text) — highlight the
                # entity_scan values instead of rendering an unmarked wall.
                return self._regex_highlight_fallback(text) or (
                    "<p>No entities detected in this document.</p>")
            parts: list[str] = []
            last = 0
            for s, e, lab, txt in spans:
                if s < last:
                    continue
                low = txt.lower()
                corr_lab = None
                corr_bg = None
                if txt.strip() == "भारत" or low == "bharat":
                    corr_lab = "GPE"; corr_bg = "#FFDC8A"
                elif any(k in low for k in ["diwali","दिवाळी","holi","होळी","navratri","नवरात्री","eid","ईद","christmas","ख्रिसमस","pongal","पोंगल","onam","ओणम","baisakhi","बैसाखी","ganesh","गणेश","dussehra","दसरा","republic","प्रजासत्ताक","independence","स्वातंत्र्य"]):
                    corr_lab = "EVENT"; corr_bg = "#FFEC8B"
                elif "रुपया" in txt or "rupee" in low:
                    corr_lab = "MONEY"; corr_bg = "#FFB6B6"
                elif any(m in low for m in ["ताजमहल","taj mahal","कुतुबमिनार","qutub","गेटवे","gateway","बॅकवॉटर","backwater","पर्वतमाला","mountain"]):
                    if any(x in low for x in ["ताजमहल","taj mahal","कुतुब","qutub","गेटवे","gateway"]):
                        corr_lab = "FAC"; corr_bg = "#FCEEB0"
                    else:
                        corr_lab = "LOC"; corr_bg = "#C1F0C1"
                parts.append(html_lib.escape(text[last:s]).replace("\n", "<br>"))
                bg = corr_bg if corr_bg else color_map.get(lab, "#E0E0E0")
                label = corr_lab if corr_lab else lab
                parts.append(
                    f'<mark style="background:{bg};padding:1px 6px 2px;border-radius:8px;border:1px solid rgba(0,0,0,.06);margin:0 2px;line-height:2.2;white-space:nowrap">'
                    f'<span style="color:#0E2E2B">{html_lib.escape(txt)}</span> '
                    f'<small style="font-size:12px;font-weight:800;letter-spacing:.04em;background:rgba(0,0,0,.08);padding:1px 4px;border-radius:8px;margin-left:4px;vertical-align:middle">{label}</small>'
                    f'</mark>'
                )
                last = e
            parts.append(html_lib.escape(text[last:]).replace("\n", "<br>"))
            header = (
                '<div style="background:#FFFEFA;border:1px solid #E0D9B8;border-radius:10px;padding:14px 16px;margin-bottom:16px;font-size:13px;line-height:1.6;color:#0E2E2B">'
                '<strong style="color:#0E2E2B">What is NER?</strong> Named Entity Recognition detects and classifies key entities — '
                '<em>persons, organizations, locations, dates, amounts</em> — turning unstructured text into structured data. '
                'As noted in the Medium article, it powers <strong>information extraction, search, chatbots, knowledge graphs and RAG systems</strong> '
                'by helping LLMs know <em>who, what, where and when</em> in a document.'
                '</div>'
            )
            return _NER_HTML_VERSION + header + '<div style="background:#fff;border:1px solid #E6EFE9;border-radius:10px;padding:18px;line-height:2.1;font-size:14px;color:#0E2E2B;max-height:520px;overflow:auto">' + "".join(parts) + '</div>'
        except Exception as e:
            fallback = self._regex_highlight_fallback(text)
            if fallback:
                return fallback
            return "<p>Entity highlighting is unavailable for this document.</p>"

    def _local_audit(self) -> dict:
        """Create a useful, source-grounded audit when a model is unavailable."""
        text = self.text
        lowered = text.lower()
        clauses = []
        for index, chunk in enumerate(self.chunks):
            match = re.match(r"\s*(\d+(?:\.\d+)*[.)])\s*([^\n]{2,100})", chunk)
            if not match:
                continue
            title = re.sub(r"\s+", " ", match.group(2)).strip(" :.-")
            body = chunk[match.end():].strip() or chunk
            severity = "High" if any(word in body.lower() for word in ("unlimited", "indemnify", "penalty", "sole discretion")) else "Medium" if any(word in body.lower() for word in ("terminate", "liability", "confidential", "payment")) else "Low"
            clauses.append({
                "clause_name": title,
                "severity": severity,
                "text_snippet": body[:700],
                "summary": f"Clause {match.group(1)} covers {title.lower()}. {body[:360]}"
            })

        date_match = re.search(r"(?:effective date|date of agreement)\s*[:\-]?\s*([^\n.;]{4,80})", text, re.I)
        dates = re.findall(r"\b(?:\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})\b", text, re.I)
        effective_date = date_match.group(1).strip() if date_match else (dates[0] if dates else "Not Specified")
        party_match = re.search(r"(?:between|by and between)\s+(.{2,80}?)\s+and\s+(.{2,80}?)(?:\s+(?:on|dated)\b|[.;\n])", text, re.I)
        parties = [part.strip(" ,.;") for part in party_match.groups()] if party_match else []
        law_match = re.search(r"\blaws? of\s+([A-Z][A-Za-z ]{2,60}?)(?:,|\.|;|\n|$)", text, re.I)
        if not law_match:
            law_match = re.search(r"\bgoverning law\s*[:\-]\s*([^.;\n]+)", text, re.I)
        governing_law = law_match.group(1).strip(" ,.;") if law_match else "Not Specified"
        agreement_type = "Service Agreement" if "service agreement" in lowered or "services" in lowered else "Agreement"

        risks = []
        if "limitation of liability" in lowered and not re.search(r"(?:liability|damages).{0,80}(?:shall not exceed|limited to|cap)", lowered):
            risks.append({"description": "The liability clause excludes some losses but does not state a clear financial liability cap.", "severity": "Medium", "mitigation": "Agree a maximum liability amount and identify any carve-outs that should remain uncapped."})
        if "terminate" in lowered:
            risks.append({"description": "Either party may have termination rights that could end the commercial arrangement on notice.", "severity": "Medium", "mitigation": "Confirm the notice period, cure rights, transition support, and any fees due after termination."})
        if "confidential" in lowered and not re.search(r"confidential.{0,200}(?:years?|months?|surviv|term)", lowered):
            risks.append({"description": "Confidentiality obligations are present, but their duration is not clearly stated.", "severity": "Low", "mitigation": "Specify how long confidentiality duties continue after the agreement ends."})

        required = {
            "Intellectual Property": ("intellectual property", "ownership", "license"),
            "Data Protection": ("personal data", "data protection", "privacy"),
            "Dispute Resolution": ("arbitration", "mediation", "dispute resolution"),
            "Force Majeure": ("force majeure",),
            "Notices": ("notice", "notices"),
        }
        missing = [{"clause_name": name, "description": f"No clear {name.lower()} provision was found. Add one to clarify rights and responsibilities."}
                   for name, terms in required.items() if not any(term in lowered for term in terms)]
        return {
            "metadata": {"agreement_type": agreement_type, "effective_date": effective_date, "parties": parties,
                         "governing_law": governing_law, "overall_risk_level": "Medium" if risks else "Low"},
            "key_clauses": clauses,
            "risks": risks,
            "missing_clauses": missing,
            "inconsistencies": []
        }



    def answer(self, question: str, provider: str = "auto"):
        passages = self.retrieve(question)
        if not passages:
            return {"answer": "I could not find a clause that directly addresses this question.", "citations": [], "mode": "retrieval"}
        context = "\n\n".join(f"[Clause {i + 1}] {chunk}" for i, chunk, _ in passages)
        system = (
            "You are a helpful Multilingual NER assistant for Indian Languages. Answer ONLY from the provided excerpts. "
            "Return clean, visually proper Markdown:\n"
            "- Output ONLY the final answer. NEVER narrate your process (no 'We are given…', no 'Steps:', no reasoning). NEVER repeat the question. Start immediately with the answer.\n"
            "- Start with 1-2 sentences that DIRECTLY answer the question in plain words.\n"
            "- Then use ### section headings (e.g. ### Locations, ### Dates). No bold inside heading.\n"
            "- Under each heading, use bullet list: - **Entity** — brief context [Clause N]\n"
            "- Bold only the entity name. Use an em dash — between entity and explanation.\n"
            "- Keep each bullet on one line. Put citation [Clause N] at end of bullet, exactly as given.\n"
            "- Do NOT use *** or ####. No nested headings. No extra formatting.\n"
            "- If nothing found for a section, write: Not found in document.\n"
            "- Keep answer concise and scannable. Do not give legal advice."
        )
        prompt = f"Question: {question}\n\nDocument excerpts:\n{context}"
        try:
            # Local models need room: generous timeout + bounded generation.
            import time as _at
            _answer_prefill = "Based on the document excerpts, here is the answer:\n\n"
            _t0 = _at.time()
            answer, used_provider = _llm_call(
                system, prompt, provider, _timeout=180,
                _options={"num_ctx": 4096, "num_predict": 380, "temperature": 0.1,
                          "stop": ["We are given", "Steps:", "Let me re-read",
                                   "However, note", "First, let me",
                                   "Okay, the user", "Let me think"]},
                _prefill=_answer_prefill)
            if answer and answer.strip() and not answer.lstrip().startswith("Based on"):
                answer = _answer_prefill + answer.strip()
            if not (answer and answer.strip()) and (_at.time() - _t0) < 30:
                # Fast failure (e.g. empty fluke) — one immediate retry before
                # falling back to the extractive answer below.
                answer, used_provider = _llm_call(
                    system, prompt, provider, _timeout=180,
                    _options={"num_ctx": 4096, "num_predict": 380, "temperature": 0.1,
                              "stop": ["We are given", "Steps:", "Let me re-read",
                                       "However, note", "First, let me",
                                       "Okay, the user", "Let me think"]},
                    _prefill=_answer_prefill)
                if answer and answer.strip() and not answer.lstrip().startswith("Based on"):
                    answer = _answer_prefill + answer.strip()
        except ValueError:
            # Quota/config failure — retrieval fallback below still answers.
            answer, used_provider = None, None
        if not answer:
            # No LLM reachable: compose a fluent extractive answer from the
            # top retrieved passages (ranked by question-word overlap) plus
            # entity bullets — never a raw clause dump.
            try:
                _stop = {"what", "when", "where", "which", "who", "whom", "whose", "does",
                         "have", "from", "that", "this", "with", "about", "there", "their",
                         "your", "document", "contract", "clause", "please", "show", "list",
                         "tell", "find", "give", "does", "amount", "date"}
                q_words = [w for w in re.findall(r"[A-Za-z]{4,}", question.lower()) if w not in _stop]
                _sents = []
                for _, ch, _ in passages:
                    _sents += re.split(r"(?<=[.!?])\s+", ch.strip())

                def _s_score(s):
                    sl = s.lower()
                    return sum(1 for w in q_words if w in sl)

                _ranked = sorted([s for s in _sents if len(s.strip()) > 30], key=_s_score, reverse=True)
                if _ranked and _s_score(_ranked[0]) > 0:
                    lead = " ".join(_ranked[:2]).strip()
                else:
                    lead = " ".join(_sents[:2]).strip()
                if lead and not lead.endswith((".", "!", "?")):
                    lead += "."
                # Strong fallback: build answer from entities in retrieved passages (no LLM needed)
                q_low = question.lower()
                wants_loc = any(k in q_low for k in ["location","gpe","city","state","country","place"])
                wants_date = any(k in q_low for k in ["date","time","year"])
                wants_person = any(k in q_low for k in ["person","people","who"])
                # Extract entities from the retrieved chunks via spaCy
                tmp_text = " ".join(c for _, c, _ in passages)
                tmp_rag = DocumentRAG(text=tmp_text, filename=self.filename)
                ents = tmp_rag.entity_scan()
                # Build markdown manually
                lines = [lead, ""]
                if wants_loc:
                    loc_vals = []
                    for e in ents:
                        if e["type"] in ("Locations","GPE","Facilities","Parties"):
                            loc_vals.extend(e["values"])
                    # dedupe and limit
                    seen = []
                    for v in loc_vals:
                        if v.lower() not in {x.lower() for x in seen}:
                            seen.append(v)
                    if seen:
                        lines.append("\n### Locations")
                        for v in seen[:12]:
                            # find clause that contains v
                            clause_no = next((str(i+1) for i, ch, _ in passages if v.lower() in ch.lower()), "1")
                            lines.append(f"- **{v}** — mentioned in document [Clause {clause_no}]")
                    else:
                        lines.append("\n### Locations\n- Not found in retrieved clauses.")
                if wants_date:
                    date_vals = []
                    for e in ents:
                        if e["type"] == "Dates":
                            date_vals.extend(e["values"])
                    if date_vals:
                        lines.append("\n### Dates")
                        for v in list(dict.fromkeys(date_vals))[:8]:
                            clause_no = next((str(i+1) for i, ch, _ in passages if v.lower() in ch.lower()), "1")
                            lines.append(f"- **{v}** — date in document [Clause {clause_no}]")
                if not wants_loc and not wants_date and not wants_person:
                    # Generic: list top entities
                    for e in ents[:4]:
                        lines.append(f"\n### {e['type']}")
                        for v in e["values"][:5]:
                            lines.append(f"- **{v}** [Clause 1]")
                answer = "\n".join(lines)
                used_provider = "retrieval"
            except Exception:
                answer = "Relevant excerpts are shown below. Review the cited clauses for details."
        return {
            "answer": answer,
            "citations": [{"clause": i + 1, "text": chunk, "relevance": round(score * 100)} for i, chunk, score in passages],
            "mode": used_provider or "retrieval",
        }

    def run_document_audit(self, provider: str = "auto") -> dict:
        from concurrent.futures import ThreadPoolExecutor as _APool
        # Truncate document to 6000 chars for LLM — enough for reliable analysis, avoids slow huge prompts.
        document_text = "\n".join(self.chunks)[:6000]
        local_audit = self._local_audit()
        system = (
            "You are an expert legal document analyst. Analyze the provided document text and output a JSON object summarizing the document.\n"
            "Your output MUST be valid JSON, conforming to this schema:\n"
            "{\n"
            "  \"metadata\": {\n"
            "    \"agreement_type\": \"Type of agreement (e.g. Non-Disclosure Agreement, SaaS Agreement, Lease, Service Agreement, etc.)\",\n"
            "    \"effective_date\": \"Effective date or Date of Agreement (or 'Not Specified')\",\n"
            "    \"parties\": [\"Party A Name\", \"Party B Name\"],\n"
            "    \"governing_law\": \"Governing Law / Jurisdiction (or 'Not Specified')\",\n"
            "    \"overall_risk_level\": \"Low\" | \"Medium\" | \"High\"\n"
            "  },\n"
            "  \"key_clauses\": [{\"clause_name\": \"...\", \"severity\": \"Low|Medium|High\", \"text_snippet\": \"...\", \"summary\": \"...\"}],\n"
            "  \"risks\": [{\"description\": \"...\", \"severity\": \"...\", \"mitigation\": \"...\"}],\n"
            "  \"missing_clauses\": [{\"clause_name\": \"...\", \"description\": \"...\"}],\n"
            "  \"inconsistencies\": []\n"
            "}\n"
            "Ensure the JSON is well-formed and valid. Do not add any conversational text before or after the JSON."
        )
        prompt = f"Document Text:\n{document_text}"

        # ── Run LLM audit, entity_scan, and NER HTML in PARALLEL for ~3x speedup ──
        def _do_llm_audit():
            try:
                return _llm_call(system, prompt, provider)
            except ValueError:
                return None, None

        def _do_entity_scan():
            try:
                return self.entity_scan()
            except Exception:
                return []

        def _do_ner_html():
            try:
                return self.get_ner_highlighted_html()
            except Exception:
                return ""

        with _APool(max_workers=3) as pool:
            fut_llm = pool.submit(_do_llm_audit)
            fut_ents = pool.submit(_do_entity_scan)
            fut_html = pool.submit(_do_ner_html)
            res, _used = fut_llm.result()
            entities = fut_ents.result()
            ner_html = fut_html.result()

        audit_data = parse_json_markdown(res)

        # Build local fallback if LLM analysis fails
        if not audit_data or "metadata" not in audit_data:
            print("Audit call failed or returned invalid JSON. Using local fallback scanner.")
            audit_data = local_audit
        else:
            model_meta = audit_data.setdefault("metadata", {})
            for key, value in local_audit["metadata"].items():
                current_value = model_meta.get(key)
                if not current_value or (isinstance(current_value, str) and current_value in {"Unknown", "Not Specified"}):
                    model_meta[key] = value
            model_clauses = audit_data.get("key_clauses") or []
            present = {str(item.get("clause_name", "")).strip().lower() for item in model_clauses}
            for clause in local_audit["key_clauses"]:
                if clause["clause_name"].lower() not in present:
                    model_clauses.append(clause)
            audit_data["key_clauses"] = model_clauses
            for key in ("risks", "missing_clauses", "inconsistencies"):
                if not audit_data.get(key):
                    audit_data[key] = local_audit[key]

        audit_data["entities"] = entities
        audit_data["ner_highlighted_html"] = ner_html
        return audit_data

    def generate_executive_report(self, audit_results: dict, provider: str = "auto") -> str:
        document_text = "\n".join(self.chunks)
        system = (
            "You are an expert legal analyst creating executive summaries for business decision-makers.\n\n"
            "Your task: Generate a COMPREHENSIVE, ACTIONABLE executive summary that allows readers to fully understand the document WITHOUT reading the original document.\n\n"
            "CRITICAL REQUIREMENTS:\n"
            "1. EXTRACT AND EXPLAIN every important detail, obligation, right, restriction, deadline, and financial term\n"
            "2. Use PLAIN LANGUAGE - translate all legal jargon into simple business terms\n"
            "3. Be SPECIFIC - include exact numbers, dates, percentages, deadlines, and conditions\n"
            "4. Cite sources using [Clause N] format for verification\n"
            "5. Highlight ACTION ITEMS and RISKS prominently\n"
            "6. Structure with clear visual hierarchy using Markdown\n\n"
            "REQUIRED STRUCTURE:\n\n"
            "# Executive Summary: [Agreement Type]\n\n"
            "## 📋 Quick Facts\n"
            "- **Document**: [filename]\n"
            "- **Agreement Type**: [type]\n"
            "- **Parties**: [Party A] and [Party B]\n"
            "- **Effective Date**: [date]\n"
            "- **Term/Duration**: [duration]\n"
            "- **Governing Law**: [jurisdiction]\n"
            "- **Overall Risk Level**: 🟢 Low / 🟡 Medium / 🔴 High\n\n"
            "## 📝 What This Agreement Does\n"
            "[2-3 sentences explaining the core purpose and what each party gets]\n\n"
            "## 💼 Party A Obligations (What [Party A Name] Must Do)\n"
            "- **[Obligation 1]**: [Plain language explanation with specifics] [Clause N]\n"
            "- **[Obligation 2]**: [Details, deadlines, conditions] [Clause N]\n"
            "[Continue for all major obligations]\n\n"
            "## 💼 Party B Obligations (What [Party B Name] Must Do)\n"
            "- **[Obligation 1]**: [Plain language explanation] [Clause N]\n"
            "- **[Obligation 2]**: [Details] [Clause N]\n"
            "[Continue for all major obligations]\n\n"
            "## 💰 Financial Terms\n"
            "- **Payment Amount**: [exact amount and currency] [Clause N]\n"
            "- **Payment Schedule**: [when payments are due] [Clause N]\n"
            "- **Late Fees/Penalties**: [consequences of late payment] [Clause N]\n"
            "- **Expenses**: [who pays for what] [Clause N]\n"
            "[Include ALL financial terms found]\n\n"
            "## ⏰ Key Dates & Deadlines\n"
            "- **Contract Start**: [date]\n"
            "- **Contract End**: [date or conditions]\n"
            "- **Renewal**: [auto-renew? notice period?] [Clause N]\n"
            "- **Notice Periods**: [how much advance notice for what actions] [Clause N]\n"
            "[All time-sensitive items]\n\n"
            "## 🚪 Termination & Exit\n"
            "- **How to Exit**: [exact procedure, notice required] [Clause N]\n"
            "- **Termination for Cause**: [what violations allow immediate termination] [Clause N]\n"
            "- **Early Termination Penalties**: [costs/consequences] [Clause N]\n"
            "- **Post-Termination Obligations**: [what continues after exit] [Clause N]\n\n"
            "## ⚖️ Liability & Risk Protection\n"
            "- **Liability Cap**: [maximum exposure for each party] [Clause N]\n"
            "- **Indemnification**: [who protects whom from what claims] [Clause N]\n"
            "- **Insurance Requirements**: [required coverage amounts] [Clause N]\n"
            "- **Warranty/Guarantee**: [what is promised/guaranteed] [Clause N]\n"
            "- **Limitations/Exclusions**: [what is NOT covered] [Clause N]\n\n"
            "## 🔒 Confidentiality & Data\n"
            "- **What's Confidential**: [definition and scope] [Clause N]\n"
            "- **How Long**: [confidentiality period] [Clause N]\n"
            "- **Data Protection**: [how personal/sensitive data is handled] [Clause N]\n"
            "- **Permitted Disclosures**: [when you CAN share confidential info] [Clause N]\n\n"
            "## 🎯 Intellectual Property\n"
            "- **Who Owns What**: [IP ownership allocation] [Clause N]\n"
            "- **License Rights**: [what can be used and how] [Clause N]\n"
            "- **Restrictions**: [what cannot be done] [Clause N]\n\n"
            "## ⚠️ Restrictions & Prohibitions\n"
            "- **Non-Compete**: [geographic/time restrictions if any] [Clause N]\n"
            "- **Non-Solicitation**: [restrictions on hiring/contacting] [Clause N]\n"
            "- **Usage Restrictions**: [what you cannot do] [Clause N]\n\n"
            "## 🏛️ Dispute Resolution\n"
            "- **Method**: [negotiation → mediation → arbitration → litigation] [Clause N]\n"
            "- **Location**: [where disputes are resolved] [Clause N]\n"
            "- **Cost Allocation**: [who pays legal fees] [Clause N]\n\n"
            "## 🚨 Key Risks & Red Flags\n"
            "[For each identified risk from audit:]  \n"
            "**[Risk Name]** (🔴 High / 🟡 Medium / 🟢 Low)\n"
            "- **Issue**: [What's problematic in plain language]\n"
            "- **Impact**: [Consequences if triggered]\n"
            "- **Recommendation**: [Specific negotiation point or mitigation]\n\n"
            "## ✅ Action Items & Recommendations\n"
            "**Before Signing:**\n"
            "1. [Specific action item]\n"
            "2. [Specific action item]\n\n"
            "**Negotiate/Clarify:**\n"
            "1. [Specific point to negotiate]\n"
            "2. [Specific point to clarify]\n\n"
            "**After Signing:**\n"
            "1. [Immediate compliance requirement]\n"
            "2. [Setup/implementation task]\n\n"
            "## 📊 Missing or Weak Clauses\n"
            "[List any standard protections missing that should be added]\n\n"
            "## 🎯 Bottom Line Recommendation\n"
            "[Clear 2-3 sentence recommendation: Sign as-is / Negotiate these points / Do not sign because...]\n\n"
            "---\n\n"
            "*Note: This summary is for informational purposes. Consult legal counsel for advice specific to your situation.*"
        )
        # The visible report is a decision brief, not a legal memorandum. Keep
        # it short enough for a non-lawyer while retaining exact numbers/dates.
        system = (
            "You are a document analyst writing for a busy non-lawyer. Return ONLY Markdown. "
            "Create a short, accurate decision brief from the document and audit data. "
            "Never invent missing facts; say 'Not stated' instead. Use exactly these sections:\n"
            "# Document at a glance\n"
            "## What this document is about (maximum 3 short sentences)\n"
            "## Key facts (document, parties, effective date, term, payment, governing law)\n"
            "## What each side must do (maximum 6 bullets total)\n"
            "## Important dates, money and exit terms\n"
            "## Main risks and what to clarify (maximum 5 bullets)\n"
            "## Bottom line (one plain-language sentence)\n"
            "Include exact amounts, dates, notice periods and clause references when present. "
            "Use short bullets, plain words, and bold the important keywords."
        )
        # Send only audit results (not full text again) — much smaller payload, faster response.
        slim_audit = {k: v for k, v in audit_results.items() if k not in ("ner_highlighted_html", "entities")}
        prompt = f"Audit Analysis Results:\n{json.dumps(slim_audit, indent=2)}"
        try:
            res, used_provider = _llm_call(system, prompt, provider)
        except ValueError:
            # Quota/config failure — template fallback below still serves the user.
            res = None
        
        if not res:
            meta = audit_results.get("metadata", {})
            parties = " and ".join(meta.get("parties") or []) or "Not stated"
            clause_lines = []
            for clause in audit_results.get("key_clauses", [])[:8]:
                clause_lines.append(f"- **{clause.get('clause_name', 'Clause')}**: {clause.get('summary', 'See source excerpt.')}")
            risk_lines = [
                f"- **{risk.get('severity', 'Medium')}** - {risk.get('description', 'Review this term.')} **Clarify:** {risk.get('mitigation', 'Confirm the wording.')}"
                for risk in audit_results.get("risks", [])[:5]
            ]
            missing_lines = [f"- **{item.get('clause_name', 'Protection')}**: {item.get('description', '')}" for item in audit_results.get("missing_clauses", [])[:4]]
            return f"""# Document at a glance

## What this document is about
This is a **{meta.get('agreement_type', 'document')}**. It sets out the services, responsibilities, payment and exit rules for the parties.

## Key facts
- **Document:** {self.filename}
- **Parties:** {parties}
- **Effective date:** {meta.get('effective_date', 'Not stated')}
- **Governing law:** {meta.get('governing_law', 'Not stated')}
- **Risk level:** {meta.get('overall_risk_level', 'Medium')}

## What each side must do
{chr(10).join(clause_lines) or '- No numbered clauses could be extracted.'}

## Main risks and what to clarify
{chr(10).join(risk_lines + missing_lines) or '- No material risk was automatically identified; confirm commercial terms before signing.'}

## Bottom line
Read the highlighted payment, termination and liability terms before signing, and clarify any item marked as missing or risky."""

            # Enhanced fallback with more structured information
            meta = audit_results.get('metadata', {})
            parties = meta.get('parties', [])
            party_str = ' and '.join(parties) if parties else 'Not specified'
            
            risk_sections = []
            for risk in audit_results.get('risks', [])[:5]:
                severity_icon = "🔴" if risk.get('severity') == 'High' else "🟡" if risk.get('severity') == 'Medium' else "🟢"
                risk_sections.append(
                    f"**{risk.get('description', 'Unknown risk')}** ({severity_icon} {risk.get('severity', 'Unknown')})\n"
                    f"- **Recommendation**: {risk.get('mitigation', 'Review this clause carefully')}\n"
                )
            
            clause_sections = []
            # Include every extracted clause in the saved report; a short sample
            # agreement can otherwise lose its final governing-law or signature clause.
            for clause in audit_results.get('key_clauses', []):
                severity_icon = "🔴" if clause.get('severity') == 'High' else "🟡" if clause.get('severity') == 'Medium' else "🟢"
                clause_sections.append(
                    f"**{clause.get('clause_name', 'Unnamed Clause')}** ({severity_icon} {clause.get('severity', 'Low')})\n"
                    f"- {clause.get('summary', 'No summary available')}\n"
                    f"- *Quote*: \"{clause.get('text_snippet', 'N/A')}\"\n"
                )
            
            missing = audit_results.get('missing_clauses', [])
            missing_sections = []
            for m in missing[:4]:
                missing_sections.append(f"- **{m.get('clause_name', 'Unknown')}**: {m.get('description', 'Important for document completeness')}")
            
            risk_icon = "🔴" if meta.get('overall_risk_level') == 'High' else "🟡" if meta.get('overall_risk_level') == 'Medium' else "🟢"
            
            res = f"""# Executive Summary: {meta.get('agreement_type', 'Document')}

## 📋 Quick Facts
- **Document**: {self.filename}
- **Agreement Type**: {meta.get('agreement_type', 'Generic Agreement')}
- **Parties**: {party_str}
- **Effective Date**: {meta.get('effective_date', 'Not Specified')}
- **Governing Law**: {meta.get('governing_law', 'Not Specified')}
- **Overall Risk Level**: {risk_icon} {meta.get('overall_risk_level', 'Unknown')}

## 📝 What This Agreement Does
This is a {meta.get('agreement_type', 'legal agreement')} between {party_str}. The agreement establishes the terms, obligations, and rights of each party. Based on automated analysis, this document has been assessed as having a **{meta.get('overall_risk_level', 'Medium')}** risk level.

## 🔍 Key Document Clauses

{chr(10).join(clause_sections) if clause_sections else "No key clauses identified. Please review the contract manually or use the Q&A tab for specific questions."}

## 🚨 Identified Risks & Concerns

{chr(10).join(risk_sections) if risk_sections else "No specific risks were automatically identified. However, manual review is always recommended before signing any legal agreement."}

## 📊 Missing or Weak Clauses

{chr(10).join(missing_sections) if missing_sections else "No obviously missing clauses detected. This doesn't guarantee completeness - consult legal counsel for comprehensive review."}

## ✅ Action Items Before Signing

1. **Review Financial Terms**: Confirm all payment amounts, schedules, and penalties are acceptable
2. **Verify Termination Rights**: Ensure you can exit the agreement if needed with reasonable notice
3. **Check Liability Caps**: Understand your maximum exposure and ensure adequate protection
4. **Confirm Jurisdiction**: Verify the governing law and dispute resolution location work for your business
5. **Consult Legal Counsel**: Have an attorney review this document for your specific situation

## 🎯 Bottom Line

This {meta.get('agreement_type', 'agreement')} has been assessed as **{meta.get('overall_risk_level', 'Medium')} risk**. {"Consider negotiating the identified concerns before signing." if audit_results.get('risks') else "Review the key terms carefully and ensure they align with your business needs."} For detailed clause-by-clause analysis, use the **Clause Analyzer** tab. For specific questions, use the **Intelligent Q&A** tab.

---

*Note: This summary is based on automated analysis and is for informational purposes only. Always consult qualified legal counsel before signing any document.*"""
            return res
        return res


def compare_documents(rag_a: DocumentRAG, rag_b: DocumentRAG, provider: str = "auto") -> dict:
    """Compare two documents side-by-side to analyze risk differences and redline changes."""
    audit_a = rag_a.run_document_audit(provider=provider)
    audit_b = rag_b.run_document_audit(provider=provider)
    
    system = (
        "You are an expert legal contract negotiator and redline specialist. Compare Contract A (Baseline) and Contract B (Counterparty/New Version).\n"
        "Analyze the substantive legal and commercial differences, identifying what changed, what got removed or added, which party is favored by the changes, and what risks were introduced.\n"
        "Output MUST be valid JSON with this exact structure:\n"
        "{\n"
        "  \"summary\": \"Concise plain-language overview of the overall changes and major differences\",\n"
        "  \"risk_delta\": \"Contract B has Higher Risk\" | \"Contract B has Lower Risk\" | \"Neutral / Balanced Changes\",\n"
        "  \"key_differences\": [\n"
        "    {\n"
        "      \"topic\": \"Clause / Subject (e.g. Liability Cap, Indemnification, Payment Terms, Termination)\",\n"
        "      \"contract_a_position\": \"Contract A position / wording\",\n"
        "      \"contract_b_position\": \"Contract B position / wording\",\n"
        "      \"impact\": \"High Risk\" | \"Medium Risk\" | \"Low / Neutral\",\n"
        "      \"analysis\": \"Plain-language explanation of which party benefits and negotiation advice\"\n"
        "    }\n"
        "  ],\n"
        "  \"added_provisions\": [\"New clauses present in B that were not in A\"],\n"
        "  \"removed_provisions\": [\"Protections or terms in A that were omitted in B\"],\n"
        "  \"recommendation\": \"Clear advice on whether to sign, reject, or specific clauses to push back on\"\n"
        "}"
    )
    prompt = (
        f"Contract A ({rag_a.filename}) Full Summary:\n{json.dumps(audit_a, indent=2)}\n\n"
        f"Contract B ({rag_b.filename}) Full Summary:\n{json.dumps(audit_b, indent=2)}\n\n"
        f"Contract A Excerpt:\n{rag_a.text[:4000]}\n\n"
        f"Contract B Excerpt:\n{rag_b.text[:4000]}"
    )
    
    res, used_provider = _llm_call(system, prompt, provider=provider)
    comp_data = parse_json_markdown(res)
    if not comp_data or "key_differences" not in comp_data:
        # Build local structured diff
        comp_data = {
            "summary": f"Comparison between {rag_a.filename} and {rag_b.filename}. Both documents analyzed for clause coverage and risk posture.",
            "risk_delta": "Contract B has Higher Risk" if audit_b.get("metadata", {}).get("overall_risk_level") == "High" else "Neutral / Balanced Changes",
            "key_differences": [
                {
                    "topic": "Overall Risk Posture",
                    "contract_a_position": f"Assessed as {audit_a.get('metadata', {}).get('overall_risk_level', 'Medium')} risk",
                    "contract_b_position": f"Assessed as {audit_b.get('metadata', {}).get('overall_risk_level', 'Medium')} risk",
                    "impact": "Medium Risk",
                    "analysis": "Review the specific liability, indemnification, and payment clauses before approving revisions."
                }
            ],
            "added_provisions": [c.get("clause_name") for c in audit_b.get("key_clauses", []) if c.get("clause_name") and c.get("clause_name") not in {x.get("clause_name") for x in audit_a.get("key_clauses", [])}],
            "removed_provisions": [c.get("clause_name") for c in audit_a.get("key_clauses", []) if c.get("clause_name") and c.get("clause_name") not in {x.get("clause_name") for x in audit_b.get("key_clauses", [])}],
            "recommendation": "Review highlighted differences and ensure liability caps and termination notice periods match expectations."
        }
    
    return {
        "contract_a": {"filename": rag_a.filename, "audit": audit_a},
        "contract_b": {"filename": rag_b.filename, "audit": audit_b},
        "comparison": comp_data,
        "mode": used_provider or "local_diff"
    }

