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
        
        # Use persistent session name from environment or default
        self.session_name = os.environ.get('TELETHON_SESSION', 'enforcement.session')
        
        # Ensure session directory exists
        self.session_dir = os.path.join(os.getcwd(), 'sessions')
        if not os.path.exists(self.session_dir):
            os.makedirs(self.session_dir, exist_ok=True)
        
        # Full path to session file (without .session extension, Telethon adds it)
        self.session_path = os.path.join(self.session_dir, 'enforcement')
        
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
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            self.engine = create_engine(database_url)
            self.Session = sessionmaker(bind=self.engine)
        else:
            logger.error("DATABASE_URL not found")
            self.engine = None
            self.Session = None
        
        logger.info(f"Enforcement Bot initialized in {'DRY-RUN' if self.dry_run else 'LIVE'} mode")
    
    async def initialize(self):
        """Initialize Telegram client and load configuration"""
        try:
            # Check if credentials are available
            if not self.api_id or not self.api_hash:
                logger.info("Telegram API credentials not configured - bot will remain in standby mode")
                logger.info("Configure credentials in admin panel at /admin/bot-setup to activate enforcement")
                return False
            
            # Convert api_id to int if it's a string
            try:
                api_id = int(self.api_id) if isinstance(self.api_id, str) else self.api_id
            except (ValueError, TypeError):
                logger.error(f"Invalid API ID format: {self.api_id}")
                return False
            
            # Create client with persistent session path
            self.client = TelegramClient(
                self.session_path,
                api_id,
                self.api_hash
            )
            
            # Check if session file exists
            session_file = f"{self.session_path}.session"
            if not os.path.exists(session_file):
                logger.info("No session file found - bot requires authentication first")
                logger.info("Use admin panel at /admin/bot-setup to authenticate the bot")
                return False
            
            # Set proper permissions for session file
            try:
                os.chmod(session_file, 0o600)
                logger.debug("Set session file permissions to 600")
            except Exception as e:
                logger.warning(f"Could not set session file permissions: {e}")
            
            # Try to connect using existing session
            try:
                await self.client.connect()
                logger.info(f"Connected to Telegram using session: {session_file}")
                
                # Check if we're authenticated
                if not await self.client.is_user_authorized():
                    logger.warning("Session expired or invalid - bot requires re-authentication")
                    logger.info("Please use the admin panel to re-authenticate the bot")
                    if self.client:
                        await self.client.disconnect()
                    return False
                
                logger.info("Telegram client connected successfully using existing session")
                
                # Load initial configuration
                await self.sync_channels()
                await self.load_whitelisted_users()
                
                return True
                
            except Exception as conn_error:
                logger.warning(f"Failed to connect with existing session: {conn_error}")
                if self.client:
                    try:
                        await self.client.disconnect()
                    except:
                        pass
                return False
            
        except Exception as e:
            logger.warning(f"Failed to initialize client: {e}")
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
        """Get users with expired subscriptions who should be banned from specific channels"""
        try:
            if not self.Session:
                return []
                
            session = self.Session()
            
            from models import User, Subscription, Plan, PlanChannel, Channel
            from sqlalchemy import and_, or_
            
            # Get users with expired subscriptions
            expired_subscriptions = session.query(Subscription).filter(
                and_(
                    Subscription.end_date < datetime.utcnow(),
                    Subscription.is_paid == True
                )
            ).all()
            
            result = []
            for subscription in expired_subscriptions:
                user = subscription.user
                plan = subscription.plan
                
                if not user.telegram_chat_id or not user.telegram_chat_id.isdigit():
                    continue
                
                user_id = int(user.telegram_chat_id)
                
                if plan.plan_type == 'bundle':
                    # Handle bundle subscriptions - get all channels in the bundle
                    plan_channels = session.query(PlanChannel).filter(
                        PlanChannel.plan_id == plan.id
                    ).all()
                    
                    for plan_channel in plan_channels:
                        channel = plan_channel.channel
                        if channel.is_active and channel.telegram_channel_id:
                            result.append({
                                'user_id': user_id,
                                'username': user.telegram_username,
                                'channel_id': channel.telegram_channel_id,
                                'channel_name': channel.name,
                                'reason': f'Bundle subscription expired: {plan.name}'
                            })
                else:
                    # Handle solo channel subscriptions
                    # For solo plans, check if there's a linked channel
                    plan_channels = session.query(PlanChannel).filter(
                        PlanChannel.plan_id == plan.id
                    ).all()
                    
                    for plan_channel in plan_channels:
                        channel = plan_channel.channel
                        if channel.is_active and channel.telegram_channel_id:
                            result.append({
                                'user_id': user_id,
                                'username': user.telegram_username,
                                'channel_id': channel.telegram_channel_id,
                                'channel_name': channel.name,
                                'reason': f'Solo subscription expired: {plan.name}'
                            })
            
            session.close()
            return result
            
        except Exception as e:
            logger.error(f"Failed to get users to ban: {e}")
            return []
    
    async def get_users_to_unban(self) -> List[Dict]:
        """Get users with active subscriptions who should be unbanned from specific channels"""
        try:
            if not self.Session:
                return []
                
            session = self.Session()
            
            from models import User, Subscription, Plan, PlanChannel, Channel
            from sqlalchemy import and_
            
            # Get users with active subscriptions
            active_subscriptions = session.query(Subscription).filter(
                and_(
                    Subscription.end_date > datetime.utcnow(),
                    Subscription.is_paid == True
                )
            ).all()
            
            result = []
            for subscription in active_subscriptions:
                user = subscription.user
                plan = subscription.plan
                
                if not user.telegram_chat_id or not user.telegram_chat_id.isdigit():
                    continue
                
                user_id = int(user.telegram_chat_id)
                
                if plan.plan_type == 'bundle':
                    # Handle bundle subscriptions - get all channels in the bundle
                    plan_channels = session.query(PlanChannel).filter(
                        PlanChannel.plan_id == plan.id
                    ).all()
                    
                    for plan_channel in plan_channels:
                        channel = plan_channel.channel
                        if channel.is_active and channel.telegram_channel_id:
                            result.append({
                                'user_id': user_id,
                                'username': user.telegram_username,
                                'channel_id': channel.telegram_channel_id,
                                'channel_name': channel.name,
                                'reason': f'Active bundle subscription: {plan.name}'
                            })
                else:
                    # Handle solo channel subscriptions
                    plan_channels = session.query(PlanChannel).filter(
                        PlanChannel.plan_id == plan.id
                    ).all()
                    
                    for plan_channel in plan_channels:
                        channel = plan_channel.channel
                        if channel.is_active and channel.telegram_channel_id:
                            result.append({
                                'user_id': user_id,
                                'username': user.telegram_username,
                                'channel_id': channel.telegram_channel_id,
                                'channel_name': channel.name,
                                'reason': f'Active solo subscription: {plan.name}'
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
        """Single enforcement cycle with bundle-aware channel enforcement"""
        try:
            logger.info("Starting bundle-aware enforcement cycle")
            
            if not self.client:
                logger.warning("Telegram client not available - skipping enforcement")
                return
            
            # Get users to ban and unban based on bundle subscriptions
            users_to_ban = await self.get_users_to_ban()
            users_to_unban = await self.get_users_to_unban()
            
            # Group actions by channel
            channel_ban_actions = {}
            channel_unban_actions = {}
            
            for user_data in users_to_ban:
                channel_id = user_data['channel_id']
                if channel_id not in channel_ban_actions:
                    channel_ban_actions[channel_id] = []
                channel_ban_actions[channel_id].append(user_data)
            
            for user_data in users_to_unban:
                channel_id = user_data['channel_id']
                if channel_id not in channel_unban_actions:
                    channel_unban_actions[channel_id] = []
                channel_unban_actions[channel_id].append(user_data)
            
            # Process each channel with its specific actions
            all_channels = set(list(channel_ban_actions.keys()) + list(channel_unban_actions.keys()))
            
            for channel_id in all_channels:
                try:
                    # Get channel entity
                    channel_entity = await self.client.get_entity(channel_id)
                    logger.info(f"Processing channel: {getattr(channel_entity, 'title', channel_id)}")
                    
                    # Process bans for this channel
                    ban_actions = channel_ban_actions.get(channel_id, [])
                    ban_count = 0
                    for user_data in ban_actions:
                        if user_data['user_id'] not in self.whitelisted_users:
                            success = await self.safe_ban_user(
                                channel_entity, 
                                user_data['user_id'], 
                                user_data['reason']
                            )
                            if success:
                                ban_count += 1
                        else:
                            logger.info(f"Skipping ban for whitelisted user {user_data['user_id']}")
                    
                    # Process unbans for this channel
                    unban_actions = channel_unban_actions.get(channel_id, [])
                    unban_count = 0
                    for user_data in unban_actions:
                        success = await self.safe_unban_user(
                            channel_entity, 
                            user_data['user_id'], 
                            user_data['reason']
                        )
                        if success:
                            unban_count += 1
                    
                    logger.info(f"Channel {channel_id}: {ban_count} bans, {unban_count} unbans")
                    
                    # Rate limiting delay
                    await asyncio.sleep(self.action_delay)
                    
                except Exception as e:
                    logger.error(f"Failed to process channel {channel_id}: {e}")
            
            logger.info("Bundle-aware enforcement cycle completed")
            
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
            # Check if credentials are available before attempting to start
            api_id = os.environ.get('TELEGRAM_API_ID')
            api_hash = os.environ.get('TELEGRAM_API_HASH')
            
            if not api_id or not api_hash:
                logger.info("Enforcement bot: Telegram API credentials not configured - running in standby mode")
                logger.info("Configure credentials at /admin/bot-setup to activate enforcement")
                # Keep the thread alive but don't attempt to connect
                while True:
                    time.sleep(60)  # Check every minute for credentials
                    new_api_id = os.environ.get('TELEGRAM_API_ID')
                    new_api_hash = os.environ.get('TELEGRAM_API_HASH')
                    if new_api_id and new_api_hash:
                        logger.info("Credentials detected, attempting to start enforcement bot")
                        break
            
            asyncio.run(start_enforcement_bot())
        except Exception as e:
            logger.info(f"Enforcement bot in standby mode: {e}")
            logger.info("Configure Telegram API credentials in admin panel to activate")
    
    # Start bot in background thread
    bot_thread = threading.Thread(target=bot_worker, daemon=True)
    bot_thread.start()
    logger.info("Enforcement bot background service started")

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
        from telethon.errors import PhoneNumberInvalidError, ApiIdInvalidError, FloodWaitError
        import asyncio
        import logging
        
        logger.info(f"Initiating Telegram auth for phone: {phone}")
        
        async def send_code():
            client = None
            try:
                # Use the same session directory structure
                session_dir = os.path.join(os.getcwd(), 'sessions')
                if not os.path.exists(session_dir):
                    os.makedirs(session_dir, exist_ok=True)
                
                # Clean up any existing temp sessions
                temp_session_path = os.path.join(session_dir, 'temp_auth')
                session_files = [f'{temp_session_path}.session', f'{temp_session_path}.session-journal']
                for file in session_files:
                    if os.path.exists(file):
                        try:
                            os.remove(file)
                        except:
                            pass
                
                client = TelegramClient(temp_session_path, int(api_id), api_hash)
                await client.connect()
                
                logger.info("Connected to Telegram servers")
                
                if not await client.is_user_authorized():
                    logger.info(f"Sending OTP code to {phone}")
                    result = await client.send_code_request(phone)
                    logger.info("OTP code sent successfully")
                    return {
                        'success': True,
                        'phone_code_hash': result.phone_code_hash
                    }
                else:
                    logger.info("User already authorized")
                    return {
                        'success': True,
                        'phone_code_hash': 'already_authorized'
                    }
                    
            except PhoneNumberInvalidError:
                logger.error(f"Invalid phone number format: {phone}")
                return {
                    'success': False,
                    'error': f"Invalid phone number format. Please use international format (e.g., +1234567890)"
                }
            except ApiIdInvalidError:
                logger.error("Invalid API ID or Hash")
                return {
                    'success': False,
                    'error': "Invalid API ID or Hash. Please check your credentials from my.telegram.org"
                }
            except FloodWaitError as e:
                logger.error(f"Rate limited, wait {e.seconds} seconds")
                return {
                    'success': False,
                    'error': f"Too many requests. Please wait {e.seconds} seconds and try again"
                }
            except Exception as e:
                logger.error(f"Unexpected error during OTP request: {e}")
                return {
                    'success': False,
                    'error': f"Failed to send OTP: {str(e)}"
                }
            finally:
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
        
        # Handle event loop properly for Flask environment
        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Use thread executor for running loop
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, send_code())
                    result = future.result(timeout=30)
            else:
                result = loop.run_until_complete(send_code())
        except RuntimeError:
            # No event loop exists, create new one
            result = asyncio.run(send_code())
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to initiate Telegram auth: {e}")
        return {
            'success': False,
            'error': f"Setup error: {str(e)}"
        }


def complete_telegram_auth(api_id: str, api_hash: str, phone: str, code: str, phone_code_hash: str) -> Dict:
    """Complete Telegram authentication with OTP code"""
    try:
        from telethon import TelegramClient
        import asyncio
        
        async def verify_code():
            client = None
            try:
                # Use same session directory structure
                session_dir = os.path.join(os.getcwd(), 'sessions')
                if not os.path.exists(session_dir):
                    os.makedirs(session_dir, exist_ok=True)
                
                temp_session_path = os.path.join(session_dir, 'temp_auth')
                client = TelegramClient(temp_session_path, int(api_id), api_hash)
                await client.connect()
                
                if phone_code_hash == 'already_authorized':
                    # Move temp session to permanent enforcement session
                    enforcement_session_path = os.path.join(session_dir, 'enforcement')
                    import shutil
                    if os.path.exists(f'{temp_session_path}.session'):
                        shutil.move(f'{temp_session_path}.session', f'{enforcement_session_path}.session')
                        # Set proper permissions
                        os.chmod(f'{enforcement_session_path}.session', 0o600)
                    return {'success': True}
                
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                
                # Authentication successful, move session to permanent location
                enforcement_session_path = os.path.join(session_dir, 'enforcement')
                
                # Disconnect temp client first
                await client.disconnect()
                
                # Move session file to enforcement location
                import shutil
                if os.path.exists(f'{temp_session_path}.session'):
                    shutil.move(f'{temp_session_path}.session', f'{enforcement_session_path}.session')
                    # Set proper permissions for the enforcement session
                    os.chmod(f'{enforcement_session_path}.session', 0o600)
                    logger.info(f"Session created and moved to: {enforcement_session_path}.session")
                
                return {'success': True}
                
            except Exception as e:
                logger.error(f"Authentication verification failed: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }
            finally:
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
        
        # Handle event loop properly for Flask environment
        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Use thread executor for running loop
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, verify_code())
                    result = future.result(timeout=30)
            else:
                result = loop.run_until_complete(verify_code())
        except RuntimeError:
            # No event loop exists, create new one
            result = asyncio.run(verify_code())
        
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