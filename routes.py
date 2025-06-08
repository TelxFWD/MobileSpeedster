from flask import render_template, request, redirect, url_for, session, flash, jsonify
from app import app, db
from models import *
from utils import login_required, calculate_discounted_price
from datetime import datetime, timedelta
import logging

@app.route('/')
def index():
    # Get site content
    hero_content = SiteContent.query.filter_by(key='hero').first()
    about_content = SiteContent.query.filter_by(key='about').first()
    
    return render_template('index.html', 
                         hero_content=hero_content,
                         about_content=about_content)

@app.route('/bundles')
def bundles():
    bundle_plans = Plan.query.filter_by(plan_type='bundle', is_active=True).all()
    return render_template('bundles.html', plans=bundle_plans)

@app.route('/channels')
def channels():
    solo_plans = Plan.query.filter_by(plan_type='solo', is_active=True).all()
    solo_channels = Channel.query.filter(
        Channel.is_active == True,
        Channel.solo_price.isnot(None)
    ).all()
    return render_template('channels.html', plans=solo_plans, channels=solo_channels)

@app.route('/support')
def support():
    faq_content = SiteContent.query.filter_by(key='faq').first()
    contact_content = SiteContent.query.filter_by(key='contact').first()
    
    # Default FAQ if none exists
    default_faq = [
        {
            'question': 'How do I access the channels after subscription?',
            'answer': 'After successful payment, you will receive a Telegram message with channel links and your dashboard will be updated with access information.'
        },
        {
            'question': 'What payment methods do you accept?',
            'answer': 'We accept PayPal and various cryptocurrencies through NOWPayments.'
        },
        {
            'question': 'Can I cancel my subscription?',
            'answer': 'Subscriptions are non-refundable but you can choose not to renew when they expire.'
        },
        {
            'question': 'How do I get support?',
            'answer': 'You can contact us through Telegram or email listed on this page.'
        }
    ]
    
    return render_template('support.html', 
                         faq_content=faq_content,
                         contact_content=contact_content,
                         default_faq=default_faq)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        mode = request.form.get('mode', 'login')
        telegram_username = request.form.get('telegram_username', '').strip()
        pin = request.form.get('pin', '').strip()
        
        if not telegram_username or not pin:
            flash('Please fill in all fields', 'error')
            return render_template('login.html')
        
        # Remove @ if present
        if telegram_username.startswith('@'):
            telegram_username = telegram_username[1:]
        
        if mode == 'signup':
            # Check if user already exists
            existing_user = User.query.filter_by(telegram_username=telegram_username).first()
            if existing_user:
                flash('Username already exists', 'error')
                return render_template('login.html')
            
            # Validate PIN (4 digits)
            if not pin.isdigit() or len(pin) != 4:
                flash('PIN must be exactly 4 digits', 'error')
                return render_template('login.html')
            
            # Create new user
            new_user = User(telegram_username=telegram_username)
            new_user.set_pin(pin)
            db.session.add(new_user)
            db.session.commit()
            
            session['user_id'] = new_user.id
            session['telegram_username'] = new_user.telegram_username
            flash('Account created successfully!', 'success')
            
            # Redirect to intended page or dashboard
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('dashboard'))
        
        else:  # login mode
            user = User.query.filter_by(telegram_username=telegram_username).first()
            if user and user.check_pin(pin) and user.is_active and not user.is_banned:
                session['user_id'] = user.id
                session['telegram_username'] = user.telegram_username
                flash('Logged in successfully!', 'success')
                
                # Redirect to intended page or dashboard
                next_page = request.args.get('next')
                if next_page:
                    return redirect(next_page)
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid credentials or account disabled', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))

@app.route('/checkout/<int:plan_id>')
def checkout(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    if not plan.is_active:
        flash('This plan is no longer available', 'error')
        return redirect(url_for('index'))
    
    # Get payment settings for frontend
    payment_settings = PaymentSettings.query.first()
    
    return render_template('checkout.html', 
                         plan=plan,
                         payment_settings=payment_settings)

@app.route('/validate_promo', methods=['POST'])
def validate_promo():
    promo_code = request.form.get('promo_code', '').strip().upper()
    plan_id = request.form.get('plan_id')
    
    if not promo_code:
        return jsonify({'valid': False, 'message': 'No promo code provided'})
    
    plan = Plan.query.get(plan_id)
    if not plan:
        return jsonify({'valid': False, 'message': 'Invalid plan'})
    
    promo = PromoCode.query.filter_by(code=promo_code).first()
    if not promo or not promo.is_valid():
        return jsonify({'valid': False, 'message': 'Invalid or expired promo code'})
    
    discounted_price = calculate_discounted_price(plan.price, promo.discount_percent)
    
    return jsonify({
        'valid': True,
        'discount_percent': promo.discount_percent,
        'original_price': plan.price,
        'discounted_price': discounted_price,
        'savings': plan.price - discounted_price
    })

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    active_subscriptions = user.get_active_subscriptions()
    
    return render_template('dashboard.html', 
                         user=user,
                         active_subscriptions=active_subscriptions)

@app.route('/renew/<int:subscription_id>')
@login_required
def renew_subscription(subscription_id):
    subscription = Subscription.query.get_or_404(subscription_id)
    
    # Verify subscription belongs to current user
    if subscription.user_id != session['user_id']:
        flash('Unauthorized', 'error')
        return redirect(url_for('dashboard'))
    
    return redirect(url_for('checkout', plan_id=subscription.plan_id))

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500
