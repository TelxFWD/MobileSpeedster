#!/usr/bin/env python3
"""
Database migration script to add recent columns and ensure schema consistency
"""
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import *
from sqlalchemy import text
import logging

def check_and_add_columns():
    """Check for missing columns and add them"""
    with app.app_context():
        try:
            # Check if telegram_chat_id column exists in user table
            result = db.session.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'user' AND column_name = 'telegram_chat_id'")
            ).fetchone()
            
            if not result:
                logging.info("Adding telegram_chat_id column to user table")
                db.session.execute("ALTER TABLE \"user\" ADD COLUMN telegram_chat_id VARCHAR(32) UNIQUE")
                db.session.commit()
            
            # Check if network column exists in transaction table
            result = db.session.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'transaction' AND column_name = 'network'"
            ).fetchone()
            
            if not result:
                logging.info("Adding network column to transaction table")
                db.session.execute("ALTER TABLE transaction ADD COLUMN network VARCHAR(32)")
                db.session.commit()
            
            # Check if solo pricing columns exist in channel table
            result = db.session.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'channel' AND column_name = 'solo_price'"
            ).fetchone()
            
            if not result:
                logging.info("Adding solo pricing columns to channel table")
                db.session.execute("ALTER TABLE channel ADD COLUMN solo_price FLOAT")
                db.session.execute("ALTER TABLE channel ADD COLUMN solo_duration_days INTEGER")
                db.session.commit()
            
            logging.info("Database schema migration completed successfully")
            
        except Exception as e:
            logging.error(f"Migration error: {e}")
            db.session.rollback()
            raise

def create_sample_data():
    """Create sample data for testing"""
    with app.app_context():
        try:
            # Create sample channels if none exist
            if Channel.query.count() == 0:
                channels = [
                    Channel(
                        name="Forex Signals Pro",
                        description="Premium forex trading signals with 85% accuracy",
                        telegram_link="https://t.me/forexsignalspro",
                        solo_price=29.99,
                        solo_duration_days=30
                    ),
                    Channel(
                        name="Crypto Alerts VIP",
                        description="Exclusive cryptocurrency trading alerts",
                        telegram_link="https://t.me/cryptoalertsvip",
                        solo_price=39.99,
                        solo_duration_days=30
                    ),
                    Channel(
                        name="Stock Market Elite",
                        description="Professional stock market analysis and signals",
                        telegram_link="https://t.me/stockmarketelite",
                        solo_price=49.99,
                        solo_duration_days=30
                    )
                ]
                
                for channel in channels:
                    db.session.add(channel)
                
                logging.info("Created sample channels")
            
            # Create sample plans if none exist
            if Plan.query.count() == 0:
                # Create individual plans for each channel
                channels = Channel.query.all()
                for channel in channels:
                    solo_plan = Plan(
                        name=f"{channel.name} - Solo",
                        description=f"Access to {channel.name} only",
                        plan_type="solo",
                        price=channel.solo_price,
                        duration_days=channel.solo_duration_days
                    )
                    db.session.add(solo_plan)
                    db.session.flush()
                    
                    # Link channel to plan
                    plan_channel = PlanChannel(plan_id=solo_plan.id, channel_id=channel.id)
                    db.session.add(plan_channel)
                
                # Create bundle plans
                bundle_plans = [
                    {
                        "name": "Starter Bundle",
                        "description": "Access to Forex and Crypto channels",
                        "price": 59.99,
                        "duration": 30,
                        "channels": [1, 2]  # First two channels
                    },
                    {
                        "name": "Premium Bundle",
                        "description": "Full access to all trading channels",
                        "price": 99.99,
                        "duration": 30,
                        "channels": [1, 2, 3]  # All channels
                    },
                    {
                        "name": "VIP Quarterly",
                        "description": "3-month access to all premium channels",
                        "price": 249.99,
                        "duration": 90,
                        "channels": [1, 2, 3]
                    }
                ]
                
                for bundle_data in bundle_plans:
                    bundle_plan = Plan(
                        name=bundle_data["name"],
                        description=bundle_data["description"],
                        plan_type="bundle",
                        price=bundle_data["price"],
                        duration_days=bundle_data["duration"],
                        folder_link="https://drive.google.com/folder/premium-resources"
                    )
                    db.session.add(bundle_plan)
                    db.session.flush()
                    
                    # Link channels to bundle
                    for channel_id in bundle_data["channels"]:
                        if channel_id <= len(channels):
                            plan_channel = PlanChannel(plan_id=bundle_plan.id, channel_id=channel_id)
                            db.session.add(plan_channel)
                
                logging.info("Created sample plans")
            
            # Create sample promo codes if none exist
            if PromoCode.query.count() == 0:
                promos = [
                    PromoCode(
                        code="WELCOME20",
                        discount_percent=20.0,
                        usage_limit=100,
                        used_count=0
                    ),
                    PromoCode(
                        code="NEWUSER15",
                        discount_percent=15.0,
                        usage_limit=50,
                        used_count=0
                    ),
                    PromoCode(
                        code="VIP30",
                        discount_percent=30.0,
                        usage_limit=20,
                        used_count=0
                    )
                ]
                
                for promo in promos:
                    db.session.add(promo)
                
                logging.info("Created sample promo codes")
            
            # Ensure bot settings exist
            if not BotSettings.query.first():
                bot_settings = BotSettings(
                    notifications_enabled=True,
                    welcome_message="Welcome to TeleSignals! Use /start to get started with premium trading signals."
                )
                db.session.add(bot_settings)
                logging.info("Created bot settings")
            
            # Ensure payment settings exist
            if not PaymentSettings.query.first():
                payment_settings = PaymentSettings(
                    paypal_sandbox=True
                )
                db.session.add(payment_settings)
                logging.info("Created payment settings")
            
            db.session.commit()
            logging.info("Sample data creation completed successfully")
            
        except Exception as e:
            logging.error(f"Sample data creation error: {e}")
            db.session.rollback()
            raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Starting database migration and setup...")
    
    try:
        check_and_add_columns()
        create_sample_data()
        print("Database migration and setup completed successfully!")
        
        # Display summary
        with app.app_context():
            print(f"\nDatabase Summary:")
            print(f"- Users: {User.query.count()}")
            print(f"- Admins: {Admin.query.count()}")
            print(f"- Channels: {Channel.query.count()}")
            print(f"- Plans: {Plan.query.count()}")
            print(f"- Promo Codes: {PromoCode.query.count()}")
            print(f"- Subscriptions: {Subscription.query.count()}")
            print(f"- Transactions: {Transaction.query.count()}")
            
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)