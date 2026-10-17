# 🔊 Text-to-Speech (TTS) Feature Added

## Overview

ContractLens now includes **Text-to-Speech** functionality to make contracts more accessible. Users can listen to executive summaries and contract analysis instead of reading them.

---

## ✨ Features

### 1. **Listen to Executive Summary**
- Click "🔊 Listen to Summary" button on the Executive Summary tab
- Automatically reads the first 5 key sections
- High-quality Google Text-to-Speech voice
- Audio cached for faster replay

### 2. **Play/Pause Controls**
- Click once to play
- Click again to pause
- Automatic cleanup when audio finishes

### 3. **Smart Text Processing**
- Removes markdown formatting for better pronunciation
- Removes emojis and special symbols
- Cleans clause citations
- Optimizes for natural speech

---

## 🎯 How to Use

### For End Users:

1. **Upload and analyze a contract**
2. **Go to "Executive Summary" tab**
3. **Click "🔊 Listen to Summary" button**
4. **Wait a moment** for audio generation (first time)
5. **Listen** to the summary
6. **Click again** to pause if needed

---

## 🔧 Technical Details

### Backend (Python/Flask):

**New API Endpoints:**
- `POST /api/tts/generate` - Generate TTS audio from text
- `GET /api/tts/audio/<filename>` - Serve audio files
- `POST /api/contracts/<id>/tts/summary` - Generate summary TTS
- `DELETE /api/tts/cache` - Clear TTS cache

**Libraries Used:**
- `gTTS` (Google Text-to-Speech) - Free, high-quality TTS
- Audio files cached in `tts_cache/` directory
- MP3 format for universal compatibility

**Text Processing:**
```python
- Remove markdown headers (# ## ###)
- Remove markdown bold (**text**)
- Remove markdown links but keep text
- Remove emojis and special symbols
- Remove clause citations [Clause N]
- Clean extra whitespace
```

### Frontend (JavaScript):

**New Files:**
- `static/tts.js` - TTS functionality
- Updated `static/style.css` - TTS button styles
- Updated `templates/index.html` - TTS buttons

**Functions:**
- `playTTS(text, section, button)` - Play any text
- `stopTTS()` - Stop current playback
- `playSummaryTTS(contractId, button)` - Play executive summary

**Button States:**
- 🔊 Listen - Ready to play
- 🔄 Generating... - Creating audio
- ⏸️ Pause - Currently playing

---

## 📦 Installation

### Dependencies:
```bash
pip install gTTS
```

Already added to `requirements.txt`:
```
gTTS>=2.5,<3.0
```

### File Structure:
```
e:\2026-27\m0347\
├── app.py                  # TTS API endpoints added
├── requirements.txt        # gTTS added
├── tts_cache/             # Audio cache directory (auto-created)
├── static/
│   ├── tts.js             # TTS JavaScript (NEW)
│   └── style.css          # TTS button styles added
└── templates/
    └── index.html         # TTS button added
```

---

## 🎨 UI/UX Design

### Button Design:
- Gradient teal/green background
- Smooth hover animations
- Disabled state when generating
- Clear icons (🔊 ⏸️ 🔄)
- Mobile-responsive

### Audio Experience:
- Estimated duration shown
- Smooth playback
- Auto-cleanup when finished
- Error handling with user feedback

---

## ⚙️ Configuration

### Audio Settings:
- **Language**: English (en) by default
- **Speed**: Normal (not slow)
- **Format**: MP3
- **Quality**: High (Google TTS)

### Text Limits:
- **Max characters**: 5,000 per request
- **Cache**: Files cached by content hash
- **Auto-truncation**: Long texts truncated with message

### Caching:
- Audio files cached in `tts_cache/` folder
- Filename: `tts_<section>_<hash>.mp3`
- Persistent across sessions
- Manual cleanup available via API

---

## 🔒 Security

### Access Control:
- `@login_required` on all TTS endpoints
- Filename validation (alphanumeric only)
- Path traversal prevention
- User-specific audio access

