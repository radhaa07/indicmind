# ContractLens - Quick Start Guide

## 🚀 Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Optional: Install offline translation (recommended)
pip install argostranslate
argospm update
argospm install translate-hi_en   # Hindi
argospm install translate-ta_en   # Tamil
argospm install translate-es_en   # Spanish
# Install other languages as needed
```

## ⚙️ Configuration

1. Copy environment template:
   ```bash
   copy .env.example .env
   ```

2. Edit `.env` and add your API keys:
   ```
   GEMINI_API_KEY=your_key_here
   GEMINI_MODEL=gemini-2.5-flash
   ```

3. (Optional) Configure Google OAuth for sign-in

## ▶️ Running

```bash
python app.py
```

Open: http://127.0.0.1:5000

## 📝 Using ContractLens

### Step 1: Upload Contract
- Click "Choose File" or drag & drop
- Supports: PDF, DOCX, TXT
- Supports: English + 100+ languages (auto-translates)

### Step 2: View Analysis

#### 🆕 Executive Summary Tab (NEW!)
**Most Important - Start Here!**

Your one-stop comprehensive breakdown:
- 📋 Quick facts (parties, dates, risk level)
- 💼 What each party must do
- 💰 All financial terms (amounts, schedules)
- ⏰ Key deadlines and dates
- 🚪 How to exit the contract
- ⚖️ Liability limits and risks
- 🚨 Red flags with recommendations
- ✅ Action items (before/after signing)
- 🎯 Bottom line: Sign, negotiate, or reject?

**Goal**: Understand the entire contract without reading the original document!

#### Clause Analyzer Tab
- View all key clauses extracted
- Severity ratings (High/Medium/Low)
- Plain-language summaries
- Exact text snippets with citations

#### Risks & Compliance Tab
- Risk flags (auto-renewal, liability, etc.)
- Entity extraction (parties, dates, amounts)
- Missing standard clauses
- Internal inconsistencies

#### Intelligent Q&A Tab
- Ask specific questions about the contract
- Get answers grounded in actual contract text
- See cited clauses with relevance scores
- Examples:
  - "What is the termination notice period?"
  - "Who owns the intellectual property?"
  - "What are the payment terms?"
  - "Are there any non-compete clauses?"

## 🌍 Multi-Language Support

### How It Works:
1. **Auto-detect** language when you upload
2. **LLM translation** attempts first (Gemini/Ollama)
3. **Offline fallback** if LLM unavailable
4. **Verification** ensures translation quality

### Supported Languages:
✅ Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali  
✅ Spanish, French, German, Italian, Portuguese  
✅ Chinese, Japanese, Korean, Arabic  
✅ 100+ total languages

### Translation Status:
Check console output for translation method used:
- `"gemini"` = Gemini API (high quality)
- `"ollama"` = Local Ollama (good quality)
- `"offline translation"` = Argostranslate (reliable fallback)

## 🔧 Troubleshooting

### "Translation failed"
**Solution 1**: Add Gemini API key to `.env`  
**Solution 2**: Install Ollama locally  
**Solution 3**: Install offline translation:
```bash
pip install argostranslate
argospm update
argospm install translate-XX_en  # Replace XX with language code
```

### "No analysis available"
- Ensure LLM is configured (Gemini API key or Ollama running)
- Check console for error messages
- Try re-uploading the document

### "Risk scan found nothing"
- Contract might use non-standard terminology
- Use Q&A tab for specific questions
- Check Executive Summary for comprehensive analysis

### Test offline translation:
```bash
python test_offline_translation.py
```

## 📊 Quick Command Reference

```bash
# Start application
python app.py

# Test imports
python -c "import rag; print('OK')"

# Test offline translation
python test_offline_translation.py

# Install language package
argospm install translate-hi_en

# List installed languages
argospm list
```

## 💡 Pro Tips

1. **Start with Executive Summary** - It gives you the complete picture in plain language

2. **Check Risk Level** - Color-coded (🔴 High / 🟡 Medium / 🟢 Low)

3. **Read Action Items** - Know what to do before and after signing

4. **Use Q&A for specifics** - Ask targeted questions about unclear sections

5. **Verify citations** - All summaries cite original clauses [Clause N]

6. **Install offline translation** - Ensures documents can be analyzed even without internet

7. **Review Bottom Line** - Get clear recommendation: sign, negotiate, or reject

## 📁 Key Files

- `app.py` - Main Flask application
- `rag.py` - Core RAG and analysis engine
- `offline_translator.py` - Offline translation module
- `templates/` - HTML templates
- `static/` - CSS, JS, images
- `uploads/` - Uploaded contracts (auto-created)

## 🆘 Getting Help

1. Check `CHANGES_SUMMARY.md` - Complete list of features
2. Check `OFFLINE_TRANSLATION.md` - Translation setup details
3. Check `WORKFLOW.txt` - Visual workflow diagram
4. Check console output - Error messages and status updates

## ⚠️ Important Notes

- This is an **informational tool**, not legal advice
- Always consult qualified legal counsel before signing
- Uploaded contracts stored locally in `uploads/` folder
- Analysis session lasts until app restarts
- Offline translation requires language packages (50-200MB each)

## ✅ Verification Checklist

Before first use:
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] `.env` file configured
- [ ] Gemini API key added (or Ollama installed)
- [ ] Offline translation installed (optional but recommended)
- [ ] Test with sample contract
- [ ] Verify Executive Summary generates properly

---

🎉 **You're ready to analyze contracts!** 🎉

For detailed documentation, see:
- `README.md` - Full project documentation
- `CHANGES_SUMMARY.md` - What's new
- `OFFLINE_TRANSLATION.md` - Translation setup guide
