@echo off
echo ========================================
echo FIXING TRANSLATION ISSUE
echo ========================================
echo.
echo Problem: Gemini rate-limited (429 error)
echo Solution: Install offline translation
echo.
echo This will take 2-3 minutes...
echo.

echo [Step 1/4] Updating package index...
argospm update
echo.

echo [Step 2/4] Installing Kannada...
argospm install translate-kn_en
echo.

echo [Step 3/4] Installing Marathi...
argospm install translate-mr_en
echo.

echo [Step 4/4] Installing Tamil...
argospm install translate-ta_en
echo.

echo ========================================
echo INSTALLATION COMPLETE!
echo ========================================
echo.
echo Now when Gemini hits rate limit,
echo the system will automatically use
echo offline translation instead.
echo.
echo Try uploading your contract again!
echo.
pause
