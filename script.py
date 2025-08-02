# Create the main bot code structure
bot_code = """
# USDT-INR Exchange Telegram Bot
# Complete implementation with database integration

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

# For location services and phone verification
import phonenumbers
from phonenumbers import geocoder, carrier

# For payment integration (optional)
import razorpay

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from BotFather
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# Database configuration
DATABASE_PATH = "usdt_exchange.db"

# Conversation states
(REGISTRATION_PHONE, REGISTRATION_LOCATION, 
 OFFER_TYPE, OFFER_AMOUNT, OFFER_RATE, OFFER_MIN_MAX, 
 OFFER_PAYMENT_METHODS, OFFER_LOCATION, OFFER_TERMS,
 BROWSE_FILTER, CONTACT_SELLER) = range(11)

class DatabaseManager:
    \"\"\"Handles all database operations\"\"\"
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        \"\"\"Initialize database tables\"\"\"
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
        \"\"\"Get user data by user_id\"\"\"
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
        \"\"\"Create new user\"\"\"
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
        \"\"\"Create new USDT offer\"\"\"
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
        \"\"\"Get offers with optional filters\"\"\"
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
                query += " AND o.city LIKE ?"
                params.append(f"%{filters['city']}%")
            if 'offer_type' in filters:
                query += " AND o.offer_type = ?"
                params.append(filters['offer_type'])
            if 'min_amount' in filters:
                query += " AND o.amount >= ?"
                params.append(filters['min_amount'])
            if 'max_rate' in filters:
                query += " AND o.rate <= ?"
                params.append(filters['max_rate'])
        
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
                'reputation_score': result[13]
            })
        
        return offers

class USDTExchangeBot:
    \"\"\"Main bot class\"\"\"
    
    def __init__(self, token: str):
        self.token = token
        self.db = DatabaseManager(DATABASE_PATH)
        self.application = Application.builder().token(token).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        \"\"\"Setup all bot handlers\"\"\"
        
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
            entry_points=[CallbackQueryHandler(self.start_offer_creation, pattern="^create_offer$")],
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
        
        # Add handlers
        self.application.add_handler(registration_conv)
        self.application.add_handler(offer_conv)
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("menu", self.show_main_menu))
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle /start command\"\"\"
        user = update.effective_user
        db_user = self.db.get_user(user.id)
        
        if db_user:
            # Existing user
            await update.message.reply_text(
                f"Welcome back, {user.first_name}! 👋\\n\\n"
                "What would you like to do today?",
                reply_markup=self.get_main_menu_keyboard()
            )
            return ConversationHandler.END
        else:
            # New user registration
            keyboard = [
                [KeyboardButton("Share Phone Number 📱", request_contact=True)]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            
            await update.message.reply_text(
                f"Hello {user.first_name}! 👋 Welcome to USDT-INR Exchange Bot.\\n\\n"
                "This bot helps you find people in your city for offline USDT-INR exchanges.\\n\\n"
                "To get started, please share your phone number for verification:",
                reply_markup=reply_markup
            )
            return REGISTRATION_PHONE
    
    async def handle_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle phone number registration\"\"\"
        user = update.effective_user
        phone = update.message.contact.phone_number
        
        # Store phone in context for later use
        context.user_data['phone'] = phone
        
        await update.message.reply_text(
            "Great! Now please tell me which city you're located in:\\n\\n"
            "Example: Mumbai, Delhi, Bangalore, etc.",
            reply_markup=ReplyKeyboardRemove()
        )
        return REGISTRATION_LOCATION
    
    async def handle_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle location registration\"\"\"
        user = update.effective_user
        city = update.message.text.strip()
        phone = context.user_data.get('phone')
        
        # Create user in database
        self.db.create_user(user.id, user.username or user.first_name, phone, city)
        
        await update.message.reply_text(
            f"Perfect! You're all set up in {city}. 🎉\\n\\n"
            "Here's what you can do:\\n"
            "• Post offers to sell/buy USDT\\n"
            "• Browse offers from others in your city\\n"
            "• Contact sellers/buyers directly\\n\\n"
            "⚠️ **Safety Reminder**: Always meet in public places and verify USDT transfers before making payments!",
            reply_markup=self.get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    def get_main_menu_keyboard(self):
        \"\"\"Get main menu inline keyboard\"\"\"
        keyboard = [
            [
                InlineKeyboardButton("📝 Post USDT Offer", callback_data="create_offer"),
                InlineKeyboardButton("🔍 Browse Offers", callback_data="browse_offers")
            ],
            [
                InlineKeyboardButton("📊 My Listings", callback_data="my_offers"),
                InlineKeyboardButton("💰 My Transactions", callback_data="my_transactions")
            ],
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                InlineKeyboardButton("❓ Help", callback_data="help")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Show main menu\"\"\"
        await update.message.reply_text(
            "Choose an option:",
            reply_markup=self.get_main_menu_keyboard()
        )
    
    async def start_offer_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Start offer creation process\"\"\"
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
    
    async def handle_offer_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle offer type selection\"\"\"
        query = update.callback_query
        await query.answer()
        
        offer_type = query.data.split("_")[-1]  # Extract SELL or BUY
        context.user_data['offer'] = {'type': offer_type}
        
        action = "sell" if offer_type == "SELL" else "buy"
        
        await query.edit_message_text(
            f"How much USDT do you want to {action}?\\n\\n"
            "Enter the amount (e.g., 100, 500, 1000):"
        )
        return OFFER_AMOUNT
    
    async def handle_offer_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle USDT amount input\"\"\"
        try:
            amount = float(update.message.text.strip())
            if amount <= 0:
                raise ValueError("Amount must be positive")
            
            context.user_data['offer']['amount'] = amount
            
            await update.message.reply_text(
                f"Great! You want to handle {amount} USDT.\\n\\n"
                "What's your exchange rate? (INR per 1 USDT)\\n"
                "Example: 85.5, 87.2, etc."
            )
            return OFFER_RATE
            
        except ValueError:
            await update.message.reply_text(
                "Please enter a valid amount (numbers only):"
            )
            return OFFER_AMOUNT
    
    async def handle_offer_rate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle exchange rate input\"\"\"
        try:
            rate = float(update.message.text.strip())
            if rate <= 0:
                raise ValueError("Rate must be positive")
            
            context.user_data['offer']['rate'] = rate
            
            await update.message.reply_text(
                "Enter minimum and maximum order amounts:\\n\\n"
                "Format: min,max\\n"
                "Example: 50,500 (min 50 USDT, max 500 USDT)"
            )
            return OFFER_MIN_MAX
            
        except ValueError:
            await update.message.reply_text(
                "Please enter a valid exchange rate (numbers only):"
            )
            return OFFER_RATE
    
    async def handle_offer_min_max(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle min/max order amounts\"\"\"
        try:
            text = update.message.text.strip()
            min_amount, max_amount = map(float, text.split(','))
            
            if min_amount <= 0 or max_amount <= 0 or min_amount > max_amount:
                raise ValueError("Invalid range")
            
            context.user_data['offer']['min_order'] = min_amount
            context.user_data['offer']['max_order'] = max_amount
            
            await update.message.reply_text(
                "What payment methods do you accept?\\n\\n"
                "Enter methods separated by commas:\\n"
                "Example: Cash, UPI, Bank Transfer, PayTM"
            )
            return OFFER_PAYMENT_METHODS
            
        except ValueError:
            await update.message.reply_text(
                "Please enter valid amounts in format: min,max\\n"
                "Example: 50,500"
            )
            return OFFER_MIN_MAX
    
    async def handle_payment_methods(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle payment methods input\"\"\"
        methods = [method.strip() for method in update.message.text.split(',')]
        context.user_data['offer']['payment_methods'] = methods
        
        user = self.db.get_user(update.effective_user.id)
        
        await update.message.reply_text(
            f"Where are you located? (Current: {user['city']})\\n\\n"
            "You can specify area/locality for more precise location:"
        )
        return OFFER_LOCATION
    
    async def handle_offer_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle offer location\"\"\"
        location = update.message.text.strip()
        context.user_data['offer']['city'] = location
        
        await update.message.reply_text(
            "Any additional terms or notes? (Optional)\\n\\n"
            "Example: Prefer morning meetings, ID verification required, etc.\\n\\n"
            "Type 'skip' if no additional terms:"
        )
        return OFFER_TERMS
    
    async def handle_offer_terms(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle additional terms and create offer\"\"\"
        terms = update.message.text.strip()
        if terms.lower() == 'skip':
            terms = ""
        
        context.user_data['offer']['terms'] = terms
        
        # Create offer in database
        offer_id = self.db.create_offer(update.effective_user.id, context.user_data['offer'])
        
        offer = context.user_data['offer']
        offer_type_text = "Selling" if offer['type'] == "SELL" else "Buying"
        
        # Send confirmation
        await update.message.reply_text(
            f"✅ **Offer Created Successfully!**\\n\\n"
            f"**{offer_type_text}**: {offer['amount']} USDT\\n"
            f"**Rate**: ₹{offer['rate']} per USDT\\n"
            f"**Order Range**: {offer['min_order']} - {offer['max_order']} USDT\\n"
            f"**Location**: {offer['city']}\\n"
            f"**Payment Methods**: {', '.join(offer['payment_methods'])}\\n"
            f"**Terms**: {terms or 'None'}\\n\\n"
            f"Your offer is now live! Others can see and contact you.\\n"
            f"**Offer ID**: #{offer_id}",
            parse_mode='Markdown',
            reply_markup=self.get_main_menu_keyboard()
        )
        
        # Clear offer data
        context.user_data.pop('offer', None)
        return ConversationHandler.END
    
    async def browse_offers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Browse available offers\"\"\"
        query = update.callback_query
        await query.answer()
        
        # Get user's city for default filtering
        user = self.db.get_user(update.effective_user.id)
        offers = self.db.get_offers({'city': user['city']})
        
        if not offers:
            await query.edit_message_text(
                f"No active offers found in {user['city']} 😔\\n\\n"
                "Try posting your own offer or check back later!",
                reply_markup=self.get_main_menu_keyboard()
            )
            return
        
        # Show first few offers
        text = f"🔍 **Active Offers in {user['city']}**\\n\\n"
        
        for i, offer in enumerate(offers[:5]):  # Show first 5
            emoji = "💰" if offer['offer_type'] == "SELL" else "🔄"
            action = "Selling" if offer['offer_type'] == "SELL" else "Buying"
            
            text += (
                f"{emoji} **{action} {offer['amount']} USDT**\\n"
                f"Rate: ₹{offer['rate']} per USDT\\n"
                f"Range: {offer['min_order']}-{offer['max_order']} USDT\\n"
                f"By: @{offer['username']} (⭐{offer['reputation_score']:.1f})\\n"
                f"Location: {offer['city']}\\n\\n"
            )
        
        # Add navigation buttons
        keyboard = []
        if len(offers) > 5:
            keyboard.append([InlineKeyboardButton("Show More", callback_data="show_more_offers")])
        
        keyboard.extend([
            [InlineKeyboardButton("🔍 Filter Offers", callback_data="filter_offers")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ])
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Handle callback queries\"\"\"
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
        # Add more callback handlers as needed
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Show help information\"\"\"
        help_text = '''
🤖 **USDT-INR Exchange Bot Help**

**Commands:**
/start - Start the bot or register
/menu - Show main menu
/help - Show this help

**Features:**
• Post offers to buy/sell USDT
• Browse offers in your city
• Direct contact with other users
• Transaction tracking
• User rating system

**Safety Tips:**
⚠️ Always meet in public places
⚠️ Verify USDT transfer before payment
⚠️ Check user ratings before trading
⚠️ Report suspicious users

**Support:**
For issues or questions, contact @your_support_username
        '''
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                help_text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")
                ]])
            )
        else:
            await update.message.reply_text(
                help_text,
                parse_mode='Markdown',
                reply_markup=self.get_main_menu_keyboard()
            )
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        \"\"\"Cancel current operation\"\"\"
        await update.message.reply_text(
            "Operation cancelled.",
            reply_markup=self.get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    def run(self):
        \"\"\"Start the bot\"\"\"
        logger.info("Starting USDT-INR Exchange Bot...")
        self.application.run_polling()

# Entry point
def main():
    \"\"\"Main function to run the bot\"\"\"
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Please set your bot token in BOT_TOKEN variable")
        return
    
    bot = USDTExchangeBot(BOT_TOKEN)
    bot.run()

if __name__ == "__main__":
    main()
"""

