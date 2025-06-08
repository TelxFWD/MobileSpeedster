from flask import render_template, request, redirect, url_for, session, flash, jsonify
from app import app, db
from models import *
from utils import admin_required
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
import json

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
    folder_link = request.form.get('folder_link', '').strip()
    channel_ids = request.form.getlist('channels')
    
    if not all([name, plan_type, price, duration_days]):
        flash('Please fill in all required fields', 'error')
        return redirect(url_for('admin_plans'))
    
    # Create plan
    plan = Plan(
        name=name,
        description=description,
        plan_type=plan_type,
        price=price,
        duration_days=duration_days,
        folder_link=folder_link if plan_type == 'bundle' else None
    )
    db.session.add(plan)
    db.session.flush()  # Get the plan ID
    
    # Add channels to plan
    for channel_id in channel_ids:
        plan_channel = PlanChannel(plan_id=plan.id, channel_id=int(channel_id))
        db.session.add(plan_channel)
    
    db.session.commit()
    flash('Plan created successfully!', 'success')
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
    solo_price = request.form.get('solo_price', type=float)
    solo_duration_days = request.form.get('solo_duration_days', type=int)
    
    if not all([name, telegram_link]):
        flash('Please fill in required fields', 'error')
        return redirect(url_for('admin_channels'))
    
    channel = Channel(
        name=name,
        description=description,
        telegram_link=telegram_link,
        solo_price=solo_price,
        solo_duration_days=solo_duration_days
    )
    db.session.add(channel)
    db.session.commit()
    
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
        
    elif setting_type == 'payment':
        payment_settings = PaymentSettings.query.first()
        if not payment_settings:
            payment_settings = PaymentSettings()
            db.session.add(payment_settings)
        
        payment_settings.paypal_client_id = request.form.get('paypal_client_id', '').strip()
        payment_settings.paypal_client_secret = request.form.get('paypal_client_secret', '').strip()
        payment_settings.paypal_sandbox = request.form.get('paypal_sandbox') == 'on'
        payment_settings.nowpayments_api_key = request.form.get('nowpayments_api_key', '').strip()
    
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
