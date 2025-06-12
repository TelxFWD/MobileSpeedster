from app import db
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_username = db.Column(db.String(64), unique=True, nullable=False)
    telegram_chat_id = db.Column(db.String(32), unique=True)
    pin_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    is_banned = db.Column(db.Boolean, default=False)
    
    # Relationships
    subscriptions = db.relationship('Subscription', backref='user', lazy=True, cascade='all, delete-orphan')
    transactions = db.relationship('Transaction', backref='user', lazy=True)

    def set_pin(self, pin):
        self.pin_hash = generate_password_hash(str(pin))
    
    def check_pin(self, pin):
        return check_password_hash(self.pin_hash, str(pin))
    
    def has_active_subscription(self):
        return any(sub.is_active() for sub in self.subscriptions)
    
    def get_active_subscriptions(self):
        return [sub for sub in self.subscriptions if sub.is_active()]

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Channel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    telegram_link = db.Column(db.String(256), nullable=False)
    telegram_channel_id = db.Column(db.String(64))  # Telegram channel ID for enforcement bot
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # For solo channels
    solo_price = db.Column(db.Float)
    solo_duration_days = db.Column(db.Integer)
    show_in_custom_bundle = db.Column(db.Boolean, default=True)
    
    # Relationships
    plan_channels = db.relationship('PlanChannel', backref='channel', lazy=True, cascade='all, delete-orphan')

class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    plan_type = db.Column(db.String(16), nullable=False)  # 'solo' or 'bundle'
    price = db.Column(db.Float, nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)
    is_lifetime = db.Column(db.Boolean, default=False)
    folder_link = db.Column(db.String(256))  # For bundles
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    plan_channels = db.relationship('PlanChannel', backref='plan', lazy=True, cascade='all, delete-orphan')
    subscriptions = db.relationship('Subscription', backref='plan', lazy=True)

    def get_channels(self):
        return [pc.channel for pc in self.plan_channels]

class PlanChannel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=False)
    is_paid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    transactions = db.relationship('Transaction', backref='subscription', lazy=True)

    def is_active(self):
        return self.is_paid and self.end_date > datetime.utcnow()

    def days_remaining(self):
        if self.is_active():
            return (self.end_date - datetime.utcnow()).days
        return 0

class PromoCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    discount_percent = db.Column(db.Float, nullable=False)
    usage_limit = db.Column(db.Integer)
    used_count = db.Column(db.Integer, default=0)
    expiry_date = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expiry_date and self.expiry_date < datetime.utcnow():
            return False
        if self.usage_limit and self.used_count >= self.usage_limit:
            return False
        return True

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'))
    transaction_id = db.Column(db.String(128), unique=True, nullable=False)
    payment_method = db.Column(db.String(32), nullable=False)  # 'paypal' or 'crypto'
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(32), nullable=False)
    network = db.Column(db.String(32))  # Blockchain network for crypto payments
    status = db.Column(db.String(32), nullable=False)
    webhook_data = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

class SiteContent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    title = db.Column(db.String(256))
    content = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class BotSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_token = db.Column(db.String(256))
    api_id = db.Column(db.String(128))
    api_hash = db.Column(db.String(256))
    phone_number = db.Column(db.String(32))
    session_string = db.Column(db.Text)  # Store session data for persistence
    enforcement_enabled = db.Column(db.Boolean, default=False)
    notifications_enabled = db.Column(db.Boolean, default=True)
    welcome_message = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @staticmethod
    def get_settings():
        """Get or create bot settings"""
        settings = BotSettings.query.first()
        if not settings:
            settings = BotSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

class PaymentSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    paypal_client_id = db.Column(db.String(256))
    paypal_client_secret = db.Column(db.String(256))
    paypal_sandbox = db.Column(db.Boolean, default=True)
    nowpayments_api_key = db.Column(db.String(256))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class BotLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action_type = db.Column(db.String(32), nullable=False)  # 'ban', 'unban', 'manual_ban', 'manual_unban'
    user_id = db.Column(db.Integer)
    channel_id = db.Column(db.String(128))
    reason = db.Column(db.String(256))
    success = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text)
    dry_run = db.Column(db.Boolean, default=False)
    admin_user = db.Column(db.String(64))  # Admin who performed manual action
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<BotLog {self.action_type} user:{self.user_id} channel:{self.channel_id}>'
