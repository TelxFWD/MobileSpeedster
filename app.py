import os
import logging
import threading
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# Create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET") or "dev-secret-key-change-in-production"
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize the app with the extension
db.init_app(app)

# Initialize database tables
def init_db():
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

# Call init_db when app starts
init_db()

# Import routes after app initialization
try:
    from routes import *
    from admin_routes import *
    from payment_handler import *
    logging.info("Routes imported successfully")
except Exception as e:
    logging.error(f"Error importing routes: {e}")

# Background services will be started after full initialization
def start_background_services():
    """Start background services after app initialization"""
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

    def run_enforcement_bot_background():
        """Start enhanced enforcement bot service in background"""
        try:
            from enforcement_bot_v2 import run_enforcement_bot_v2_background
            run_enforcement_bot_v2_background()
        except Exception as e:
            logger.error(f"Failed to start enforcement bot V2 service: {e}")

    # Check enforcement bot configuration
    api_id = os.environ.get('TELEGRAM_API_ID')
    api_hash = os.environ.get('TELEGRAM_API_HASH')
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')

    if not api_id or not api_hash or not bot_token:
        logger.info("Enforcement bot in standby mode - configure Telegram API credentials at /admin/bot-setup to activate")
    else:
        logger.info("Starting enhanced enforcement bot V2 with bot authentication")
        run_enforcement_bot_background()

# Start background services
start_background_services()