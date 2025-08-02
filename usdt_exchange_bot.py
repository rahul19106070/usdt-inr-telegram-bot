# USDT-INR Exchange Telegram Bot
# Complete implementation with database integration

import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API*", category=UserWarning)

import os
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json
import re

# Telegram bot libraries
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from telegram.helpers import escape_markdown

# For location services and phone verification
import phonenumbers
from phonenumbers import geocoder, carrier

# For payment integration (optional)
import razorpay

# Suppress the pkg_resources UserWarning from razorpay
warnings.filterwarnings("ignore", category=UserWarning, module="razorpay.client")

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from BotFather
BOT_TOKEN = "8454139319:AAHWFilxWVgmyzwnjzMUlW7GPoScvqPf0fk"

# Database configuration
DATABASE_PATH = "usdt_exchange.db"

# Conversation states
(REGISTRATION_PHONE, REGISTRATION_LOCATION, 
 OFFER_TYPE, OFFER_AMOUNT, OFFER_RATE, OFFER_MIN_MAX, 
 OFFER_PAYMENT_METHODS, OFFER_LOCATION, OFFER_TERMS,
 BROWSE_FILTER, CONTACT_SELLER) = range(11)

class DatabaseManager:
    """Handles all database operations"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                phone TEXT,
                city TEXT,
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verification_status INTEGER DEFAULT 0,
                reputation_score REAL DEFAULT 5.0,
                is_blocked INTEGER DEFAULT 0
            )
        ''')

        # Offers table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS offers (
                offer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                offer_type TEXT, -- 'SELL' or 'BUY'
                amount REAL,
                rate REAL,
                min_order REAL,
                max_order REAL,
                city TEXT,
                payment_methods TEXT, -- JSON string
                terms TEXT,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'ACTIVE', -- 'ACTIVE', 'COMPLETED', 'CANCELLED'
                expiry_date TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Transactions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id INTEGER,
                seller_id INTEGER,
                offer_id INTEGER,
                amount REAL,
                rate REAL,
                total_inr REAL,
                status TEXT DEFAULT 'INITIATED',
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_date TIMESTAMP,
                meeting_location TEXT,
                notes TEXT,
                FOREIGN KEY (buyer_id) REFERENCES users (user_id),
                FOREIGN KEY (seller_id) REFERENCES users (user_id),
                FOREIGN KEY (offer_id) REFERENCES offers (offer_id)
            )
        ''')

        # Ratings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ratings (
                rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER,
                rater_id INTEGER,
                rated_user_id INTEGER,
                rating INTEGER, -- 1-5 stars
                comment TEXT,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id),
                FOREIGN KEY (rater_id) REFERENCES users (user_id),
                FOREIGN KEY (rated_user_id) REFERENCES users (user_id)
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user data by user_id"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return {
                'user_id': result[0], 'username': result[1], 'phone': result[2],
                'city': result[3], 'registration_date': result[4],
                'last_active': result[5], 'verification_status': result[6],
                'reputation_score': result[7], 'is_blocked': result[8]
            }
        return None

    def create_user(self, user_id: int, username: str, phone: str, city: str):
        """Create new user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO users (user_id, username, phone, city)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, phone, city))

        conn.commit()
        conn.close()
        logger.info(f"Created new user: {user_id}")

    def create_offer(self, user_id: int, offer_data: Dict) -> int:
        """Create new USDT offer"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO offers (user_id, offer_type, amount, rate, min_order, 
                              max_order, city, payment_methods, terms, expiry_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, offer_data['type'], offer_data['amount'], offer_data['rate'],
            offer_data['min_order'], offer_data['max_order'], offer_data['city'],
            json.dumps(offer_data['payment_methods']), offer_data['terms'],
            datetime.now() + timedelta(days=7)  # Expire after 7 days
        ))

        offer_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Created offer {offer_id} for user {user_id}")
        return offer_id

    def get_offers(self, filters: Dict = None) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = '''
        SELECT o.*, u.username, u.reputation_score
        FROM offers o
        JOIN users u ON o.user_id = u.user_id
        WHERE o.status = 'ACTIVE' AND o.expiry_date > datetime('now')
        '''
        params = []

        if filters:
            if 'city' in filters:
                query += " AND LOWER(o.city) LIKE ?"
                params.append(f"%{filters['city'].lower()}%")
            if 'offer_type' in filters:
                query += " AND o.offer_type = ?"
                params.append(filters['offer_type'])
            if 'min_amount' in filters:
                query += " AND o.amount >= ?"
                params.append(filters['min_amount'])
            if 'max_rate' in filters:
                query += " AND o.rate <= ?"
                params.append(filters['max_rate'])
            if 'user_id' in filters:
                query += " AND o.user_id = ?"
                params.append(filters['user_id'])

        query += " ORDER BY o.created_date DESC"
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()

        offers = []
        for result in results:
            offers.append({
                'offer_id': result[0], 'user_id': result[1], 'offer_type': result[2],
                'amount': result[3], 'rate': result[4], 'min_order': result[5],
                'max_order': result[6], 'city': result[7],
                'payment_methods': json.loads(result[8]), 'terms': result[9],
                'created_date': result[10], 'username': result[12],
                'reputation_score': result[13],
                'status': result[11] if len(result) > 11 else 'ACTIVE',
            })

        return offers

class USDTExchangeBot:
    """Main bot class"""

    def __init__(self, token: str):
        self.token = token
        self.db = DatabaseManager(DATABASE_PATH)
        self.application = Application.builder().token(token).build()
        self.setup_handlers()

    def get_main_menu_keyboard(self):
        """Get main menu as a reply keyboard"""
        keyboard = [
            ["📝 Post USDT Offer", "🔍 Browse Offers"],
            ["📊 My Listings", "💰 My Transactions"],
            ["⚙️ Settings", "❓ Help"]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    def setup_handlers(self):
        """Setup all bot handlers"""
        # Registration conversation handler
        registration_conv = ConversationHandler(
            entry_points=[CommandHandler("start", self.start_command)],
            states={
                REGISTRATION_PHONE: [MessageHandler(filters.CONTACT, self.handle_phone)],
                REGISTRATION_LOCATION: [MessageHandler(filters.TEXT, self.handle_location)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )
        # Offer creation conversation handler
        offer_conv = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^📝 Post USDT Offer$'), self.start_offer_creation_from_menu),
                CallbackQueryHandler(self.start_offer_creation, pattern="^create_offer$")
            ],
            states={
                OFFER_TYPE: [CallbackQueryHandler(self.handle_offer_type, pattern="^offer_type_")],
                OFFER_AMOUNT: [MessageHandler(filters.TEXT, self.handle_offer_amount)],
                OFFER_RATE: [MessageHandler(filters.TEXT, self.handle_offer_rate)],
                OFFER_MIN_MAX: [MessageHandler(filters.TEXT, self.handle_offer_min_max)],
                OFFER_PAYMENT_METHODS: [MessageHandler(filters.TEXT, self.handle_payment_methods)],
                OFFER_LOCATION: [MessageHandler(filters.TEXT, self.handle_offer_location)],
                OFFER_TERMS: [MessageHandler(filters.TEXT, self.handle_offer_terms)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )
        # Offer browsing conversation handler
        offer_browse_conv = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^🔍 Browse Offers$'), self.browse_offers_from_menu),
                CallbackQueryHandler(self.browse_offers, pattern="^browse_offers$")
            ],
            states={
                BROWSE_FILTER: [MessageHandler(filters.TEXT, self.handle_browse_city)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )
        # My Listings conversation handler
        my_listings_conv = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^📊 My Listings$'), self.show_my_listings_from_menu),
                CallbackQueryHandler(self.show_my_listings, pattern="^my_offers$")
            ],
            states={},
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )
        # Add handlers
        self.application.add_handler(registration_conv)
        self.application.add_handler(offer_conv)
        self.application.add_handler(offer_browse_conv)
        self.application.add_handler(my_listings_conv)
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("menu", self.show_main_menu))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_menu_commands))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        db_user = self.db.get_user(user.id)
        if db_user:
            await update.message.reply_text(
                f"Welcome back, {user.first_name}! 👋\n\nWhat would you like to do today?",
                reply_markup=self.get_main_menu_keyboard()
            )
            return ConversationHandler.END
        else:
            keyboard = [[KeyboardButton("Share Phone Number 📱", request_contact=True)]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            await update.message.reply_text(
                f"Hello {user.first_name}! 👋 Welcome to USDT-INR Exchange Bot.\n\n"
                "This bot helps you find people in your city for offline USDT-INR exchanges.\n\n"
                "To get started, please share your phone number for verification:",
                reply_markup=reply_markup
            )
            return REGISTRATION_PHONE

    async def handle_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle phone number registration"""
        user = update.effective_user
        phone = update.message.contact.phone_number

        # Store phone in context for later use
        context.user_data['phone'] = phone

        await update.message.reply_text(
            "Great! Now please tell me which city you're located in:\n\n"
            "Example: Mumbai, Delhi, Bangalore, etc.",
            reply_markup=ReplyKeyboardRemove()
        )
        return REGISTRATION_LOCATION

    async def handle_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle location registration"""
        user = update.effective_user
        city = update.message.text.strip()
        phone = context.user_data.get('phone')

        # Create user in database
        self.db.create_user(user.id, user.username or user.first_name, phone, city)

        await update.message.reply_text(
            f"Perfect! You're all set up in {city}. 🎉\n\n"
            "Here's what you can do:\n"
            "• Post offers to sell/buy USDT\n"
            "• Browse offers from others in your city\n"
            "• Contact sellers/buyers directly\n\n"
            "⚠️ <b>Safety Reminder</b>: Always meet in public places and verify USDT transfers before making payments!",
            parse_mode='HTML',
            reply_markup=self.get_main_menu_keyboard()
        )
        return ConversationHandler.END

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu"""
        await update.message.reply_text(
            "🏠 <b>Main Menu</b>\n\nChoose an option from the menu below:",
            parse_mode='HTML',
            reply_markup=self.get_main_menu_keyboard()
        )

    async def start_offer_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start offer creation process"""
        query = update.callback_query
        await query.answer()

        keyboard = [
            [InlineKeyboardButton("💰 Sell USDT for INR", callback_data="offer_type_SELL")],
            [InlineKeyboardButton("🔄 Buy USDT with INR", callback_data="offer_type_BUY")]
        ]

        await query.edit_message_text(
            "What type of offer would you like to create?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return OFFER_TYPE

    async def start_offer_creation_from_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start offer creation process from menu command (reply keyboard)"""
        keyboard = [
            [InlineKeyboardButton("💰 Sell USDT for INR", callback_data="offer_type_SELL")],
            [InlineKeyboardButton("🔄 Buy USDT with INR", callback_data="offer_type_BUY")]
        ]
        await update.message.reply_text(
            "What type of offer would you like to create?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return OFFER_TYPE

    async def handle_offer_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle offer type selection"""
        query = update.callback_query
        await query.answer()

        offer_type = query.data.split("_")[-1]  # Extract SELL or BUY
        context.user_data['offer'] = {'type': offer_type}

        action = "sell" if offer_type == "SELL" else "buy"

        await query.edit_message_text(
            f"How much USDT do you want to {action}?\n\n"
            "Enter the amount (e.g., 100, 500, 1000):"
        )
        return OFFER_AMOUNT

    async def handle_offer_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle USDT amount input"""
        try:
            amount = float(update.message.text.strip())
            if amount <= 0:
                raise ValueError("Amount must be positive")

            context.user_data['offer']['amount'] = amount

            await update.message.reply_text(
                f"Great! You want to handle {amount} USDT.\n\n"
                "What's your exchange rate? (INR per 1 USDT)\n"
                "Example: 85.5, 87.2, etc."
            )
            return OFFER_RATE

        except ValueError:
            await update.message.reply_text(
                "Please enter a valid amount (numbers only):"
            )
            return OFFER_AMOUNT

    async def handle_offer_rate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle exchange rate input"""
        try:
            rate = float(update.message.text.strip())
            if rate <= 0:
                raise ValueError("Rate must be positive")

            context.user_data['offer']['rate'] = rate

            await update.message.reply_text(
                "Enter minimum and maximum order amounts:\n\n"
                "Format: min,max\n"
                "Example: 50,500 (min 50 USDT, max 500 USDT)"
            )
            return OFFER_MIN_MAX

        except ValueError:
            await update.message.reply_text(
                "Please enter a valid exchange rate (numbers only):"
            )
            return OFFER_RATE

    async def handle_offer_min_max(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle min/max order amounts"""
        try:
            text = update.message.text.strip()
            min_amount, max_amount = map(float, text.split(','))

            if min_amount <= 0 or max_amount <= 0 or min_amount > max_amount:
                raise ValueError("Invalid range")

            context.user_data['offer']['min_order'] = min_amount
            context.user_data['offer']['max_order'] = max_amount

            await update.message.reply_text(
                "What payment methods do you accept?\n\n"
                "Enter methods separated by commas:\n"
                "Example: Cash, UPI, Bank Transfer, PayTM"
            )
            return OFFER_PAYMENT_METHODS

        except ValueError:
            await update.message.reply_text(
                "Please enter valid amounts in format: min,max\n"
                "Example: 50,500"
            )
            return OFFER_MIN_MAX

    async def handle_payment_methods(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle payment methods input"""
        methods = [method.strip() for method in update.message.text.split(',')]
        context.user_data['offer']['payment_methods'] = methods

        await update.message.reply_text(
            "Which city are you posting this offer in? (e.g., Ludhiana, Delhi, Mumbai)",
            reply_markup=ReplyKeyboardRemove()
        )
        return OFFER_LOCATION

    async def handle_offer_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle main city for offer"""
        city = update.message.text.strip().lower()
        context.user_data['offer']['city'] = city

        await update.message.reply_text(
            "You can specify area/locality for more precise location (optional):\n\n"
            "Example: Ram Nagar, 33 Feet Road\n\nType your area/locality or type 'skip' to continue."
        )
        return OFFER_TERMS

    def format_offer_details_html(self, offer, include_user=True, include_id=False):
        """Format offer details using HTML"""
        emoji = "💰" if offer['offer_type'] == "SELL" else "🔄"
        action = "Selling" if offer['offer_type'] == "SELL" else "Buying"
        try:
            rep_score = float(offer['reputation_score'])
            rep_str = f"⭐{rep_score:.1f}"
        except Exception:
            rep_str = str(offer['reputation_score'])
        details = (
            f"{emoji} <b>{action} {offer['amount']} USDT</b>\n"
            f"Rate: ₹{offer['rate']} per USDT\n"
            f"Range: {offer['min_order']}-{offer['max_order']} USDT\n"
        )
        if include_user:
            details += f"By: @{offer['username']} ({rep_str})\n"
        details += f"Location: {offer['city'].capitalize()}\n"
        if include_id:
            details += f"Offer ID: #{offer['offer_id']}\n"
        return details

    def format_offer_with_contact_html(self, offer):
        """Format offer details with contact button using HTML"""
        emoji = "💰" if offer['offer_type'] == "SELL" else "🔄"
        action = "Selling" if offer['offer_type'] == "SELL" else "Buying"
        try:
            rep_score = float(offer['reputation_score'])
            rep_str = f"⭐{rep_score:.1f}"
        except Exception:
            rep_str = str(offer['reputation_score'])
        text = (
            f"{emoji} <b>{action} {offer['amount']} USDT</b>\n"
            f"Rate: ₹{offer['rate']} per USDT\n"
            f"Range: {offer['min_order']}-{offer['max_order']} USDT\n"
            f"By: @{offer['username']} ({rep_str})\n"
            f"Location: {offer['city'].capitalize()}\n"
            f"Offer ID: #{offer['offer_id']}\n"
        )
        keyboard = [[
            InlineKeyboardButton("💬 Contact User", callback_data=f"contact_{offer['user_id']}")
        ]]
        return text, InlineKeyboardMarkup(keyboard)

    async def handle_offer_terms(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle additional terms and create offer"""
        area_or_terms = update.message.text.strip()
        if area_or_terms.lower() == 'skip':
            area_or_terms = ""

        # If user provided area/locality, add it to terms
        offer = context.user_data['offer']
        if offer.get('terms'):
            offer['terms'] += f"\nArea/Locality: {area_or_terms}" if area_or_terms else ""
        else:
            offer['terms'] = f"Area/Locality: {area_or_terms}" if area_or_terms else ""

        # Create offer in database
        offer_id = self.db.create_offer(update.effective_user.id, offer)
        offer_type_text = "Selling" if offer['type'] == "SELL" else "Buying"

        # Send confirmation with proper escaping and error handling
        try:
            await update.message.reply_text(
                f"✅ <b>Offer Created Successfully!</b>\n\n"
                f"{offer_type_text}: {offer['amount']} USDT\n"
                f"Rate: ₹{offer['rate']} per USDT\n"
                f"Order Range: {offer['min_order']} - {offer['max_order']} USDT\n"
                f"City: {offer['city'].capitalize()}\n"
                f"Payment Methods: {', '.join(offer['payment_methods'])}\n"
                f"Terms/Area: {offer['terms'] or 'None'}\n\n"
                f"Your offer is now live! Others can see and contact you.\n"
                f"Offer ID: #{offer_id}",
                parse_mode='HTML',
                reply_markup=self.get_main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"Error sending offer confirmation: {e}")
            await update.message.reply_text(
                "Your offer was created successfully, but we encountered an issue displaying the details.",
                reply_markup=self.get_main_menu_keyboard()
            )

        # Clear offer data
        context.user_data.pop('offer', None)
        return ConversationHandler.END

    async def browse_offers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Browse available offers"""
        query = update.callback_query
        await query.answer()

        # Ask the user for city
        await query.edit_message_text(
            "Enter the city you want to browse offers in:\n\n"
            "Example: Mumbai, Delhi, Bangalore, etc.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        # Set state variable to expect city input in next message
        context.user_data['browsing_offers'] = True
        return BROWSE_FILTER

    async def browse_offers_from_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Browse available offers from menu command (reply keyboard)"""
        await update.message.reply_text(
            "Enter the city you want to browse offers in:\n\nExample: Mumbai, Delhi, Bangalore, etc.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        context.user_data['browsing_offers'] = True
        return BROWSE_FILTER

    async def handle_browse_city(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        city_raw = update.message.text.strip()
        city = city_raw.lower()  # for DB filtering
        offers = self.db.get_offers({'city': city})
        if not offers:
            await update.message.reply_text(
                f"No active offers found in {city_raw} 😔\n\nTry posting your own offer or check back later!",
                parse_mode='HTML',
                reply_markup=self.get_main_menu_keyboard()
            )
            return ConversationHandler.END
        await update.message.reply_text(
            f"🔍 <b>Active Offers in {city_raw.capitalize()}</b>\n\nFound {len(offers)} offers. Click on any offer to contact the user:",
            parse_mode='HTML'
        )
        for offer in offers[:5]:
            text, reply_markup = self.format_offer_with_contact_html(offer)
            await update.message.reply_text(
                text,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        await update.message.reply_text(
            "That's all for now!",
            reply_markup=self.get_main_menu_keyboard()
        )
        return ConversationHandler.END

    async def handle_contact_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact user button click"""
        query = update.callback_query
        await query.answer()
        user_id = int(query.data.split("_")[1])
        user = self.db.get_user(user_id)
        if not user:
            await query.edit_message_text(
                "User not found. They may have deleted their account.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="browse_offers")]])
            )
            return
        keyboard = [
            [InlineKeyboardButton("💬 Send Message", url=f"tg://user?id={user_id}")],
            [InlineKeyboardButton("🔙 Back to Offers", callback_data="browse_offers")]
        ]
        await query.edit_message_text(
            f"Contacting: <b>@{user['username'] or 'User'}</b>\n\n"
            f"Location: {user['city']}\n"
            f"Reputation: ⭐{user['reputation_score']}\n\n"
            "Click the button below to send them a message:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def show_my_listings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()  # Acknowledge the callback
        user_id = update.effective_user.id
        offers = self.db.get_offers({'user_id': user_id})
        if not offers:
            await query.edit_message_text(
                "You have no active listings.\n\nUse 'Post USDT Offer' to create one!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return
        await query.edit_message_text(
            f"📊 <b>My Active Listings</b>\n\nYou have {len(offers)} active offers:",
            parse_mode='HTML'
        )
        for offer in offers:
            text, reply_markup = self.format_offer_with_contact_html(offer)
            await update.effective_message.reply_text(
                text,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        await update.effective_message.reply_text(
            "That's all your listings!",
            reply_markup=self.get_main_menu_keyboard()
        )

    async def show_my_listings_from_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user's listings from the main menu (reply keyboard)"""
        user_id = update.effective_user.id
        offers = self.db.get_offers({'user_id': user_id})
        if not offers:
            await update.message.reply_text(
                "You have no active listings.\n\nUse 'Post USDT Offer' to create one!",
                reply_markup=self.get_main_menu_keyboard()
            )
            return
        await update.message.reply_text(
            f"📊 <b>My Active Listings</b>\n\nYou have {len(offers)} active offers:",
            parse_mode='HTML'
        )
        for offer in offers:
            text, reply_markup = self.format_offer_with_contact_html(offer)
            await update.message.reply_text(
                text,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        await update.message.reply_text(
            "That's all your listings!",
            reply_markup=self.get_main_menu_keyboard()
        )

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        data = query.data
        if data == "browse_offers":
            await self.browse_offers(update, context)
        elif data == "main_menu":
            await query.edit_message_text(
                "Choose an option:",
                reply_markup=self.get_main_menu_keyboard()
            )
        elif data == "help":
            await self.help_command(update, context)
        elif data == "my_offers":
            await self.show_my_listings(update, context)
        elif data.startswith("contact_"):
            await self.handle_contact_user(update, context)
        # Add more callback handlers as needed

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help information"""
        help_text = '''
🤖 <b>USDT-INR Exchange Bot Help</b>
<b>Commands:</b>
        '''
        if update.callback_query:
            await update.callback_query.edit_message_text(
                help_text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[\
                    InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")
                ]])
            )
        else:
            await update.message.reply_text(
                help_text,
                parse_mode='HTML',
                reply_markup=self.get_main_menu_keyboard()
            )

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command to exit a conversation"""
        if update.message:
            await update.message.reply_text(
                "Operation cancelled. Returning to main menu.",
                reply_markup=self.get_main_menu_keyboard()
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                "Operation cancelled. Returning to main menu.",
                reply_markup=self.get_main_menu_keyboard()
            )
        return ConversationHandler.END

    async def handle_menu_commands(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle menu commands from the reply keyboard"""
        text = update.message.text
        # Flows handled by conversation handlers, so do nothing here for those
        if text in ["📝 Post USDT Offer", "🔍 Browse Offers", "📊 My Listings"]:
            return
        elif text == "💰 My Transactions":
            await update.message.reply_text(
                "Transaction history feature coming soon!",
                reply_markup=self.get_main_menu_keyboard()
            )
        elif text == "⚙️ Settings":
            await update.message.reply_text(
                "Settings feature coming soon!",
                reply_markup=self.get_main_menu_keyboard()
            )
        elif text == "❓ Help":
            await self.help_command(update, context)

if __name__ == "__main__":
    bot = USDTExchangeBot(BOT_TOKEN)
    bot.application.run_polling()
