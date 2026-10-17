import os
import re
import json
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


def extract_text(path: Path) -> str:
    try:
        if path.suffix.lower() == ".txt":
            return path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".docx":
            doc = Document(path)
            # Contracts frequently put parties, fees, dates, and schedules in tables.
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
        raise ValueError(f"Unsupported file type: {path.suffix}")
    except Exception as e:
        raise ValueError(f"Failed to extract text from {path.name}: {str(e)}")


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


def split_contract(text: str, size: int = 900, overlap: int = 180) -> list[str]:
    if not text or not text.strip():
        return [""]
    
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


def _llm_call(system: str, prompt: str, provider: str = "auto", _retry: int = 3) -> tuple[str | None, str | None]:
    import time
    chosen = provider.lower() if provider else "auto"
    if chosen not in {"auto", "gemini", "ollama"}:
        chosen = "auto"
    if chosen in {"auto", "gemini"} and os.getenv("GEMINI_API_KEY"):
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        for attempt in range(_retry):
            try:
                response = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent",
                    params={"key": os.environ["GEMINI_API_KEY"]},
                    json={"system_instruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}]},
                    timeout=90)
                if response.status_code == 429:
                    if attempt == _retry - 1:
                        raise ValueError(
                            "Gemini rate limit or API quota reached. Wait a few minutes, check your Gemini API quota, "
                            "or use a running local Ollama model."
                        )
                    wait = min((2 ** attempt) * 5, 60)   # 5s, 10s, 20s (capped at 60s)
                    print(f"Gemini 429 rate-limit hit — retrying in {wait}s (attempt {attempt+1}/{_retry})")
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()["candidates"][0]["content"]["parts"][0]["text"], "gemini"
            except requests.exceptions.HTTPError as e:
                if response.status_code in {500, 502, 503} and attempt < _retry - 1:
                    wait = min((2 ** attempt) * 3, 30)  # 3s, 6s, 12s (capped at 30s)
                    print(f"Gemini server error {response.status_code} — retrying in {wait}s")
                    time.sleep(wait)
                    continue
                print("Gemini LLM call failed. Check the configured model, API key, and network connection.")
                if chosen == "gemini":
                    return None, None
                break
            except ValueError:
                # Preserve the user-facing quota message instead of hiding it.
                raise
            except Exception as e:
                print("Gemini LLM call failed. Check the configured model, API key, and network connection.")
                if chosen == "gemini":
                    return None, None
                break
    if chosen in {"auto", "ollama"}:
        try:
            response = requests.post(
                f"{os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')}/api/chat",
                json={"model": os.getenv("OLLAMA_MODEL", "llama3.2"), "stream": False,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
                timeout=10)  # fail fast if Ollama not running
            response.raise_for_status()
            return response.json()["message"]["content"], "ollama"
        except requests.exceptions.ConnectionError:
            print("Ollama not running — skipping local fallback")
            return None, None
        except Exception as e:
            print(f"Ollama LLM call failed: {e}")
            return None, None
    return None, None


SCRIPT_LANGUAGE_HINTS = [
    (r"[\u0B80-\u0BFF]", "ta"), (r"[\u0C80-\u0CFF]", "kn"),
    (r"[\u0900-\u097F]", "hi"), (r"[\u0C00-\u0C7F]", "te"),
    (r"[\u0D00-\u0D7F]", "ml"), (r"[\u0980-\u09FF]", "bn"),
]


def _is_verified_english(text: str) -> bool:
    """Reject untranslated responses before they reach RAG."""
    if len(re.findall(r"[A-Za-z]", text)) < 30:
        return False
    source_script_chars = sum(len(re.findall(pattern, text)) for pattern, _ in SCRIPT_LANGUAGE_HINTS)
    return source_script_chars / max(len(re.findall(r"\w", text, re.UNICODE)), 1) < 0.02


def translate_to_english(text: str, provider: str = "auto") -> tuple[str, str]:
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
        "Output ONLY the complete translated English contract text."
    )

    import time
    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(2)  # brief pause between chunks to avoid Gemini 429 rate-limit
        prompt = f"Contract segment to translate ({i+1} of {len(chunks)}):\n\n{chunk}"
        translated_part = None
        # A translation must be complete, so retry a transient provider failure
        # once before rejecting the document rather than passing native text on.
        for translation_attempt in range(2):
            translated_part, _ = _llm_call(system_prompt, prompt, provider)
            if translated_part and _is_verified_english(translated_part):
                break
            if translation_attempt == 0:
                time.sleep(2)
        if translated_part and _is_verified_english(translated_part):
            translated_parts.append(translated_part.strip())
        else:
            raise ValueError(
                f"Could not complete a verified English translation of this {lang_name} document. "
                "Check the selected AI provider and upload again. The document was not sent to analysis."
            )

    return "\n\n".join(translated_parts), lang_name


