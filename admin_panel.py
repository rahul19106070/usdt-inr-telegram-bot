
# Admin Panel for USDT-INR Exchange Bot
import sqlite3
from datetime import datetime, timedelta
import json

class AdminPanel:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_stats(self):
        """Get bot statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Total users
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        # New users today
        cursor.execute("SELECT COUNT(*) FROM users WHERE date(registration_date) = date('now')")
        new_users_today = cursor.fetchone()[0]

        # Active offers
        cursor.execute("SELECT COUNT(*) FROM offers WHERE status = 'ACTIVE'")
        active_offers = cursor.fetchone()[0]

        # Total transactions
        cursor.execute("SELECT COUNT(*) FROM transactions")
        total_transactions = cursor.fetchone()[0]

        # Completed transactions today
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE date(completed_date) = date('now')")
        transactions_today = cursor.fetchone()[0]

        conn.close()

        return {
            'total_users': total_users,
            'new_users_today': new_users_today,
            'active_offers': active_offers,
            'total_transactions': total_transactions,
            'transactions_today': transactions_today
        }

    def get_top_users(self, limit=10):
        """Get top users by reputation"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT username, reputation_score, 
                   (SELECT COUNT(*) FROM transactions WHERE buyer_id = u.user_id OR seller_id = u.user_id) as transaction_count
            FROM users u 
            ORDER BY reputation_score DESC, transaction_count DESC 
            LIMIT ?
        ''', (limit,))

        results = cursor.fetchall()
        conn.close()

        return results

    def get_recent_offers(self, limit=10):
        """Get recent offers"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT o.offer_id, u.username, o.offer_type, o.amount, o.rate, o.city, o.created_date
            FROM offers o
            JOIN users u ON o.user_id = u.user_id
            ORDER BY o.created_date DESC
            LIMIT ?
        ''', (limit,))

        results = cursor.fetchall()
        conn.close()

        return results

    def block_user(self, user_id, reason=""):
        """Block a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,))

        # Deactivate all user's offers
        cursor.execute("UPDATE offers SET status = 'BLOCKED' WHERE user_id = ?", (user_id,))

        conn.commit()
        conn.close()

        return True

    def generate_report(self):
        """Generate comprehensive report"""
        stats = self.get_stats()
        top_users = self.get_top_users()
        recent_offers = self.get_recent_offers()

        report = f'''
📊 USDT-INR Exchange Bot Report
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

📈 STATISTICS:
• Total Users: {stats['total_users']}
• New Users Today: {stats['new_users_today']}
• Active Offers: {stats['active_offers']}
• Total Transactions: {stats['total_transactions']}
• Transactions Today: {stats['transactions_today']}

⭐ TOP USERS:
'''
        for i, (username, score, tx_count) in enumerate(top_users, 1):
            report += f"{i}. @{username} - ⭐{score:.1f} ({tx_count} transactions)\n"

        report += "\n📝 RECENT OFFERS:\n"
        for offer in recent_offers:
            offer_id, username, offer_type, amount, rate, city, created = offer
            report += f"#{offer_id} - @{username} {offer_type} {amount} USDT at ₹{rate} in {city}\n"

        return report

# Usage example for admin commands in main bot
def add_admin_handlers(application):
    """Add admin command handlers to the bot"""

    async def admin_stats(update, context):
        user_id = update.effective_user.id
        if user_id not in ADMIN_USER_IDS:
            await update.message.reply_text("❌ Access denied.")
            return

        admin = AdminPanel(DATABASE_PATH)
        report = admin.generate_report()
        await update.message.reply_text(report, parse_mode='Markdown')

    async def admin_block_user(update, context):
        user_id = update.effective_user.id
        if user_id not in ADMIN_USER_IDS:
            await update.message.reply_text("❌ Access denied.")
            return

        if not context.args:
            await update.message.reply_text("Usage: /block_user <user_id> [reason]")
            return

        target_user_id = int(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else ""

        admin = AdminPanel(DATABASE_PATH)
        admin.block_user(target_user_id, reason)

        await update.message.reply_text(f"✅ User {target_user_id} has been blocked.")

    # Add handlers
    application.add_handler(CommandHandler("admin_stats", admin_stats))
    application.add_handler(CommandHandler("block_user", admin_block_user))
