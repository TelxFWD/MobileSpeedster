
from flask import request, jsonify
from app import app, db
from models import User
import logging

@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    """Handle Telegram webhook updates"""
    try:
        update = request.get_json()
        
        if 'message' in update:
            message = update['message']
            chat_id = str(message['chat']['id'])
            
            # Try to get username
            username = None
            if 'username' in message['from']:
                username = message['from']['username']
            
            # Handle /start command
            if message.get('text', '').startswith('/start'):
                if username:
                    # Update user's chat_id if they exist
                    user = User.query.filter_by(telegram_username=username).first()
                    if user:
                        user.telegram_chat_id = chat_id
                        db.session.commit()
                        
                        # Send welcome message
                        from telegram_bot import send_telegram_message
                        welcome_msg = f"""
🤖 <b>Welcome {username}!</b>

Your account has been linked to this bot.
You'll now receive notifications about your subscriptions here.

<b>Commands:</b>
/status - Check subscription status
/help - Get help
"""
                        send_telegram_message(chat_id, welcome_msg)
                        return jsonify({'status': 'ok'})
                
                # Generic welcome for unregistered users
                from telegram_bot import send_telegram_message
                welcome_msg = """
🤖 <b>Welcome to TeleSignals Bot!</b>

To receive notifications, please register on our website first with your Telegram username, then send /start again.
"""
                send_telegram_message(chat_id, welcome_msg)
            
            # Handle /status command
            elif message.get('text', '').startswith('/status'):
                if username:
                    from telegram_bot import handle_status_command
                    handle_status_command(chat_id, username)
        
        return jsonify({'status': 'ok'})
        
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({'status': 'error'}), 500
