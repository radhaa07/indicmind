# Offline Translation Integration Guide

## Overview
This guide explains how to integrate offline translation as a fallback when LLM-based translation fails.

## Installation

```bash
pip install argostranslate
```

Then download language packages:
```bash
# Update package index
argospm update

# Install specific language pairs (examples)
argospm install translate-hi_en  # Hindi to English
argospm install translate-ta_en  # Tamil to English
argospm install translate-es_en  # Spanish to English
argospm install translate-fr_en  # French to English
```

## Integration Steps

### Step 1: Import the offline translator module

At the top of `rag.py`, add:
```python
try:
    from offline_translator import offline_translate
    OFFLINE_TRANSLATION_AVAILABLE = True
except ImportError:
    OFFLINE_TRANSLATION_AVAILABLE = False
```

### Step 2: Modify the `translate_to_english` function

Replace the error handling section (around line 333) from:

```python
        if translated_part and _is_verified_english(translated_part):
            translated_parts.append(translated_part.strip())
        else:
            raise ValueError(
                f"Could not complete a verified English translation of this {lang_name} document. "
                "Check the selected AI provider and upload again. The document was not sent to analysis."
            )
```

To:

```python
        if translated_part and _is_verified_english(translated_part):
            translated_parts.append(translated_part.strip())
        else:
            # Try offline translation as fallback before raising error
            if translation_attempt == 1 and OFFLINE_TRANSLATION_AVAILABLE:  # Only try offline on final attempt
                print(f"LLM translation failed for chunk {i+1}. Attempting offline translation...")
                offline_result = offline_translate("\n\n".join(chunks), lang, SCRIPT_LANGUAGE_HINTS)
                if offline_result:
                    print("✓ Offline translation successful")
                    return offline_result, f"{lang_name} (offline translation)"
            
            if translation_attempt == 1:  # Final attempt failed
                error_msg = f"Could not complete a verified English translation of this {lang_name} document. "
                if not OFFLINE_TRANSLATION_AVAILABLE:
                    error_msg += "Install argostranslate for offline fallback: pip install argostranslate. "
                error_msg += "Check the selected AI provider and upload again."
                raise ValueError(error_msg)
```

## How It Works

1. **Primary**: LLM-based translation (Gemini/Ollama) is attempted first
2. **Fallback**: If LLM translation fails after 2 attempts, offline translation is tried
3. **Verification**: All translations are verified to ensure they're actually in English
4. **Error**: If both methods fail, a clear error message is shown

## Benefits

- **No internet required** for fallback translation
- **Free** - no API costs for offline translation
- **Privacy** - documents stay on local machine
- **Reliability** - works when LLM APIs are down or rate-limited

## Supported Languages

The offline translator supports many languages including:
- **Indian**: Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, Punjabi, Urdu, Nepali
- **European**: Spanish, French, German, Italian, Portuguese, Dutch, Russian
- **Asian**: Chinese, Japanese, Korean, Arabic

## Testing

To test the offline translation:

```python
from offline_translator import offline_translate

# Example Hindi text
hindi_text = "यह एक परीक्षण अनुबंध है।"
result = offline_translate(hindi_text, "hi", SCRIPT_LANGUAGE_HINTS)
print(result)
```

## Notes

- Offline translation quality may be lower than LLM-based translation
- Works best for common language pairs
- Requires downloading language packages (can be 50-200MB each)
- The `offline_translator.py` module is already created and ready to use
