# Offline Translation Setup Guide

## Overview
Your ContractLens application now has **offline translation fallback** support. When LLM-based translation (Gemini/Ollama) fails, the system automatically attempts offline translation using `argostranslate`.

## Installation

### Step 1: Install argostranslate
```bash
pip install argostranslate
```

### Step 2: Download Language Packages
```bash
# Update package index
argospm update

# Install language pairs you need (examples):
argospm install translate-hi_en  # Hindi → English
argospm install translate-ta_en  # Tamil → English
argospm install translate-te_en  # Telugu → English
argospm install translate-kn_en  # Kannada → English
argospm install translate-es_en  # Spanish → English
argospm install translate-fr_en  # French → English
argospm install translate-de_en  # German → English
argospm install translate-ar_en  # Arabic → English
argospm install translate-zh_en  # Chinese → English
```

### List Available Packages
```bash
argospm list
```

## How It Works

1. **Primary Method**: System first tries LLM-based translation (Gemini or Ollama)
2. **Automatic Fallback**: If LLM fails after 2 attempts, offline translation is triggered
3. **Verification**: All translations are verified to ensure output is valid English
4. **Clear Feedback**: Console shows which translation method was used

## Supported Languages

- **Indian Languages**: Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, Punjabi, Urdu, Nepali, Odia
- **European Languages**: Spanish, French, German, Italian, Portuguese, Dutch, Russian
- **Asian Languages**: Chinese, Japanese, Korean, Arabic
- **And more**: 100+ language pairs available

## Benefits

✅ **No Internet Required** - Works completely offline  
✅ **Free** - No API costs or rate limits  
✅ **Privacy** - Documents never leave your machine  
✅ **Reliable** - Works when LLM APIs are down  
✅ **Automatic** - No code changes needed, just install packages

## Usage

Just upload any non-English contract as usual. The system will:
1. Try LLM translation first (better quality)
2. Fall back to offline translation if LLM unavailable
3. Show clear messages indicating which method was used

## Testing Offline Translation

```python
from offline_translator import offline_translate

# Test with sample text
text = "यह एक परीक्षण है"  # "This is a test" in Hindi
result = offline_translate(text, "hi", [])
print(result)
```

## Troubleshooting

### "Language pair not installed"
Install the specific language package:
```bash
argospm install translate-XX_en  # Replace XX with language code
```

### "argostranslate not installed"
```bash
pip install argostranslate
```

### Check Installed Packages
```bash
argospm list
```

## Quality Notes

- **LLM Translation**: Higher quality, better context understanding, preserves legal terminology
- **Offline Translation**: Good quality, faster, works offline, may miss some context

The system automatically uses the best available option.

## Package Sizes

Each language package is typically 50-200MB. Install only the languages you need.

## Files Created

- `offline_translator.py` - Main offline translation module
- `rag.py` - Updated with automatic fallback integration
- `OFFLINE_TRANSLATION.md` - This guide

---

**Status**: ✅ Offline translation is now integrated and ready to use!
