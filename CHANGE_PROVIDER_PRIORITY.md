# Change LLM Provider Priority

## Why Gemini is Used First

The system checks providers in this order:

```
1. Check if GEMINI_API_KEY exists in .env
   → If YES: Use Gemini first
   
2. If Gemini fails or not configured:
   → Try Ollama (if running)
   
3. If both fail:
   → Try Offline Translation (if installed)
```

## Current Configuration

Your `.env` file has:
```bash
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:1.5b
```

**Result:** Gemini is tried first because `GEMINI_API_KEY` exists.

---

## Option 1: Use Ollama First (Recommended for avoiding rate limits)

### Edit `.env` file:

**Comment out the Gemini API key:**
```bash
# Gemini (disabled - commented out to use Ollama first)
# GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Ollama local model (PRIMARY)
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:1.5b
```

**Then start Ollama:**
```bash
ollama serve
```

**Result:**
- ✅ Ollama used first (free, no rate limits)
- ✅ Offline translation as fallback
- ✅ No more 429 errors

---

## Option 2: Keep Gemini but Add Offline Fallback (Easiest)

**Keep your current `.env` as-is.**

**Just install offline translation:**
```bash
.\FIX_TRANSLATION_NOW.bat
```

**Result:**
- ✅ Gemini tried first (high quality when available)
- ✅ If rate-limited → offline translation automatically used
- ✅ Best of both worlds

---

## Option 3: Use Only Offline Translation

### Edit `.env` file:

**Comment out both Gemini and Ollama:**
```bash
# Gemini (disabled)
# GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Ollama (disabled)
# OLLAMA_HOST=http://127.0.0.1:11434
# OLLAMA_MODEL=qwen2.5:1.5b
```

**Install offline translation:**
```bash
.\FIX_TRANSLATION_NOW.bat
```

**Result:**
- ✅ Only offline translation used
- ✅ Always works, never fails
- ✅ No rate limits, no API needed

---

## Comparison

| Method | Quality | Speed | Rate Limits | Cost | Internet |
|--------|---------|-------|-------------|------|----------|
| **Gemini** | Excellent | Fast | Yes (15/min free) | Free/Paid | Required |
| **Ollama** | Good | Medium | No | Free | No |
| **Offline** | Good | Fast | No | Free | No |

---

## Recommended Setup by Use Case

### For Development/Testing:
```bash
# Best: Ollama (reliable, no limits)
# GEMINI_API_KEY=...
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:1.5b
```
+ Install offline translation as backup

### For Production (Low Volume):
```bash
# Best: Gemini with offline fallback
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-2.5-flash
```
+ Install offline translation as backup

### For Production (High Volume):
```bash
# Best: Gemini paid tier OR Ollama + offline
GEMINI_API_KEY=your_paid_key
# Or use Ollama
```

### For Maximum Reliability:
```bash
# All three enabled
GEMINI_API_KEY=your_key
OLLAMA_HOST=http://127.0.0.1:11434
```
+ Install offline translation
+ System tries all three in order

---

## How to Change Priority

### Quick Changes:

#### Switch to Ollama Primary:
```bash
# In .env, add # before GEMINI_API_KEY
# GEMINI_API_KEY=...

# Then run:
ollama serve
```

#### Switch Back to Gemini:
```bash
# In .env, remove # before GEMINI_API_KEY
GEMINI_API_KEY=...
```

#### Test Current Provider:
```bash
python -c "import os; print('Primary:', 'Gemini' if os.getenv('GEMINI_API_KEY') else 'Ollama/Offline')"
```

---

## Fix Your Current Issue NOW

**Since you're rate-limited, do this:**

### Immediate Fix (choose one):

**Option A: Add Offline Fallback (2 minutes)**
```bash
.\FIX_TRANSLATION_NOW.bat
# Keep using Gemini, but with offline fallback
```

**Option B: Switch to Ollama (30 seconds)**
```bash
# 1. Edit .env, comment out: # GEMINI_API_KEY=...
# 2. Run: ollama serve
# 3. Try contract again
```

**Option C: Wait (1 minute)**
```bash
# Gemini rate limit resets every 60 seconds
# Just wait 1 minute and try again
```

---

## Understanding the Code

In `rag.py`, the `_llm_call` function checks:

```python
def _llm_call(system, prompt, provider="auto", _retry=3):
    chosen = provider  # Usually "auto"
    
    # Step 1: Try Gemini if API key exists
    if chosen in {"auto", "gemini"} and os.getenv("GEMINI_API_KEY"):
        # Try Gemini...
        return result, "gemini"
    
    # Step 2: Try Ollama if Gemini failed or no key
    if chosen in {"auto", "ollama"}:
        # Try Ollama...
        return result, "ollama"
    
    # Step 3: Return None (then offline translation tries)
    return None, None
```

Then in `translate_to_english`:
```python
# Try LLM translation
translated_part, _ = _llm_call(system_prompt, prompt, provider)

if not translated_part:
    # Try offline translation
    offline_result = offline_translate(...)
```

---

## My Recommendation

**For your situation RIGHT NOW:**

1. **Install offline translation** (fixes the immediate problem)
   ```bash
   .\FIX_TRANSLATION_NOW.bat
   ```

2. **Fix Ollama** (for better long-term reliability)
   ```bash
   ollama serve
   # Keep this running in a separate terminal
   ```

3. **Optional: Comment out Gemini temporarily**
   - Edit `.env`
   - Add `#` before `GEMINI_API_KEY=...`
   - Use Ollama as primary instead

This gives you:
- ✅ No rate limits (Ollama or offline)
- ✅ Always works (offline fallback)
- ✅ High quality (Ollama is good)
- ✅ Free forever

---

**Quick Fix File:**
```bash
.\FIX_TRANSLATION_NOW.bat
```

**Then you're good to go!** 🎉
