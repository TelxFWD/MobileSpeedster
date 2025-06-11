import os
import logging
import threading
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
from config import get_config

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# Create the app
app = Flask(__name__)

# Load configuration
config_class = get_config()
app.config.from_object(config_class)

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Initialize the app with the extension
db.init_app(app)

with app.app_context():
    # Import models to ensure tables are created
    import models
    db.create_all()

    # Create default admin user if none exists
    from models import Admin
    from werkzeug.security import generate_password_hash

    if not Admin.query.first():
        default_admin = Admin(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            is_active=True
        )
        db.session.add(default_admin)
        db.session.commit()
        logging.info("Default admin user created: admin/admin123")

# Import routes at module level
from routes import *
from admin_routes import *
from payment_handler import *

# Start bot service
def start_bot_background():
    """Start bot service in background"""
    try:
        from bot_service import run_bot_service
        run_bot_service()
    except Exception as e:
        logging.error(f"Failed to start bot service: {e}")

# Start bot in background thread
bot_thread = threading.Thread(target=start_bot_background, daemon=True)
bot_thread.start()

# Start enforcement bot in background
def start_enforcement_bot_background():
    """Start enforcement bot service in background"""
    try:
        from enforcement_bot import run_enforcement_bot_background
        run_enforcement_bot_background()
    except Exception as e:
        logging.error(f"Failed to start enforcement bot: {e}")

# Start enforcement bot in background thread
enforcement_thread = threading.Thread(target=start_enforcement_bot_background, daemon=True)
enforcement_thread.start()