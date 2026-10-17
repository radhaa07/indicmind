# OTP-Based Email Authentication

## Overview

The application now uses **OTP (One-Time Password)** authentication instead of traditional passwords. When users sign in or register, they receive a 6-digit code via email that serves as their login credential.

## Key Features

✅ **Passwordless Authentication** - No passwords to remember or manage  
✅ **Email-Based OTP** - 6-digit codes sent to user's email  
✅ **Time-Limited Codes** - OTPs expire after 10 minutes  
✅ **Single-Use Codes** - Each OTP can only be used once  
✅ **Secure** - Codes are invalidated after use or expiration  
✅ **SSO Compatible** - Works alongside Google OAuth (not affected)

## How It Works

### Registration Flow

1. User enters their **name** and **email**
2. System sends a **6-digit OTP** to their email
3. User enters the OTP to verify their email
4. Account is created and user is logged in

### Login Flow

1. User enters their **email address**
2. System checks if account exists
3. If exists, sends a **6-digit OTP** to their email
4. User enters the OTP to authenticate
5. User is logged in

### OTP Lifecycle

- **Generation**: 6-digit random numeric code
- **Validity**: 10 minutes from creation
- **Usage**: Single use only
- **Security**: Old OTPs are automatically invalidated when new ones are requested

## Email Configuration

### Required Environment Variables

Add these to your `.env` file:

```env
# Email configuration for OTP authentication
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=your-email@gmail.com
```

### Gmail Setup (Recommended)

1. **Enable 2-Factor Authentication** on your Google account
2. **Generate App Password**:
   - Go to Google Account → Security → 2-Step Verification → App passwords
   - Select "Mail" and generate a password
   - Use this password as `SMTP_PASSWORD`

3. **Configure .env**:
```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=youremail@gmail.com
SMTP_PASSWORD=your-16-digit-app-password
FROM_EMAIL=youremail@gmail.com
```

### Other Email Providers

#### Outlook/Hotmail
```env
SMTP_HOST=smtp-mail.outlook.com
SMTP_PORT=587
SMTP_USER=youremail@outlook.com
SMTP_PASSWORD=your-password
```

#### Yahoo Mail
```env
SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=youremail@yahoo.com
SMTP_PASSWORD=your-app-password
```

#### Custom SMTP Server
```env
SMTP_HOST=mail.yourdomain.com
SMTP_PORT=587
SMTP_USER=noreply@yourdomain.com
SMTP_PASSWORD=your-password
FROM_EMAIL=noreply@yourdomain.com
```

## Database Schema

### New Table: `otp_codes`

```sql
CREATE TABLE otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    otp_code TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    used INTEGER DEFAULT 0
);
```

### Modified Table: `users`

The `password_hash` field is retained for:
- Google OAuth users (stores random hash)
- Backward compatibility
- Future migration options

For OTP users, a random UUID hash is stored (not used for authentication).

## Security Features

### 1. Time-Based Expiration
- OTPs expire after 10 minutes
- Expired codes cannot be used

### 2. Single-Use Codes
- Each OTP is marked as "used" after verification
- Prevents replay attacks

### 3. Automatic Invalidation
- When a new OTP is requested, all previous unused OTPs for that email are invalidated
- Prevents multiple active codes

### 4. Email Verification
- Only verified email addresses can create accounts
- OTP confirms email ownership

### 5. Rate Limiting (Recommended Enhancement)
Consider adding rate limiting to prevent abuse:
- Limit OTP requests per email (e.g., 3 per hour)
- Limit failed verification attempts (e.g., 5 per OTP)

## User Experience

### Email Template

The OTP email includes:
- Clear subject line: "Your Login Code - AI Legal Contract Analyzer"
- Large, centered OTP code for easy reading
- Expiration notice (10 minutes)
- Security note about ignoring unsolicited emails
- Professional HTML formatting

### UI Features

