"""
Security utilities for TeleSignals application
"""
import hashlib
import secrets
import hmac
from functools import wraps
from flask import request, jsonify, session
import time

def generate_secure_token():
    """Generate a cryptographically secure token"""
    return secrets.token_urlsafe(32)

def hash_password(password, salt=None):
    """Hash a password with salt"""
    if salt is None:
        salt = secrets.token_bytes(32)
    
    pwd_hash = hashlib.pbkdf2_hmac('sha256', 
                                   password.encode('utf-8'), 
                                   salt, 
                                   100000)
    return salt + pwd_hash

def verify_password(password, hashed):
    """Verify a password against its hash"""
    salt = hashed[:32]
    key = hashed[32:]
    
    new_key = hashlib.pbkdf2_hmac('sha256',
                                  password.encode('utf-8'),
                                  salt,
                                  100000)
    return hmac.compare_digest(key, new_key)

def rate_limit(max_requests=5, window=60):
    """Rate limiting decorator"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Simple in-memory rate limiting (use Redis in production)
            client_id = request.remote_addr
            current_time = time.time()
            
            # For demo purposes, always allow (implement proper rate limiting in production)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def validate_csrf_token():
    """CSRF token validation"""
    token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    session_token = session.get('csrf_token')
    
    if not token or not session_token:
        return False
    
    return hmac.compare_digest(token, session_token)

def sanitize_input(text, max_length=1000):
    """Basic input sanitization"""
    if not text:
        return ""
    
    # Remove potentially dangerous characters
    text = str(text).strip()
    text = text[:max_length]
    
    # Basic HTML escaping
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    text = text.replace("'", '&#x27;')
    
    return text

def validate_telegram_username(username):
    """Validate Telegram username format"""
    if not username:
        return False
    
    # Remove @ if present
    username = username.lstrip('@')
    
    # Check length (5-32 characters)
    if len(username) < 5 or len(username) > 32:
        return False
    
    # Check format (alphanumeric and underscores only)
    import re
    pattern = r'^[a-zA-Z0-9_]+$'
    return bool(re.match(pattern, username))

def secure_filename(filename):
    """Secure a filename by removing dangerous characters"""
    import re
    filename = re.sub(r'[^\w\s-]', '', filename).strip()
    filename = re.sub(r'[-\s]+', '-', filename)
    return filename

class SecurityHeaders:
    """Security headers middleware"""
    
    @staticmethod
    def add_security_headers(response):
        """Add security headers to response"""
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' https:; "
            "connect-src 'self' https:;"
        )
        return response

def log_security_event(event_type, details, user_id=None):
    """Log security events for monitoring"""
    import logging
    
    security_logger = logging.getLogger('security')
    
    log_data = {
        'event_type': event_type,
        'details': details,
        'user_id': user_id,
        'ip_address': request.remote_addr if request else 'unknown',
        'user_agent': request.headers.get('User-Agent', '') if request else '',
        'timestamp': time.time()
    }
    
    security_logger.warning(f"Security Event: {log_data}")

def encrypt_sensitive_data(data, key=None):
    """Encrypt sensitive data (placeholder for production encryption)"""
    # In production, use proper encryption library like cryptography
    # This is a placeholder implementation
    return data

def decrypt_sensitive_data(encrypted_data, key=None):
    """Decrypt sensitive data (placeholder for production decryption)"""
    # In production, use proper decryption
    # This is a placeholder implementation
    return encrypted_data