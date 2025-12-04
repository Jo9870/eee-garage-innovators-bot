import os
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# -------------------
# Logging (for Render)
# -------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------
# Commands
# -------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *EEE Garage Innovators Track Bot*\nBot is running successfully!",
        parse_mode="Markdown"
    )

async def zoom_future(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔔 Reminder for AY25/26 teams: Please join the next Zoom update with your PIC!"
    )

async def zoom_before(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔔 Reminder for pre-AY25/26 teams: Please attend your scheduled Zoom update with PIC!"
    )

async def pitch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎤 Reminder: Pitching Night is coming soon! Please prepare your deck!"
    )

async def sharing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤝 Reminder: Sharing Session is happening soon! Make sure your team is ready!"
    )

async def purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📄 Please send your purchase request sheet to the committee!"
    )

# -------------------
# Webhook Startup
# -------------------
def main():
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

    # Build bot
    application = Application.builder().token(TOKEN).build()

    # Add commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("zoom_new", zoom_future))
    application.add_handler(CommandHandler("zoom_old", zoom_before))
    application.add_handler(CommandHandler("pitch", pitch))
    application.add_handler(CommandHandler("sharing", sharing))
    application.add_handler(CommandHandler("purchase", purchase))

    # Start webhook
    port = int(os.environ.get("PORT", 10000))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