class ContractRAG:
    def __init__(self, text: str, filename: str):
        self.filename = filename
        if not text or not text.strip():
            text = "Empty document"
        self.text = text
        self.chunks = split_contract(text)
        # Ensure we have at least one chunk
        if not self.chunks or all(not c.strip() for c in self.chunks):
            self.chunks = ["Empty document"]
        # Character n-grams make retrieval more forgiving of legal word forms
        # such as "terminate", "termination", and "terminating".
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform(self.chunks)

    def retrieve(self, question: str, k: int = 4):
        if not question or not question.strip():
            return []
        scores = cosine_similarity(self.vectorizer.transform([question]), self.matrix).flatten()
        order = scores.argsort()[::-1][:k]
        return [(int(i), self.chunks[i], float(scores[i])) for i in order if scores[i] > 0]

    def risk_scan(self):
        joined = " ".join(self.chunks).lower()
        found = []
        for name, phrases in RISK_RULES.items():
            if any(phrase in joined for phrase in phrases):
                found.append(name)
        return {
            "flags": found,
            "message": f"Found {len(found)} contract areas worth reviewing." if found else "No common risk terms were detected automatically.",
        }

    def entity_scan(self):
        """Extract a small, transparent set of useful contract entities without an LLM."""
        text = " ".join(self.chunks)
        patterns = {
            "Parties": r"(?:between|by and between)\s+([A-Z][A-Za-z0-9&.,' -]{2,70}?)\s+and\s+([A-Z][A-Za-z0-9&.,' -]{2,70}?)(?:\s+(?:on|dated)|[.,;(])",
            "Dates": r"\b(?:\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})\b",
            "Amounts": r"(?:USD|INR|EUR|GBP|\$|₹|€|£)\s?[\d,]+(?:\.\d{2})?",
            "Jurisdictions": r"(?:governed by the laws of|courts? of|jurisdiction of)\s+([A-Z][A-Za-z ]{2,45}?)(?:\s+(?:and|which|subject)|[.,;]|$)",
        }
        entities = []
        for label, pattern in patterns.items():
            values = []
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                matched_values = list(match.groups()) if label == "Parties" else [match.group(1) if match.lastindex else match.group(0)]
                for value in matched_values:
                    value = value.strip(" ,.;")
                    if value and value.lower() not in {v.lower() for v in values}:
                        values.append(value)
                if len(values) == 4:
                    break
            if values:
                entities.append({"type": label, "values": values})
        terms = [term.title() for term in LEGAL_TERMS if term in text.lower()]
        if terms:
            entities.append({"type": "Key topics", "values": terms[:6]})
        return entities

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
        system = ("You are a careful legal contract analyst. Answer only from the provided contract excerpts. "
                  "State uncertainty clearly. Do not give legal advice. Cite excerpts as [Clause N]. Keep the answer concise.")
        prompt = f"Question: {question}\n\nContract excerpts:\n{context}"
        answer, used_provider = _llm_call(system, prompt, provider)
        if not answer:
            answer = "Relevant contract language is shown below. Review the cited clauses for the exact obligation, exception, and deadline."
        return {
            "answer": answer,
            "citations": [{"clause": i + 1, "text": chunk, "relevance": round(score * 100)} for i, chunk, score in passages],
            "mode": used_provider or "retrieval",
        }

    def run_contract_audit(self, provider: str = "auto") -> dict:
        contract_text = "\n".join(self.chunks)
        local_audit = self._local_audit()
        system = (
            "You are an expert legal contract analyst. Analyze the provided contract text and output a JSON object summarizing the contract.\n"
            "Your output MUST be valid JSON, conforming to this schema:\n"
            "{\n"
            "  \"metadata\": {\n"
            "    \"agreement_type\": \"Type of agreement (e.g. Non-Disclosure Agreement, SaaS Agreement, Lease, Service Agreement, etc.)\",\n"
            "    \"effective_date\": \"Effective date or Date of Agreement (or 'Not Specified')\",\n"
            "    \"parties\": [\"Party A Name\", \"Party B Name\"],\n"
            "    \"governing_law\": \"Governing Law / Jurisdiction (or 'Not Specified')\",\n"
            "    \"overall_risk_level\": \"Low\" | \"Medium\" | \"High\"\n"
            "  },\n"
            "  \"key_clauses\": [\n"
            "    {\n"
            "      \"clause_name\": \"Name of Clause (e.g., Termination, Liability Cap, Indemnification, Intellectual Property, Confidentiality, Payment Terms, Dispute Resolution)\",\n"
            "      \"severity\": \"Low\" | \"Medium\" | \"High\",\n"
            "      \"text_snippet\": \"Exact short quote from the contract addressing this clause\",\n"
            "      \"summary\": \"Concise plain-language explanation of what this clause means and its implications\"\n"
            "    }\n"
            "  ],\n"
            "  \"risks\": [\n"
            "    {\n"
            "      \"description\": \"Description of the risk identified\",\n"
            "      \"severity\": \"Low\" | \"Medium\" | \"High\",\n"
            "      \"mitigation\": \"Proposed negotiation stance or mitigation strategy\"\n"
            "    }\n"
            "  ],\n"
            "  \"missing_clauses\": [\n"
            "    {\n"
            "      \"clause_name\": \"Name of missing standard clause\",\n"
            "      \"description\": \"Why it is missing and why it is important to have for this type of agreement\"\n"
            "    }\n"
            "  ],\n"
            "  \"inconsistencies\": [\n"
            "    \"Any internal contradiction found (e.g. conflicting notice periods or payment terms), or return empty list if none\"\n"
            "  ]\n"
            "}\n"
            "Ensure the JSON is well-formed and valid. Do not add any conversational text before or after the JSON."
        )
        prompt = f"Contract Text:\n{contract_text}"
        res, used_provider = _llm_call(system, prompt, provider)
        audit_data = parse_json_markdown(res)
        
        # Build local fallback if LLM analysis fails
        if not audit_data or "metadata" not in audit_data:
            print("Audit call failed or returned invalid JSON. Using local fallback scanner.")
            audit_data = local_audit
        else:
            # Keep every numbered source clause even when the model summarises
            # only a few. The model adds interpretation; local parsing preserves
            # coverage and exact excerpts for the user to verify.
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
        return audit_data

    def generate_executive_report(self, audit_results: dict, provider: str = "auto") -> str:
        contract_text = "\n".join(self.chunks)
        system = (
            "You are an expert legal analyst creating executive summaries for business decision-makers.\n\n"
            "Your task: Generate a COMPREHENSIVE, ACTIONABLE executive summary that allows readers to fully understand the contract WITHOUT reading the original document.\n\n"
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
            "You are a contract analyst writing for a busy non-lawyer. Return ONLY Markdown. "
            "Create a short, accurate decision brief from the contract and audit data. "
            "Never invent missing facts; say 'Not stated' instead. Use exactly these sections:\n"
            "# Contract at a glance\n"
            "## What this contract is about (maximum 3 short sentences)\n"
            "## Key facts (document, parties, effective date, term, payment, governing law)\n"
            "## What each side must do (maximum 6 bullets total)\n"
            "## Important dates, money and exit terms\n"
            "## Main risks and what to clarify (maximum 5 bullets)\n"
            "## Bottom line (one plain-language sentence)\n"
            "Include exact amounts, dates, notice periods and clause references when present. "
            "Use short bullets, plain words, and bold the important keywords."
        )
        prompt = f"Contract Full Text:\n{contract_text}\n\n---\n\nAudit Analysis Results:\n{json.dumps(audit_results, indent=2)}"
        res, used_provider = _llm_call(system, prompt, provider)
        
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
            return f"""# Contract at a glance

## What this contract is about
This is a **{meta.get('agreement_type', 'contract')}**. It sets out the services, responsibilities, payment and exit rules for the parties.

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
                missing_sections.append(f"- **{m.get('clause_name', 'Unknown')}**: {m.get('description', 'Important for contract completeness')}")
            
            risk_icon = "🔴" if meta.get('overall_risk_level') == 'High' else "🟡" if meta.get('overall_risk_level') == 'Medium' else "🟢"
            
            res = f"""# Executive Summary: {meta.get('agreement_type', 'Contract')}

