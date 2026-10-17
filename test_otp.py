"""
Test script for OTP authentication system
Run this after configuring your SMTP settings in .env
"""

import os
import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load environment
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

def test_database_setup():
    """Test if OTP table exists"""
    print("Testing database setup...")
    
    db_path = BASE_DIR / "contractlens.db"
    if not db_path.exists():
        print("❌ Database not found. Run app.py first to initialize.")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='otp_codes'")
        if cursor.fetchone():
            print("✅ OTP table exists")
            
            # Check table structure
            cursor.execute("PRAGMA table_info(otp_codes)")
            columns = [col[1] for col in cursor.fetchall()]
            expected = ['id', 'email', 'otp_code', 'created_at', 'expires_at', 'used']
            
            if all(col in columns for col in expected):
                print("✅ Table structure is correct")
                return True
            else:
                print(f"❌ Missing columns. Expected: {expected}, Found: {columns}")
                return False
        else:
            print("❌ OTP table not found. Run app.py to initialize database.")
            return False
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False
    finally:
        conn.close()


def test_smtp_config():
    """Test SMTP configuration"""
    print("\nTesting SMTP configuration...")
    
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("FROM_EMAIL")
    
    missing = []
    if not smtp_host: missing.append("SMTP_HOST")
    if not smtp_port: missing.append("SMTP_PORT")
    if not smtp_user: missing.append("SMTP_USER")
    if not smtp_password: missing.append("SMTP_PASSWORD")
    
    if missing:
        print(f"❌ Missing configuration: {', '.join(missing)}")
        print("   Add these to your .env file")
        return False
    
    print(f"✅ SMTP_HOST: {smtp_host}")
    print(f"✅ SMTP_PORT: {smtp_port}")
    print(f"✅ SMTP_USER: {smtp_user}")
    print(f"✅ SMTP_PASSWORD: {'*' * len(smtp_password)}")
    print(f"✅ FROM_EMAIL: {from_email or smtp_user}")
    
    return True


def test_smtp_connection():
    """Test actual SMTP connection"""
    print("\nTesting SMTP connection...")
    
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    
    if not smtp_user or not smtp_password:
        print("❌ SMTP credentials not configured")
        return False
    
    try:
        import smtplib
        print(f"   Connecting to {smtp_host}:{smtp_port}...")
        
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            print("   ✅ Connected")
            server.starttls()
            print("   ✅ TLS started")
            server.login(smtp_user, smtp_password)
            print("   ✅ Login successful")
        
        print("✅ SMTP connection test passed")
        return True
        
    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication failed. Check your SMTP_USER and SMTP_PASSWORD")
        print("   For Gmail, make sure you're using an App Password, not your regular password")
        return False
    except smtplib.SMTPException as e:
        print(f"❌ SMTP error: {e}")
        return False
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False


def test_send_email():
    """Send a test email"""
    print("\nTesting email send...")
    
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("FROM_EMAIL", smtp_user)
    
    test_email = input(f"Enter email to send test OTP to (press Enter for {smtp_user}): ").strip()
    if not test_email:
        test_email = smtp_user
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        import random
        import string
        
        # Generate test OTP
        test_otp = ''.join(random.choices(string.digits, k=6))
        
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = test_email
        msg['Subject'] = "Test OTP - AI Legal Contract Analyzer"
        
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <h2 style="color: #2563eb;">Test OTP Email</h2>
                <p>This is a test email from your OTP authentication system.</p>
                <div style="background-color: #f3f4f6; padding: 20px; text-align: center; border-radius: 8px; margin: 20px 0;">
                    <h1 style="font-size: 36px; letter-spacing: 8px; margin: 0; color: #2563eb;">{test_otp}</h1>
                </div>
                <p>If you received this email, your OTP system is working correctly! ✅</p>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        print(f"✅ Test email sent to {test_email}")
        print(f"   Test OTP: {test_otp}")
        print("   Check your inbox!")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False


def test_otp_storage():
    """Test OTP storage and retrieval"""
    print("\nTesting OTP storage...")
    
    db_path = BASE_DIR / "contractlens.db"
    if not db_path.exists():
        print("❌ Database not found")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Insert test OTP
        test_email = "test@example.com"
        test_otp = "123456"
        expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
        
        cursor.execute(
            "INSERT INTO otp_codes (email, otp_code, expires_at) VALUES (?, ?, ?)",
            (test_email, test_otp, expires_at)
        )
        conn.commit()
        print(f"✅ Test OTP stored for {test_email}")
        
        # Retrieve it
        cursor.execute(
            "SELECT * FROM otp_codes WHERE email = ? AND otp_code = ? ORDER BY created_at DESC LIMIT 1",
            (test_email, test_otp)
        )
        row = cursor.fetchone()
        
        if row:
            print(f"✅ Test OTP retrieved successfully")
            
            # Clean up
            cursor.execute("DELETE FROM otp_codes WHERE email = ?", (test_email,))
            conn.commit()
            print("✅ Test data cleaned up")
            return True
        else:
            print("❌ Failed to retrieve test OTP")
            return False
            
    except Exception as e:
        print(f"❌ Storage error: {e}")
        return False
    finally:
        conn.close()


def main():
    """Run all tests"""
    print("=" * 60)
    print("OTP Authentication System Test")
    print("=" * 60)
    
    results = {}
    
    # Run tests
    results['database'] = test_database_setup()
    results['config'] = test_smtp_config()
    
    if results['config']:
        results['connection'] = test_smtp_connection()
        
        if results['connection']:
            send_test = input("\nDo you want to send a test email? (y/n): ").strip().lower()
            if send_test == 'y':
                results['email'] = test_send_email()
        else:
            results['email'] = False
    else:
        results['connection'] = False
        results['email'] = False
    
    if results['database']:
        results['storage'] = test_otp_storage()
    else:
        results['storage'] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test.capitalize():20} {status}")
    
    all_passed = all(results.values())
    
    print("=" * 60)
    if all_passed:
        print("🎉 All tests passed! Your OTP system is ready to use.")
    else:
        print("⚠️  Some tests failed. Please check the errors above.")
        print("\nCommon solutions:")
        print("1. Run app.py first to initialize the database")
        print("2. Add SMTP configuration to .env file")
        print("3. For Gmail, use an App Password (not regular password)")
        print("4. Enable 2-Factor Authentication on your email account")
    print("=" * 60)


if __name__ == "__main__":
    main()