# Save the bot code to a file
with open("usdt_exchange_bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)

print("✅ Bot code has been generated and saved to 'usdt_exchange_bot.py'")
print("\n📁 File created: usdt_exchange_bot.py")
print("📏 File size:", len(bot_code), "characters")

# Create requirements.txt
requirements = """python-telegram-bot==20.7
phonenumbers==8.13.27
razorpay==1.3.0
sqlite3
asyncio
"""

with open("requirements.txt", "w") as f:
    f.write(requirements)

print("📁 Requirements file created: requirements.txt")

# Create configuration template
config_template = """# Configuration file for USDT-INR Exchange Bot

# Telegram Bot Configuration
BOT_TOKEN = "YOUR_BOT_TOKEN_FROM_BOTFATHER"

# Database Configuration
DATABASE_PATH = "usdt_exchange.db"
BACKUP_INTERVAL = 3600  # seconds

# Payment Gateway (Optional - for premium features)
RAZORPAY_KEY_ID = "YOUR_RAZORPAY_KEY_ID"
RAZORPAY_KEY_SECRET = "YOUR_RAZORPAY_KEY_SECRET"

# Bot Settings
MAX_OFFERS_PER_USER = 5
OFFER_EXPIRY_DAYS = 7
MIN_USDT_AMOUNT = 10
MAX_USDT_AMOUNT = 10000

# Admin Configuration
ADMIN_USER_IDS = [123456789]  # Add admin Telegram user IDs

# Logging Configuration
LOG_LEVEL = "INFO"
LOG_FILE = "bot.log"

# Safety Features
ENABLE_PHONE_VERIFICATION = True
ENABLE_LOCATION_VERIFICATION = True
ENABLE_USER_RATINGS = True
ENABLE_ESCROW = False  # Premium feature

# Notification Settings
NOTIFY_NEW_OFFERS = True
NOTIFY_PRICE_ALERTS = True
NOTIFY_SYSTEM_UPDATES = True
"""

with open("config.py", "w") as f:
    f.write(config_template)

print("📁 Configuration template created: config.py")
print("\n🎉 All files have been generated successfully!")