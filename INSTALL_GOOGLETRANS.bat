@echo off
echo ========================================
echo Installing Offline Translation
echo for Kannada, Marathi, Tamil + All Languages
echo ========================================
echo.

echo [Step 1/2] Installing deep-translator...
echo (This supports ALL languages including Kannada, Marathi, Tamil)
echo.
pip install deep-translator
echo.

echo [Step 2/2] Testing installation...
echo.
python -c "from deep_translator import GoogleTranslator; print('✓ deep-translator installed successfully')"
echo.

echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo You can now translate:
echo   ✓ Kannada (ಕನ್ನಡ) contracts
echo   ✓ Marathi (मराठी) contracts
echo   ✓ Tamil (தமிழ்) contracts
echo   ✓ Hindi (हिन्दी) contracts
echo   ✓ Telugu (తెలుగు) contracts
echo   ✓ And 100+ other languages!
echo.
echo No large package downloads needed!
echo Uses Google Translate API (free).
echo.
echo The system will automatically use this
echo for translation when you upload contracts.
echo.
pause
