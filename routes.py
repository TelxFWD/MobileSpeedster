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

@app.route('/api/promo/validate', methods=['POST'])
def api_validate_promo():
    """Enhanced API endpoint for real-time promo code validation"""
    try:
        data = request.get_json()
        code = data.get('code', '').strip().upper()
        plan_id = data.get('plan_id')
        
        if not code or not plan_id:
            return jsonify({'success': False, 'message': 'Code and plan ID required'})
        
        promo = PromoCode.query.filter_by(code=code, is_active=True).first()
        plan = Plan.query.get(plan_id)
        
        if not promo or not plan:
            return jsonify({'success': False, 'message': 'Invalid promo code'})
        
        if not promo.is_valid():
            return jsonify({'success': False, 'message': 'Promo code expired or usage limit reached'})
        
        original_price = float(plan.price)
        discount_amount = (original_price * promo.discount_percent) / 100
        discounted_price = original_price - discount_amount
        
        return jsonify({
            'success': True,
            'code': promo.code,
            'discount_percent': promo.discount_percent,
            'original_price': original_price,
            'discount_amount': discount_amount,
            'discounted_price': discounted_price,
            'savings': discount_amount
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': 'Validation error'})

@app.route('/user/subscription/<int:subscription_id>/cancel', methods=['POST'])
@login_required
def cancel_subscription(subscription_id):
    """Cancel a user subscription"""
    subscription = Subscription.query.filter_by(
        id=subscription_id, 
        user_id=session['user_id']
    ).first_or_404()
    
    if not subscription.is_active():
        flash('Subscription is already inactive', 'error')
        return redirect(url_for('dashboard'))
    
    # Mark subscription as cancelled (set end_date to now)
    subscription.end_date = datetime.utcnow()
    db.session.commit()
    
    flash('Subscription cancelled successfully', 'success')
    return redirect(url_for('dashboard'))

@app.route('/api/user/profile', methods=['GET', 'POST'])
@login_required
def user_profile_api():
    """User profile management API"""
    user = User.query.get(session['user_id'])
    
    if request.method == 'GET':
        return jsonify({
            'success': True,
            'user': {
                'telegram_username': user.telegram_username,
                'created_at': user.created_at.isoformat(),
                'is_active': user.is_active,
                'subscription_count': len(user.get_active_subscriptions())
            }
        })
    
    elif request.method == 'POST':
        data = request.get_json()
        new_pin = data.get('new_pin')
        current_pin = data.get('current_pin')
        
        if not current_pin or not user.check_pin(current_pin):
            return jsonify({'success': False, 'message': 'Invalid current PIN'})
        
        if not new_pin or not validate_pin(new_pin):
            return jsonify({'success': False, 'message': 'New PIN must be 4 digits'})
        
        user.set_pin(new_pin)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'PIN updated successfully'})

@app.route('/api/plans/search')
def search_plans():
    """Search plans by type and filters"""
    plan_type = request.args.get('type', 'all')
    search_term = request.args.get('q', '').strip()
    
    query = Plan.query.filter_by(is_active=True)
    
    if plan_type and plan_type != 'all':
        query = query.filter_by(plan_type=plan_type)
    
    if search_term:
        query = query.filter(
            db.or_(
                Plan.name.ilike(f'%{search_term}%'),
                Plan.description.ilike(f'%{search_term}%')
            )
        )
    
    plans = query.order_by(Plan.created_at.desc()).all()
    
    return jsonify({
        'success': True,
        'plans': [{
            'id': plan.id,
            'name': plan.name,
            'description': plan.description,
            'plan_type': plan.plan_type,
            'price': plan.price,
            'duration_days': plan.duration_days,
            'channels': [{'name': ch.name} for ch in plan.get_channels()]
        } for plan in plans]
    })
