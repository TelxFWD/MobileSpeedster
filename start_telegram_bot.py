#!/usr/bin/env python3
"""
Start Telegram bot in background
"""
import os
import sys
import threading
import logging
import telebot
from telebot import types

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User, Plan, Subscription
from telegram_bot import handle_start_command, handle_status_command

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def start_bot():
    """Start the Telegram bot"""
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not found")
        return
    
    bot = telebot.TeleBot(bot_token)
    logger.info(f"Starting bot polling...")
    
    @bot.message_handler(commands=['start'])
    def handle_start(message):
        """Handle /start command"""
        try:
            chat_id = message.chat.id
            username = message.from_user.username
            
            if not username:
                bot.reply_to(message, "❌ Please set a Telegram username first to use this bot.")
                return
            
            with app.app_context():
                # Check if user exists
                user = User.query.filter_by(telegram_username=username).first()
                
                if user:
                    # Update chat ID
                    user.telegram_chat_id = str(chat_id)
                    try:
                        db.session.commit()
                    except Exception as e:
                        logging.error(f"Error updating chat ID: {e}")
                        db.session.rollback()
                    
                    welcome_text = f"""
🎉 Welcome back to TeleSignals, @{username}!

Your account is active. Use /status to check your subscriptions.

Available commands:
• /start - Show this welcome message
• /status - Check subscription status
• /help - Get help and support

Visit our website to manage subscriptions and browse plans.
"""
                else:
                    welcome_text = f"""
🎉 Welcome to TeleSignals, @{username}!

To get started:
1. Visit our website to create an account
2. Choose a subscription plan
3. Complete payment
4. Start receiving premium signals!

Available commands:
• /start - Show this welcome message  
• /status - Check subscription status
• /help - Get help and support
"""
                
                bot.reply_to(message, welcome_text)
                
        except Exception as e:
            logger.error(f"Error in /start handler: {e}")
            bot.reply_to(message, "❌ An error occurred. Please try again later.")
    
    @bot.message_handler(commands=['status'])
    def handle_status(message):
        """Handle /status command"""
        try:
            chat_id = message.chat.id
            username = message.from_user.username
            
            if not username:
                bot.reply_to(message, "❌ Please set a Telegram username first.")
                return
            
            with app.app_context():
                user = User.query.filter_by(telegram_username=username).first()
                
                if not user:
                    status_text = """
❌ Account not found!

Please visit our website to create an account and purchase a subscription.
"""
                else:
                    # Update chat ID
                    user.telegram_chat_id = str(chat_id)
                    db.session.commit()
                    
                    active_subs = user.get_active_subscriptions()
                    
                    if active_subs:
                        status_text = f"✅ Account Status: Active\n\n📋 Your Active Subscriptions:\n\n"
                        
                        for sub in active_subs:
                            plan = sub.plan
                            days_left = sub.days_remaining()
                            status_text += f"• {plan.name}\n"
                            status_text += f"  Type: {plan.plan_type.title()}\n"
                            status_text += f"  Days remaining: {days_left}\n"
                            status_text += f"  Expires: {sub.end_date.strftime('%Y-%m-%d')}\n\n"
                    else:
                        status_text = """
❌ No Active Subscriptions

Visit our website to browse and purchase subscription plans.
"""
                
                bot.reply_to(message, status_text)
                
        except Exception as e:
            logger.error(f"Error in /status handler: {e}")
            bot.reply_to(message, "❌ An error occurred. Please try again later.")
    
    @bot.message_handler(commands=['help'])
    def handle_help(message):
        """Handle /help command"""
        help_text = """
🆘 TeleSignals Help

Available Commands:
• /start - Welcome message and getting started
• /status - Check your subscription status  
• /help - Show this help message

📞 Need Support?
Visit our website for:
• Account management
• Subscription plans
• Payment options
• Technical support

🔔 Notifications:
You'll receive automatic notifications for:
• New subscription activations
• Subscription renewals
• Expiry warnings
• Important updates
"""
        bot.reply_to(message, help_text)
    
    @bot.message_handler(func=lambda message: True)
    def handle_all_messages(message):
        """Handle all other messages"""
        bot.reply_to(message, """
🤖 TeleSignals Bot

I only respond to commands. Available commands:
• /start - Get started
• /status - Check subscription status
• /help - Get help

For full access to our services, visit our website.
""")
    
    try:
        logger.info("Bot started successfully!")
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        logger.error(f"Bot polling error: {e}")

if __name__ == "__main__":
    start_bot()