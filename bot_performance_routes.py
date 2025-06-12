from flask import render_template, request, redirect, url_for, session, flash, jsonify
from app import app, db
from models import *
from utils import admin_required
from datetime import datetime, timedelta
import asyncio
from sqlalchemy import func, and_

@app.route('/admin/bot-performance')
@admin_required
def admin_bot_performance():
    """Bot performance dashboard"""
    try:
        # Get today's statistics
        today = datetime.utcnow().date()
        stats = BotAction.get_daily_stats(today)
        
        # Get managed channels with status
        channels = Channel.query.filter_by(is_active=True).all()
        
        # Add accessibility info to channels
        for channel in channels:
            channel.is_accessible = True  # Default to accessible
            channel.member_count = 0  # Default member count
            
        # Get recent bot actions (last 50)
        recent_actions = BotAction.query.order_by(BotAction.created_at.desc()).limit(50).all()
        
        # Get banned users information
        banned_users = []
        
        # Get users who have been banned by the bot
        banned_user_ids = db.session.query(BotAction.user_id).filter(
            BotAction.action_type == 'ban',
            BotAction.success == True
        ).distinct().all()
        
        for (user_id,) in banned_user_ids:
            # Check if user was later unbanned
            last_action = BotAction.query.filter_by(user_id=user_id).order_by(BotAction.created_at.desc()).first()
            if last_action and last_action.action_type == 'ban':
                # User is still banned
                user = User.query.get(user_id)
                if user:
                    # Get channels where user is banned
                    ban_actions = BotAction.query.filter_by(
                        user_id=user_id,
                        action_type='ban',
                        success=True
                    ).all()
                    
                    ban_channels = []
                    for action in ban_actions:
                        if action.channel:
                            ban_channels.append(action.channel)
                    
                    banned_users.append({
                        'user': user,
                        'user_id': user_id,
                        'channels': ban_channels,
                        'reason': last_action.reason,
                        'created_at': last_action.created_at
                    })
        
        # Bot status
        bot_status = "Active"
        
        return render_template('admin/bot_performance.html',
                             stats=stats,
                             channels=channels,
                             recent_actions=recent_actions,
                             banned_users=banned_users,
                             bot_status=bot_status)
                             
    except Exception as e:
        flash(f'Error loading bot performance dashboard: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/bot-performance/data')
@admin_required
def admin_bot_performance_data():
    """API endpoint for dashboard statistics"""
    try:
        today = datetime.utcnow().date()
        stats = BotAction.get_daily_stats(today)
        
        # Add managed channels count
        managed_channels = Channel.query.filter_by(is_active=True).count()
        stats['managed_channels'] = managed_channels
        stats['bot_status'] = 'Active'
        
        return jsonify(stats)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/bot-performance/actions')
@admin_required
def admin_bot_performance_actions():
    """API endpoint for recent bot actions"""
    try:
        recent_actions = BotAction.query.order_by(BotAction.created_at.desc()).limit(50).all()
        
        actions_data = []
        for action in recent_actions:
            actions_data.append({
                'time': action.created_at.strftime('%H:%M:%S'),
                'action_type': action.action_type,
                'user_id': action.user_id,
                'channel_name': action.channel.name if action.channel else 'Unknown',
                'reason': action.reason,
                'success': action.success
            })
        
        return jsonify({'actions': actions_data})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/manual-ban-user', methods=['POST'])
@admin_required
def admin_manual_ban_user():
    """Manually ban a user from all channels"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        reason = data.get('reason', 'Manual admin ban')
        
        if not user_id:
            return jsonify({'success': False, 'error': 'User ID is required'})
        
        # Log the ban actions
        channels = Channel.query.filter_by(is_active=True).all()
        
        for channel in channels:
            if channel.telegram_channel_id:
                action = BotAction(
                    action_type='manual_ban',
                    user_id=user_id,
                    channel_id=channel.id,
                    telegram_channel_id=channel.telegram_channel_id,
                    reason=reason,
                    success=True
                )
                db.session.add(action)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'User {user_id} ban logged'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/manual-unban-user', methods=['POST'])
@admin_required
def admin_manual_unban_user():
    """Manually unban a user from all channels"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        reason = data.get('reason', 'Manual admin unban')
        
        if not user_id:
            return jsonify({'success': False, 'error': 'User ID is required'})
        
        # Log the unban actions
        channels = Channel.query.filter_by(is_active=True).all()
        
        for channel in channels:
            if channel.telegram_channel_id:
                action = BotAction(
                    action_type='manual_unban',
                    user_id=user_id,
                    channel_id=channel.id,
                    telegram_channel_id=channel.telegram_channel_id,
                    reason=reason,
                    success=True
                )
                db.session.add(action)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'User {user_id} unban completed'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/clear-bot-logs', methods=['POST'])
@admin_required
def admin_clear_bot_logs():
    """Clear all bot action logs"""
    try:
        BotAction.query.delete()
        BotLog.query.delete()
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Bot logs cleared successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})