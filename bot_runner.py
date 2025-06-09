#!/usr/bin/env python3
"""
Telegram Bot Runner for TeleSignals
Handles bot polling, command processing, and user interactions
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime, timedelta

import telebot
from telebot import types

# Add the current directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import Flask app and models
from app import app, db
from models import User, BotSettings, Subscription, Plan
from telegram_bot import (
    send_subscription_notification,
    send_renewal_notification, 
    send_expiry_warning,
    broadcast_message
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TeleSignalsBot:
    def __init__(self):
        self.bot = None
        self.running = False
        self.init_bot()
        
    def init_bot(self):
        """Initialize the Telegram bot"""
        try:
            # Get bot token from environment or database
            bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
            
            if not bot_token:
                with app.app_context():
                    bot_settings = BotSettings.query.first()
                    if bot_settings and bot_settings.bot_token:
                        bot_token = bot_settings.bot_token
            
            if not bot_token:
                logger.error("No Telegram bot token found. Please set TELEGRAM_BOT_TOKEN environment variable or configure in admin settings.")
                return False
                
            self.bot = telebot.TeleBot(bot_token)
            self.setup_handlers()
            logger.info("Telegram bot initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            return False
    
    def setup_handlers(self):
        """Set up message and command handlers"""
        
        @self.bot.message_handler(commands=['start'])
        def handle_start(message):
            """Handle /start command"""
            try:
                chat_id = message.chat.id
                username = message.from_user.username
                
                if not username:
                    self.bot.send_message(
                        chat_id,
                        "❌ You need to set a Telegram username to use this bot.\n\n"
                        "Go to Settings → Edit Profile → Username in Telegram app."
                    )
                    return
                
                logger.info(f"Start command from @{username} (chat_id: {chat_id})")
                
                with app.app_context():
                    # Find or create user
                    user = User.query.filter_by(telegram_username=username).first()
                    
                    if user:
                        # Update chat_id for existing user
                        user.telegram_chat_id = str(chat_id)
                        db.session.commit()
                        
                        # Check for active subscriptions
                        active_subs = user.get_active_subscriptions()
                        if active_subs:
                            sub_info = f"✅ You have {len(active_subs)} active subscription(s)."
                            
                            # Create inline keyboard for subscription details
                            keyboard = types.InlineKeyboardMarkup()
                            keyboard.add(types.InlineKeyboardButton("📊 View Status", callback_data="status"))
                            
                            message_text = f"""
🎉 <b>Welcome back, @{username}!</b>

Your Telegram account has been linked successfully!
{sub_info}

<b>Available Commands:</b>
/status - Check your subscription status
/help - Show help information

Visit our website to manage your subscriptions!
"""
                        else:
                            keyboard = types.InlineKeyboardMarkup()
                            keyboard.add(types.InlineKeyboardButton("🛒 Browse Plans", url="https://your-website.com"))
                            
                            message_text = f"""
🎉 <b>Welcome back, @{username}!</b>

Your account is linked but you don't have any active subscriptions.

<b>Available Commands:</b>
/status - Check your subscription status
/help - Show help information
"""
                    else:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("🚀 Get Started", url="https://your-website.com"))
                        
                        message_text = f"""
👋 <b>Welcome to TeleSignals, @{username}!</b>

To get started:
1. Visit our website and create an account with username: <code>{username}</code>
2. Purchase a subscription plan
3. Return here and use /status to check your subscription

<b>Available Commands:</b>
/status - Check your subscription status
/help - Show help information
"""
                    
                    self.bot.send_message(
                        chat_id, 
                        message_text, 
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                    
            except Exception as e:
                logger.error(f"Error in start command: {e}")
                self.bot.send_message(
                    message.chat.id,
                    "❌ An error occurred. Please try again later."
                )
        
        @self.bot.message_handler(commands=['status'])
        def handle_status(message):
            """Handle /status command"""
            try:
                chat_id = message.chat.id
                username = message.from_user.username
                
                if not username:
                    self.bot.send_message(
                        chat_id,
                        "❌ You need to set a Telegram username to use this bot."
                    )
                    return
                
                logger.info(f"Status command from @{username} (chat_id: {chat_id})")
                
                with app.app_context():
                    user = User.query.filter_by(telegram_username=username).first()
                    
                    if not user:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("📝 Register", url="https://your-website.com"))
                        
                        self.bot.send_message(
                            chat_id,
                            "❌ You are not registered in our system. Please register on our website first.",
                            reply_markup=keyboard
                        )
                        return
                    
                    # Update chat_id if not set
                    if not user.telegram_chat_id:
                        user.telegram_chat_id = str(chat_id)
                        db.session.commit()
                    
                    active_subs = user.get_active_subscriptions()
                    
                    if not active_subs:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("🛒 Browse Plans", url="https://your-website.com"))
                        
                        message_text = """
📊 <b>Subscription Status</b>

❌ No active subscriptions found.

