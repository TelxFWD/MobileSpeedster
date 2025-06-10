"""
TeleSignals Enforcement Bot
Advanced backend bot with auto-ban/unban capabilities and safety features
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from telethon import TelegramClient, errors
from telethon.tl.types import User, Channel, Chat
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('enforcement_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class EnforcementBot:
    """Advanced Telegram enforcement bot with safety features"""
    
    def __init__(self):
        self.api_id = os.environ.get('TELEGRAM_API_ID')
        self.api_hash = os.environ.get('TELEGRAM_API_HASH')
        self.bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.phone = os.environ.get('TELEGRAM_PHONE')
        self.session_name = 'enforcement_bot'
        
        # Safety configuration
        self.dry_run = os.environ.get('BOT_MODE', 'dry-run') == 'dry-run'
        self.max_actions_per_minute = 20
        self.action_delay = 3  # seconds between actions
        self.scan_interval = 300  # 5 minutes
        
        # Rate limiting
        self.last_action_time = 0
        self.actions_this_minute = 0
        self.minute_start = time.time()
        
        # Tracking
        self.managed_channels: Set[str] = set()
        self.whitelisted_users: Set[int] = set()
        self.client: Optional[TelegramClient] = None
        self.running = False
        
        # Database connection
        self.engine = create_engine(os.environ.get('DATABASE_URL'))
        self.Session = sessionmaker(bind=self.engine)
        
        logger.info(f"Enforcement Bot initialized in {'DRY-RUN' if self.dry_run else 'LIVE'} mode")
    
    async def initialize(self):
        """Initialize Telegram client and load configuration"""
        try:
            self.client = TelegramClient(
                self.session_name,
                self.api_id,
                self.api_hash
            )
            
            await self.client.start(phone=self.phone)
            logger.info("Telegram client connected successfully")
            
            # Load initial configuration
            await self.sync_channels()
            await self.load_whitelisted_users()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize client: {e}")
            return False
    
    async def sync_channels(self):
        """Auto-sync channels from database"""
        try:
            session = self.Session()
            
            # Import here to avoid circular imports
            from models import Channel
            
            active_channels = session.query(Channel).filter(
                Channel.is_active == True,
                Channel.telegram_link.isnot(None)
            ).all()
            
            new_channels = set()
            for channel in active_channels:
                # Extract channel identifier from telegram_link
                if 't.me/' in channel.telegram_link:
                    channel_id = channel.telegram_link.split('t.me/')[-1]
                    new_channels.add(channel_id)
            
            old_count = len(self.managed_channels)
            self.managed_channels = new_channels
            new_count = len(self.managed_channels)
            
            logger.info(f"Channel sync complete: {old_count} -> {new_count} channels")
            session.close()
            
        except Exception as e:
            logger.error(f"Failed to sync channels: {e}")
    
    async def load_whitelisted_users(self):
        """Load whitelisted users from database"""
        try:
            session = self.Session()
            
            # Import here to avoid circular imports
            from models import User
            
            # Load admin users and other whitelisted users
            # You can add a whitelist field to User model or create separate table
            whitelisted = session.query(User).filter(
                User.is_active == True,
                User.is_banned == False
            ).all()
            
            self.whitelisted_users = {
                int(user.telegram_chat_id) for user in whitelisted 
                if user.telegram_chat_id and user.telegram_chat_id.isdigit()
            }
            
            logger.info(f"Loaded {len(self.whitelisted_users)} whitelisted users")
            session.close()
            
        except Exception as e:
            logger.error(f"Failed to load whitelisted users: {e}")
    
    async def rate_limit_check(self):
        """Check and enforce rate limiting"""
        current_time = time.time()
        
        # Reset counter every minute
        if current_time - self.minute_start >= 60:
            self.actions_this_minute = 0
            self.minute_start = current_time
        
        # Check if we've hit the limit
        if self.actions_this_minute >= self.max_actions_per_minute:
            wait_time = 60 - (current_time - self.minute_start)
            logger.warning(f"Rate limit reached, waiting {wait_time:.1f} seconds")
            await asyncio.sleep(wait_time)
            self.actions_this_minute = 0
            self.minute_start = time.time()
        
        # Enforce delay between actions
        time_since_last = current_time - self.last_action_time
        if time_since_last < self.action_delay:
            await asyncio.sleep(self.action_delay - time_since_last)
        
        self.last_action_time = time.time()
        self.actions_this_minute += 1
    
    async def safe_ban_user(self, channel_entity, user_id: int, reason: str = "Subscription expired") -> bool:
        """Safely ban user with error handling"""
        try:
            await self.rate_limit_check()
            
            if user_id in self.whitelisted_users:
                logger.info(f"Skipping ban for whitelisted user {user_id}")
                return False
            
            if self.dry_run:
                logger.info(f"DRY-RUN: Would ban user {user_id} from channel {channel_entity.id} - {reason}")
                return True
            
            await self.client.edit_permissions(
                channel_entity,
                user_id,
                view_messages=False
            )
            
            logger.info(f"Banned user {user_id} from channel {channel_entity.id} - {reason}")
            await self.log_action("ban", user_id, channel_entity.id, reason)
            return True
            
        except errors.FloodWaitError as e:
            logger.warning(f"Flood wait error: sleeping for {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
            return False
            
        except errors.PeerFloodError:
            logger.warning("Peer flood error: backing off for 60 seconds")
            await asyncio.sleep(60)
            return False
            
        except errors.UserNotParticipantError:
            logger.info(f"User {user_id} not in channel {channel_entity.id}")
            return False
            
        except Exception as e:
            logger.error(f"Failed to ban user {user_id}: {e}")
            return False
    
    async def safe_unban_user(self, channel_entity, user_id: int, reason: str = "Subscription renewed") -> bool:
        """Safely unban user with error handling"""
        try:
            await self.rate_limit_check()
            
            if self.dry_run:
                logger.info(f"DRY-RUN: Would unban user {user_id} from channel {channel_entity.id} - {reason}")
                return True
            
            await self.client.edit_permissions(
                channel_entity,
                user_id,
                view_messages=True
            )
            
            logger.info(f"Unbanned user {user_id} from channel {channel_entity.id} - {reason}")
            await self.log_action("unban", user_id, channel_entity.id, reason)
            return True
            
        except errors.FloodWaitError as e:
            logger.warning(f"Flood wait error: sleeping for {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
            return False
            
        except errors.PeerFloodError:
            logger.warning("Peer flood error: backing off for 60 seconds")
            await asyncio.sleep(60)
            return False
            
        except Exception as e:
            logger.error(f"Failed to unban user {user_id}: {e}")
            return False
    
    async def log_action(self, action_type: str, user_id: int, channel_id: int, reason: str):
        """Log bot actions to database"""
        try:
            session = self.Session()
            
            # Create BotLog entry if table exists
            try:
                from models import BotLog
                log_entry = BotLog(
                    action_type=action_type,
                    user_id=user_id,
                    channel_id=channel_id,
                    reason=reason,
                    timestamp=datetime.utcnow(),
                    dry_run=self.dry_run
                )
                session.add(log_entry)
                session.commit()
            except ImportError:
                # BotLog table doesn't exist yet
                pass
            
            session.close()
            
        except Exception as e:
            logger.error(f"Failed to log action: {e}")
    
    async def get_users_to_ban(self) -> List[Dict]:
        """Get users with expired subscriptions who should be banned"""
        try:
            session = self.Session()
            
            from models import User, Subscription
            from sqlalchemy import and_, or_
            
            # Users with expired subscriptions or no active subscriptions
            expired_users = session.query(User).outerjoin(Subscription).filter(
                and_(
                    User.is_active == True,
                    User.is_banned == False,
                    User.telegram_chat_id.isnot(None),
                    or_(
                        Subscription.id.is_(None),  # No subscriptions
                        and_(
                            Subscription.end_date < datetime.utcnow(),
                            Subscription.is_paid == True
                        )  # Expired paid subscriptions
                    )
                )
            ).distinct().all()
            
            result = []
            for user in expired_users:
                if user.telegram_chat_id and user.telegram_chat_id.isdigit():
                    result.append({
                        'user_id': int(user.telegram_chat_id),
                        'username': user.telegram_username,
                        'reason': 'Subscription expired or missing'
                    })
            
            session.close()
            return result
            
        except Exception as e:
            logger.error(f"Failed to get users to ban: {e}")
            return []
    
    async def get_users_to_unban(self) -> List[Dict]:
        """Get users with active subscriptions who should be unbanned"""
        try:
            session = self.Session()
            
            from models import User, Subscription
            from sqlalchemy import and_
            
            # Users with active subscriptions who might be banned
            active_users = session.query(User).join(Subscription).filter(
                and_(
                    User.is_active == True,
                    User.telegram_chat_id.isnot(None),
                    Subscription.end_date > datetime.utcnow(),
                    Subscription.is_paid == True
                )
            ).distinct().all()
            
            result = []
            for user in active_users:
                if user.telegram_chat_id and user.telegram_chat_id.isdigit():
                    result.append({
                        'user_id': int(user.telegram_chat_id),
                        'username': user.telegram_username,
                        'reason': 'Active subscription found'
                    })
            
            session.close()
            return result
            
        except Exception as e:
            logger.error(f"Failed to get users to unban: {e}")
            return []
    
    async def enforce_channel(self, channel_id: str):
        """Enforce subscription rules for a specific channel"""
        try:
            # Get channel entity
            try:
                channel_entity = await self.client.get_entity(channel_id)
            except Exception as e:
                logger.error(f"Failed to get channel entity for {channel_id}: {e}")
                return
            
            logger.info(f"Enforcing rules for channel: {channel_entity.title} ({channel_id})")
            
            # Get users to ban and unban
            users_to_ban = await self.get_users_to_ban()
            users_to_unban = await self.get_users_to_unban()
            
            # Process bans
            ban_count = 0
            for user_data in users_to_ban:
                success = await self.safe_ban_user(
                    channel_entity, 
                    user_data['user_id'], 
                    user_data['reason']
                )
                if success:
                    ban_count += 1
            
            # Process unbans
            unban_count = 0
            for user_data in users_to_unban:
                success = await self.safe_unban_user(
                    channel_entity, 
                    user_data['user_id'], 
                    user_data['reason']
                )
                if success:
                    unban_count += 1
            
            logger.info(f"Channel {channel_id}: {ban_count} bans, {unban_count} unbans")
            
        except Exception as e:
            logger.error(f"Failed to enforce channel {channel_id}: {e}")
    
    async def enforcement_cycle(self):
        """Single enforcement cycle across all channels"""
        try:
            logger.info("Starting enforcement cycle")
            
            # Sync channels and whitelist
            await self.sync_channels()
            await self.load_whitelisted_users()
            
            # Process each channel
            for channel_id in self.managed_channels:
                await self.enforce_channel(channel_id)
                
                # Small delay between channels
                await asyncio.sleep(2)
            
            logger.info("Enforcement cycle completed")
            
        except Exception as e:
            logger.error(f"Enforcement cycle failed: {e}")
    
    async def run(self):
        """Main bot loop"""
        self.running = True
        logger.info("Enforcement bot started")
        
        while self.running:
            try:
                await self.enforcement_cycle()
                
                # Wait for next cycle
                logger.info(f"Waiting {self.scan_interval} seconds until next cycle")
                await asyncio.sleep(self.scan_interval)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying
    
    async def stop(self):
        """Stop the bot gracefully"""
        self.running = False
        if self.client:
            await self.client.disconnect()
        logger.info("Enforcement bot stopped")
    
    async def manual_ban_user(self, user_id: int, reason: str = "Manual ban") -> Dict:
        """Manually ban user from all channels"""
        results = []
        
        for channel_id in self.managed_channels:
            try:
                channel_entity = await self.client.get_entity(channel_id)
                success = await self.safe_ban_user(channel_entity, user_id, reason)
                results.append({
                    'channel': channel_entity.title,
                    'channel_id': channel_id,
                    'success': success
                })
            except Exception as e:
                results.append({
                    'channel': channel_id,
                    'channel_id': channel_id,
                    'success': False,
                    'error': str(e)
                })
        
        return {
            'user_id': user_id,
            'total_channels': len(self.managed_channels),
            'successful_bans': sum(1 for r in results if r['success']),
            'results': results
        }
    
    async def manual_unban_user(self, user_id: int, reason: str = "Manual unban") -> Dict:
        """Manually unban user from all channels"""
        results = []
        
        for channel_id in self.managed_channels:
            try:
                channel_entity = await self.client.get_entity(channel_id)
                success = await self.safe_unban_user(channel_entity, user_id, reason)
                results.append({
                    'channel': channel_entity.title,
                    'channel_id': channel_id,
                    'success': success
                })
            except Exception as e:
                results.append({
                    'channel': channel_id,
                    'channel_id': channel_id,
                    'success': False,
                    'error': str(e)
                })
        
        return {
            'user_id': user_id,
            'total_channels': len(self.managed_channels),
            'successful_unbans': sum(1 for r in results if r['success']),
            'results': results
        }

# Global bot instance
enforcement_bot = None

async def start_enforcement_bot():
    """Start the enforcement bot"""
    global enforcement_bot
    
    try:
        enforcement_bot = EnforcementBot()
        
        if await enforcement_bot.initialize():
            await enforcement_bot.run()
        else:
            logger.error("Failed to initialize enforcement bot")
            
    except Exception as e:
        logger.error(f"Enforcement bot crashed: {e}")

def run_enforcement_bot_background():
    """Run enforcement bot in background thread"""
    def bot_worker():
        try:
            asyncio.run(start_enforcement_bot())
        except Exception as e:
            logger.error(f"Background bot worker failed: {e}")
    
    # Start bot in background thread
    bot_thread = threading.Thread(target=bot_worker, daemon=True)
    bot_thread.start()
    logger.info("Enforcement bot started in background")

async def get_enforcement_bot():
    """Get the global enforcement bot instance"""
    global enforcement_bot
    return enforcement_bot

# Utility functions for admin panel
async def admin_ban_user(user_id: int, reason: str = "Admin action") -> Dict:
    """Admin function to ban user from all channels"""
    bot = await get_enforcement_bot()
    if bot and bot.client:
        return await bot.manual_ban_user(user_id, reason)
    else:
        return {'error': 'Enforcement bot not available'}

async def admin_unban_user(user_id: int, reason: str = "Admin action") -> Dict:
    """Admin function to unban user from all channels"""
    bot = await get_enforcement_bot()
    if bot and bot.client:
        return await bot.manual_unban_user(user_id, reason)
    else:
        return {'error': 'Enforcement bot not available'}


def initiate_telegram_auth(api_id: str, api_hash: str, phone: str) -> Dict:
    """Initiate Telegram authentication and send OTP"""
    try:
        from telethon import TelegramClient
        import asyncio
        
        async def send_code():
            client = TelegramClient('temp_session', int(api_id), api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                result = await client.send_code_request(phone)
                await client.disconnect()
                return {
                    'success': True,
                    'phone_code_hash': result.phone_code_hash
                }
            else:
                await client.disconnect()
                return {
                    'success': True,
                    'phone_code_hash': 'already_authorized'
                }
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(send_code())
        loop.close()
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to initiate Telegram auth: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def complete_telegram_auth(api_id: str, api_hash: str, phone: str, code: str, phone_code_hash: str) -> Dict:
    """Complete Telegram authentication with OTP code"""
    try:
        from telethon import TelegramClient
        import asyncio
        
        async def verify_code():
            client = TelegramClient('temp_session', int(api_id), api_hash)
            await client.connect()
            
            if phone_code_hash == 'already_authorized':
                await client.disconnect()
                return {'success': True}
            
            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                await client.disconnect()
                return {'success': True}
            except Exception as e:
                await client.disconnect()
                return {
                    'success': False,
                    'error': str(e)
                }
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(verify_code())
        loop.close()
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to complete Telegram auth: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def restart_enforcement_bot() -> Dict:
    """Restart the enforcement bot with new credentials"""
    try:
        global enforcement_bot
        
        # Stop existing bot if running
        if enforcement_bot:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(enforcement_bot.stop())
            loop.close()
            enforcement_bot = None
        
        # Start new bot instance
        import threading
        def start_new_bot():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(start_enforcement_bot())
            
        bot_thread = threading.Thread(target=start_new_bot, daemon=True)
        bot_thread.start()
        
        logger.info("Enforcement bot restarted successfully")
        return {'success': True}
        
    except Exception as e:
        logger.error(f"Failed to restart enforcement bot: {e}")
        return {
            'success': False,
            'error': str(e)
        }