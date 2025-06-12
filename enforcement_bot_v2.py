"""
TeleSignals Enforcement Bot V2
Advanced backend bot with bot authentication for scalability and reliability
"""

import os
import time
import asyncio
import logging
import threading
import random
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional

from telethon import TelegramClient, errors
from telethon.tl.functions.channels import EditBannedRequest, GetParticipantsRequest
from telethon.tl.types import ChatBannedRights, ChannelParticipantsSearch, ChannelParticipantsAdmins
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

class EnforcementBotV2:
    """
    Enhanced enforcement bot using bot authentication for stability
    Implements advanced rate limiting and error handling for 90+ channels
    """
    
    def __init__(self):
        self.api_id = os.environ.get('TELEGRAM_API_ID')
        self.api_hash = os.environ.get('TELEGRAM_API_HASH')
        self.bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        
        self.client = None
        self.running = False
        self.managed_channels = {}
        self.whitelisted_users = set()
        
        # Enhanced rate limiting for scalability
        self.base_delay = 1.0  # Base delay between actions
        self.max_delay = 3.0   # Max delay for regular actions
        self.flood_delay_min = 10  # Min delay after flood error
        self.flood_delay_max = 30  # Max delay after flood error
        
        # Performance tracking
        self.actions_this_minute = 0
        self.max_actions_per_minute = 20  # Conservative limit
        self.minute_start = time.time()
        self.last_action_time = 0
        
        # Database setup
        self.Session = None
        self.setup_database()
        
        # Dry run mode (set to False for production)
        self.dry_run = False
        
        # Enforcement interval (seconds)
        self.scan_interval = 300  # 5 minutes
        
    def setup_database(self):
        """Setup database connection"""
        try:
            database_url = os.environ.get('DATABASE_URL')
            if database_url:
                engine = create_engine(database_url)
                self.Session = sessionmaker(bind=engine)
        except Exception as e:
            logger.error(f"Database setup failed: {e}")
    
    async def initialize(self):
        """Initialize bot with proper authentication"""
        try:
            if not self.api_id or not self.api_hash or not self.bot_token:
                logger.error("Missing Telegram credentials")
                return False
            
            # Use bot authentication for stability and proper permissions
            self.client = TelegramClient('enforcement_bot_v2', int(self.api_id), self.api_hash)
            await self.client.start(bot_token=self.bot_token)
            
            me = await self.client.get_me()
            logger.info(f"Enforcement bot initialized as: {me.first_name} (@{me.username})")
            
            # Load configuration
            await self.sync_channels()
            await self.load_whitelisted_users()
            
            return True
            
        except Exception as e:
            logger.error(f"Bot initialization failed: {e}")
            return False
    
    async def sync_channels(self):
        """Load managed channels from database"""
        try:
            from app import app, db
            from models import Channel
            
            with app.app_context():
                channels = Channel.query.filter(
                    Channel.is_active == True,
                    Channel.telegram_channel_id.isnot(None)
                ).all()
                
                old_count = len(self.managed_channels)
                self.managed_channels = {}
                
                for channel in channels:
                    channel_id = channel.telegram_channel_id.strip()
                    if channel_id:
                        self.managed_channels[channel_id] = {
                            'name': channel.name,
                            'db_id': channel.id
                        }
                
                logger.info(f"Synced {len(self.managed_channels)} channels (was {old_count})")
                
        except Exception as e:
            logger.error(f"Channel sync failed: {e}")
    
    async def load_whitelisted_users(self):
        """Load users who should never be banned"""
        try:
            from app import app, db
            from models import User, Admin, Subscription
            from sqlalchemy import and_
            
            with app.app_context():
                whitelisted_ids = set()
                
                # Add admin users
                try:
                    admins = Admin.query.filter(Admin.is_active == True).all()
                    for admin in admins:
                        if hasattr(admin, 'telegram_chat_id') and admin.telegram_chat_id and admin.telegram_chat_id.isdigit():
                            whitelisted_ids.add(int(admin.telegram_chat_id))
                except Exception as e:
                    logger.warning(f"Could not load admin users: {e}")
                
                # Add users with active subscriptions
                try:
                    active_subscriptions = Subscription.query.filter(
                        and_(
                            Subscription.end_date > datetime.utcnow(),
                            Subscription.is_paid == True
                        )
                    ).all()
                    
                    for subscription in active_subscriptions:
                        user = subscription.user
                        if user.telegram_chat_id and user.telegram_chat_id.isdigit():
                            whitelisted_ids.add(int(user.telegram_chat_id))
                            
                except Exception as e:
                    logger.warning(f"Could not load active subscribers: {e}")
                
                self.whitelisted_users = whitelisted_ids
                logger.info(f"Loaded {len(self.whitelisted_users)} whitelisted users")
            
        except Exception as e:
            logger.error(f"Failed to load whitelisted users: {e}")
            self.whitelisted_users = set()
    
    async def smart_delay(self, is_flood_recovery=False):
        """Implement intelligent rate limiting with randomization"""
        current_time = time.time()
        
        # Reset counter every minute
        if current_time - self.minute_start >= 60:
            self.actions_this_minute = 0
            self.minute_start = current_time
        
        # Check rate limit
        if self.actions_this_minute >= self.max_actions_per_minute:
            wait_time = 60 - (current_time - self.minute_start)
            logger.warning(f"Rate limit reached, waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
            self.actions_this_minute = 0
            self.minute_start = time.time()
        
        # Apply delay based on context
        if is_flood_recovery:
            # Longer randomized delay after flood errors
            delay = random.uniform(self.flood_delay_min, self.flood_delay_max)
            logger.info(f"Flood recovery delay: {delay:.1f}s")
        else:
            # Regular randomized delay
            delay = random.uniform(self.base_delay, self.max_delay)
        
        # Ensure minimum time between actions
        time_since_last = current_time - self.last_action_time
        if time_since_last < delay:
            await asyncio.sleep(delay - time_since_last)
        
        self.last_action_time = time.time()
        self.actions_this_minute += 1
    
    async def safe_ban_user(self, channel_entity, user_id: int, reason: str = "Unauthorized access") -> Dict:
        """Safely ban user with comprehensive error handling"""
        result = {
            'success': False,
            'user_id': user_id,
            'channel_id': channel_entity.id,
            'reason': reason,
            'error': None
        }
        
        try:
            await self.smart_delay()
            
            # Skip if user is whitelisted
            if user_id in self.whitelisted_users:
                result['error'] = 'User is whitelisted'
                return result
            
            if self.dry_run:
                logger.info(f"DRY-RUN: Would ban user {user_id} from {channel_entity.title} - {reason}")
                result['success'] = True
                return result
            
            # Use EditBannedRequest for proper ban enforcement
            banned_rights = ChatBannedRights(
                until_date=None,  # Permanent ban
                view_messages=True,  # Remove view access
                send_messages=True,
                send_media=True,
                send_stickers=True,
                send_gifs=True,
                send_games=True,
                send_inline=True,
                embed_links=True
            )
            
            await self.client(EditBannedRequest(
                channel=channel_entity,
                participant=user_id,
                banned_rights=banned_rights
            ))
            
            logger.info(f"✓ Banned user {user_id} from {channel_entity.title} - {reason}")
            result['success'] = True
            await self.log_action("ban", user_id, channel_entity.id, reason, True)
            
        except errors.FloodWaitError as e:
            error_msg = f"Flood wait: {e.seconds}s"
            result['error'] = error_msg
            logger.warning(f"⚠ {error_msg} - backing off")
            await asyncio.sleep(e.seconds)
            await self.smart_delay(is_flood_recovery=True)
            
        except errors.UserAdminInvalidError:
            error_msg = "Cannot ban admin user"
            result['error'] = error_msg
            logger.info(f"⚠ Cannot ban admin user {user_id}")
            
        except errors.UserNotParticipantError:
            error_msg = "User not in channel"
            result['error'] = error_msg
            logger.debug(f"User {user_id} not in channel {channel_entity.title}")
            
        except errors.ChatAdminRequiredError:
            error_msg = "Bot lacks admin permissions"
            result['error'] = error_msg
            logger.error(f"✗ Bot lacks admin permissions in {channel_entity.title}")
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            result['error'] = error_msg
            logger.error(f"✗ Failed to ban user {user_id}: {e}")
            await self.log_action("ban", user_id, channel_entity.id, reason, False, str(e))
        
        return result
    
    async def safe_unban_user(self, channel_entity, user_id: int, reason: str = "Access restored") -> Dict:
        """Safely unban user with comprehensive error handling"""
        result = {
            'success': False,
            'user_id': user_id,
            'channel_id': channel_entity.id,
            'reason': reason,
            'error': None
        }
        
        try:
            await self.smart_delay()
            
            if self.dry_run:
                logger.info(f"DRY-RUN: Would unban user {user_id} from {channel_entity.title} - {reason}")
                result['success'] = True
                return result
            
            # Remove all restrictions
            unbanned_rights = ChatBannedRights(
                until_date=None,
                view_messages=False,
                send_messages=False,
                send_media=False,
                send_stickers=False,
                send_gifs=False,
                send_games=False,
                send_inline=False,
                embed_links=False
            )
            
            await self.client(EditBannedRequest(
                channel=channel_entity,
                participant=user_id,
                banned_rights=unbanned_rights
            ))
            
            logger.info(f"✓ Unbanned user {user_id} from {channel_entity.title} - {reason}")
            result['success'] = True
            await self.log_action("unban", user_id, channel_entity.id, reason, True)
            
        except errors.FloodWaitError as e:
            error_msg = f"Flood wait: {e.seconds}s"
            result['error'] = error_msg
            logger.warning(f"⚠ {error_msg} - backing off")
            await asyncio.sleep(e.seconds)
            await self.smart_delay(is_flood_recovery=True)
            
        except Exception as e:
            error_msg = f"Unban error: {str(e)}"
            result['error'] = error_msg
            logger.error(f"✗ Failed to unban user {user_id}: {e}")
            await self.log_action("unban", user_id, channel_entity.id, reason, False, str(e))
        
        return result
    
    async def get_channel_participants(self, channel_entity) -> Set[int]:
        """Get all channel participants efficiently"""
        try:
            participants = set()
            
            # Get participants in batches for efficiency
            async for participant in self.client.iter_participants(channel_entity):
                if not participant.bot:  # Skip bots
                    participants.add(participant.id)
            
            return participants
            
        except Exception as e:
            logger.error(f"Failed to get participants for {channel_entity.title}: {e}")
            return set()
    
    async def get_channel_admins(self, channel_entity) -> Set[int]:
        """Get channel admin user IDs"""
        try:
            admins = set()
            
            async for admin in self.client.iter_participants(channel_entity, filter=ChannelParticipantsAdmins):
                admins.add(admin.id)
            
            return admins
            
        except Exception as e:
            logger.error(f"Failed to get admins for {channel_entity.title}: {e}")
            return set()
    
    async def enforce_channel_access(self, channel_id: str, channel_info: Dict) -> Dict:
        """Enforce access control for a single channel"""
        stats = {
            'channel_id': channel_id,
            'channel_name': channel_info['name'],
            'bans': 0,
            'unbans': 0,
            'errors': 0,
            'skipped_admins': 0
        }
        
        try:
            # Get channel entity
            try:
                channel_entity = await self.client.get_entity(channel_id)
            except Exception as e:
                logger.error(f"✗ Cannot access channel {channel_id}: {e}")
                stats['errors'] += 1
                return stats
            
            logger.info(f"🔍 Processing channel: {channel_entity.title} ({channel_id})")
            
            # Get current participants and admins
            all_participants = await self.get_channel_participants(channel_entity)
            channel_admins = await self.get_channel_admins(channel_entity)
            
            # Get bot's own ID to avoid self-ban
            me = await self.client.get_me()
            bot_id = me.id
            
            # Combine all protected users
            protected_users = self.whitelisted_users | channel_admins | {bot_id}
            
            logger.info(f"📊 Channel stats: {len(all_participants)} participants, {len(channel_admins)} admins, {len(self.whitelisted_users)} whitelisted")
            
            # Process each participant
            for user_id in all_participants:
                # Skip protected users
                if user_id in protected_users:
                    if user_id in channel_admins:
                        stats['skipped_admins'] += 1
                    continue
                
                # Check if user should have access
                if await self.user_has_channel_access(user_id, channel_info['db_id']):
                    # User should have access - unban if needed
                    result = await self.safe_unban_user(channel_entity, user_id, "Active subscription")
                    if result['success']:
                        stats['unbans'] += 1
                    elif result['error']:
                        stats['errors'] += 1
                else:
                    # User should not have access - ban them
                    result = await self.safe_ban_user(channel_entity, user_id, "No active subscription")
                    if result['success']:
                        stats['bans'] += 1
                    elif result['error'] and 'whitelisted' not in result['error']:
                        stats['errors'] += 1
            
            logger.info(f"✅ Channel {channel_entity.title}: {stats['bans']} bans, {stats['unbans']} unbans, {stats['skipped_admins']} admin skips, {stats['errors']} errors")
            
        except Exception as e:
            logger.error(f"✗ Channel enforcement failed for {channel_id}: {e}")
            stats['errors'] += 1
        
        return stats
    
    async def user_has_channel_access(self, user_id: int, channel_db_id: int) -> bool:
        """Check if user should have access to specific channel"""
        try:
            from app import app, db
            from models import User, Subscription, Plan, PlanChannel
            from sqlalchemy import and_
            
            with app.app_context():
                # Find user by telegram ID
                user = User.query.filter(User.telegram_chat_id == str(user_id)).first()
                if not user:
                    return False
                
                # Check for active subscriptions that include this channel
                active_subscriptions = Subscription.query.filter(
                    and_(
                        Subscription.user_id == user.id,
                        Subscription.end_date > datetime.utcnow(),
                        Subscription.is_paid == True
                    )
                ).all()
                
                for subscription in active_subscriptions:
                    # Check if this subscription's plan includes the channel
                    plan_has_channel = PlanChannel.query.filter(
                        and_(
                            PlanChannel.plan_id == subscription.plan_id,
                            PlanChannel.channel_id == channel_db_id
                        )
                    ).first()
                    
                    if plan_has_channel:
                        return True
                
                return False
                
        except Exception as e:
            logger.error(f"Error checking access for user {user_id}: {e}")
            return False
    
    async def enforcement_cycle(self):
        """Main enforcement cycle - process all managed channels"""
        try:
            logger.info("🚀 Starting enforcement cycle")
            
            if not self.client:
                logger.warning("⚠ Telegram client not available")
                return
            
            # Refresh configuration
            await self.sync_channels()
            await self.load_whitelisted_users()
            
            if not self.managed_channels:
                logger.info("ℹ No channels configured for enforcement")
                return
            
            # Track overall statistics
            total_stats = {
                'channels_processed': 0,
                'total_bans': 0,
                'total_unbans': 0,
                'total_errors': 0,
                'total_skipped_admins': 0
            }
            
            # Process each channel
            for channel_id, channel_info in self.managed_channels.items():
                try:
                    stats = await self.enforce_channel_access(channel_id, channel_info)
                    
                    total_stats['channels_processed'] += 1
                    total_stats['total_bans'] += stats['bans']
                    total_stats['total_unbans'] += stats['unbans']
                    total_stats['total_errors'] += stats['errors']
                    total_stats['total_skipped_admins'] += stats['skipped_admins']
                    
                except Exception as e:
                    logger.error(f"✗ Failed to process channel {channel_id}: {e}")
                    total_stats['total_errors'] += 1
            
            # Log cycle completion
            logger.info(f"🏁 Enforcement cycle completed: {total_stats['channels_processed']} channels, "
                       f"{total_stats['total_bans']} bans, {total_stats['total_unbans']} unbans, "
                       f"{total_stats['total_skipped_admins']} admin skips, {total_stats['total_errors']} errors")
            
            # Log statistics to database
            await self.log_enforcement_stats(total_stats)
            
        except Exception as e:
            logger.error(f"✗ Enforcement cycle failed: {e}")
    
    async def log_action(self, action_type: str, user_id: int, channel_id: int, reason: str, success: bool, error_msg: str = None):
        """Log enforcement actions to database"""
        try:
            from app import app, db
            from models import BotLog
            
            with app.app_context():
                log_entry = BotLog(
                    action_type=action_type,
                    user_id=user_id,
                    channel_id=channel_id,
                    reason=reason,
                    success=success,
                    error_message=error_msg,
                    timestamp=datetime.utcnow(),
                    dry_run=self.dry_run
                )
                db.session.add(log_entry)
                db.session.commit()
                
        except Exception as e:
            logger.error(f"Failed to log action: {e}")
    
    async def log_enforcement_stats(self, stats: Dict):
        """Log enforcement cycle statistics"""
        try:
            from app import app, db
            from models import BotLog
            
            with app.app_context():
                log_entry = BotLog(
                    action_type='enforcement_cycle',
                    reason=f"Processed {stats['channels_processed']} channels: {stats['total_bans']} bans, "
                           f"{stats['total_unbans']} unbans, {stats['total_errors']} errors",
                    success=stats['total_errors'] == 0,
                    error_message=f"{stats['total_errors']} errors occurred" if stats['total_errors'] > 0 else None,
                    timestamp=datetime.utcnow(),
                    dry_run=self.dry_run
                )
                db.session.add(log_entry)
                db.session.commit()
                
        except Exception as e:
            logger.error(f"Failed to log stats: {e}")
    
    async def run(self):
        """Main bot loop"""
        self.running = True
        logger.info("🤖 Enforcement bot V2 started")
        
        while self.running:
            try:
                await self.enforcement_cycle()
                
                logger.info(f"⏱ Waiting {self.scan_interval}s until next cycle")
                await asyncio.sleep(self.scan_interval)
                
            except Exception as e:
                logger.error(f"✗ Error in main loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying
    
    async def stop(self):
        """Stop the bot gracefully"""
        self.running = False
        if self.client:
            await self.client.disconnect()
        logger.info("🛑 Enforcement bot stopped")

# Global bot instance
_enforcement_bot_v2 = None

async def start_enforcement_bot_v2():
    """Start the enhanced enforcement bot"""
    global _enforcement_bot_v2
    
    try:
        _enforcement_bot_v2 = EnforcementBotV2()
        
        if await _enforcement_bot_v2.initialize():
            await _enforcement_bot_v2.run()
        else:
            logger.error("Failed to initialize enforcement bot V2")
            
    except Exception as e:
        logger.error(f"Enforcement bot V2 startup failed: {e}")

def run_enforcement_bot_v2_background():
    """Run enforcement bot V2 in background thread"""
    def bot_worker():
        try:
            from app import app
            with app.app_context():
                asyncio.run(start_enforcement_bot_v2())
        except Exception as e:
            logger.error(f"Enforcement bot V2 background thread failed: {e}")
    
    thread = threading.Thread(target=bot_worker, daemon=True)
    thread.start()
    logger.info("Enforcement bot V2 started in background")

async def get_enforcement_bot_v2():
    """Get the global enforcement bot V2 instance"""
    return _enforcement_bot_v2

if __name__ == "__main__":
    # Direct run for testing
    asyncio.run(start_enforcement_bot_v2())