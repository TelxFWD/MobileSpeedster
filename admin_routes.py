from flask import render_template, request, redirect, url_for, session, flash, jsonify
from app import app, db
from models import *
from utils import admin_required
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
import json

# Make datetime available in templates
@app.context_processor
def inject_datetime():
    return {'moment': datetime}

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Please fill in all fields', 'error')
            return render_template('admin/login.html')
        
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password) and admin.is_active:
            session['admin_id'] = admin.id
            session['admin_username'] = admin.username
            admin.last_login = datetime.utcnow()
            db.session.commit()
            flash('Admin logged in successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_username', None)
    flash('Admin logged out successfully', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    # Get statistics
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True, is_banned=False).count()
    total_subscriptions = Subscription.query.count()
    active_subscriptions = Subscription.query.filter(
        Subscription.end_date > datetime.utcnow(),
        Subscription.is_paid == True
    ).count()
    
    # Revenue calculation
    total_revenue = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.status == 'completed'
    ).scalar() or 0
    
    # Most popular plans
    popular_plans = db.session.query(
        Plan.name,
        db.func.count(Subscription.id).label('subscription_count')
    ).join(Subscription).group_by(Plan.id).order_by(
        db.func.count(Subscription.id).desc()
    ).limit(5).all()
    
    # Recent transactions
    recent_transactions = Transaction.query.order_by(
        Transaction.created_at.desc()
    ).limit(10).all()
    
    return render_template('admin/dashboard.html',
                         total_users=total_users,
                         active_users=active_users,
                         total_subscriptions=total_subscriptions,
                         active_subscriptions=active_subscriptions,
                         total_revenue=total_revenue,
                         popular_plans=popular_plans,
                         recent_transactions=recent_transactions)

@app.route('/admin/users')
@admin_required
def admin_users():
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = User.query
    if search:
        query = query.filter(User.telegram_username.contains(search))
    
    users = query.paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('admin/users.html', users=users, search=search)

