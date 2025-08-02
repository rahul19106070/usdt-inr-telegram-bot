#!/bin/bash
# Deployment script for USDT-INR Exchange Bot

echo "🚀 Starting USDT-INR Exchange Bot Deployment..."

# Create logs directory
mkdir -p logs

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo "📥 Installing dependencies..."
pip install --upgrade -r requirements.txt

# Check if config is set up
if grep -q "YOUR_BOT_TOKEN_FROM_BOTFATHER" config.py; then
    echo "⚠️  WARNING: Please update your bot token in config.py"
    echo "❌ Deployment stopped. Configure your bot token first."
    exit 1
fi

# Create systemd service file (optional)
if [ "$1" = "--service" ]; then
    echo "🔧 Creating systemd service..."
    cat > usdt-exchange-bot.service << EOF
[Unit]
Description=USDT-INR Exchange Telegram Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
Environment=PATH=$(pwd)/venv/bin
ExecStart=$(pwd)/venv/bin/python usdt_exchange_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    echo "📋 Service file created: usdt-exchange-bot.service"
    echo "To install: sudo cp usdt-exchange-bot.service /etc/systemd/system/"
    echo "To enable: sudo systemctl enable usdt-exchange-bot"
    echo "To start: sudo systemctl start usdt-exchange-bot"
fi

# Test bot configuration
echo "🧪 Testing bot configuration..."
python -c "
import sqlite3
from config import BOT_TOKEN, DATABASE_PATH
print('✅ Configuration test passed')
"

if [ $? -eq 0 ]; then
    echo "✅ Deployment completed successfully!"
    echo "🏃 Run: python usdt_exchange_bot.py"
else
    echo "❌ Deployment failed. Check configuration."
fi
