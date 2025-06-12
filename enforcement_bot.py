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
        # Load credentials from database or fall back to environment
        self.db_settings = None
        self.load_credentials_from_db()
        
        # Ensure session directory exists
        self.session_dir = os.path.join(os.getcwd(), 'sessions')
        if not os.path.exists(self.session_dir):
            os.makedirs(self.session_dir, exist_ok=True)
        
        # Full path to session file (without .session extension, Telethon adds it)
        self.session_path = os.path.join(self.session_dir, 'enforcement')
    
    def load_credentials_from_db(self):
        """Load credentials from database settings"""
        try:
            from app import app, db
            from models import BotSettings
            
            with app.app_context():
                settings = BotSettings.get_settings()
                self.db_settings = settings
                
                # Use database credentials if available, otherwise fall back to environment
                self.api_id = settings.api_id or os.environ.get('TELEGRAM_API_ID')
                self.api_hash = settings.api_hash or os.environ.get('TELEGRAM_API_HASH')
                self.bot_token = settings.bot_token or os.environ.get('TELEGRAM_BOT_TOKEN')
                self.phone = settings.phone_number or os.environ.get('TELEGRAM_PHONE')
                
                logger.info(f"Loaded credentials from database: API ID: {bool(self.api_id)}, API Hash: {bool(self.api_hash)}, Bot Token: {bool(self.bot_token)}")
                
        except Exception as e:
            logger.warning(f"Failed to load credentials from database: {e}")
            # Fall back to environment variables
            self.api_id = os.environ.get('TELEGRAM_API_ID')
            self.api_hash = os.environ.get('TELEGRAM_API_HASH')
            self.bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
            self.phone = os.environ.get('TELEGRAM_PHONE')
        
        # Safety configuration
        self.dry_run = os.environ.get('BOT_MODE', 'live') == 'dry-run'
        self.max_actions_per_minute = 20
        self.action_delay = 3  # seconds between actions
        self.scan_interval = 300  # 5 minutes
        
        # Rate limiting
        self.last_action_time = 0
        self.actions_this_minute = 0
        self.minute_start = time.time()
        
        # Tracking
        self.managed_channels: Dict[str, Dict] = {}
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
            
            # Only sync channels that have telegram_channel_id configured
            active_channels = session.query(Channel).filter(
                Channel.is_active == True,
                Channel.telegram_channel_id.isnot(None),
                Channel.telegram_channel_id != ''
            ).all()
            
            new_channels = {}
            for channel in active_channels:
                # Use the configured telegram_channel_id for enforcement
                channel_id = channel.telegram_channel_id.strip()
                if channel_id:
                    # Store both the ID and channel name for reference
                    new_channels[channel_id] = {
                        'name': channel.name,
                        'db_id': channel.id
                    }
            
            old_count = len(self.managed_channels)
            self.managed_channels = new_channels
            new_count = len(self.managed_channels)
            
            logger.info(f"Channel sync complete: {old_count} -> {new_count} channels")
            if new_count > 0:
                logger.info(f"Managing channels: {list(new_channels.keys())}")
            else:
                logger.warning("No channels configured with telegram_channel_id - enforcement bot will be idle")
            
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
    
    async def enforce_unauthorized_users(self, channel_entity, channel_id: int, authorized_user_ids: set) -> tuple[int, int]:
        """Ban all unauthorized users currently in the channel"""
        bans = 0
        errors = 0
        
        try:
            # Get bot's own user ID to avoid self-ban
            me = await self.client.get_me()
            bot_user_id = me.id
            
            # Iterate through all channel participants
            async for participant in self.client.iter_participants(channel_entity):
                # Skip bots
                if participant.bot:
                    continue
                    
                # Skip channel admins and creators
                if hasattr(participant, 'participant'):
                    if hasattr(participant.participant, 'admin_rights') or \
                       hasattr(participant.participant, 'creator'):
                        continue
                
                user_id = participant.id
                
                # Skip bot itself
                if user_id == bot_user_id:
                    continue
                
                # Skip whitelisted users
                if user_id in self.whitelisted_users:
                    continue
                    
                # Skip authorized users for this channel
                if user_id in authorized_user_ids:
                    continue
                
                # User is unauthorized - ban them
                if await self.rate_limit_check():
                    success = await self.safe_ban_user(
                        channel_entity, 
                        user_id, 
                        "Unauthorized access - no active subscription"
                    )
                    if success:
                        bans += 1
                    else:
                        errors += 1
                else:
                    # Rate limit hit, skip remaining users for this channel
                    logger.warning(f"Rate limit reached, skipping remaining users in channel")
                    break
                    
        except Exception as e:
            logger.error(f"Error enforcing unauthorized users in channel {channel_id}: {e}")
            errors += 1
            
        return bans, errors

    async def enforcement_cycle(self):
        """Enhanced enforcement cycle with comprehensive subscription management"""
        try:
            logger.info("Starting enhanced enforcement cycle")
            
            if not self.client:
                logger.warning("Telegram client not available - skipping enforcement")
                return
            
            # Refresh channel list from database
            await self.sync_channels()
            
            if not self.managed_channels:
                logger.info("No channels configured for enforcement")
                return
            
            # Statistics tracking
            total_bans = 0
            total_unbans = 0
            total_unauthorized_bans = 0
            total_errors = 0
            
            # Process each channel individually for better control
            for channel_id, channel_info in self.managed_channels.items():
                channel_name = channel_info['name']
                
                try:
                    logger.info(f"Processing channel: {channel_name} ({channel_id})")
                    
                    # Validate channel ID format
                    if not channel_id.startswith('@') and not channel_id.startswith('-100'):
                        logger.warning(f"Invalid channel ID format: {channel_id}. Expected format: @username or -100xxxxxxxxx")
                        total_errors += 1
                        continue
                    
                    # Additional validation for numeric IDs
                    if channel_id.startswith('-100'):
                        try:
                            # Ensure it's a valid numeric ID after -100
                            int(channel_id[4:])  # Check if the part after -100 is numeric
                            if len(channel_id) < 14:  # Channel IDs are typically longer
                                logger.warning(f"Channel ID {channel_id} appears too short, may be invalid")
                        except ValueError:
                            logger.warning(f"Invalid numeric channel ID format: {channel_id}")
                            total_errors += 1
                            continue
                    
                    # Try to get channel entity with better error handling and alternative methods
                    try:
                        # First try to get entity directly
                        try:
                            channel_entity = await self.client.get_entity(channel_id)
                            logger.debug(f"Successfully found channel: {channel_entity.title}")
                        except ValueError as ve:
                            if "Cannot find any entity" in str(ve):
                                logger.info(f"Direct entity lookup failed for {channel_id}, trying alternative methods...")
                                
                                # Try to get entity using input peer
                                try:
                                    from telethon.tl.types import InputPeerChannel
                                    # Extract channel ID and access hash (we'll use 0 for access hash and let Telegram resolve it)
                                    if channel_id.startswith('-100'):
                                        numeric_id = int(channel_id[4:])  # Remove -100 prefix
                                        input_peer = InputPeerChannel(numeric_id, 0)
                                        channel_entity = await self.client.get_entity(input_peer)
                                        logger.info(f"Successfully resolved channel using InputPeer: {channel_entity.title}")
                                    else:
                                        raise ValueError("Invalid channel ID format")
                                except Exception as input_peer_error:
                                    logger.warning(f"InputPeer method failed: {input_peer_error}")
                                    
                                    # Try getting dialogs to find the channel
                                    try:
                                        logger.info(f"Searching for channel {channel_id} in dialogs...")
                                        async for dialog in self.client.iter_dialogs():
                                            if hasattr(dialog.entity, 'id'):
                                                # Convert entity ID to channel format for comparison
                                                if hasattr(dialog.entity, 'megagroup') or hasattr(dialog.entity, 'broadcast'):
                                                    entity_channel_id = f"-100{dialog.entity.id}"
                                                    if entity_channel_id == channel_id:
                                                        channel_entity = dialog.entity
                                                        logger.info(f"Found channel in dialogs: {channel_entity.title}")
                                                        break
                                        else:
                                            raise ValueError(f"Channel {channel_id} not found in dialogs")
                                    except Exception as dialog_error:
                                        logger.error(f"Dialog search failed: {dialog_error}")
                                        raise ve  # Re-raise original error
                            else:
                                raise ve
                                
                    except errors.UsernameNotOccupiedError:
                        logger.error(f"Channel username {channel_id} does not exist or is invalid")
                        total_errors += 1
                        continue
                    except errors.ChannelPrivateError:
                        logger.error(f"Channel {channel_id} is private or bot is not a member")
                        total_errors += 1
                        continue
                    except ValueError as ve:
                        logger.warning(f"Channel {channel_id} entity not found. Bot may not be added to channel or channel may be private")
                        logger.info(f"Skipping channel {channel_name} - ensure bot is added as admin")
                        total_errors += 1
                        continue
                    except Exception as entity_error:
                        logger.error(f"Cannot access channel {channel_id}: {entity_error}")
                        logger.warning(f"Bot may need to be added to channel {channel_id} as admin")
                        total_errors += 1
                        continue
                    
                    # Get users who should have access to this specific channel
                    authorized_users = await self.get_authorized_users_for_channel(channel_info['db_id'])
                    
                    # Convert authorized users to a set of IDs for fast O(1) lookup
                    authorized_user_ids = set()
                    if authorized_users:
                        authorized_user_ids = {user_data['telegram_user_id'] for user_data in authorized_users}
                    
                    # Get users who should be banned from this specific channel
                    banned_users = await self.get_banned_users_for_channel(channel_info['db_id'])
                    
                    # Process bans for this channel
                    for user_data in banned_users:
                        if await self.rate_limit_check():
                            success = await self.safe_ban_user(
                                channel_entity,
                                user_data['telegram_user_id'],
                                user_data['reason']
                            )
                            if success:
                                total_bans += 1
                            else:
                                total_errors += 1
                    
                    # Process unbans for this channel  
                    for user_data in authorized_users:
                        if await self.rate_limit_check():
                            success = await self.safe_unban_user(
                                channel_entity,
                                user_data['telegram_user_id'],
                                user_data['reason']
                            )
                            if success:
                                total_unbans += 1
                            else:
                                total_errors += 1
                    
                    # NEW: Enforce unauthorized users - ban ALL users currently in channel who shouldn't be there
                    unauthorized_bans, unauthorized_errors = await self.enforce_unauthorized_users(
                        channel_entity, 
                        channel_info['db_id'], 
                        authorized_user_ids
                    )
                    total_unauthorized_bans += unauthorized_bans
                    total_errors += unauthorized_errors
                    
                    # Log channel processing completion
                    logger.info(f"Channel {channel_name} processed: {len(banned_users)} subscription bans, {len(authorized_users)} unbans, {unauthorized_bans} unauthorized bans")
                    
                except Exception as e:
                    logger.error(f"Failed to process channel {channel_name}: {e}")
                    total_errors += 1
                    continue
            
            # Log cycle completion
            logger.info(f"Enforcement cycle completed: {total_bans} subscription bans, {total_unbans} unbans, {total_unauthorized_bans} unauthorized bans, {total_errors} errors")
            
            # Store enforcement statistics
            await self.log_enforcement_stats(total_bans + total_unauthorized_bans, total_unbans, total_errors)
            
        except Exception as e:
            logger.error(f"Enforcement cycle failed: {e}")

    async def get_managed_channels(self):
        """Get all channels that should be managed by the enforcement bot"""
        try:
            from app import app, db
            from models import Channel
            
            with app.app_context():
                # Get all active channels with telegram_channel_id configured
                channels = Channel.query.filter(
                    Channel.is_active == True,
                    Channel.telegram_channel_id.isnot(None)
                ).all()
                
                result = []
                for channel in channels:
                    result.append({
                        'id': channel.id,
                        'name': channel.name,
                        'telegram_channel_id': channel.telegram_channel_id
                    })
                
                return result
            
        except Exception as e:
            logger.error(f"Failed to get managed channels: {e}")
            return []

    async def list_accessible_channels(self):
        """List all channels/groups the bot can access for debugging"""
        try:
            if not self.client:
                logger.error("Telegram client not available")
                return []
            
            accessible_channels = []
            logger.info("Listing all accessible channels/groups...")
            
            async for dialog in self.client.iter_dialogs():
                if hasattr(dialog.entity, 'id'):
                    entity_type = type(dialog.entity).__name__
                    entity_id = dialog.entity.id
                    entity_title = getattr(dialog.entity, 'title', 'Unknown')
                    
                    # Check if it's a channel or supergroup
                    if hasattr(dialog.entity, 'megagroup') or hasattr(dialog.entity, 'broadcast'):
                        channel_id = f"-100{entity_id}"
                        accessible_channels.append({
                            'title': entity_title,
                            'id': entity_id,
                            'channel_id': channel_id,
                            'type': entity_type,
                            'is_megagroup': getattr(dialog.entity, 'megagroup', False),
                            'is_broadcast': getattr(dialog.entity, 'broadcast', False)
                        })
                        logger.info(f"Found channel: {entity_title} ({channel_id}) - Type: {entity_type}")
            
            logger.info(f"Total accessible channels: {len(accessible_channels)}")
            return accessible_channels
            
        except Exception as e:
            logger.error(f"Failed to list accessible channels: {e}")
            return []

    async def get_authorized_users_for_channel(self, channel_id: int):
        """Get users who should have access to a specific channel"""
        try:
            from app import app, db
            from models import User, Subscription, Plan, PlanChannel, Channel
            from sqlalchemy import and_
            
            with app.app_context():
                # Get users with active subscriptions that include this channel
                authorized_users = []
                
                # Get all active subscriptions
                active_subscriptions = Subscription.query.filter(
                    and_(
                        Subscription.end_date > datetime.utcnow(),
                        Subscription.is_paid == True
                    )
                ).all()
                
                for subscription in active_subscriptions:
                    user = subscription.user
                    plan = subscription.plan
                    
                    # Skip banned users
                    if user.is_banned:
                        continue
                    
                    # Check if user has telegram_chat_id
                    if not user.telegram_chat_id or not user.telegram_chat_id.isdigit():
                        continue
                    
                    telegram_user_id = int(user.telegram_chat_id)
                    
                    # Check if this plan includes the channel
                    plan_has_channel = PlanChannel.query.filter(
                        and_(
                            PlanChannel.plan_id == plan.id,
                            PlanChannel.channel_id == channel_id
                        )
                    ).first()
                    
                    if plan_has_channel:
                        authorized_users.append({
                            'user_id': user.id,
                            'telegram_user_id': telegram_user_id,
                            'username': user.telegram_username,
                            'plan_name': plan.name,
                            'reason': f'Active subscription: {plan.name}'
                        })
                
                return authorized_users
            
        except Exception as e:
            logger.error(f"Failed to get authorized users for channel {channel_id}: {e}")
            return []

    async def get_banned_users_for_channel(self, channel_id: int):
        """Get users who should be banned from a specific channel"""
        try:
            from app import app, db
            from models import User, Subscription, Plan, PlanChannel, Channel
            from sqlalchemy import and_, or_
            
            with app.app_context():
                banned_users = []
                
                # Get users who are explicitly banned
                banned_user_records = User.query.filter(User.is_banned == True).all()
                
                for user in banned_user_records:
                    if user.telegram_chat_id and user.telegram_chat_id.isdigit():
                        banned_users.append({
                            'user_id': user.id,
                            'telegram_user_id': int(user.telegram_chat_id),
                            'username': user.telegram_username,
                            'reason': 'User is banned'
                        })
                
                # Get users with expired subscriptions for this channel
                expired_subscriptions = Subscription.query.filter(
                    or_(
                        Subscription.end_date < datetime.utcnow(),
                        Subscription.is_paid == False
                    )
                ).all()
                
                for subscription in expired_subscriptions:
                    user = subscription.user
                    plan = subscription.plan
                    
                    # Skip if user is already in banned list
                    if user.is_banned:
                        continue
                    
                    if not user.telegram_chat_id or not user.telegram_chat_id.isdigit():
                        continue
                    
                    telegram_user_id = int(user.telegram_chat_id)
                    
                    # Check if this expired plan included the channel
                    plan_had_channel = PlanChannel.query.filter(
                        and_(
                            PlanChannel.plan_id == plan.id,
                            PlanChannel.channel_id == channel_id
                        )
                    ).first()
                    
                    if plan_had_channel:
                        # Check if user has any other active subscription for this channel
                        has_active_access = False
                        active_subscriptions = Subscription.query.filter(
                            and_(
                                Subscription.user_id == user.id,
                                Subscription.end_date > datetime.utcnow(),
                                Subscription.is_paid == True
                            )
                        ).all()
                        
                        for active_sub in active_subscriptions:
                            active_plan_has_channel = PlanChannel.query.filter(
                                and_(
                                    PlanChannel.plan_id == active_sub.plan_id,
                                    PlanChannel.channel_id == channel_id
                                )
                            ).first()
                            
                            if active_plan_has_channel:
                                has_active_access = True
                                break
                        
                        # If no active access, user should be banned
                        if not has_active_access:
                            banned_users.append({
                                'user_id': user.id,
                                'telegram_user_id': telegram_user_id,
                                'username': user.telegram_username,
                                'reason': f'Subscription expired: {plan.name}'
                            })
                
                return banned_users
            
        except Exception as e:
            logger.error(f"Failed to get banned users for channel {channel_id}: {e}")
            return []

    async def log_enforcement_stats(self, bans: int, unbans: int, errors: int):
        """Log enforcement cycle statistics"""
        try:
            from app import app, db
            from models import BotLog
            
            with app.app_context():
                log_entry = BotLog(
                    action_type='enforcement_cycle',
                    reason=f'Cycle completed: {bans} bans, {unbans} unbans, {errors} errors',
                    success=errors == 0,
                    error_message=f'{errors} errors occurred' if errors > 0 else None,
                    dry_run=self.dry_run
                )
                
                db.session.add(log_entry)
                db.session.commit()
            
        except Exception as e:
            logger.error(f"Failed to log enforcement stats: {e}")

    async def get_users_to_ban(self):
        """Legacy method for backward compatibility"""
        return []

    async def get_users_to_unban(self):
        """Legacy method for backward compatibility"""
        return []

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
        
        if not self.client:
            logger.error("Telegram client not initialized for manual ban")
            return {
                'user_id': user_id,
                'error': 'Telegram client not available',
                'successful_bans': 0,
                'results': []
            }
        
        # Get current managed channels
        try:
            await self.sync_channels()
            if not self.managed_channels:
                return {
                    'user_id': user_id,
                    'error': 'No channels configured',
                    'successful_bans': 0,
                    'results': []
                }
        except Exception as e:
            logger.error(f"Failed to sync channels for manual ban: {e}")
            return {
                'user_id': user_id,
                'error': f'Failed to load channels: {str(e)}',
                'successful_bans': 0,
                'results': []
            }
        
        for channel_id, channel_info in self.managed_channels.items():
            try:
                channel_entity = await self.client.get_entity(channel_id)
                success = await self.safe_ban_user(channel_entity, user_id, reason)
                results.append({
                    'channel': getattr(channel_entity, 'title', channel_info.get('name', 'Unknown')),
                    'channel_id': channel_id,
                    'success': success
                })
                
                # Log the manual action
                await self.log_action('manual_ban', user_id, channel_info.get('id', 0), reason)
                
            except Exception as e:
                logger.error(f"Failed to ban user {user_id} from channel {channel_id}: {e}")
                results.append({
                    'channel': channel_info.get('name', channel_id),
                    'channel_id': channel_id,
                    'success': False,
                    'error': str(e)
                })
        
        successful_bans = sum(1 for r in results if r['success'])
        logger.info(f"Manual ban user {user_id}: {successful_bans}/{len(results)} channels")
        
        return {
            'user_id': user_id,
            'total_channels': len(results),
            'successful_bans': successful_bans,
            'results': results
        }
    
    async def manual_unban_user(self, user_id: int, reason: str = "Manual unban") -> Dict:
        """Manually unban user from all channels"""
        results = []
        
        if not self.client:
            logger.error("Telegram client not initialized for manual unban")
            return {
                'user_id': user_id,
                'error': 'Telegram client not available',
                'successful_unbans': 0,
                'results': []
            }
        
        # Get current managed channels
        try:
            await self.sync_channels()
            if not self.managed_channels:
                return {
                    'user_id': user_id,
                    'error': 'No channels configured',
                    'successful_unbans': 0,
                    'results': []
                }
        except Exception as e:
            logger.error(f"Failed to sync channels for manual unban: {e}")
            return {
                'user_id': user_id,
                'error': f'Failed to load channels: {str(e)}',
                'successful_unbans': 0,
                'results': []
            }
        
        for channel_id, channel_info in self.managed_channels.items():
            try:
                channel_entity = await self.client.get_entity(channel_id)
                success = await self.safe_unban_user(channel_entity, user_id, reason)
                results.append({
                    'channel': getattr(channel_entity, 'title', channel_info.get('name', 'Unknown')),
                    'channel_id': channel_id,
                    'success': success
                })
                
                # Log the manual action
                await self.log_action('manual_unban', user_id, channel_info.get('id', 0), reason)
                
            except Exception as e:
                logger.error(f"Failed to unban user {user_id} from channel {channel_id}: {e}")
                results.append({
                    'channel': channel_info.get('name', channel_id),
                    'channel_id': channel_id,
                    'success': False,
                    'error': str(e)
                })
        
        successful_unbans = sum(1 for r in results if r['success'])
        logger.info(f"Manual unban user {user_id}: {successful_unbans}/{len(results)} channels")
        
        return {
            'user_id': user_id,
            'total_channels': len(results),
            'successful_unbans': successful_unbans,
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
    """Run enforcement bot in background thread with proper Flask context"""
    def bot_worker():
        try:
            # Import Flask app for context
            from app import app
            
            # Check if credentials are available before attempting to start
            api_id = os.environ.get('TELEGRAM_API_ID')
            api_hash = os.environ.get('TELEGRAM_API_HASH')
            
            if not api_id or not api_hash:
                logger.info("Enforcement bot: Telegram API credentials not configured - running in standby mode")
                logger.info("Configure credentials at /admin/bot-setup to activate enforcement")
                return
            
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run bot within Flask application context
            with app.app_context():
                try:
                    loop.run_until_complete(start_enforcement_bot())
                except Exception as e:
                    logger.error(f"Enforcement bot error: {e}")
                finally:
                    loop.close()
                    
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
        
        # Use thread-safe approach for Flask environment
        import concurrent.futures
        
        def run_in_thread():
            # Create new event loop for this thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(send_code())
            finally:
                new_loop.close()
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_in_thread)
            result = future.result(timeout=30)
        
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
        
        # Use thread-safe approach for Flask environment
        import concurrent.futures
        
        def run_in_thread():
            # Create new event loop for this thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(verify_code())
            finally:
                new_loop.close()
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_in_thread)
            result = future.result(timeout=30)
        
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