@app.route('/admin/user/<int:user_id>/toggle_status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)
    action = request.form.get('action')
    
    if action == 'ban':
        user.is_banned = True
        flash(f'User {user.telegram_username} has been banned', 'success')
    elif action == 'unban':
        user.is_banned = False
        flash(f'User {user.telegram_username} has been unbanned', 'success')
    elif action == 'deactivate':
        user.is_active = False
        flash(f'User {user.telegram_username} has been deactivated', 'success')
    elif action == 'activate':
        user.is_active = True
        flash(f'User {user.telegram_username} has been activated', 'success')
    
    db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/extend', methods=['POST'])
@admin_required
def extend_user_subscription(user_id):
    user = User.query.get_or_404(user_id)
    days = request.form.get('days', type=int)
    
    if not days or days <= 0:
        flash('Invalid number of days', 'error')
        return redirect(url_for('admin_users'))
    
    # Extend all active subscriptions
    for subscription in user.get_active_subscriptions():
        subscription.end_date += timedelta(days=days)
    
    db.session.commit()
    flash(f'Extended {user.telegram_username} subscriptions by {days} days', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/plans')
@admin_required
def admin_plans():
    plans = Plan.query.order_by(Plan.created_at.desc()).all()
    channels = Channel.query.filter_by(is_active=True).all()
    return render_template('admin/plans.html', plans=plans, channels=channels)

@app.route('/admin/plan/create', methods=['POST'])
@admin_required
def create_plan():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    plan_type = request.form.get('plan_type')
    price = request.form.get('price', type=float)
    duration_days = request.form.get('duration_days', type=int)
    is_lifetime = request.form.get('is_lifetime') == 'on'
    folder_link = request.form.get('folder_link', '').strip()
    channel_ids = request.form.getlist('channels')
    
    # Validation
    if not all([name, plan_type, price]):
        flash('Please fill in all required fields', 'error')
        return redirect(url_for('admin_plans'))
    
    # For lifetime plans, duration_days should be 0 or very high number
    if is_lifetime:
        duration_days = 36500  # 100 years as "lifetime"
    elif not duration_days or duration_days <= 0:
        flash('Please specify duration for non-lifetime plans', 'error')
        return redirect(url_for('admin_plans'))
    
    # Create plan
    plan = Plan(
        name=name,
        description=description,
        plan_type=plan_type,
        price=price,
        duration_days=duration_days,
        is_lifetime=is_lifetime,
        folder_link=folder_link if plan_type == 'bundle' else None
    )
    db.session.add(plan)
    db.session.flush()  # Get the plan ID
    
    # Add channels to plan
    for channel_id in channel_ids:
        plan_channel = PlanChannel(plan_id=plan.id, channel_id=int(channel_id))
        db.session.add(plan_channel)
    
    db.session.commit()
    
    plan_type_text = "Lifetime" if is_lifetime else "Regular"
    flash(f'{plan_type_text} plan created successfully!', 'success')
    return redirect(url_for('admin_plans'))

@app.route('/admin/plan/<int:plan_id>/toggle', methods=['POST'])
@admin_required
def toggle_plan_status(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    plan.is_active = not plan.is_active
    db.session.commit()
    
    status = 'activated' if plan.is_active else 'deactivated'
    flash(f'Plan {plan.name} has been {status}', 'success')
    return redirect(url_for('admin_plans'))

@app.route('/admin/channels')
@admin_required
def admin_channels():
    channels = Channel.query.order_by(Channel.created_at.desc()).all()
    return render_template('admin/channels.html', channels=channels)

@app.route('/admin/channel/create', methods=['POST'])
@admin_required
def create_channel():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    telegram_link = request.form.get('telegram_link', '').strip()
    telegram_channel_id = request.form.get('telegram_channel_id', '').strip()
    solo_price = request.form.get('solo_price', type=float)
    solo_duration_days = request.form.get('solo_duration_days', type=int)
    show_in_custom_bundle = request.form.get('show_in_custom_bundle') == 'on'
    
    if not all([name, telegram_link]):
        flash('Please fill in required fields', 'error')
        return redirect(url_for('admin_channels'))
    
    # Validate channel ID format if provided
    if telegram_channel_id:
        # Remove @ if present and validate format
        if telegram_channel_id.startswith('@'):
            telegram_channel_id = telegram_channel_id[1:]
        elif telegram_channel_id.startswith('-100'):
            # Numeric channel ID format is valid
            pass
        else:
            # Try to parse as numeric ID
            try:
                int(telegram_channel_id)
            except ValueError:
                flash('Invalid channel ID format. Use @channelname or numeric ID', 'error')
                return redirect(url_for('admin_channels'))
    
    channel = Channel(
        name=name,
        description=description,
        telegram_link=telegram_link,
        telegram_channel_id=telegram_channel_id or None,
        solo_price=solo_price,
        solo_duration_days=solo_duration_days,
        show_in_custom_bundle=show_in_custom_bundle
    )
    db.session.add(channel)
    db.session.commit()
    
    # Check bot access if channel ID is provided
    if telegram_channel_id:
        try:
            from enforcement_bot import check_bot_channel_access
            access_result = check_bot_channel_access(telegram_channel_id)
            if access_result.get('success'):
                if access_result.get('has_access'):
                    flash(f'Channel created successfully! Bot has admin access to {telegram_channel_id}', 'success')
                else:
                    flash(f'Channel created but bot needs admin access to {telegram_channel_id}', 'warning')
            else:
                flash(f'Channel created but could not verify bot access: {access_result.get("error", "Unknown error")}', 'warning')
        except Exception as e:
            flash('Channel created but could not check bot access', 'warning')
    else:
        flash('Channel created successfully!', 'success')
    
    return redirect(url_for('admin_channels'))

@app.route('/admin/channel/<int:channel_id>/toggle', methods=['POST'])
@admin_required
def toggle_channel_status(channel_id):
    channel = Channel.query.get_or_404(channel_id)
    channel.is_active = not channel.is_active
    db.session.commit()
    
    status = 'activated' if channel.is_active else 'deactivated'
    flash(f'Channel {channel.name} has been {status}', 'success')
    return redirect(url_for('admin_channels'))

@app.route('/admin/channel/<int:channel_id>/edit', methods=['POST'])
@admin_required
def edit_channel(channel_id):
    channel = Channel.query.get_or_404(channel_id)
    
    channel.name = request.form.get('name', '').strip()
    channel.description = request.form.get('description', '').strip()
    channel.telegram_link = request.form.get('telegram_link', '').strip()
    telegram_channel_id = request.form.get('telegram_channel_id', '').strip()
    channel.solo_price = request.form.get('solo_price', type=float)
    channel.solo_duration_days = request.form.get('solo_duration_days', type=int)
    channel.show_in_custom_bundle = request.form.get('show_in_custom_bundle') == 'on'
    
    if not all([channel.name, channel.telegram_link]):
        flash('Please fill in required fields', 'error')
        return redirect(url_for('admin_channels'))
    
    # Validate and update channel ID if provided
    old_channel_id = channel.telegram_channel_id
    if telegram_channel_id:
        if telegram_channel_id.startswith('@'):
            telegram_channel_id = telegram_channel_id[1:]
        elif not telegram_channel_id.startswith('-100'):
            try:
                int(telegram_channel_id)
            except ValueError:
                flash('Invalid channel ID format. Use @channelname or numeric ID', 'error')
                return redirect(url_for('admin_channels'))
        
        channel.telegram_channel_id = telegram_channel_id
    else:
        channel.telegram_channel_id = None
    
    db.session.commit()
    
    # Check bot access if channel ID was updated
    if telegram_channel_id and telegram_channel_id != old_channel_id:
        try:
            from enforcement_bot import check_bot_channel_access
            access_result = check_bot_channel_access(telegram_channel_id)
            if access_result.get('success'):
                if access_result.get('has_access'):
                    flash(f'Channel updated successfully! Bot has admin access to {telegram_channel_id}', 'success')
                else:
                    flash(f'Channel updated but bot needs admin access to {telegram_channel_id}', 'warning')
            else:
                flash(f'Channel updated but could not verify bot access: {access_result.get("error", "Unknown error")}', 'warning')
        except Exception as e:
            flash('Channel updated but could not check bot access', 'warning')
    else:
        flash('Channel updated successfully!', 'success')
    
    return redirect(url_for('admin_channels'))

@app.route('/admin/promos')
@admin_required
def admin_promos():
    promos = PromoCode.query.order_by(PromoCode.created_at.desc()).all()
    return render_template('admin/promos.html', promos=promos)

@app.route('/admin/promo/create', methods=['POST'])
@admin_required
def create_promo():
    code = request.form.get('code', '').strip().upper()
    discount_percent = request.form.get('discount_percent', type=float)
    usage_limit = request.form.get('usage_limit', type=int)
    expiry_date_str = request.form.get('expiry_date')
    
    if not all([code, discount_percent]):
        flash('Please fill in required fields', 'error')
        return redirect(url_for('admin_promos'))
    
    if PromoCode.query.filter_by(code=code).first():
        flash('Promo code already exists', 'error')
        return redirect(url_for('admin_promos'))
    
    expiry_date = None
    if expiry_date_str:
        try:
            expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid expiry date format', 'error')
            return redirect(url_for('admin_promos'))
    
    promo = PromoCode(
        code=code,
        discount_percent=discount_percent,
        usage_limit=usage_limit,
        expiry_date=expiry_date
    )
    db.session.add(promo)
    db.session.commit()
    
    flash('Promo code created successfully!', 'success')
    return redirect(url_for('admin_promos'))

@app.route('/admin/content')
@admin_required
def admin_content():
    contents = SiteContent.query.all()
    return render_template('admin/content.html', contents=contents)

@app.route('/admin/content/update', methods=['POST'])
@admin_required
def update_content():
    key = request.form.get('key')
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    
    if not key:
        flash('Invalid content key', 'error')
        return redirect(url_for('admin_content'))
    
    site_content = SiteContent.query.filter_by(key=key).first()
    if not site_content:
        site_content = SiteContent(key=key)
        db.session.add(site_content)
    
    site_content.title = title
    site_content.content = content
    site_content.updated_at = datetime.utcnow()
    
    db.session.commit()
    flash('Content updated successfully!', 'success')
    return redirect(url_for('admin_content'))

@app.route('/admin/payments')
@admin_required
def admin_payments():
    transactions = Transaction.query.order_by(Transaction.created_at.desc()).limit(100).all()
    payment_settings = PaymentSettings.query.first()
    return render_template('admin/payments.html', 
                         transactions=transactions,
                         payment_settings=payment_settings)

@app.route('/admin/settings')
@admin_required
def admin_settings():
    bot_settings = BotSettings.query.first()
    payment_settings = PaymentSettings.query.first()
    return render_template('admin/settings.html',
                         bot_settings=bot_settings,
                         payment_settings=payment_settings)

@app.route('/admin/settings/update', methods=['POST'])
@admin_required
def update_settings():
    setting_type = request.form.get('setting_type')
    
    if setting_type == 'bot':
        bot_settings = BotSettings.query.first()
        if not bot_settings:
            bot_settings = BotSettings()
            db.session.add(bot_settings)
        
        bot_settings.bot_token = request.form.get('bot_token', '').strip()
        bot_settings.notifications_enabled = request.form.get('notifications_enabled') == 'on'
        bot_settings.welcome_message = request.form.get('welcome_message', '').strip()
        
    elif setting_type == 'paypal':
        payment_settings = PaymentSettings.query.first()
        if not payment_settings:
            payment_settings = PaymentSettings()
            db.session.add(payment_settings)
        
        payment_settings.paypal_client_id = request.form.get('paypal_client_id', '').strip()
        payment_settings.paypal_client_secret = request.form.get('paypal_client_secret', '').strip()
        payment_settings.paypal_sandbox = request.form.get('paypal_sandbox') == 'on'
    
    elif setting_type == 'nowpayments':
        payment_settings = PaymentSettings.query.first()
        if not payment_settings:
            payment_settings = PaymentSettings()
            db.session.add(payment_settings)
        
        payment_settings.nowpayments_api_key = request.form.get('nowpayments_api_key', '').strip()
    
    elif setting_type == 'payment':
        # Keep the old payment handler for backward compatibility
        payment_settings = PaymentSettings.query.first()
        if not payment_settings:
            payment_settings = PaymentSettings()
            db.session.add(payment_settings)
        
        # Only update fields that are provided
        paypal_client_id = request.form.get('paypal_client_id', '').strip()
        paypal_client_secret = request.form.get('paypal_client_secret', '').strip()
        nowpayments_api_key = request.form.get('nowpayments_api_key', '').strip()
        
        if paypal_client_id:
            payment_settings.paypal_client_id = paypal_client_id
        if paypal_client_secret:
            payment_settings.paypal_client_secret = paypal_client_secret
        if request.form.get('paypal_sandbox') is not None:
            payment_settings.paypal_sandbox = request.form.get('paypal_sandbox') == 'on'
        if nowpayments_api_key:
            payment_settings.nowpayments_api_key = nowpayments_api_key
    
    elif setting_type == 'admin':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        admin = Admin.query.get(session['admin_id'])
        if not admin.check_password(current_password):
            flash('Current password is incorrect', 'error')
            return redirect(url_for('admin_settings'))
        
        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return redirect(url_for('admin_settings'))
        
        if len(new_password) < 6:
            flash('New password must be at least 6 characters', 'error')
            return redirect(url_for('admin_settings'))
        
        admin.set_password(new_password)
    
    db.session.commit()
    flash('Settings updated successfully!', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/promo/<int:promo_id>/toggle', methods=['POST'])
@admin_required
def toggle_promo_status(promo_id):
    """Toggle promo code active status"""
    promo = PromoCode.query.get_or_404(promo_id)
    promo.is_active = not promo.is_active
    db.session.commit()
    
    status = 'activated' if promo.is_active else 'deactivated'
    flash(f'Promo code {promo.code} has been {status}', 'success')
    return redirect(url_for('admin_promos'))

@app.route('/admin/promo/<int:promo_id>/delete', methods=['POST'])
@admin_required
def delete_promo(promo_id):
    """Delete a promo code"""
    promo = PromoCode.query.get_or_404(promo_id)
    code = promo.code
    db.session.delete(promo)
    db.session.commit()
    
    flash(f'Promo code {code} has been deleted', 'success')
    return redirect(url_for('admin_promos'))

@app.route('/admin/channel/<int:channel_id>/delete', methods=['POST'])
@admin_required
def delete_channel(channel_id):
    """Delete a channel"""
    channel = Channel.query.get_or_404(channel_id)
    
    # Check if channel is used in any plans
    if channel.plan_channels:
        flash('Cannot delete channel - it is used in existing plans', 'error')
        return redirect(url_for('admin_channels'))
    
    name = channel.name
    db.session.delete(channel)
    db.session.commit()
    
    flash(f'Channel {name} has been deleted', 'success')
    return redirect(url_for('admin_channels'))

@app.route('/admin/plan/<int:plan_id>/edit', methods=['POST'])
@admin_required
def edit_plan(plan_id):
    """Edit an existing plan"""
    plan = Plan.query.get_or_404(plan_id)
    
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    plan_type = request.form.get('plan_type')
    price = request.form.get('price', type=float)
    duration_days = request.form.get('duration_days', type=int)
    is_lifetime = request.form.get('is_lifetime') == 'on'
    folder_link = request.form.get('folder_link', '').strip()
    channel_ids = request.form.getlist('channels')
    
    # Validation
    if not all([name, plan_type, price]):
        flash('Please fill in all required fields', 'error')
        return redirect(url_for('admin_plans'))
    
    # For lifetime plans, duration_days should be 0 or very high number
    if is_lifetime:
        duration_days = 36500  # 100 years as "lifetime"
    elif not duration_days or duration_days <= 0:
        flash('Please specify duration for non-lifetime plans', 'error')
        return redirect(url_for('admin_plans'))
    
    # Update plan
    plan.name = name
    plan.description = description
    plan.plan_type = plan_type
    plan.price = price
    plan.duration_days = duration_days
    plan.is_lifetime = is_lifetime
    plan.folder_link = folder_link if plan_type == 'bundle' else None
    
    # Update plan channels
    PlanChannel.query.filter_by(plan_id=plan_id).delete()
    for channel_id in channel_ids:
        plan_channel = PlanChannel(plan_id=plan.id, channel_id=int(channel_id))
        db.session.add(plan_channel)
    
    db.session.commit()
    
    plan_type_text = "Lifetime" if is_lifetime else "Regular"
    flash(f'{plan_type_text} plan updated successfully!', 'success')
    return redirect(url_for('admin_plans'))

@app.route('/admin/plan/<int:plan_id>/delete', methods=['POST'])
@admin_required
def delete_plan(plan_id):
    """Delete a plan"""
    plan = Plan.query.get_or_404(plan_id)
    
    # Check if plan has active subscriptions
    active_subs = Subscription.query.filter_by(plan_id=plan_id).filter(
        Subscription.end_date > datetime.utcnow()
    ).count()
    
    if active_subs > 0:
        flash('Cannot delete plan - it has active subscriptions', 'error')
        return redirect(url_for('admin_plans'))
    
    name = plan.name
    
    # Delete plan channels first
    PlanChannel.query.filter_by(plan_id=plan_id).delete()
    
    # Delete the plan
    db.session.delete(plan)
    db.session.commit()
    
    flash(f'Plan {name} has been deleted', 'success')
    return redirect(url_for('admin_plans'))

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    """Delete a user and all associated data"""
    user = User.query.get_or_404(user_id)
    
    # Check if user has active subscriptions
    active_subs = user.get_active_subscriptions()
    if active_subs:
        flash('Cannot delete user - they have active subscriptions', 'error')
        return redirect(url_for('admin_users'))
    
    username = user.telegram_username
    
    # Delete associated transactions
    Transaction.query.filter_by(user_id=user_id).delete()
    
    # Delete user
    db.session.delete(user)
    db.session.commit()
    
    flash(f'User {username} has been deleted', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/analytics')
@admin_required
def admin_analytics():
    """Admin analytics dashboard"""
    from sqlalchemy import func
    
    # User statistics
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True, is_banned=False).count()
    banned_users = User.query.filter_by(is_banned=True).count()
    
    # Subscription statistics
    total_subscriptions = Subscription.query.count()
    active_subscriptions = Subscription.query.filter(
        Subscription.end_date > datetime.utcnow()
    ).count()
    expired_subscriptions = Subscription.query.filter(
        Subscription.end_date <= datetime.utcnow()
    ).count()
    
    # Revenue statistics
    total_revenue = db.session.query(func.sum(Transaction.amount)).filter_by(
        status='completed'
    ).scalar() or 0
    
    monthly_revenue = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.status == 'completed',
        Transaction.created_at >= datetime.utcnow().replace(day=1)
    ).scalar() or 0
    
    # Popular plans
    popular_plans = db.session.query(
        Plan.name,
        func.count(Subscription.id).label('subscription_count')
    ).join(Subscription).group_by(Plan.id, Plan.name).order_by(
        func.count(Subscription.id).desc()
    ).limit(5).all()
    
    # Recent activity
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_transactions = Transaction.query.order_by(
        Transaction.created_at.desc()
    ).limit(10).all()
    
    return render_template('admin/analytics.html',
                         total_users=total_users,
                         active_users=active_users,
                         banned_users=banned_users,
                         total_subscriptions=total_subscriptions,
                         active_subscriptions=active_subscriptions,
                         expired_subscriptions=expired_subscriptions,
                         total_revenue=total_revenue,
                         monthly_revenue=monthly_revenue,
                         popular_plans=popular_plans,
                         recent_users=recent_users,
                         recent_transactions=recent_transactions)

@app.route('/admin/backup')
@admin_required
def admin_backup():
    """Database backup functionality"""
    import json
    from datetime import datetime
    
    try:
        # Create backup data
        backup_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'users': [],
            'plans': [],
            'channels': [],
            'subscriptions': [],
            'promo_codes': [],
            'transactions': []
        }
        
        # Export users (without sensitive data)
        for user in User.query.all():
            backup_data['users'].append({
                'id': user.id,
                'telegram_username': user.telegram_username,
                'created_at': user.created_at.isoformat(),
                'is_active': user.is_active,
                'is_banned': user.is_banned
            })
        
        # Export plans
        for plan in Plan.query.all():
            backup_data['plans'].append({
                'id': plan.id,
                'name': plan.name,
                'description': plan.description,
                'plan_type': plan.plan_type,
                'price': float(plan.price),
                'duration_days': plan.duration_days,
                'is_active': plan.is_active,
                'created_at': plan.created_at.isoformat()
            })
        
        # Export channels
        for channel in Channel.query.all():
            backup_data['channels'].append({
                'id': channel.id,
                'name': channel.name,
                'description': channel.description,
                'telegram_link': channel.telegram_link,
                'solo_price': float(channel.solo_price) if channel.solo_price else None,
                'solo_duration_days': channel.solo_duration_days,
                'is_active': channel.is_active,
                'created_at': channel.created_at.isoformat()
            })
        
        filename = f"telesignals_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        
        response = app.response_class(
            response=json.dumps(backup_data, indent=2),
            status=200,
            mimetype='application/json'
        )
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        return response
        
    except Exception as e:
        flash(f'Backup failed: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/manual-subscription', methods=['GET', 'POST'])
@admin_required
def admin_manual_subscription():
    """Manual subscription assignment tool"""
    from datetime import datetime, timedelta
    import logging
    
    if request.method == 'POST':
        try:
            # Get form data
            user_identifier = request.form.get('user_identifier', '').strip()
            plan_id = request.form.get('plan_id')
            subscription_type = request.form.get('subscription_type')
            duration_days = int(request.form.get('duration_days', 30))
            
            # Find user by Telegram ID or username
            user = None
            if user_identifier.isdigit():
                user = User.query.filter_by(telegram_chat_id=user_identifier).first()
            else:
                if user_identifier.startswith('@'):
                    user_identifier = user_identifier[1:]
                user = User.query.filter_by(telegram_username=user_identifier).first()
            
            if not user:
                flash(f'User not found: {user_identifier}', 'error')
                return redirect(url_for('admin_manual_subscription'))
            
            # Get plan
            plan = Plan.query.get(plan_id)
            if not plan:
                flash('Selected plan not found', 'error')
                return redirect(url_for('admin_manual_subscription'))
            
            # Create subscription
            end_date = datetime.utcnow() + timedelta(days=duration_days)
            if subscription_type == 'lifetime':
                end_date = datetime.utcnow() + timedelta(days=36500)  # 100 years
            
            subscription = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                start_date=datetime.utcnow(),
                end_date=end_date,
                is_paid=True
            )
            
            db.session.add(subscription)
            db.session.commit()
            
            logging.info(f"Admin {session['admin_username']} manually assigned subscription: User {user.telegram_username} -> Plan {plan.name}")
            flash(f'Successfully assigned {plan.name} to {user.telegram_username} for {duration_days} days', 'success')
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Manual subscription assignment failed: {e}")
            flash(f'Error assigning subscription: {str(e)}', 'error')
    
    # Get all plans and users for form
    plans = Plan.query.filter_by(is_active=True).all()
    recent_users = User.query.filter_by(is_active=True).order_by(User.created_at.desc()).limit(20).all()
    
    return render_template('admin/manual_subscription.html', plans=plans, recent_users=recent_users)

@app.route('/admin/user-ban-control', methods=['GET', 'POST'])
@admin_required
def admin_user_ban_control():
    """User ban control page"""
    import asyncio
    import logging
    
    if request.method == 'POST':
        action = request.form.get('action')
        user_identifier = request.form.get('user_identifier', '').strip()
        reason = request.form.get('reason', 'Admin action')
        
        try:
            # Find user
            user = None
            if user_identifier.isdigit():
                user_id = int(user_identifier)
                user = User.query.filter_by(telegram_chat_id=user_identifier).first()
            else:
                if user_identifier.startswith('@'):
                    user_identifier = user_identifier[1:]
                user = User.query.filter_by(telegram_username=user_identifier).first()
                if user and user.telegram_chat_id and user.telegram_chat_id.isdigit():
                    user_id = int(user.telegram_chat_id)
                else:
                    flash('User Telegram ID not found', 'error')
                    return redirect(url_for('admin_user_ban_control'))
            
            if not user:
                flash(f'User not found: {user_identifier}', 'error')
                return redirect(url_for('admin_user_ban_control'))
            
            # Execute ban/unban action
            if action == 'ban':
                # Update user status in database
                user.is_banned = True
                db.session.commit()
                
                # Try to execute Telegram bans
                try:
                    from enforcement_bot import admin_ban_user
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(admin_ban_user(user_id, reason))
                    loop.close()
                    
                    if 'error' in result:
                        flash(f'Database updated but Telegram ban failed: {result["error"]}', 'warning')
                    else:
                        successful = result.get('successful_bans', 0)
                        total = result.get('total_channels', 0)
                        flash(f'Banned user from {successful}/{total} channels', 'success')
                        
                except Exception as e:
                    logging.error(f"Telegram ban failed: {e}")
                    flash(f'User banned in database. Telegram ban failed: {str(e)}', 'warning')
                
                # Log action
                log_entry = BotLog(
                    action_type='manual_ban',
                    user_id=user_id,
                    reason=reason,
                    admin_user=session['admin_username'],
                    timestamp=datetime.utcnow()
                )
                db.session.add(log_entry)
                db.session.commit()
                
            elif action == 'unban':
                # Update user status in database
                user.is_banned = False
                db.session.commit()
                
                # Try to execute Telegram unbans
                try:
                    from enforcement_bot import admin_unban_user
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(admin_unban_user(user_id, reason))
                    loop.close()
                    
                    if 'error' in result:
                        flash(f'Database updated but Telegram unban failed: {result["error"]}', 'warning')
                    else:
                        successful = result.get('successful_unbans', 0)
                        total = result.get('total_channels', 0)
                        flash(f'Unbanned user from {successful}/{total} channels', 'success')
                        
                except Exception as e:
                    logging.error(f"Telegram unban failed: {e}")
                    flash(f'User unbanned in database. Telegram unban failed: {str(e)}', 'warning')
                
                # Log action
                log_entry = BotLog(
                    action_type='manual_unban',
                    user_id=user_id,
                    reason=reason,
                    admin_user=session['admin_username'],
                    timestamp=datetime.utcnow()
                )
                db.session.add(log_entry)
                db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Ban control action failed: {e}")
            flash(f'Action failed: {str(e)}', 'error')
    
    # Get recent bot logs
    recent_logs = BotLog.query.filter(
        BotLog.action_type.in_(['manual_ban', 'manual_unban'])
    ).order_by(BotLog.timestamp.desc()).limit(20).all()
    
    # Get recent users
    recent_users = User.query.filter_by(is_active=True).order_by(User.created_at.desc()).limit(20).all()
    
    return render_template('admin/user_ban_control.html', recent_logs=recent_logs, recent_users=recent_users)

@app.route('/admin/bot-logs')
@admin_required
def admin_bot_logs():
    """View bot action logs"""
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    logs = BotLog.query.order_by(BotLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('admin/bot_logs.html', logs=logs)

@app.route('/admin/enforcement-status')
@admin_required
def admin_enforcement_status():
    """Check enforcement bot status"""
    import asyncio
    
    try:
        from enforcement_bot import get_enforcement_bot
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot = loop.run_until_complete(get_enforcement_bot())
        loop.close()
        
        if bot:
            status = {
                'running': bot.running,
                'dry_run': bot.dry_run,
                'managed_channels': len(bot.managed_channels),
                'whitelisted_users': len(bot.whitelisted_users),
                'scan_interval': bot.scan_interval
            }
        else:
            status = {'running': False, 'error': 'Bot not initialized'}
            
    except Exception as e:
        status = {'running': False, 'error': str(e)}
    
    # Get recent statistics
    from datetime import timedelta
    
    recent_logs = BotLog.query.filter(
        BotLog.timestamp >= datetime.utcnow() - timedelta(hours=24)
    ).all()
    
    stats = {
        'total_actions_24h': len(recent_logs),
        'bans_24h': len([l for l in recent_logs if 'ban' in l.action_type and l.success]),
        'unbans_24h': len([l for l in recent_logs if 'unban' in l.action_type and l.success]),
        'errors_24h': len([l for l in recent_logs if not l.success])
    }
    
    total_channels = Channel.query.filter_by(is_active=True).count()
    
    return render_template('admin/enforcement_status.html', status=status, stats=stats, total_channels=total_channels)


@app.route('/admin/bot-setup', methods=['GET', 'POST'])
@admin_required
def admin_bot_setup():
    """Setup Telegram API credentials for enforcement bot"""
    if request.method == 'POST':
        try:
            action = request.form.get('action')
            
            if action == 'cancel_setup':
                # Clear session data
                session.pop('temp_bot_config', None)
                session.pop('otp_required', None)
                session.pop('phone_code_hash', None)
                flash('Bot setup cancelled', 'info')
                return redirect(url_for('admin_bot_setup'))
            
            elif action == 'submit_credentials':
                # Store credentials temporarily in session for OTP verification
                session['temp_bot_config'] = {
                    'api_id': request.form.get('api_id'),
                    'api_hash': request.form.get('api_hash'),
                    'bot_token': request.form.get('bot_token'),
                    'phone': request.form.get('phone'),
                    'mode': request.form.get('mode', 'dry-run')
                }
                
                # Initiate OTP verification
                from enforcement_bot import initiate_telegram_auth
                result = initiate_telegram_auth(
                    session['temp_bot_config']['api_id'],
                    session['temp_bot_config']['api_hash'],
                    session['temp_bot_config']['phone']
                )
                
                if result['success']:
                    session['otp_required'] = True
                    session['phone_code_hash'] = result.get('phone_code_hash')
                    flash('OTP sent to your phone. Please enter the verification code.', 'success')
                else:
                    flash(f'Failed to send OTP: {result["error"]}', 'error')
                    
            elif action == 'resend_otp':
                if not session.get('temp_bot_config'):
                    flash('No active setup session. Please start over.', 'error')
                    return redirect(url_for('admin_bot_setup'))
                
                temp_config = session['temp_bot_config']
                
                # Resend OTP
                from enforcement_bot import initiate_telegram_auth
                result = initiate_telegram_auth(
                    temp_config['api_id'],
                    temp_config['api_hash'],
                    temp_config['phone']
                )
                
                if result['success']:
                    session['phone_code_hash'] = result.get('phone_code_hash')
                    flash('OTP code resent to your phone. Please check your messages.', 'success')
                else:
                    flash(f'Failed to resend OTP: {result["error"]}', 'error')
                    
            elif action == 'verify_otp':
                if not session.get('otp_required'):
                    flash('No OTP verification in progress', 'error')
                    return redirect(url_for('admin_bot_setup'))
                
                otp_code = request.form.get('otp_code')
                temp_config = session.get('temp_bot_config')
                phone_code_hash = session.get('phone_code_hash')
                
                if not all([otp_code, temp_config, phone_code_hash]):
                    flash('Invalid verification attempt', 'error')
                    return redirect(url_for('admin_bot_setup'))
                
                # Verify OTP and complete setup
                from enforcement_bot import complete_telegram_auth
                result = complete_telegram_auth(
                    temp_config['api_id'],
                    temp_config['api_hash'],
                    temp_config['phone'],
                    otp_code,
                    phone_code_hash
                )
                
                if result['success']:
                    # Save credentials to environment/database
                    import os
                    os.environ['TELEGRAM_API_ID'] = temp_config['api_id']
                    os.environ['TELEGRAM_API_HASH'] = temp_config['api_hash']
                    os.environ['TELEGRAM_BOT_TOKEN'] = temp_config['bot_token']
                    os.environ['TELEGRAM_PHONE'] = temp_config['phone']
                    os.environ['BOT_MODE'] = temp_config['mode']
                    
                    # Save to database for persistence
                    bot_settings = BotSettings.query.first()
                    if not bot_settings:
                        bot_settings = BotSettings()
                        db.session.add(bot_settings)
                    
                    bot_settings.bot_token = temp_config['bot_token']
                    db.session.commit()
                    
                    # Clear session data
                    session.pop('temp_bot_config', None)
                    session.pop('otp_required', None)
                    session.pop('phone_code_hash', None)
                    
                    # Log the action
                    log_entry = BotLog(
                        action_type='bot_setup',
                        reason='Bot credentials configured successfully',
                        success=True,
                        admin_user=session.get('admin_username')
                    )
                    db.session.add(log_entry)
                    db.session.commit()
                    
                    flash('Bot credentials configured successfully! The enforcement bot will restart automatically.', 'success')
                    
                    # Restart enforcement bot with new credentials
                    from enforcement_bot import restart_enforcement_bot
                    restart_enforcement_bot()
                    
                else:
                    flash(f'OTP verification failed: {result["error"]}', 'error')
                    
            elif action == 'restart_bot':
                # Restart the enforcement bot
                from enforcement_bot import restart_enforcement_bot
                result = restart_enforcement_bot()
                
                if result['success']:
                    flash('Enforcement bot restarted successfully', 'success')
                else:
                    flash(f'Failed to restart bot: {result["error"]}', 'error')
                    
        except Exception as e:
            flash(f'Error during bot setup: {str(e)}', 'error')
            logging.error(f"Bot setup error: {e}")
        
        return redirect(url_for('admin_bot_setup'))
    
    # GET request - show setup form
    otp_required = session.get('otp_required', False)
    temp_config = session.get('temp_bot_config', {})
    
    # Check current bot status
    import os
    current_config = {
        'api_id': os.environ.get('TELEGRAM_API_ID'),
        'api_hash': bool(os.environ.get('TELEGRAM_API_HASH')),
        'bot_token': bool(os.environ.get('TELEGRAM_BOT_TOKEN')),
        'phone': os.environ.get('TELEGRAM_PHONE'),
        'mode': os.environ.get('BOT_MODE', 'dry-run')
    }
    
    return render_template('admin/bot_setup.html', 
                         otp_required=otp_required,
                         temp_config=temp_config,
                         current_config=current_config)

@app.route('/admin/channel-access')
@admin_required
def admin_channel_access():
    """Channel access management page"""
    try:
        from enforcement_bot import bulk_check_channels, get_session_status
        
        # Get bot status
        bot_status = get_session_status()
        
        # Get channel access status
        if bot_status.get('status', {}).get('bot_running'):
            access_results = bulk_check_channels()
        else:
            access_results = {'success': False, 'error': 'Bot not running'}
        
        return render_template('admin/channel_access.html',
                             bot_status=bot_status,
                             access_results=access_results)
    except Exception as e:
        flash(f'Error checking channel access: {str(e)}', 'error')
        return redirect(url_for('admin_channels'))

@app.route('/admin/check-channel-access/<int:channel_id>')
@admin_required
def check_single_channel_access(channel_id):
    """Check access for a single channel"""
    try:
        channel = Channel.query.get_or_404(channel_id)
        
        if not channel.telegram_channel_id:
            return jsonify({
                'success': False,
                'error': 'No channel ID configured'
            })
        
        from enforcement_bot import check_bot_channel_access
        result = check_bot_channel_access(channel.telegram_channel_id)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/admin/channel/<int:channel_id>/check-access', methods=['POST'])
@admin_required
def check_single_channel_access_post(channel_id):
    """Check access for a single channel via POST"""
    try:
        channel = Channel.query.get_or_404(channel_id)
        
        if not channel.telegram_channel_id:
            return jsonify({
                'success': False,
                'error': 'No channel ID configured'
            })
        
        from enforcement_bot import check_bot_channel_access
        result = check_bot_channel_access(channel.telegram_channel_id)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/admin/enforcement-settings', methods=['GET', 'POST'])
@admin_required
def admin_enforcement_settings():
    """Enforcement bot settings management"""
    if request.method == 'POST':
        try:
            # Update enforcement settings
            import os
            
            # Update bot mode
            new_mode = request.form.get('bot_mode', 'dry-run')
            if new_mode in ['dry-run', 'live']:
                os.environ['BOT_MODE'] = new_mode
                
                # Update .env file for persistence
                env_path = '.env'
                if os.path.exists(env_path):
                    with open(env_path, 'r') as f:
                        lines = f.readlines()
                    
                    # Update or add BOT_MODE line
                    found = False
                    for i, line in enumerate(lines):
                        if line.startswith('BOT_MODE='):
                            lines[i] = f'BOT_MODE={new_mode}\n'
                            found = True
                            break
                    
                    if not found:
                        lines.append(f'BOT_MODE={new_mode}\n')
                    
                    with open(env_path, 'w') as f:
                        f.writelines(lines)
                
                flash(f'Bot mode updated to {new_mode}', 'success')
                
                # Restart enforcement bot to apply new settings
                from enforcement_bot import restart_enforcement_bot
                restart_result = restart_enforcement_bot()
                
                if restart_result.get('success'):
                    flash('Enforcement bot restarted with new settings', 'success')
                else:
                    flash('Settings saved but bot restart failed', 'warning')
            else:
                flash('Invalid bot mode', 'error')
                
        except Exception as e:
            flash(f'Error updating settings: {str(e)}', 'error')
        
        return redirect(url_for('admin_enforcement_settings'))
    
    # GET request - show settings
    import os
    from enforcement_bot import get_session_status
    
    settings = {
        'bot_mode': os.environ.get('BOT_MODE', 'dry-run'),
        'api_configured': bool(os.environ.get('TELEGRAM_API_ID') and os.environ.get('TELEGRAM_API_HASH')),
        'scan_interval': 300,  # 5 minutes
        'max_actions_per_minute': 20
    }
    
    bot_status = get_session_status()
    
    return render_template('admin/enforcement_settings.html',
                         settings=settings,
                         bot_status=bot_status)

@app.route('/admin/manual-enforcement', methods=['POST'])
@admin_required
def admin_manual_enforcement():
    """Manual user ban/unban actions"""
    try:
        action = request.form.get('action')
        user_id = request.form.get('user_id', type=int)
        reason = request.form.get('reason', 'Manual admin action')
        
        if not user_id:
            flash('User ID is required', 'error')
            return redirect(url_for('admin_users'))
        
        # Get user for logging
        user = User.query.get(user_id)
        if not user:
            flash('User not found', 'error')
            return redirect(url_for('admin_users'))
        
        from enforcement_bot import admin_ban_user, admin_unban_user
        
        if action == 'ban':
            # Convert user ID to telegram chat ID for banning
            if user.telegram_chat_id:
                telegram_user_id = int(user.telegram_chat_id)
                
                # Run ban operation asynchronously
                import asyncio
                try:
                    result = asyncio.run(admin_ban_user(telegram_user_id, reason))
                    
                    if result.get('error'):
                        flash(f'Ban failed: {result["error"]}', 'error')
                    else:
                        successful_bans = result.get('successful_bans', 0)
                        total_channels = result.get('total_channels', 0)
                        flash(f'User banned from {successful_bans}/{total_channels} channels', 'success')
                        
                        # Update user status
                        user.is_banned = True
                        db.session.commit()
                        
                except Exception as e:
                    flash(f'Ban operation failed: {str(e)}', 'error')
            else:
                flash('User has no Telegram chat ID', 'error')
                
        elif action == 'unban':
            if user.telegram_chat_id:
                telegram_user_id = int(user.telegram_chat_id)
                
                import asyncio
                try:
                    result = asyncio.run(admin_unban_user(telegram_user_id, reason))
                    
                    if result.get('error'):
                        flash(f'Unban failed: {result["error"]}', 'error')
                    else:
                        successful_unbans = result.get('successful_unbans', 0)
                        total_channels = result.get('total_channels', 0)
                        flash(f'User unbanned from {successful_unbans}/{total_channels} channels', 'success')
                        
                        # Update user status
                        user.is_banned = False
                        db.session.commit()
                        
                except Exception as e:
                    flash(f'Unban operation failed: {str(e)}', 'error')
            else:
                flash('User has no Telegram chat ID', 'error')
        else:
            flash('Invalid action', 'error')
            
    except Exception as e:
        flash(f'Manual enforcement error: {str(e)}', 'error')
    
    return redirect(url_for('admin_users'))

@app.route('/admin/enforcement-logs')
@admin_required  
def admin_enforcement_logs():
    """View enforcement bot logs"""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    logs = BotLog.query.order_by(BotLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('admin/enforcement_logs.html', logs=logs)

@app.route('/admin/test-enforcement')
@admin_required
def admin_test_enforcement():
    """Test enforcement bot functionality"""
    try:
        from enforcement_bot import get_enforcement_bot
        import asyncio
        
        async def test_bot():
            bot = await get_enforcement_bot()
            if not bot or not bot.client:
                return {'success': False, 'error': 'Bot not available'}
            
            # Test basic connectivity
            try:
                me = await bot.client.get_me()
                return {
                    'success': True,
                    'bot_info': {
                        'id': me.id,
                        'username': me.username,
                        'first_name': me.first_name
                    }
                }
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        result = asyncio.run(test_bot())
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })
