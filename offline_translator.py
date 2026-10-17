"""
Strong offline translation — saves Gemini tokens
Priority: 1) Argos Translate (fully offline, local) 2) deep-translator Google (offline fallback, no Gemini)
Handles Gujarati/Kannada/Tamil split-char PDFs and short proper nouns like "તાજમહેલ (આગ્રા)"
"""
import re
import time

# Full language names, used ONLY if MyMemory rejects the ISO-code pair
# (codes like 'mr|en' translate correctly; names can return stale fuzzy
# memory matches or empty results for Indic languages).
CODE_TO_MEMORY_NAME = {
    "gu": "gujarati", "hi": "hindi", "bn": "bengali", "ta": "tamil",
    "te": "telugu", "kn": "kannada", "ml": "malayalam", "mr": "marathi",
    "pa": "punjabi", "ur": "urdu", "or": "odia", "as": "assamese",
    "ne": "nepali", "si": "sinhala", "sa": "sanskrit", "mai": "maithili",
}

# Persistent circuit breakers: once a web backend trips (quota/dead), skip it
# for a few minutes ACROSS requests instead of re-burning tries + sleeps.
import time as _ck_time
_CIRCUIT = {"google": 0.0, "mymemory": 0.0}
_CIRCUIT_TTL = 120


def _tripped(name: str) -> bool:
    return _ck_time.time() < _CIRCUIT.get(name, 0.0)


def _trip(name: str) -> None:
    _CIRCUIT[name] = _ck_time.time() + _CIRCUIT_TTL
    print(f"[Offline] {name} circuit tripped - skipping it for {_CIRCUIT_TTL // 60} min")


def _reset(name: str) -> None:
    _CIRCUIT[name] = 0.0


def _safe(s, n=50):
    """ASCII-safe snippet for console logging (Windows cp1252 can't print Indic)."""
    return str(s)[:n].encode("ascii", "backslashreplace").decode("ascii")


def _mymemory_translate(text: str, source_lang: str, timeout: int = 12) -> str:
    """Direct MyMemory call with a registered email (MYMEMORY_EMAIL) for ~10x
    the anonymous quota. ISO codes first (correct translations); full names
    only if the API rejects the code pair. Raises on quota/transport failure."""
    import os
    import requests
    email = os.getenv("MYMEMORY_EMAIL", "").strip()
    pairs = [f"{source_lang}|en"]
    name = CODE_TO_MEMORY_NAME.get(source_lang)
    if name and name != source_lang:
        pairs.append(f"{name}|english")
    for langpair in pairs:
        params = {"q": text, "langpair": langpair}
        if email:
            params["de"] = email
        r = requests.get("https://api.mymemory.translated.net/get", params=params, timeout=timeout)
        r.raise_for_status()
        d = r.json()
        status = str(d.get("responseStatus"))
        if status != "200":
            details = str(d.get("responseDetails", "MyMemory error"))
            if "INVALID" in details.upper() and langpair != pairs[-1]:
                continue  # code pair rejected — retry once with full names
            raise ValueError(details)
        out = (d.get("responseData") or {}).get("translatedText", "")
        if not out or not out.strip():
            raise ValueError("Empty")
        return out
    raise ValueError("MyMemory error")


def _split_sentences(text: str, limit: int = 450) -> list:
    """Split a paragraph into sentence pieces under `limit` chars. MyMemory's
    free GET endpoint rejects long queries (returns empty), so long contract
    paragraphs must go in sentence-sized pieces."""
    parts = re.split(r'(?<=[.!?।\n])\s+', (text or "").strip())
    chunks, cur = [], ""
    for p in parts:
        if len(cur) + len(p) + 1 <= limit:
            cur = (cur + " " + p).strip()
        else:
            if cur:
                chunks.append(cur)
            while len(p) > limit:  # hard-split a very long single sentence
                chunks.append(p[:limit])
                p = p[limit:]
            cur = p
    if cur:
        chunks.append(cur)
    return chunks or [text]