Visit our website to purchase a subscription and get access to premium signals!
"""
                    else:
                        message_text = "📊 <b>Your Active Subscriptions</b>\n\n"
                        
                        for sub in active_subs:
                            days_left = sub.days_remaining()
                            status_emoji = "🟢" if days_left > 7 else "🟡" if days_left > 3 else "🔴"
                            
                            message_text += f"{status_emoji} <b>{sub.plan.name}</b>\n"
                            message_text += f"   ⏰ {days_left} days remaining\n"
                            message_text += f"   📅 Expires: {sub.end_date.strftime('%Y-%m-%d')}\n"
                            
                            # Add channel links for this plan
                            channels = sub.plan.get_channels()
                            if channels:
                                message_text += "   📺 Channels:\n"
                                for ch in channels[:3]:  # Limit to first 3 channels
                                    message_text += f"      • <a href='{ch.telegram_link}'>{ch.name}</a>\n"
                            
                            if sub.plan.folder_link:
                                message_text += f"   📁 <a href='{sub.plan.folder_link}'>Access Folder</a>\n"
                            
                            message_text += "\n"
                        
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(types.InlineKeyboardButton("🔄 Renew", url="https://your-website.com"))
                    
                    self.bot.send_message(
                        chat_id,
                        message_text,
                        parse_mode='HTML',
                        reply_markup=keyboard,
                        disable_web_page_preview=True
                    )
                    
            except Exception as e:
                logger.error(f"Error in status command: {e}")
                self.bot.send_message(
                    message.chat.id,
                    "❌ Error retrieving status. Please try again later."
                )
        
        @self.bot.message_handler(commands=['help'])
        def handle_help(message):
            """Handle /help command"""
            help_text = """
🤖 <b>TeleSignals Bot Commands</b>

/start - Initialize your account and link with Telegram
/status - Check your subscription status and access channels
/help - Show this help message

<b>How to use:</b>
1. Use /start to link your Telegram account
2. Visit our website to purchase subscriptions
3. Use /status to access your channels and check expiry dates

<b>Need support?</b>
Contact our support team through the website.
"""
            
            self.bot.send_message(
                message.chat.id,
                help_text,
                parse_mode='HTML'
            )
        
        @self.bot.callback_query_handler(func=lambda call: True)
        def handle_callback_query(call):
            """Handle inline keyboard callbacks"""
            try:
                if call.data == "status":
                    # Simulate status command
                    message = type('obj', (object,), {
                        'chat': type('obj', (object,), {'id': call.message.chat.id})(),
                        'from_user': call.from_user
                    })()
                    handle_status(message)
                    
                self.bot.answer_callback_query(call.id)
                
            except Exception as e:
                logger.error(f"Error in callback query: {e}")
                self.bot.answer_callback_query(call.id, "❌ Error occurred")
        
        @self.bot.message_handler(func=lambda message: True)
        def handle_all_messages(message):
            """Handle all other messages"""
            username = message.from_user.username or "User"
            
            response = f"""
Hello @{username}! 👋

I'm the TeleSignals bot. Here are the available commands:

/start - Link your account
/status - Check subscription status  
/help - Show help information

Type any command to get started!
"""
            
            self.bot.send_message(
                message.chat.id,
                response,
                parse_mode='HTML'
            )
    
    def start_polling(self):
        """Start bot polling"""
        if not self.bot:
            logger.error("Bot not initialized")
            return False
        
        self.running = True
        logger.info("Starting Telegram bot polling...")
        
        try:
            # Test bot connection
            bot_info = self.bot.get_me()
            logger.info(f"Bot connected: @{bot_info.username}")
            
            # Start polling with error handling
            while self.running:
                try:
                    self.bot.polling(
                        none_stop=False,
                        interval=2,
                        timeout=20,
                        long_polling_timeout=15
                    )
                except Exception as e:
                    logger.error(f"Polling error: {e}")
                    if self.running:
                        logger.info("Retrying in 5 seconds...")
                        time.sleep(5)
                    
        except Exception as e:
            logger.error(f"Failed to start polling: {e}")
            return False
        
        logger.info("Bot polling stopped")
        return True
    
    def stop_polling(self):
        """Stop bot polling"""
        self.running = False
        if self.bot:
            self.bot.stop_polling()
        logger.info("Bot polling stopped")
    
    def send_message(self, chat_id, text, parse_mode='HTML'):
        """Send message to specific chat"""
        try:
            if self.bot:
                self.bot.send_message(chat_id, text, parse_mode=parse_mode)
                return True
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
        return False

# Global bot instance
telegram_bot = TeleSignalsBot()

def run_bot():
    """Run the bot in polling mode"""
    telegram_bot.start_polling()

def send_telegram_message(chat_id, message, parse_mode='HTML'):
    """Send a message via the bot (used by telegram_bot.py functions)"""
    return telegram_bot.send_message(chat_id, message, parse_mode)

if __name__ == "__main__":
    print("Starting TeleSignals Bot...")
    run_bot()