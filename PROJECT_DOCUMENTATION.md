
# TeleSignals - Telegram Trading Signals Platform

## Project Overview

TeleSignals is a comprehensive web-based platform for managing and selling Telegram trading signal subscriptions. It combines a Flask web application with Telegram bot integration to provide a complete subscription management system for trading signal providers.

## Architecture & Technology Stack

### Backend Framework
- **Flask**: Main web framework
- **SQLAlchemy & Flask-SQLAlchemy**: ORM for database operations
- **Gunicorn**: WSGI HTTP Server for production deployment
- **PostgreSQL**: Primary database (with SQLite fallback for development)

### Frontend Technologies
- **Tailwind CSS**: Utility-first CSS framework (currently via CDN)
- **Alpine.js**: Lightweight JavaScript framework for interactivity
- **Feather Icons**: Icon library
- **Responsive Design**: Mobile-optimized interface

### External Integrations
- **Telegram Bot API**: For bot functionality and user interaction
- **PayPal API**: Payment processing
- **NOWPayments API**: Cryptocurrency payment processing

## Database Schema

### Core Models

#### User Model
- Stores user information including Telegram username and chat ID
- Secure PIN-based authentication (hashed)
- Tracks subscription status and ban status
- Relationships: subscriptions, transactions

#### Admin Model
- Administrative user accounts
- Password-based authentication (hashed)
- Session management and login tracking

#### Channel Model
- Telegram signal channels/groups
- Individual pricing for solo subscriptions
- Can be active/inactive
- Relationships: plan associations

#### Plan Model
- Subscription plans (solo channels or bundles)
- Pricing and duration configuration
- Support for both individual channels and bundle packages
- Optional folder links for bundle access

#### Subscription Model
- User subscription records
- Tracks active subscriptions and expiration dates
- Payment status tracking
- Automatic expiration handling

#### Transaction Model
- Payment transaction records
- Support for multiple payment methods (PayPal, crypto)
- Webhook data storage for payment verification

#### PromoCode Model
- Discount code system
- Usage limits and expiration dates
- Percentage-based discounts

### Support Models
- **PlanChannel**: Many-to-many relationship between plans and channels
- **SiteContent**: CMS for website content management
- **BotSettings**: Telegram bot configuration
- **PaymentSettings**: Payment gateway configurations

## Application Structure

### Core Files

#### main.py
- Application entry point
- Imports the Flask app from app.py

#### app.py
- Flask application factory
- Database initialization
- Default admin user creation
- Route imports and bot service startup

#### models.py
- All SQLAlchemy model definitions
- Database relationships and constraints
- Business logic methods (e.g., subscription validation)

#### config.py
- Configuration management with environment-based settings
- Development, production, and testing configurations
- Security and database settings

### Route Handlers

#### routes.py
- Public-facing routes (homepage, channels, bundles, checkout)
- User authentication and dashboard
- Subscription management

#### admin_routes.py
- Administrative interface routes
- Channel and plan management
- User management and analytics
- Content management system

#### payment_handler.py
- Payment processing logic
- PayPal and cryptocurrency payment handling
- Webhook processing for payment verification

### Bot Integration

#### bot_service.py
- Telegram bot service implementation
- Background thread management
- User interaction handling

#### telegram_bot.py / bot_runner.py
- Bot command handlers
- Message processing
- Integration with web application database

## Key Features

### User Management
- Telegram username-based registration
- Secure PIN authentication
- Subscription tracking and management
- Ban/unban functionality

### Subscription System
- Individual channel subscriptions
- Bundle packages with multiple channels
- Flexible pricing and duration options
- Automatic expiration handling
- Grace period support

### Payment Processing
- PayPal integration for traditional payments
- Cryptocurrency payments via NOWPayments
- Transaction tracking and verification
- Webhook handling for payment confirmation

### Administrative Interface
- Comprehensive admin dashboard
- Channel and plan management
- User management and analytics
- Content management system
- Promotional code system
- Payment gateway configuration

### Content Management
- Dynamic website content editing
- Hero section customization
- About section management
- FAQ system

## Security Features

### Authentication & Authorization
- Hashed PIN storage for users
- Secure admin password handling
- Session management with secure cookies
- CSRF protection

### Data Protection
- SQL injection prevention via SQLAlchemy ORM
- Input validation and sanitization
- Secure environment variable handling

## Deployment Configuration

### Production Setup
- Gunicorn WSGI server
- PostgreSQL database
- Environment-based configuration
- Secure session handling

### Development Setup
- SQLite database fallback
- Debug mode with auto-reload
- Simplified authentication

## Environment Variables

### Required Configuration
- `DATABASE_URL`: Database connection string
- `TELEGRAM_BOT_TOKEN`: Telegram bot API token
- `SECRET_KEY`: Flask session encryption key

### Payment Integration
- `PAYPAL_CLIENT_ID` & `PAYPAL_CLIENT_SECRET`: PayPal API credentials
- `NOWPAYMENTS_API_KEY`: Cryptocurrency payment API key
- Sandbox mode flags for testing

### Optional Settings
- `SESSION_SECRET`: Additional session security
- Email configuration for notifications
- Logging and cache settings

## API Integrations

### Telegram Bot API
- User interaction and command handling
- Message sending and receiving
- Chat management and user verification

### Payment Gateways
- PayPal REST API for traditional payments
- NOWPayments API for cryptocurrency
- Webhook endpoints for payment confirmation

## File Structure Organization

### Templates Directory
- Jinja2 HTML templates with Tailwind CSS styling
- Responsive design patterns
- Admin interface templates separate from public templates

### Static Assets
- CSS customizations
- JavaScript enhancements
- Image assets and icons

### Database Migrations
- Schema migration scripts
- Data transformation utilities
- Database setup and maintenance tools

## Business Logic

### Subscription Management
- Automatic expiration checking
- Grace period handling
- Subscription renewal and upgrade paths
- Bundle vs. individual channel logic

### Payment Processing
- Multi-gateway payment support
- Transaction verification and logging
- Refund and chargeback handling
- Currency conversion support

### User Experience
- Mobile-responsive interface
- Real-time status updates
- Intuitive navigation and workflows
- Error handling and user feedback

## Development Workflow

### Local Development
- SQLite database for quick setup
- Debug mode with detailed error messages
- Hot reload for development efficiency

### Production Deployment
- PostgreSQL for production reliability
- Gunicorn for production serving
- Environment-based configuration switching

This documentation provides a comprehensive overview of the TeleSignals platform, covering all major components, features, and technical implementation details necessary for AI understanding and further development.