def reset_enforcement_session() -> Dict:
    """Reset/delete the enforcement bot session for fresh authentication"""
    try:
        session_dir = os.path.join(os.getcwd(), 'sessions')
        enforcement_session = os.path.join(session_dir, 'enforcement.session')
        
        # Remove session file if it exists
        if os.path.exists(enforcement_session):
            os.remove(enforcement_session)
            logger.info("Enforcement bot session file deleted")
            
        # Remove any journal files
        journal_file = f"{enforcement_session}-journal"
        if os.path.exists(journal_file):
            os.remove(journal_file)
            
        return {
            'success': True, 
            'message': 'Session reset successfully. Re-authenticate in admin panel.'
        }
        
    except Exception as e:
        logger.error(f"Failed to reset session: {e}")
        return {'success': False, 'error': str(e)}

def get_session_status() -> Dict:
    """Get current session status and information"""
    try:
        session_dir = os.path.join(os.getcwd(), 'sessions')
        enforcement_session = os.path.join(session_dir, 'enforcement.session')
        
        status = {
            'session_exists': os.path.exists(enforcement_session),
            'session_path': enforcement_session,
            'api_configured': bool(os.environ.get('TELEGRAM_API_ID') and os.environ.get('TELEGRAM_API_HASH')),
            'bot_running': enforcement_bot is not None
        }
        
        if status['session_exists']:
            import stat
            file_stats = os.stat(enforcement_session)
            status['session_size'] = file_stats.st_size
            status['session_permissions'] = oct(stat.S_IMODE(file_stats.st_mode))
            status['last_modified'] = file_stats.st_mtime
        
        return {'success': True, 'status': status}
        
    except Exception as e:
        logger.error(f"Failed to get session status: {e}")
        return {'success': False, 'error': str(e)}