1. **Passwordless Notice**: Clear indication that no password is needed
2. **OTP Input Field**: Large, formatted input for 6-digit code
3. **Resend Option**: Users can request a new code if needed
4. **Visual Feedback**: Success/error messages for all actions

## Testing

### Manual Testing

1. **Registration**:
   ```
   1. Navigate to /register
   2. Enter name and email
   3. Click "Send Verification Code"
   4. Check email inbox
   5. Enter 6-digit code
   6. Verify account creation and auto-login
   ```

2. **Login**:
   ```
   1. Navigate to /login
   2. Enter registered email
   3. Click "Send Login Code"
   4. Check email inbox
   5. Enter 6-digit code
   6. Verify successful login
   ```

3. **Expiration**:
   ```
   1. Request OTP
   2. Wait 11 minutes
   3. Try to use expired code
   4. Verify error message
   ```

4. **Reuse Prevention**:
   ```
   1. Request and use an OTP successfully
   2. Try to use the same OTP again
   3. Verify rejection
   ```

## Troubleshooting

### OTP Not Received

1. **Check Spam/Junk Folder**: Email might be filtered
2. **Verify SMTP Config**: Ensure credentials are correct
3. **Check Firewall**: Port 587 might be blocked
4. **Test SMTP Connection**: Use a tool like `telnet` to verify SMTP access

### "Failed to send OTP" Error

1. **Gmail**: Ensure App Password is used (not regular password)
2. **2FA**: Some providers require 2FA to be enabled
3. **Less Secure Apps**: Some providers require this setting (not recommended)
4. **Check Logs**: Review Flask application logs for detailed error messages

### OTP Always Invalid

1. **Time Sync**: Ensure server time is correct (affects expiration)
2. **Database**: Verify OTP is stored correctly
3. **Case Sensitivity**: OTP should be numeric only (no case issues)

## Migration from Password-Based Auth

If migrating from the old password-based system:

1. **Existing Users**: Can still use Google OAuth
2. **New Flow**: Next login will use OTP system
3. **No Data Loss**: User accounts remain unchanged
4. **Backward Compatible**: Old `password_hash` field retained

## Advantages Over Passwords

✅ **No Password Management**: Users don't need to create/remember passwords  
✅ **No Password Resets**: Eliminates forgot password flows  
✅ **Enhanced Security**: No stored passwords to breach  
✅ **Phishing Resistant**: Time-limited codes reduce phishing risks  
✅ **Better UX**: Simpler authentication flow  
✅ **Email Verification**: Confirms email ownership on every login

## Future Enhancements

Consider adding:

1. **SMS OTP**: Alternative to email OTP
2. **Rate Limiting**: Prevent abuse of OTP generation
3. **Account Recovery**: Alternative verification methods
4. **Remember Device**: Option to skip OTP on trusted devices
5. **Admin Dashboard**: Monitor OTP usage and failed attempts
6. **Audit Logging**: Track all authentication attempts

## API Reference

### New Functions

#### `generate_otp()`
Generates a 6-digit numeric OTP code.

#### `send_otp_email(email, otp_code)`
Sends OTP via configured SMTP server.

**Raises**: `ValueError` if SMTP configuration is missing.

#### `store_otp(email, otp_code)`
Stores OTP in database with 10-minute expiration.  
Automatically invalidates previous unused OTPs.

#### `verify_otp(email, otp_code)`
Verifies OTP code for given email.

**Returns**: `True` if valid and not expired, `False` otherwise.

## Notes

- **This is NOT for SSO**: The OTP system is separate from Google OAuth
- **Email Required**: SMTP configuration must be set up before use
- **Production Ready**: Includes proper error handling and security measures
- **No Breaking Changes**: Existing Google OAuth flow continues to work

## Support

For issues or questions:
1. Check SMTP configuration in `.env`
2. Review application logs
3. Verify email provider settings
4. Test with a simple SMTP client first