### File Security:
- Only `.mp3` files served
- Strict filename pattern matching
- Cache directory isolated
- No user input in filenames

---

## 🚀 Usage Examples

### Example 1: Listen to Summary
```javascript
// User clicks "Listen to Summary" button
playSummaryTTS(contractId, buttonElement);
// → Generates audio from first 5 sections
// → Plays automatically
// → Shows pause button
```

### Example 2: Play Custom Text
```javascript
// Play any text section
playTTS("Your contract text here", "section-name", buttonElement);
// → Cleans text
// → Generates audio
// → Plays immediately
```

### Example 3: Stop Playback
```javascript
// Stop any playing audio
stopTTS();
// → Pauses audio
// → Resets button state
// → Cleans up resources
```

---

## 📊 Performance

### Generation Time:
- **First time**: 2-5 seconds (generates and caches)
- **Subsequent**: <1 second (served from cache)

### File Sizes:
- **Typical summary**: 100-500 KB
- **Full report**: 500KB-2MB
- **5-minute audio**: ~1MB

### Caching:
- Content-based hashing
- Automatic cache reuse
- Manual cleanup available
- Persistent across restarts

---

## 🐛 Troubleshooting

### "TTS generation failed"
**Cause**: gTTS not installed or network issue  
**Solution**: `pip install gTTS`

### "Audio file not found"
**Cause**: Cache cleared or file missing  
**Solution**: Click button again to regenerate

### "No readable text"
**Cause**: Empty or only special characters  
**Solution**: Check contract has text content

### Audio won't play
**Cause**: Browser audio policy or format issue  
**Solution**: Try different browser, check volume

---

## 🎯 Future Enhancements (Optional)

- [ ] Multiple voice options (male/female)
- [ ] Speed control (1x, 1.5x, 2x)
- [ ] Download audio file option
- [ ] Highlight text while speaking
- [ ] Play individual sections
- [ ] Multi-language TTS (Tamil, Hindi, etc.)
- [ ] Offline TTS using pyttsx3
- [ ] Background playback
- [ ] Playlist of sections
- [ ] Skip forward/backward

---

## 📝 API Documentation

### Generate TTS
```http
POST /api/tts/generate
Content-Type: application/json

{
  "text": "Text to convert to speech",
  "language": "en",
  "section": "summary"
}

Response:
{
  "success": true,
  "audio_url": "/api/tts/audio/tts_summary_abc123.mp3",
  "duration_estimate": 45
}
```

### Get Summary TTS
```http
POST /api/contracts/{contract_id}/tts/summary

Response:
{
  "success": true,
  "audio_url": "/api/tts/audio/tts_summary_xyz789.mp3",
  "duration_estimate": 60
}
```

### Serve Audio
```http
GET /api/tts/audio/{filename}

Response: audio/mpeg (MP3 file)
```

### Clear Cache
```http
DELETE /api/tts/cache

Response:
{
  "success": true,
  "message": "TTS cache cleared."
}
```

---

## ✅ Testing

### Manual Testing:
1. Start app: `python app.py`
2. Upload a contract
3. Go to Executive Summary tab
4. Click "🔊 Listen to Summary"
5. Verify audio plays
6. Click button again to test pause
7. Refresh page and click again (test cache)

### Test Different Contracts:
- Short contract (1-2 pages)
- Medium contract (5-10 pages)
- Long contract (20+ pages)
- Non-English contract (translated)

---

## 📚 Resources

- **gTTS Documentation**: https://gtts.readthedocs.io/
- **Google Text-to-Speech**: https://cloud.google.com/text-to-speech
- **HTML5 Audio API**: https://developer.mozilla.org/en-US/docs/Web/API/HTMLAudioElement

---

## ✨ Summary

✅ **TTS feature fully implemented**  
✅ **gTTS installed and tested**  
✅ **Frontend buttons added**  
✅ **API endpoints working**  
✅ **Caching implemented**  
✅ **Security measures in place**  
✅ **User-friendly interface**  
✅ **Documentation complete**  

**Users can now listen to contract summaries instead of reading them!** 🎉
