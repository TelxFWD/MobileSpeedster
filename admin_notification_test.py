#!/usr/bin/env python3
"""
Admin tool to test notifications manually
"""
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User, Plan, Subscription, BotSettings
from telegram_bot import send_subscription_notification, send_telegram_message
from datetime import datetime, timedelta

def send_test_notification():
    """Send test notification to specific user"""
    with app.app_context():
        username = input("Enter Telegram username (without @): ").strip()
        if not username:
            print("Username required")
            return
        
        user = User.query.filter_by(telegram_username=username).first()
        if not user:
            print(f"User {username} not found")
            return
        
        if not user.telegram_chat_id:
            print(f"User {username} has no chat_id. They need to start the bot first.")
            return
        
        # List available plans
        plans = Plan.query.filter_by(is_active=True).all()
        if not plans:
            print("No active plans found")
            return
        
        print("\nAvailable plans:")
        for i, plan in enumerate(plans, 1):
            print(f"{i}. {plan.name} ({plan.plan_type}) - ${plan.price}")
        
        try:
            choice = int(input("\nSelect plan number: ")) - 1
            if choice < 0 or choice >= len(plans):
                print("Invalid choice")
                return
            
            selected_plan = plans[choice]
            
            # Send notification
            result = send_subscription_notification(user, selected_plan)
            if result:
                print(f"✅ Test notification sent successfully to @{username}")
            else:
                print(f"❌ Failed to send notification to @{username}")
                
        except ValueError:
            print("Invalid input")

def create_test_subscription():
    """Create a test subscription and send notification"""
    with app.app_context():
        username = input("Enter Telegram username (without @): ").strip()
        if not username:
            print("Username required")
            return
        
        user = User.query.filter_by(telegram_username=username).first()
        if not user:
            # Create user if doesn't exist
            user = User(telegram_username=username)
            user.set_pin('0000')
            # Set chat_id from logs (you'll need to update this)
            user.telegram_chat_id = '7764733376'  # Update with actual chat_id
            db.session.add(user)
            db.session.flush()
            print(f"Created new user: {username}")
        
        # Get plan
        plans = Plan.query.filter_by(is_active=True).all()
        if not plans:
            print("No active plans found")
            return
        
        print("\nAvailable plans:")
        for i, plan in enumerate(plans, 1):
            print(f"{i}. {plan.name} ({plan.plan_type}) - ${plan.price}")
        
        try:
            choice = int(input("\nSelect plan number: ")) - 1
            selected_plan = plans[choice]
            
            # Create subscription
            subscription = Subscription(
                user_id=user.id,
                plan_id=selected_plan.id,
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow() + timedelta(days=selected_plan.duration_days),
                is_paid=True
            )
            db.session.add(subscription)
            db.session.commit()
            
            # Send notification
            result = send_subscription_notification(user, selected_plan)
            if result:
                print(f"✅ Subscription created and notification sent to @{username}")
            else:
                print(f"✅ Subscription created but notification failed for @{username}")
                
        except ValueError:
            print("Invalid input")
        except Exception as e:
            print(f"Error: {e}")
            db.session.rollback()

if __name__ == "__main__":
    print("Telegram Notification Test Tool")
    print("1. Send test notification")
    print("2. Create test subscription with notification")
    
    choice = input("\nSelect option (1 or 2): ").strip()
    
    if choice == "1":
        send_test_notification()
    elif choice == "2":
        create_test_subscription()
    else:
        print("Invalid choice")