# Configuration file for USDT-INR Exchange Bot

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
