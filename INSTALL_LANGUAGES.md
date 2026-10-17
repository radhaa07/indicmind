# How to Install Offline Translation for Indian Languages

## Quick Install (Recommended)

### Option 1: Run the Batch Script (Easiest)

Just double-click this file:
```
install_indian_languages.bat
```

This will automatically install Kannada, Marathi, and Tamil translation packages.

---

## Manual Installation

### Option 2: Step-by-Step Commands

Open Command Prompt or PowerShell in your project folder and run:

```bash
# Step 1: Install argostranslate (if not already installed)
pip install argostranslate

# Step 2: Update package index
argospm update

# Step 3: Install Indian language packages
argospm install translate-kn_en   # Kannada → English
argospm install translate-mr_en   # Marathi → English
argospm install translate-ta_en   # Tamil → English
```

### Install Additional Indian Languages (Optional)

```bash
argospm install translate-hi_en   # Hindi → English
argospm install translate-bn_en   # Bengali → English
argospm install translate-te_en   # Telugu → English
argospm install translate-gu_en   # Gujarati → English
argospm install translate-ml_en   # Malayalam → English
argospm install translate-pa_en   # Punjabi → English
argospm install translate-ur_en   # Urdu → English
```

---

## Verify Installation

### Check installed languages:
```bash
argospm list
```

You should see output like:
```
Installed packages:
  translate-kn_en (1.x)
  translate-mr_en (1.x)
  translate-ta_en (1.x)
```

### Test with Python:
```bash
python test_offline_translation.py
```

---

## Package Sizes

Each language package is approximately:
- Kannada: ~50-100 MB
- Marathi: ~50-100 MB
- Tamil: ~50-100 MB

**Total**: ~150-300 MB for all three languages

---

## How It Works

Once installed:

1. **Upload a contract** in Kannada, Marathi, or Tamil
2. **System tries LLM translation first** (Gemini/Ollama) - best quality
3. **If LLM fails**, automatically uses offline translation
4. **Translation happens locally** - no internet needed for fallback
5. **Contract is analyzed** as normal

---

## Troubleshooting

### "Command 'argospm' not found"
Make sure argostranslate is installed:
```bash
pip install argostranslate
```

### "Package not found"
Update the package index first:
```bash
argospm update
```

### Check if Python scripts folder is in PATH
The `argospm` command should be in your Python Scripts folder:
- Windows: `C:\Users\YourName\AppData\Local\Programs\Python\Python3xx\Scripts\`
- Or in your virtual environment: `.venv\Scripts\`

If not working, try:
```bash
python -m argostranslate.package update
python -m argostranslate.package install translate-kn_en
```

### Installation is slow
Language packages are 50-100MB each. Be patient, it may take a few minutes depending on your internet speed.

---

## Testing

After installation, test with these sample texts:

### Kannada Test:
```bash
python -c "from offline_translator import offline_translate; from rag import SCRIPT_LANGUAGE_HINTS; print(offline_translate('ಇದು ಒಂದು ಪರೀಕ್ಷೆ', 'kn', SCRIPT_LANGUAGE_HINTS))"
```

### Marathi Test:
```bash
python -c "from offline_translator import offline_translate; from rag import SCRIPT_LANGUAGE_HINTS; print(offline_translate('ही एक चाचणी आहे', 'mr', SCRIPT_LANGUAGE_HINTS))"
```

### Tamil Test:
```bash
python -c "from offline_translator import offline_translate; from rag import SCRIPT_LANGUAGE_HINTS; print(offline_translate('இது ஒரு சோதனை', 'ta', SCRIPT_LANGUAGE_HINTS))"
```

---

## Uninstall (if needed)

To remove packages:
```bash
argospm remove translate-kn_en
argospm remove translate-mr_en
argospm remove translate-ta_en
```

---

## Quick Reference

| Language | Code | Install Command |
|----------|------|-----------------|
| Kannada  | kn   | `argospm install translate-kn_en` |
| Marathi  | mr   | `argospm install translate-mr_en` |
| Tamil    | ta   | `argospm install translate-ta_en` |
| Hindi    | hi   | `argospm install translate-hi_en` |
| Bengali  | bn   | `argospm install translate-bn_en` |
| Telugu   | te   | `argospm install translate-te_en` |
| Gujarati | gu   | `argospm install translate-gu_en` |
| Malayalam| ml   | `argospm install translate-ml_en` |
| Punjabi  | pa   | `argospm install translate-pa_en` |
| Urdu     | ur   | `argospm install translate-ur_en` |

---

## Status Check

After installation, your system status:
- ✅ **Primary Translation**: Gemini API or Ollama (high quality)
- ✅ **Fallback Translation**: Offline (Kannada, Marathi, Tamil)
- ✅ **No internet required** for fallback
- ✅ **Fully automatic** - just upload contracts

---

**Need help?** Run the test script:
```bash
python test_offline_translation.py
```

This will show you which languages are installed and working!