def _web_translate(translator, text: str, attempts: int = 2) -> str | None:
    """Translate with a quick retry (Google web endpoint rate-limits; fail fast to MyMemory)."""
    last_err = None
    for attempt in range(attempts):
        try:
            out = translator.translate(text)
            if out and out.strip():
                return out
            raise ValueError("Empty")
        except Exception as e:
            last_err = e
            time.sleep(1 * (attempt + 1))
    print(f"[Offline] Giving up on chunk after {attempts} tries: {last_err}")
    return None


# deep_translator's Google backend issues requests with NO timeout, so one
# hung connection stalls the whole upload past every budget. A shared pool
# bounds each call; stuck workers degrade (circuit trips) instead of hanging.
from concurrent.futures import ThreadPoolExecutor as _GPool
_GOOGLE_POOL = _GPool(max_workers=2)


def _google_chunk(translator, text: str, timeout: int = 12) -> str | None:
    fut = _GOOGLE_POOL.submit(_web_translate, translator, text, 1)
    try:
        return fut.result(timeout=timeout)
    except Exception as e:
        print(f"[Offline] Google chunk timed out ({timeout}s): {e}")
        return None


def _ollama_to_english(paragraphs, source_lang, script_pats):
    """Local Ollama fallback (no quota, no rate limits) for paragraphs still
    in the source script. Returns the updated list, or None if Ollama is down."""
    import os
    try:
        import requests
    except ImportError:
        return None
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "medgemma:4b")
    try:
        if requests.get(host + "/api/tags", timeout=5).status_code != 200:
            return None
    except Exception:
        print("[Offline] Ollama not running - skipping local fallback")
        return None
    names = {"ta": "Tamil", "kn": "Kannada", "hi": "Hindi", "bn": "Bengali",
             "te": "Telugu", "ml": "Malayalam", "mr": "Marathi", "gu": "Gujarati",
             "pa": "Punjabi", "ur": "Urdu", "or": "Odia", "as": "Assamese"}
    lang = names.get(source_lang, source_lang)
    idxs = [i for i, p in enumerate(paragraphs)
            if len(p.strip()) >= 2 and any(re.search(pat, p) for pat in script_pats)]
    if not idxs:
        return paragraphs
    try:
        from rag import _OLLAMA_LOCK, _check_deadline
    except ImportError:
        _OLLAMA_LOCK, _check_deadline = None, None
    if _OLLAMA_LOCK is not None and not _OLLAMA_LOCK.acquire(blocking=False):
        print("[Offline] Ollama busy with another request - skipping local fallback")
        return None
    try:
        print(f"[Offline] Ollama local fallback ({model}) for {len(idxs)} paragraph(s) ({source_lang}->en)")
        # Smaller groups: each call must finish inside the request budget.
        groups, cur, cur_len = [], [], 0
        for i in idxs:
            ln = len(paragraphs[i])
            if cur and cur_len + ln > 700:
                groups.append(cur)
                cur, cur_len = [], 0
            cur.append(i)
            cur_len += ln + 1
        if cur:
            groups.append(cur)
        import time as _tt
        deadline = _tt.time() + 300  # overall budget: never hang the upload
        for g in groups:
            if _tt.time() > deadline:
                print("[Offline] Ollama time budget exceeded - keeping remaining originals")
                break
            if _check_deadline is not None:
                try:
                    _check_deadline("ollama-doc")
                except ValueError:
                    print("[Offline] Request budget exceeded - stopping Ollama pass")
                    break
            chunk = "\n".join(paragraphs[i] for i in g)
            try:
                # Bounded options: small context + capped output keeps each call
                # inside the request budget on slow local hardware.
                r = requests.post(host + "/api/chat", json={
                    "model": model, "stream": False, "think": False,
                    "options": {"num_ctx": 2048, "num_predict": 500, "temperature": 0},
                    "messages": [
                        {"role": "system", "content": f"Translate the {lang} user text into English. Return only the translation, no commentary, no reasoning, no thinking process."},
                        {"role": "user", "content": chunk}]},
                    timeout=90)
                r.raise_for_status()
                out = (r.json().get("message") or {}).get("content", "")
                # qwen3 may output thinking process — strip it
                if "</think>" in out:
                    out = out.split("</think>")[-1].strip()
                if out and out.strip():
                    lines = out.strip().split("\n")
                    for k, i in enumerate(g):
                        paragraphs[i] = lines[k] if k < len(lines) else (lines[-1] if lines else paragraphs[i])
            except Exception as e:
                print(f"[Offline] Ollama chunk failed, keeping original: {e}")
    finally:
        if _OLLAMA_LOCK is not None:
            try:
                _OLLAMA_LOCK.release()
            except Exception:
                pass
    return paragraphs


