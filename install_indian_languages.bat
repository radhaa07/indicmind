@echo off
echo ========================================
echo Installing Indian Language Packages
echo for Offline Translation
echo ========================================
echo.

echo [Step 1/4] Installing argostranslate...
pip install argostranslate
echo.

echo [Step 2/4] Updating package index...
argospm update
echo.

echo [Step 3/4] Installing language packages...
echo.

echo Installing Kannada (Kannada to English)...
argospm install translate-kn_en
echo.

echo Installing Marathi (Marathi to English)...
argospm install translate-mr_en
echo.

echo Installing Tamil (Tamil to English)...
argospm install translate-ta_en
echo.

echo [Step 4/4] Verifying installation...
echo.
argospm list
echo.

echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo You can now translate:
echo   - Kannada contracts
echo   - Marathi contracts
echo   - Tamil contracts
echo.
echo The system will automatically use offline
echo translation when LLM is unavailable.
echo.
pause
