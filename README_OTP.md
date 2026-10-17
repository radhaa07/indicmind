# 🔐 OTP Authentication - Quick Reference

## What is OTP Authentication?

Your app now uses **passwordless authentication**. Instead of remembering passwords, users receive a **6-digit code via email** every time they sign in.

## Why OTP?

✅ **No passwords to forget** - Users never create or remember passwords  
✅ **More secure** - Time-limited codes reduce phishing risks  
✅ **Better UX** - Simpler, faster login experience  
✅ **Email verified** - Automatically confirms email ownership  

## How It Works

### Registration
1. User enters **name** and **email**
2. System sends **6-digit OTP** to email
3. User enters OTP
4. Account created and logged in ✅

### Login
1. User enters **email**
2. System sends **6-digit OTP** to email
3. User enters OTP
4. Logged in ✅

## Setup (5 Minutes)

### 1. Get Gmail App Password

```
1. Enable 2FA on Gmail: https://myaccount.google.com/security
2. Generate App Password: https://myaccount.google.com/apppasswords
3. Select "Mail" app
4. Copy the 16-digit password
```

### 2. Update .env File

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=xxxx-xxxx-xxxx-xxxx  # 16-digit app password
FROM_EMAIL=your-email@gmail.com
```

### 3. Run & Test

```bash
# Start the app
python app.py

# Test OTP system (optional)
python test_otp.py
```

## Email Providers

### Gmail (Recommended)
```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```

### Outlook
```env
SMTP_HOST=smtp-mail.outlook.com
SMTP_PORT=587
SMTP_USER=your-email@outlook.com
SMTP_PASSWORD=your-password
```

### Yahoo
```env
SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=your-email@yahoo.com
SMTP_PASSWORD=your-app-password
```

### SendGrid (Production)
```env
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=your-sendgrid-api-key
FROM_EMAIL=noreply@yourdomain.com
```

## Security Features

| Feature | Details |
|---------|---------|
| **Expiration** | 10 minutes |
| **Usage** | Single-use only |
| **Length** | 6 digits |
| **Type** | Numeric (0-9) |
| **Invalidation** | Old codes auto-invalidated |

## Troubleshooting

### OTP Not Received?
- ✅ Check spam/junk folder
- ✅ Verify SMTP config in .env
- ✅ Wait 30 seconds (email delivery delay)

### "Failed to send OTP"?
- ✅ Use App Password (not regular password) for Gmail
- ✅ Enable 2FA on your email account
- ✅ Check SMTP credentials

### "Invalid OTP"?
- ✅ Check if code expired (10 min limit)
- ✅ Ensure you're using the latest code
- ✅ Request new code if needed

## Testing

Run the test script:
```bash
python test_otp.py
```

Tests include:
- Database setup
- SMTP configuration
- Email connection
- Test email delivery
- OTP storage/retrieval

## Files Created

| File | Purpose |
|------|---------|
| `OTP_AUTHENTICATION.md` | Complete technical docs |
| `OTP_SETUP_GUIDE.md` | Step-by-step setup |
| `OTP_IMPLEMENTATION_SUMMARY.md` | Implementation details |
| `test_otp.py` | Automated testing |
| `README_OTP.md` | This quick reference |

## Features

✅ Passwordless login  
✅ Email verification  
✅ 6-digit OTP codes  
✅ 10-minute expiration  
✅ Single-use codes  
✅ Auto-invalidation  
✅ Professional emails  
✅ Resend functionality  
✅ Works with Google OAuth  

## Important Notes

⚠️ **This is NOT for SSO** - The OTP system is separate from Google OAuth  
⚠️ **Email required** - SMTP must be configured before use  
⚠️ **No breaking changes** - Google OAuth still works  
⚠️ **Production ready** - Includes proper error handling  

## Quick Commands

```bash
# Initialize database (automatic)
python app.py

# Test OTP system
python test_otp.py

# Check OTP table
sqlite3 contractlens.db "SELECT * FROM otp_codes;"

# Clear expired OTPs (manual cleanup)
sqlite3 contractlens.db "DELETE FROM otp_codes WHERE used = 1 OR expires_at < datetime('now');"
```

## Need Help?

1. Read `OTP_SETUP_GUIDE.md` for detailed setup
2. Run `test_otp.py` to diagnose issues
3. Check Flask app logs for error details
4. Verify SMTP credentials in .env

## Success Indicators

✅ Test script passes all checks  
✅ OTP received in email inbox  
✅ Login successful with OTP  
✅ No SMTP errors in logs  

## Next Steps

After setup:
1. Configure SMTP in .env
2. Run test_otp.py
3. Try registration with your email
4. Check inbox for OTP
5. Complete login
6. You're done! 🎉

---

**Status**: ✅ Ready to use  
**Python Version**: 3.7+  
**Dependencies**: Built-in (smtplib, email)  
**Support**: See documentation files
