# IndicMind

Upload a PDF, DOCX, or TXT contract and ask questions grounded in retrieved contract clauses. The app always returns the supporting clauses. Use Gemini 3.5 Flash with a Gemini API key, or use an Ollama model running locally; both are prompted only with retrieved clauses.

**NEW**: Automatic offline translation fallback for non-English contracts when LLM translation fails.

## Run it

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Optional: add your Gemini key, then set variables from .env for the current shell:
# Get-Content .env | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] } }
python app.py
```

Open http://127.0.0.1:5000.

## Models

- **Gemini:** Set `GEMINI_API_KEY`; use `gemini-2.5-flash` for translation and contract analysis.
- **Ollama:** Install and start Ollama, then download a local model: `ollama pull llama3.2`. Change `OLLAMA_MODEL` if desired.
- **Auto:** Gemini first when configured, then Ollama, then retrieval-only clauses.

## Translation Support

The system automatically translates non-English contracts to English before analysis.

**Translation Methods** (automatic fallback):
1. **LLM Translation** (Primary): High-quality translation using Gemini or Ollama
2. **Offline Translation** (Fallback): Free, local translation using argostranslate when LLM is unavailable

**Supported Languages**: Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Spanish, French, German, Arabic, Chinese, and 100+ more.

**Setup Offline Translation** (optional but recommended):
```bash
pip install argostranslate
argospm update
argospm install translate-hi_en  # Install Hindi→English (example)
argospm install translate-ta_en  # Install Tamil→English (example)
```

See `OFFLINE_TRANSLATION.md` for complete setup instructions.

## Google Sign-In

Create a Google OAuth **Web application** client and put its values in `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. For local development, register this exact redirect URI in Google Cloud:

```
http://127.0.0.1:5000/auth/google/callback
```

## Notes

- Uploaded contracts stay in the local `uploads/` folder and the in-memory analysis session lasts until the app restarts.
- This is an informational review tool, not legal advice. Have qualified counsel review important agreements.
- Offline translation requires downloading language packages (50-200MB each) but provides reliable fallback when APIs are unavailable.
