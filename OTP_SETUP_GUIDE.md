# Quick OTP Setup Guide

## 🚀 5-Minute Setup

### Step 1: Configure Email (Gmail Example)

1. **Enable 2-Factor Authentication** on your Gmail account:
   - Go to https://myaccount.google.com/security
   - Enable 2-Step Verification

2. **Generate App Password**:
   - Visit https://myaccount.google.com/apppasswords
   - Select "Mail" as the app
   - Copy the 16-digit password

3. **Update .env file**:
   ```env
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your-email@gmail.com
   SMTP_PASSWORD=xxxx-xxxx-xxxx-xxxx  # 16-digit app password
   FROM_EMAIL=your-email@gmail.com
   ```

### Step 2: Initialize Database

The OTP table will be created automatically when you run the app:

```bash
python app.py
```

### Step 3: Test It Out

1. Navigate to http://localhost:5000/register
2. Enter your name and email
3. Click "Send Verification Code"
4. Check your email inbox
5. Enter the 6-digit code
6. You're in! 🎉

## ✅ Verification Checklist

- [ ] SMTP credentials added to `.env`
- [ ] App password generated (for Gmail)
- [ ] Flask app restarted
- [ ] Test email sent successfully
- [ ] OTP received in inbox
- [ ] Login successful with OTP

## 🔧 Common Issues

### Issue: "Failed to send OTP"

**Solution**: Check your `.env` file configuration
- Verify `SMTP_USER` is correct
- Ensure `SMTP_PASSWORD` is the app password (not your regular password)
- Check `SMTP_HOST` and `SMTP_PORT`

### Issue: "No OTP received"

**Solution**: Check email filters
- Look in Spam/Junk folder
- Add sender to contacts
- Check email server logs

### Issue: "Invalid or expired OTP"

**Solution**: 
- OTPs expire after 10 minutes
- Each OTP can only be used once
- Request a new code if needed

## 📧 Other Email Providers

### Outlook/Hotmail
```env
SMTP_HOST=smtp-mail.outlook.com
SMTP_PORT=587
SMTP_USER=your-email@outlook.com
SMTP_PASSWORD=your-password
FROM_EMAIL=your-email@outlook.com
```

### Yahoo Mail
```env
SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=your-email@yahoo.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=your-email@yahoo.com
```

### SendGrid (Production)
```env
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=your-sendgrid-api-key
FROM_EMAIL=noreply@yourdomain.com
```

## 🎯 Features Enabled

✅ Passwordless login (no passwords to remember)  
✅ Email verification on registration  
✅ Secure 6-digit OTP codes  
✅ 10-minute expiration  
✅ Single-use codes  
✅ Automatic code invalidation  
✅ Professional email templates  

## 🔐 Security Notes

- OTPs expire after 10 minutes
- Each code can only be used once
- Old codes are invalidated when new ones are requested
- Google OAuth still works alongside OTP
- No passwords stored for OTP users

## 📝 Testing Commands

Test your SMTP configuration with Python:

```python
import smtplib
from email.mime.text import MIMEText

# Update with your credentials
smtp_host = "smtp.gmail.com"
smtp_port = 587
smtp_user = "your-email@gmail.com"
smtp_password = "your-app-password"

msg = MIMEText("Test email from OTP system")
msg['Subject'] = "Test Email"
msg['From'] = smtp_user
msg['To'] = smtp_user

try:
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
    print("✅ Email sent successfully!")
except Exception as e:
    print(f"❌ Failed: {e}")
```

## 🎊 You're All Set!

Your application now has:
- Modern passwordless authentication
- Secure email-based OTP system
- Better user experience
- Enhanced security

For detailed documentation, see `OTP_AUTHENTICATION.md`
