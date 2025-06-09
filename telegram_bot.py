import os
import logging
from models import BotSettings, User, Plan
import requests
import json

def get_bot_token():
    """Get bot token from settings"""
    bot_settings = BotSettings.query.first()
    if bot_settings and bot_settings.bot_token:
        return bot_settings.bot_token
    return os.environ.get('TELEGRAM_BOT_TOKEN')

def send_telegram_message(chat_id, message, parse_mode='HTML'):
    """Send message via Telegram Bot API"""
    try:
        token = get_bot_token()
        if not token:
            logging.error("No Telegram bot token configured")
            return False
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': parse_mode
        }
        
        response = requests.post(url, json=data)
        return response.status_code == 200
        
    except Exception as e:
        logging.error(f"Telegram message send error: {e}")
        return False

def get_user_chat_id(telegram_username):
    """Get user's chat ID by username"""
    from app import db
    from models import User
    
    user = User.query.filter_by(telegram_username=telegram_username).first()
    if user and hasattr(user, 'telegram_chat_id') and user.telegram_chat_id:
        return user.telegram_chat_id
    
    # If no chat_id stored, we can't send messages
    logging.warning(f"No chat_id found for user {telegram_username}")
    return None

def send_subscription_notification(user, plan):
    """Send subscription activation notification"""
    try:
        bot_settings = BotSettings.query.first()
        if not bot_settings or not bot_settings.notifications_enabled:
            return False
        
        chat_id = get_user_chat_id(user.telegram_username)
        if not chat_id:
            logging.warning(f"Cannot send notification to {user.telegram_username}: no chat_id")
            return False
        
        # Get channels for the plan
        channels = plan.get_channels()
        channel_links = "\n".join([f"• <a href='{ch.telegram_link}'>{ch.name}</a>" 
                                  for ch in channels])
        
        message = f"""
🎉 <b>Subscription Activated!</b>

Hello @{user.telegram_username}!

Your <b>{plan.name}</b> subscription is now active!

<b>📅 Duration:</b> {plan.duration_days} days
<b>💰 Plan Type:</b> {plan.plan_type.title()}

<b>📺 Your Channels:</b>
{channel_links}
"""
        
        if plan.folder_link:
            message += f"\n<b>📁 Folder Link:</b> <a href='{plan.folder_link}'>Access Folder</a>"
        
        message += f"""

<b>🔗 Dashboard:</b> Access your dashboard at our website
<b>⏰ Expiry:</b> Check your dashboard for exact expiry date

Thank you for subscribing! 🚀
"""
        
        return send_telegram_message(chat_id, message)
        
    except Exception as e:
        logging.error(f"Subscription notification error: {e}")
        return False

def send_renewal_notification(user, plan):
    """Send subscription renewal notification"""
    try:
        chat_id = get_user_chat_id(user.telegram_username)
        
        message = f"""
🔄 <b>Subscription Renewed!</b>

Hello @{user.telegram_username}!

Your <b>{plan.name}</b> subscription has been renewed!

<b>📅 Extended by:</b> {plan.duration_days} days
<b>🔗 Dashboard:</b> Check your dashboard for updated expiry date

Thank you for your continued support! 🌟
"""
        
        return send_telegram_message(chat_id, message)
        
    except Exception as e:
        logging.error(f"Renewal notification error: {e}")
        return False

def send_expiry_warning(user, subscription):
    """Send subscription expiry warning"""
    try:
        chat_id = get_user_chat_id(user.telegram_username)
        days_remaining = subscription.days_remaining()
        
        message = f"""
⚠️ <b>Subscription Expiring Soon!</b>

Hello @{user.telegram_username}!

Your <b>{subscription.plan.name}</b> subscription will expire in <b>{days_remaining} day(s)</b>!

<b>🔄 Renew Now:</b> Visit our website to renew your subscription
<b>🔗 Dashboard:</b> Access your dashboard to manage subscriptions

Don't miss out on your signals! 📈
"""
        
        return send_telegram_message(chat_id, message)
        
    except Exception as e:
        logging.error(f"Expiry warning error: {e}")
        return False

def broadcast_message(message, user_filter=None):
    """Broadcast message to users"""
    try:
        from app import db
        
        query = User.query.filter_by(is_active=True, is_banned=False)
        if user_filter:
            # Apply additional filters if needed
            pass
        
        users = query.all()
        success_count = 0
        
        for user in users:
            if send_telegram_message(get_user_chat_id(user.telegram_username), message):
                success_count += 1
        
        logging.info(f"Broadcast sent to {success_count}/{len(users)} users")
        return success_count
        
    except Exception as e:
        logging.error(f"Broadcast error: {e}")
        return 0

# Bot command handlers (if implementing a full bot)
def handle_start_command(chat_id, username):
    """Handle /start command"""
    welcome_message = """
🤖 <b>Welcome to Telegram Signals Bot!</b>

This bot will send you notifications about your subscriptions.

<b>Commands:</b>
/start - Show this welcome message
/status - Check your subscription status
/help - Get help

Visit our website to subscribe to premium signals! 📈
"""
    
    # Store chat_id for this user
    # In production, you'd save this to database
    
    return send_telegram_message(chat_id, welcome_message)

def handle_status_command(chat_id, username):
    """Handle /status command"""
    try:
        from app import db
        
        user = User.query.filter_by(telegram_username=username).first()
        if not user:
            message = """
❌ <b>No Account Found</b>

You don't have an active account. Please visit our website to subscribe!
"""
        else:
            active_subs = user.get_active_subscriptions()
            if active_subs:
                sub_list = []
                for sub in active_subs:
                    sub_list.append(f"• <b>{sub.plan.name}</b> - {sub.days_remaining()} days remaining")
                
                message = f"""
✅ <b>Active Subscriptions</b>

{chr(10).join(sub_list)}

Visit your dashboard for more details!
"""
            else:
                message = """
⏰ <b>No Active Subscriptions</b>

You don't have any active subscriptions. Visit our website to subscribe!
"""
        
        return send_telegram_message(chat_id, message)
        
    except Exception as e:
        logging.error(f"Status command error: {e}")
        return False