def check_bot_channel_access(channel_id: str) -> Dict:
    """Check if bot has admin access to a specific channel"""
    try:
        global enforcement_bot
        
        if not enforcement_bot or not enforcement_bot.client:
            return {
                'success': False,
                'error': 'Enforcement bot not initialized. Configure Telegram API credentials first.'
            }
        
        # Check if bot has a client initialized
        if not hasattr(enforcement_bot.client, '_loop') or enforcement_bot.client._loop is None:
            return {
                'success': False,
                'error': 'Enforcement bot client not properly initialized'
            }
        
        # Use the bot's existing event loop
        bot_loop = enforcement_bot.client._loop
        
        # Handle event loop properly for Flask/threading environment
        async def check_access():
            try:
                # Get channel entity with improved resolution
                channel_entity = None
                
                try:
                    channel_entity = await enforcement_bot.client.get_entity(channel_id)
                except ValueError as ve:
                    if "Cannot find any entity" in str(ve):
                        logger.info(f"Direct lookup failed for {channel_id}, searching in dialogs...")
                        
                        # Search in dialogs
                        async for dialog in enforcement_bot.client.iter_dialogs():
                            if hasattr(dialog.entity, 'id'):
                                if hasattr(dialog.entity, 'megagroup') or hasattr(dialog.entity, 'broadcast'):
                                    entity_channel_id = f"-100{dialog.entity.id}"
                                    if entity_channel_id == channel_id:
                                        channel_entity = dialog.entity
                                        logger.info(f"Found channel in dialogs: {channel_entity.title}")
                                        break
                        
                        if not channel_entity:
                            raise ValueError(f"Channel {channel_id} not found in accessible channels")
                    else:
                        raise ve
                
                if not channel_entity:
                    return {
                        'success': False,
                        'error': 'Channel entity could not be resolved'
                    }
                
                # Get bot's permissions in the channel
                permissions = await enforcement_bot.client.get_permissions(channel_entity, 'me')
                
                # Check if bot has admin rights
                has_admin = permissions.is_admin if permissions else False
                can_ban = permissions.ban_users if permissions else False
                can_invite = permissions.invite_users if permissions else False
                
                return {
                    'success': True,
                    'has_access': has_admin,
                    'can_ban': can_ban,
                    'can_invite': can_invite,
                    'channel_title': getattr(channel_entity, 'title', 'Unknown'),
                    'channel_type': type(channel_entity).__name__,
                    'entity_id': getattr(channel_entity, 'id', 'Unknown')
                }
                
            except errors.ChannelPrivateError:
                return {
                    'success': False,
                    'error': 'Channel is private or bot is not a member'
                }
            except errors.UsernameNotOccupiedError:
                return {
                    'success': False,
                    'error': 'Channel username does not exist'
                }
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Failed to check channel access: {str(e)}'
                }
        
        # Use asyncio.run_coroutine_threadsafe to submit the coroutine to the bot's event loop
        import concurrent.futures
        
        future = asyncio.run_coroutine_threadsafe(check_access(), bot_loop)
        try:
            result = future.result(timeout=30)
            return result
        except concurrent.futures.TimeoutError:
            return {
                'success': False,
                'error': 'Channel access check timed out'
            }
        
    except Exception as e:
        logger.error(f"Failed to check bot channel access: {e}")
        return {
            'success': False,
            'error': str(e)
        }

def bulk_check_channels() -> Dict:
    """Check bot access for all channels in database"""
    try:
        from models import Channel
        from app import db
        
        channels = Channel.query.filter(Channel.telegram_channel_id.isnot(None)).all()
        results = []
        
        for channel in channels:
            access_result = check_bot_channel_access(channel.telegram_channel_id)
            results.append({
                'channel_id': channel.id,
                'channel_name': channel.name,
                'telegram_channel_id': channel.telegram_channel_id,
                'access_check': access_result
            })
        
        return {
            'success': True,
            'total_channels': len(channels),
            'results': results
        }
        
    except Exception as e:
        logger.error(f"Failed to bulk check channels: {e}")
        return {
            'success': False,
            'error': str(e)
        }