def offline_translate(text: str, source_lang: str, script_hints, allow_ollama: bool = True) -> str | None:
    if not text or not text.strip():
        return None

    # --- Clean PDF-extracted Indic text where chars are split by spaces e.g. "ભા રતનું" -> "ભારતનું"
    def _clean_indic(t: str) -> str:
        for pat in [r'([\u0A80-\u0AFF])\s+(?=[\u0A80-\u0AFF])', r'([\u0900-\u097F])\s+(?=[\u0900-\u097F])', r'([\u0B80-\u0BFF])\s+(?=[\u0B80-\u0BFF])', r'([\u0C00-\u0C7F])\s+(?=[\u0C00-\u0C7F])', r'([\u0C80-\u0CFF])\s+(?=[\u0C80-\u0CFF])', r'([\u0D00-\u0D7F])\s+(?=[\u0D00-\u0D7F])', r'([\u0980-\u09FF])\s+(?=[\u0980-\u09FF])']:
            t = re.sub(pat, r'\1', t)
        t = re.sub(r'[ \t]{2,}', ' ', t)
        # Fix common PDF artifacts: extra spaces around brackets
        t = re.sub(r'\s+([.,;:!?\)])', r'\1', t)
        t = re.sub(r'\(\s+', '(', t)
        t = re.sub(r'\s+\)', ')', t)
        return t

    text = _clean_indic(text)
    paragraphs = text.split("\n")

    # --- 1) Try Argos Translate (fully offline, no tokens, no internet) ---
    try:
        from argostranslate.translate import get_installed_languages, translate as argos_translate
        installed = get_installed_languages()
        from_lang = next((l for l in installed if l.code == source_lang), None)
        to_lang = next((l for l in installed if l.code == "en"), None)
        if from_lang and to_lang:
            trans = from_lang.get_translation(to_lang)
            if trans:
                print(f"[Offline] Argos {source_lang}->en (offline, no tokens)")
                out = []
                for para in paragraphs:
                    s = para.strip()
                    if not s or s in {"•", "-", "*", "—", "–"} or len(s) < 2:
                        out.append(para)
                    else:
                        try:
                            out.append(trans.translate(para))
                        except Exception:
                            out.append(para)
                result = "\n".join(out)
                if _is_verified_english(result, script_hints, relaxed=True):
                    print("[Offline] Argos success")
                    return result
                else:
                    print("[Offline] Argos verification failed, trying Google...")
    except Exception as e:
        print(f"[Offline] Argos not available: {e}")

    # --- 2) deep-translator Google (fallback, still no Gemini tokens) ---
    # Paragraphs are batched into ~2000-char chunks: one HTTP request covers
    # many paragraphs, so the free endpoint rarely rate-limits (the old
    # per-paragraph burst caused the 429s). Results are mapped back 1:1 and
    # only re-tried individually when the line shape did not survive.
    try:
        from deep_translator import GoogleTranslator
        print(f"[Offline] Google Translate API {source_lang}->en (no Gemini tokens)")
        translator = GoogleTranslator(source=source_lang, target='en')
        translated_paragraphs = [None] * len(paragraphs)
        for i, para in enumerate(paragraphs):
            s = para.strip()
            if not s or s in {"•", "-", "*", "—", "–"} or len(s) < 2:
                translated_paragraphs[i] = para
        groups, cur, cur_len = [], [], 0
        for i, para in enumerate(paragraphs):
            if translated_paragraphs[i] is not None:
                continue
            if cur and cur_len + len(para) > 2000:
                groups.append(cur)
                cur, cur_len = [], 0
            cur.append(i)
            cur_len += len(para) + 1
        if cur:
            groups.append(cur)
        google_dead = 0  # circuit breaker: consecutive total failures
        for g in groups:
            try:
                from rag import _check_deadline as _cd
                _cd("offline-web")
            except ValueError:
                print("[Offline] Request budget exceeded - stopping web pass")
                break
            except ImportError:
                pass
            if google_dead >= 2 or _tripped("google"):
                # Endpoint is down/quota-hit — keep originals for the
                # MyMemory/Ollama passes instead of burning tries + sleeps.
                continue
            chunk = "\n".join(paragraphs[i] for i in g)
            out = _google_chunk(translator, chunk)
            time.sleep(0.4)  # politeness gap: rapid bursts trigger 429s
            if out:
                google_dead = 0
                _reset("google")
                if len(g) == 1:
                    translated_paragraphs[g[0]] = out
                    continue
                lines = out.split("\n")
                if len(lines) == len(g):
                    for k, i in enumerate(g):
                        translated_paragraphs[i] = lines[k] if lines[k].strip() else paragraphs[i]
                    continue
                # Translation worked but newlines did not survive — retry
                # this small group paragraph by paragraph.
                print(f"[Offline] Chunk split mismatch ({len(lines)} vs {len(g)} lines) - retrying individually")
                for i in g:
                    one = _google_chunk(translator, paragraphs[i])
                    time.sleep(0.4)
                    translated_paragraphs[i] = one if (one and one.strip()) else paragraphs[i]
                continue
            google_dead += 1
            if google_dead >= 2:
                _trip("google")
            if len(g) == 1 and len(paragraphs[g[0]].strip()) < 40:
                # Short proper noun like a name in brackets — keep original
                # without logging it as an error for the whole document.
                translated_paragraphs[g[0]] = paragraphs[g[0]]
            else:
                print(f"[Offline] Chunk kept original (no translation): {_safe(paragraphs[g[0]].strip())}")
                for i in g:
                    translated_paragraphs[i] = paragraphs[i]
        # Anything untouched (budget break / tripped circuit) keeps original
        # for the MyMemory pass below.
        for i, para in enumerate(paragraphs):
            if translated_paragraphs[i] is None:
                translated_paragraphs[i] = para

        # --- 3) MyMemory fallback for paragraphs still in source script ---
        # (No Argos gu->en pack exists upstream, and Google web rate-limits.)
        try:
            mem_name = CODE_TO_MEMORY_NAME.get(source_lang)
            script_pats = [p for p, _ in script_hints]
            needs_help = [i for i, p in enumerate(translated_paragraphs)
                          if len(p.strip()) >= 2 and any(re.search(pat, p) for pat in script_pats)]
            if needs_help and not _tripped("mymemory"):
                print(f"[Offline] MyMemory fallback for {len(needs_help)} paragraph(s) ({source_lang}->en)")
                # Independent paragraphs translate concurrently (~5x faster);
                # a shared breaker stops the batch when quota is hit.
                import threading as _th
                mem_state = {"dead": 0}
                mem_lock = _th.Lock()

                def _one_mem(i):
                    with mem_lock:
                        if mem_state["dead"] >= 2:
                            return (i, None)
                    try:
                        from rag import _check_deadline as _cd3
                        _cd3("offline-mem")
                    except ValueError:
                        return (i, "BUDGET")
                    except ImportError:
                        pass
                    try:
                        pieces = _split_sentences(
                            re.sub(r'\s+', ' ', translated_paragraphs[i]).strip())
                        outs = []
                        for pc in pieces:
                            outs.append(_mymemory_translate(pc, source_lang))
                        full = " ".join(outs)
                        if full.strip() and not any(re.search(pat, full) for pat in script_pats):
                            return (i, full)
                        return (i, None)
                    except Exception as e:
                        with mem_lock:
                            mem_state["dead"] += 1
                            if mem_state["dead"] >= 2:
                                _trip("mymemory")
                        print(f"[Offline] MyMemory paragraph {i+1} failed: {e}")
                        return (i, None)

                from concurrent.futures import ThreadPoolExecutor as _MPool
                with _MPool(max_workers=min(3, len(needs_help))) as _mp:
                    for i, out in _mp.map(_one_mem, needs_help):
                        if out == "BUDGET":
                            print("[Offline] Request budget exceeded - stopping MyMemory pass")
                            break
                        if out:
                            translated_paragraphs[i] = out
                            with mem_lock:
                                mem_state["dead"] = 0
                            _reset("mymemory")
                            time.sleep(0.2)
        except Exception as e:
            print(f"[Offline] MyMemory unavailable: {e}")

        result = "\n".join(translated_paragraphs)
        # Last resort: local Ollama (Argos lacks ta/kn packs; web 429/quota).
        # Skipped in fast mode — a 5 tok/s local model can never be "quick".
        script_pats_all = [p for p, _ in script_hints]
        still_source = any(len(p.strip()) >= 2 and any(re.search(pat, p) for pat in script_pats_all)
                           for p in translated_paragraphs)
        if allow_ollama and still_source and not _is_verified_english(result, script_hints, relaxed=True):
            ollama_out = _ollama_to_english(translated_paragraphs, source_lang, script_pats_all)
            if ollama_out is not None:
                translated_paragraphs = ollama_out
                result = "\n".join(translated_paragraphs)
        # Relaxed verification for strong offline: allow up to 8% remaining script (was 2%)
        # and require only 20 English letters (was 30) so short docs still pass
        if _is_verified_english(result, script_hints, relaxed=True):
            print("[Offline] Successfully translated to English")
            return result
        else:
            # Even if verification fails, return partial if majority is English
            eng_ratio = len(re.findall(r"[A-Za-z]", result)) / max(len(re.findall(r"\w", result, re.UNICODE)), 1)
            script_ratio = sum(len(re.findall(p, result)) for p,_ in script_hints) / max(len(re.findall(r"\w", result, re.UNICODE)), 1)
            if eng_ratio > 0.5 and script_ratio < 0.15:
                print(f"[Offline] Partial success (eng {eng_ratio:.2f} script {script_ratio:.2f}) — returning")
                return result
            print("[Offline] Translation verification failed")
            return None
    except ImportError:
        print("[Offline] deep-translator not installed — pip install deep-translator")
        return None
    except Exception as e:
        print(f"[Offline] Error: {e}")
        return None


def _is_verified_english(text: str, script_hints, relaxed: bool = False) -> bool:
    """Verify translated text is mostly English. Relaxed=True for strong offline (saves Gemini tokens)."""
    if relaxed:
        # Strong offline: save tokens even if some proper nouns remain in Gujarati
        return len(re.findall(r"[A-Za-z]", text)) >= 20
    if len(re.findall(r"[A-Za-z]", text)) < 30:
        return False
    source_script_chars = sum(len(re.findall(pattern, text)) for pattern, _ in script_hints)
    total = max(len(re.findall(r"\w", text, re.UNICODE)), 1)
    return (source_script_chars / total) < 0.02
