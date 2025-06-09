from flask import request, redirect, url_for, flash, session, jsonify, render_template
from app import app, db
from models import *
from utils import generate_transaction_id
from datetime import datetime, timedelta
import requests
import json
import logging
import os

# PayPal API endpoints
PAYPAL_SANDBOX_API = "https://api.sandbox.paypal.com"
PAYPAL_LIVE_API = "https://api.paypal.com"

# NOWPayments API endpoint
NOWPAYMENTS_API = "https://api.nowpayments.io/v1"

def get_paypal_access_token(is_sandbox=True):
    """Get PayPal access token"""
    payment_settings = PaymentSettings.query.first()
    if not payment_settings or not payment_settings.paypal_client_id:
        return None
    
    base_url = PAYPAL_SANDBOX_API if is_sandbox else PAYPAL_LIVE_API
    auth_url = f"{base_url}/v1/oauth2/token"
    
    auth = (payment_settings.paypal_client_id, payment_settings.paypal_client_secret)
    headers = {
        'Accept': 'application/json',
        'Accept-Language': 'en_US',
    }
    data = 'grant_type=client_credentials'
    
    try:
        response = requests.post(auth_url, headers=headers, data=data, auth=auth)
        if response.status_code == 200:
            return response.json().get('access_token')
    except Exception as e:
        logging.error(f"PayPal auth error: {e}")
    
    return None

def cleanup_expired_sessions():
    """Clean up expired payment sessions"""
    try:
        if 'payment_order' in session:
            payment_order = session['payment_order']
            if 'expires_at' in payment_order:
                expires_at = datetime.fromisoformat(payment_order['expires_at'])
                if datetime.utcnow() > expires_at:
                    logging.info("Cleaning up expired payment session")
                    session.pop('payment_order', None)
                    return True
    except Exception as e:
        logging.error(f"Error cleaning up session: {e}")
        session.pop('payment_order', None)
    return False

