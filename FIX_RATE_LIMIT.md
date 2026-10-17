# Fix: Gemini 429 Rate Limit Error

## Problem
You're seeing these errors:
```
Gemini 429 rate-limit hit — retrying in 5s (attempt 1/3)
Gemini 429 rate-limit hit — retrying in 10s (attempt 2/3)
Ollama LLM call failed: 500 Server Error
```

## Why This Happens

### Gemini Rate Limits:
- Free tier: **15 requests per minute**
- Translation uses multiple API calls (one per chunk)
- You're likely exceeding the free quota

### Why Gemini for Translation?
The system uses this priority:
1. **Gemini** (if GEMINI_API_KEY set) - High quality, fast
2. **Ollama** (if running) - Good quality, local
3. **Offline Translation** (if packages installed) - Fallback

Since you have `GEMINI_API_KEY` set in `.env`, it tries Gemini first.

---

## Solution 1: Install Offline Translation (RECOMMENDED) ⭐

This gives you a reliable fallback that works without rate limits:

### Quick Fix (Run this now):
```bash
# Double-click this file:
FIX_TRANSLATION_NOW.bat
```

Or run manually:
```bash
argospm update
argospm install translate-kn_en
argospm install translate-mr_en
argospm install translate-ta_en
```

**After installation:**
- Gemini will still be tried first
- If rate-limited → Automatically uses offline translation
- No more failed translations!

---

## Solution 2: Fix Ollama (Make it primary)

The Ollama 500 error means the model isn't loaded properly.

### Fix Ollama:
```bash
# Load the model into memory
ollama run qwen2.5:1.5b

# Or in a separate terminal, keep it running:
ollama serve
```

### Test Ollama:
```bash
curl http://127.0.0.1:11434/api/generate -d "{\"model\":\"qwen2.5:1.5b\",\"prompt\":\"hello\",\"stream\":false}"
```

**To prefer Ollama over Gemini**, edit `.env`:
```bash
# Comment out Gemini to use Ollama first
# GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
```

---

## Solution 3: Wait Between Requests

If you want to keep using Gemini only:

### Upgrade to Paid Tier:
- Go to: https://ai.google.dev/pricing
- Gemini API paid tier: **1,000 requests per minute**
- Much more reliable

### Or spread out requests:
- Wait 1-2 minutes between document uploads
- Free tier resets every minute

---

## Solution 4: Use Environment Variable Override

Force the system to use offline translation first by setting:

Add to `.env`:
```bash
# Force offline translation as primary (not implemented yet, but you can modify code)
TRANSLATION_PROVIDER=offline
```

---

## Recommended Setup

### Best Configuration for Your Situation:

```bash
# In .env file:

# Option 1: Keep Gemini but with offline fallback (RECOMMENDED)
GEMINI_API_KEY=your_key_here          # Keep this
GEMINI_MODEL=gemini-2.5-flash

# Then install offline translation (run FIX_TRANSLATION_NOW.bat)
# This way: Gemini first, offline fallback

# Option 2: Use Ollama primarily
# GEMINI_API_KEY=your_key_here        # Comment this out
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:1.5b

# Then run: ollama serve (keep it running)
```

---

## Quick Fix NOW

### Fastest solution (do this now):

1. **Run this command:**
   ```bash
   .\FIX_TRANSLATION_NOW.bat
   ```

2. **Wait 2-3 minutes** for packages to download

3. **Try your contract again**

4. **Result:** 
   - Gemini tries first
   - If rate-limited → offline translation kicks in automatically
   - Translation succeeds!

---

## Understanding the Error Log

```
Ollama LLM call failed: 500 Server Error
→ Ollama model not responding (not critical, system moves to next)

Gemini 429 rate-limit hit — retrying in 5s (attempt 1/3)
→ Too many requests to Gemini API

Gemini 429 rate-limit hit — retrying in 10s (attempt 2/3)
→ Still rate-limited, retrying with backoff

[If offline translation installed]
→ LLM translation failed. Attempting offline translation...
→ ✓ Offline translation successful
→ Document proceeds to analysis
```

---

## Testing After Fix

### Test offline translation:
```bash
python test_offline_translation.py
```

### Expected output:
```
✓ argostranslate is installed
✓ Found 3 installed language packages:
  - Kannada (kn)
  - Marathi (mr)
  - Tamil (ta)
✓ Translation successful!
```

---

## Rate Limit Info

### Gemini Free Tier Limits:
- **15 requests per minute**
- **1,500 requests per day**
- Resets every 60 seconds

### Why Translation Uses Multiple Requests:
- Large contracts are split into ~6000 character chunks
- Each chunk = 1 API request
- A 10-page contract might use 3-5 requests
- Multiple contracts = rate limit quickly hit

---

## Long-term Solution

### For Production Use:

1. **Install offline translation** (always have a fallback)
   ```bash
   .\FIX_TRANSLATION_NOW.bat
   ```

2. **Choose your primary method:**
   - **Gemini paid tier** ($0.075 per 1M characters) - Best quality
   - **Ollama** (free, local) - Good quality, no rate limits
   - **Offline** (free, local) - Reliable fallback

3. **Best setup:**
   - Primary: Gemini paid OR Ollama local
   - Fallback: Offline translation (always installed)

---

## Summary

**Right now, do this:**
```bash
# Run this file (takes 2-3 minutes):
FIX_TRANSLATION_NOW.bat

# Then try your contract again
```

**After that:**
- ✅ Rate limits won't stop translations
- ✅ Offline translation will catch failures
- ✅ Your contracts will always be translated

---

**Need immediate help?** Run:
```bash
.\FIX_TRANSLATION_NOW.bat
```

Then try uploading your contract again in 3 minutes!
