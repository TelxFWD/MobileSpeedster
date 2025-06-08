from functools import wraps
from flask import session, redirect, url_for, flash, request
import secrets
import string

def login_required(f):
    """Decorator to require user login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'error')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to require admin login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Admin access required', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def generate_transaction_id():
    """Generate unique transaction ID"""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16))

def calculate_discounted_price(original_price, discount_percent):
    """Calculate price after discount"""
    return original_price * (1 - discount_percent / 100)

def format_currency(amount, currency='USD'):
    """Format currency for display"""
    if currency == 'USD':
        return f"${amount:.2f}"
    return f"{amount:.2f} {currency}"

def validate_telegram_username(username):
    """Validate Telegram username format"""
    if not username:
        return False
    
    # Remove @ if present
    if username.startswith('@'):
        username = username[1:]
    
    # Basic validation - alphanumeric and underscores, 5-32 chars
    if not username.replace('_', '').isalnum():
        return False
    
    if len(username) < 5 or len(username) > 32:
        return False
    
    return True

def validate_pin(pin):
    """Validate 4-digit PIN"""
    return pin and pin.isdigit() and len(pin) == 4

def get_user_subscription_status(user):
    """Get user's overall subscription status"""
    active_subscriptions = user.get_active_subscriptions()
    
    if not active_subscriptions:
        return {
            'status': 'inactive',
            'message': 'No active subscriptions',
            'color': 'red'
        }
    
    # Find subscription expiring soonest
    earliest_expiry = min(sub.end_date for sub in active_subscriptions)
    days_remaining = min(sub.days_remaining() for sub in active_subscriptions)
    
    if days_remaining <= 3:
        return {
            'status': 'expiring',
            'message': f'Expires in {days_remaining} day(s)',
            'color': 'orange'
        }
    elif days_remaining <= 7:
        return {
            'status': 'active_warning',
            'message': f'Expires in {days_remaining} day(s)',
            'color': 'yellow'
        }
    else:
        return {
            'status': 'active',
            'message': f'{len(active_subscriptions)} active subscription(s)',
            'color': 'green'
        }

def sanitize_html(text):
    """Basic HTML sanitization"""
    if not text:
        return ""
    
    # Simple escaping - in production use a proper library like bleach
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    text = text.replace("'", '&#x27;')
    
    return text

def truncate_text(text, length=100):
    """Truncate text to specified length"""
    if not text or len(text) <= length:
        return text
    return text[:length] + "..."