@app.route('/create_paypal_order', methods=['POST'])
def create_paypal_order():
    """Create PayPal order"""
    try:
        plan_id = request.form.get('plan_id', type=int)
        telegram_username = request.form.get('telegram_username', '').strip()
        promo_code = request.form.get('promo_code', '').strip()
        
        if not plan_id or not telegram_username:
            return jsonify({'error': 'Missing required fields'}), 400
        
        plan = Plan.query.get(plan_id)
        if not plan or not plan.is_active:
            return jsonify({'error': 'Invalid plan'}), 400
        
        # Calculate price with promo code
        final_price = plan.price
        if promo_code:
            promo = PromoCode.query.filter_by(code=promo_code.upper()).first()
            if promo and promo.is_valid():
                final_price = final_price * (1 - promo.discount_percent / 100)
        
        # Get PayPal settings
        payment_settings = PaymentSettings.query.first()
        if not payment_settings:
            return jsonify({'error': 'Payment not configured'}), 500
        
        access_token = get_paypal_access_token(payment_settings.paypal_sandbox)
        if not access_token:
            return jsonify({'error': 'PayPal authentication failed'}), 500
        
        # Create PayPal order
        base_url = PAYPAL_SANDBOX_API if payment_settings.paypal_sandbox else PAYPAL_LIVE_API
        order_url = f"{base_url}/v2/checkout/orders"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}',
        }
        
        order_data = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {
                    "currency_code": "USD",
                    "value": f"{final_price:.2f}"
                },
                "description": f"{plan.name} Subscription"
            }],
            "application_context": {
                "return_url": url_for('paypal_success', _external=True),
                "cancel_url": url_for('paypal_cancel', _external=True)
            }
        }
        
        response = requests.post(order_url, headers=headers, json=order_data)
        
        if response.status_code == 201:
            order = response.json()
            
            # Store order info in session with timestamp
            session['payment_order'] = {
                'order_id': order['id'],
                'plan_id': plan_id,
                'telegram_username': telegram_username,
                'promo_code': promo_code,
                'amount': final_price,
                'created_at': datetime.utcnow().isoformat(),
                'expires_at': (datetime.utcnow() + timedelta(minutes=30)).isoformat()
            }
            
            # Get approval URL
            approval_url = None
            for link in order.get('links', []):
                if link.get('rel') == 'approve':
                    approval_url = link.get('href')
                    break
            
            return jsonify({'approval_url': approval_url})
        else:
            logging.error(f"PayPal order creation failed: {response.text}")
            return jsonify({'error': 'Failed to create PayPal order'}), 500
            
    except Exception as e:
        logging.error(f"PayPal order creation error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/paypal/success')
def paypal_success():
    """Handle PayPal payment success"""
    try:
        # Log all callback parameters for debugging
        logging.info(f"PayPal callback received with parameters: {dict(request.args)}")
        
        # PayPal returns 'token' in callback which is the order ID
        order_id = request.args.get('token') or request.args.get('orderID') or request.args.get('order_id')
        payment_order = session.get('payment_order')
        
        # Enhanced validation with logging
        if not order_id:
            logging.error("PayPal success: No order ID provided in callback")
            flash('Payment verification failed - missing order ID', 'error')
            return redirect(url_for('index'))
            
        if not payment_order:
            logging.error(f"PayPal success: No payment session found for order {order_id}")
            flash('Payment session expired. Please try again.', 'error')
            return redirect(url_for('index'))
            
        if payment_order.get('order_id') != order_id:
            logging.error(f"PayPal success: Order ID mismatch. Session: {payment_order.get('order_id')}, Callback: {order_id}")
            flash('Payment verification failed - order mismatch', 'error')
            return redirect(url_for('index'))
            
        # Check session expiration
        if 'expires_at' in payment_order:
            expires_at = datetime.fromisoformat(payment_order['expires_at'])
            if datetime.utcnow() > expires_at:
                logging.error(f"PayPal success: Payment session expired for order {order_id}")
                session.pop('payment_order', None)
                flash('Payment session expired. Please try again.', 'error')
                return redirect(url_for('index'))
        
        # Log successful callback
        logging.info(f"PayPal success callback received for order: {order_id}")
        logging.info(f"Payment order data: {payment_order}")
        
        # Capture the payment
        payment_settings = PaymentSettings.query.first()
        if not payment_settings:
            logging.error("PayPal success: No payment settings configured")
            flash('Payment configuration error. Please contact support.', 'error')
            return redirect(url_for('index'))
            
        access_token = get_paypal_access_token(payment_settings.paypal_sandbox)
        
        if not access_token:
            logging.error("PayPal success: Failed to get access token")
            flash('Payment verification failed. Please contact support.', 'error')
            return redirect(url_for('index'))
        
        base_url = PAYPAL_SANDBOX_API if payment_settings.paypal_sandbox else PAYPAL_LIVE_API
        capture_url = f"{base_url}/v2/checkout/orders/{order_id}/capture"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}',
        }
        
        response = requests.post(capture_url, headers=headers)
        
        if response.status_code == 201:
            capture_data = response.json()
            
            # Process successful payment
            success = process_successful_payment(
                payment_order['telegram_username'],
                payment_order['plan_id'],
                payment_order['promo_code'],
                payment_order['amount'],
                'paypal',
                order_id,
                capture_data
            )
            
            if success:
                session.pop('payment_order', None)
                flash('Payment successful! Your subscription is now active.', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Payment processed but subscription activation failed. Please contact support.', 'error')
        else:
            flash('Payment capture failed. Please contact support.', 'error')
            
    except Exception as e:
        logging.error(f"PayPal success handling error: {e}")
        flash('Payment processing error. Please contact support.', 'error')
    
    return redirect(url_for('index'))

@app.route('/paypal/cancel')
def paypal_cancel():
    """Handle PayPal payment cancellation"""
    session.pop('payment_order', None)
    flash('Payment cancelled', 'info')
    return redirect(url_for('index'))

@app.route('/create_crypto_payment', methods=['POST'])
def create_crypto_payment():
    """Create NOWPayments crypto payment"""
    try:
        plan_id = request.form.get('plan_id', type=int)
        telegram_username = request.form.get('telegram_username', '').strip()
        promo_code = request.form.get('promo_code', '').strip()
        currency = request.form.get('crypto_currency', 'btc').lower()
        
        if not plan_id or not telegram_username:
            return jsonify({'error': 'Missing required fields'}), 400
        
        plan = Plan.query.get(plan_id)
        if not plan or not plan.is_active:
            return jsonify({'error': 'Invalid plan'}), 400
        
        # Calculate price with promo code
        final_price = plan.price
        if promo_code:
            promo = PromoCode.query.filter_by(code=promo_code.upper()).first()
            if promo and promo.is_valid():
                final_price = final_price * (1 - promo.discount_percent / 100)
        
        # Get NOWPayments API key
        payment_settings = PaymentSettings.query.first()
        if not payment_settings or not payment_settings.nowpayments_api_key:
            return jsonify({'error': 'Crypto payments not configured'}), 500
        
        # First, check if the currency is available
        headers = {
            'x-api-key': payment_settings.nowpayments_api_key,
            'Content-Type': 'application/json'
        }
        
        # Get available currencies
        try:
            currencies_response = requests.get(f'{NOWPAYMENTS_API}/currencies', headers=headers)
            if currencies_response.status_code == 200:
                available_currencies = currencies_response.json().get('currencies', [])
                logging.info(f"Available currencies: {available_currencies[:10]}...")  # Log first 10 for debugging
                
                # Check if requested currency is available
                if currency not in available_currencies:
                    # Try common variations for USDT
                    if currency == 'usdt':
                        # Check for USDT variations
                        usdt_variants = ['usdttrc20', 'usdterc20', 'usdt-trc20', 'usdt-erc20', 'tether']
                        found_variant = None
                        for variant in usdt_variants:
                            if variant in available_currencies:
                                found_variant = variant
                                break
                        
                        if found_variant:
                            currency = found_variant
                            logging.info(f"Using USDT variant: {found_variant}")
                        else:
                            # Return error instead of fallback for USDT
                            return jsonify({'error': 'USDT is not available. Please select a different cryptocurrency.'}), 400
                    else:
                        # For other currencies, fall back to BTC
                        logging.warning(f"Currency {currency} not available, falling back to BTC")
                        currency = 'btc'
                else:
                    logging.info(f"Using requested currency: {currency}")
            else:
                logging.warning(f"Could not fetch currencies: {currencies_response.text}")
                # Don't fallback, return error
                return jsonify({'error': 'Unable to verify cryptocurrency availability. Please try again.'}), 500
        except Exception as e:
            logging.warning(f"Error checking currencies: {e}")
            return jsonify({'error': 'Cryptocurrency service temporarily unavailable. Please try again.'}), 500
        
        # Create payment with improved error handling
        payment_data = {
            'price_amount': round(final_price, 2),
            'price_currency': 'usd',
            'pay_currency': currency,
            'order_id': generate_transaction_id(),
            'order_description': f'{plan.name} Subscription'
        }
        
        logging.info(f"Creating NOWPayments order: {payment_data}")
        
        response = requests.post(f'{NOWPAYMENTS_API}/payment', 
                               headers=headers, json=payment_data, timeout=30)
        
        logging.info(f"NOWPayments response: {response.status_code} - {response.text}")
        
        if response.status_code == 201:
            payment = response.json()
            
            # Remove @ if present
            if telegram_username.startswith('@'):
                telegram_username = telegram_username[1:]
            
            # Get or create user for crypto payments
            user = User.query.filter_by(telegram_username=telegram_username).first()
            if not user:
                # Create user with default PIN for crypto payments
                user = User(telegram_username=telegram_username)
                user.set_pin('0000')  # Default PIN, user must change on first login
                db.session.add(user)
                db.session.flush()  # Get the user ID
            
            # Store payment info with network information
            network = payment.get('network', '')
            transaction = Transaction(
                user_id=user.id,
                transaction_id=payment['order_id'],
                payment_method='crypto',
                amount=final_price,
                currency=currency.upper(),
                network=network,
                status='pending',
                webhook_data=json.dumps({
                    'plan_id': plan_id,
                    'telegram_username': telegram_username,
                    'promo_code': promo_code,
                    'nowpayments_id': payment['payment_id'],
                    'network': network
                })
            )
            db.session.add(transaction)
            db.session.commit()
            
            return jsonify({
                'payment_address': payment['pay_address'],
                'pay_amount': payment['pay_amount'],
                'pay_currency': payment['pay_currency'],
                'network': payment.get('network', ''),
                'order_id': payment['order_id']
            })
        else:
            error_msg = f"NOWPayments creation failed: Status {response.status_code} - {response.text}"
            logging.error(error_msg)
            
            # Try to parse error message for user-friendly response
            try:
                error_data = response.json()
                user_message = error_data.get('message', 'Failed to create crypto payment')
                if 'estimate' in user_message.lower():
                    user_message = 'Cryptocurrency service temporarily unavailable. Please try again later or use PayPal.'
            except:
                user_message = 'Failed to create crypto payment. Please try again later.'
            
            return jsonify({'error': user_message}), 500
            
    except requests.exceptions.Timeout:
        logging.error("NOWPayments request timeout")
        return jsonify({'error': 'Payment service timeout. Please try again.'}), 500
    except requests.exceptions.RequestException as e:
        logging.error(f"NOWPayments request error: {e}")
        return jsonify({'error': 'Payment service unavailable. Please try again later.'}), 500
    except Exception as e:
        logging.error(f"Crypto payment creation error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/webhook/nowpayments', methods=['POST'])
def nowpayments_webhook():
    """Handle NOWPayments webhook"""
    try:
        data = request.get_json()
        if not data:
            return 'No data', 400
        
        # Find transaction
        order_id = data.get('order_id')
        transaction = Transaction.query.filter_by(transaction_id=order_id).first()
        
        if not transaction:
            logging.error(f"Transaction not found for order_id: {order_id}")
            return 'Transaction not found', 404
        
        # Update transaction status
        payment_status = data.get('payment_status')
        transaction.status = payment_status
        transaction.webhook_data = json.dumps(data)
        
        if payment_status == 'finished':
            # Payment completed, activate subscription
            webhook_data = json.loads(transaction.webhook_data)
            
            success = process_successful_payment(
                webhook_data['telegram_username'],
                webhook_data['plan_id'],
                webhook_data.get('promo_code'),
                transaction.amount,
                'crypto',
                order_id,
                data
            )
            
            if success:
                transaction.completed_at = datetime.utcnow()
        
        db.session.commit()
        return 'OK', 200
        
    except Exception as e:
        logging.error(f"NOWPayments webhook error: {e}")
        return 'Error', 500

@app.route('/api/payment/status/<order_id>')
def check_payment_status(order_id):
    """Check payment status for debugging"""
    try:
        payment_order = session.get('payment_order')
        
        return jsonify({
            'order_id': order_id,
            'session_exists': payment_order is not None,
            'session_order_id': payment_order.get('order_id') if payment_order else None,
            'session_expired': cleanup_expired_sessions(),
            'current_time': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/test/nowpayments')
def test_nowpayments():
    """Test NOWPayments API connection"""
    try:
        payment_settings = PaymentSettings.query.first()
        if not payment_settings or not payment_settings.nowpayments_api_key:
            return jsonify({'error': 'NOWPayments not configured'}), 500
        
        headers = {
            'x-api-key': payment_settings.nowpayments_api_key,
            'Content-Type': 'application/json'
        }
        
        # Test API status
        status_response = requests.get(f'{NOWPAYMENTS_API}/status', headers=headers, timeout=10)
        
        # Test available currencies
        currencies_response = requests.get(f'{NOWPAYMENTS_API}/currencies', headers=headers, timeout=10)
        
        return jsonify({
            'api_status': {
                'status_code': status_response.status_code,
                'response': status_response.json() if status_response.status_code == 200 else status_response.text
            },
            'currencies': {
                'status_code': currencies_response.status_code,
                'available': currencies_response.json().get('currencies', [])[:10] if currencies_response.status_code == 200 else []
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def process_successful_payment(telegram_username, plan_id, promo_code, amount, payment_method, transaction_id, webhook_data):
    """Process successful payment and activate subscription"""
    try:
        # Remove @ if present
        if telegram_username.startswith('@'):
            telegram_username = telegram_username[1:]
        
        # Get or create user
        user = User.query.filter_by(telegram_username=telegram_username).first()
        if not user:
            # For payments, we create user automatically if they don't exist
            # They'll need to set a PIN when they first login
            user = User(telegram_username=telegram_username)
            user.set_pin('0000')  # Default PIN, user must change on first login
            db.session.add(user)
            db.session.flush()
        
        # Get plan
        plan = Plan.query.get(plan_id)
        if not plan:
            logging.error(f"Plan not found: {plan_id}")
            return False
        
        # Check for existing active subscription to prevent duplicates
        existing_sub = Subscription.query.filter_by(
            user_id=user.id,
            plan_id=plan_id
        ).filter(
            Subscription.end_date > datetime.utcnow(),
            Subscription.is_paid == True
        ).first()
        
        if existing_sub:
            # Extend existing subscription instead of creating new one
            existing_sub.end_date += timedelta(days=plan.duration_days)
        else:
            # Create new subscription
            subscription = Subscription(
                user_id=user.id,
                plan_id=plan_id,
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow() + timedelta(days=plan.duration_days),
                is_paid=True
            )
            db.session.add(subscription)
            db.session.flush()
        
        # Create transaction record
        transaction = Transaction(
            user_id=user.id,
            subscription_id=subscription.id if not existing_sub else existing_sub.id,
            transaction_id=transaction_id,
            payment_method=payment_method,
            amount=amount,
            currency='USD',
            status='completed',
            webhook_data=json.dumps(webhook_data),
            completed_at=datetime.utcnow()
        )
        db.session.add(transaction)
        
        # Update promo code usage if used
        if promo_code:
            promo = PromoCode.query.filter_by(code=promo_code.upper()).first()
            if promo and promo.is_valid():
                promo.used_count += 1
        
        db.session.commit()
        
        # Send Telegram notification
        from telegram_bot import send_subscription_notification
        send_subscription_notification(user, plan)
        
        return True
        
    except Exception as e:
        logging.error(f"Payment processing error: {e}")
        db.session.rollback()
        return False