## 📋 Quick Facts
- **Document**: {self.filename}
- **Agreement Type**: {meta.get('agreement_type', 'Generic Agreement')}
- **Parties**: {party_str}
- **Effective Date**: {meta.get('effective_date', 'Not Specified')}
- **Governing Law**: {meta.get('governing_law', 'Not Specified')}
- **Overall Risk Level**: {risk_icon} {meta.get('overall_risk_level', 'Unknown')}

## 📝 What This Agreement Does
This is a {meta.get('agreement_type', 'legal agreement')} between {party_str}. The agreement establishes the terms, obligations, and rights of each party. Based on automated analysis, this contract has been assessed as having a **{meta.get('overall_risk_level', 'Medium')}** risk level.

## 🔍 Key Contract Clauses

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
5. **Consult Legal Counsel**: Have an attorney review this contract for your specific situation

## 🎯 Bottom Line

This {meta.get('agreement_type', 'agreement')} has been assessed as **{meta.get('overall_risk_level', 'Medium')} risk**. {"Consider negotiating the identified concerns before signing." if audit_results.get('risks') else "Review the key terms carefully and ensure they align with your business needs."} For detailed clause-by-clause analysis, use the **Clause Analyzer** tab. For specific questions, use the **Intelligent Q&A** tab.

---

*Note: This summary is based on automated analysis and is for informational purposes only. Always consult qualified legal counsel before signing any contract.*"""
        
        return res
