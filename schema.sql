-- TeleSignals Database Schema
-- Complete schema with all tables and recent column additions

-- Users table with telegram_chat_id column
CREATE TABLE IF NOT EXISTS "user" (
    id SERIAL PRIMARY KEY,
    telegram_username VARCHAR(64) UNIQUE NOT NULL,
    telegram_chat_id VARCHAR(32) UNIQUE,
    pin_hash VARCHAR(256) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    is_banned BOOLEAN DEFAULT FALSE
);

-- Admin users table
CREATE TABLE IF NOT EXISTS admin (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Channels table with solo pricing options
CREATE TABLE IF NOT EXISTS channel (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    telegram_link VARCHAR(256) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    solo_price FLOAT,
    solo_duration_days INTEGER
);

-- Plans table
CREATE TABLE IF NOT EXISTS plan (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    plan_type VARCHAR(16) NOT NULL CHECK (plan_type IN ('solo', 'bundle')),
    price FLOAT NOT NULL,
    duration_days INTEGER NOT NULL,
    folder_link VARCHAR(256),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Plan-Channel relationship table
CREATE TABLE IF NOT EXISTS plan_channel (
    id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES plan(id) ON DELETE CASCADE,
    channel_id INTEGER NOT NULL REFERENCES channel(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(plan_id, channel_id)
);

-- Subscriptions table
CREATE TABLE IF NOT EXISTS subscription (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    plan_id INTEGER NOT NULL REFERENCES plan(id),
    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_date TIMESTAMP NOT NULL,
    is_paid BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Promo codes table
CREATE TABLE IF NOT EXISTS promo_code (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) UNIQUE NOT NULL,
    discount_percent FLOAT NOT NULL,
    usage_limit INTEGER,
    used_count INTEGER DEFAULT 0,
    expiry_date TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Transactions table with network column for crypto payments
CREATE TABLE IF NOT EXISTS transaction (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    subscription_id INTEGER REFERENCES subscription(id),
    transaction_id VARCHAR(128) UNIQUE NOT NULL,
    payment_method VARCHAR(32) NOT NULL CHECK (payment_method IN ('paypal', 'crypto')),
    amount FLOAT NOT NULL,
    currency VARCHAR(32) NOT NULL,
    network VARCHAR(32),
    status VARCHAR(32) NOT NULL,
    webhook_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Site content management table
CREATE TABLE IF NOT EXISTS site_content (
    id SERIAL PRIMARY KEY,
    key VARCHAR(64) UNIQUE NOT NULL,
    title VARCHAR(256),
    content TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bot settings table
CREATE TABLE IF NOT EXISTS bot_settings (
    id SERIAL PRIMARY KEY,
    bot_token VARCHAR(256),
    notifications_enabled BOOLEAN DEFAULT TRUE,
    welcome_message TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Payment settings table
CREATE TABLE IF NOT EXISTS payment_settings (
    id SERIAL PRIMARY KEY,
    paypal_client_id VARCHAR(256),
    paypal_client_secret VARCHAR(256),
    paypal_sandbox BOOLEAN DEFAULT TRUE,
    nowpayments_api_key VARCHAR(256),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for better performance
CREATE INDEX IF NOT EXISTS idx_user_telegram_username ON "user"(telegram_username);
CREATE INDEX IF NOT EXISTS idx_user_telegram_chat_id ON "user"(telegram_chat_id);
CREATE INDEX IF NOT EXISTS idx_subscription_user_id ON subscription(user_id);
CREATE INDEX IF NOT EXISTS idx_subscription_end_date ON subscription(end_date);
CREATE INDEX IF NOT EXISTS idx_transaction_user_id ON transaction(user_id);
CREATE INDEX IF NOT EXISTS idx_transaction_status ON transaction(status);
CREATE INDEX IF NOT EXISTS idx_plan_active ON plan(is_active);
CREATE INDEX IF NOT EXISTS idx_channel_active ON channel(is_active);

-- Insert default admin user if not exists
INSERT INTO admin (username, password_hash, is_active)
SELECT 'admin', 'scrypt:32768:8:1$SNGO7bkv1aG9xUBg$bb1e5b5d63b8e6b8a7b8c9d0e1f2g3h4i5j6k7l8m9n0o1p2q3r4s5t6u7v8w9x0y1z2', TRUE
WHERE NOT EXISTS (SELECT 1 FROM admin WHERE username = 'admin');

-- Insert default bot settings if not exists
INSERT INTO bot_settings (notifications_enabled, welcome_message)
SELECT TRUE, 'Welcome to TeleSignals! Use /start to get started.'
WHERE NOT EXISTS (SELECT 1 FROM bot_settings);

-- Insert default payment settings if not exists
INSERT INTO payment_settings (paypal_sandbox)
SELECT TRUE
WHERE NOT EXISTS (SELECT 1 FROM payment_settings);