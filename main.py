import os
import io
import json
import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =========================
# BASIC CONFIG
# =========================

load_dotenv()  # used locally; on Render env vars come from dashboard

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
GDRIVE_SERVICE_ACCOUNT_JSON = os.environ["GDRIVE_SERVICE_ACCOUNT_JSON"]
DRIVE_ROOT_FOLDER_ID = os.environ["DRIVE_ROOT_FOLDER_ID"]  # your main folder

CONFIG_FILE_NAME = "innovators_bot_config.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Singapore")


# =========================
# GOOGLE DRIVE HELPERS
# =========================

def get_drive_service():
    info = json.loads(GDRIVE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    service = build("drive", "v3", credentials=creds)
    return service


def find_config_file(service):
    """Return (file_id or None) for the config file in the root folder."""
    query = (
        f"'{DRIVE_ROOT_FOLDER_ID}' in parents and "
        f"name = '{CONFIG_FILE_NAME}' and trashed = false"
    )
    results = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id, name)", pageSize=1)
        .execute()
    )
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    return None


def load_config() -> dict:
    """Load config JSON from Drive. If none, create default and upload."""
    service = get_drive_service()
    file_id = find_config_file(service)
    if file_id is None:
        # default config
        config = {
            "admins": [],  # list of Telegram user IDs
            "pic_chat_id_new": None,     # AY25/26 onwards
            "pic_chat_id_old": None,     # before AY25/26
            "quarterly_chat_ids": [],    # optional list of chats for quarterly reminders
            "pitch_chat_id": None,
            "pitch_datetime": None,      # ISO string
            "sharing_chat_id": None,
            "sharing_datetime": None,    # ISO string
        }
        save_config(config)
        return config

    # download file
    request = service.files().get_media(fileId=file_id)
    data = request.execute()
    config = json.loads(data.decode("utf-8"))
    return config


def save_config(config: dict):
    """Save config JSON to Drive (create or update)."""
    service = get_drive_service()
    file_id = find_config_file(service)

    data_bytes = json.dumps(config, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(
        io.BytesIO(data_bytes),
        mimetype="application/json",
        resumable=False
    )
    file_metadata = {
        "name": CONFIG_FILE_NAME,
        "parents": [DRIVE_ROOT_FOLDER_ID],
    }

    if file_id is None:
        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id")
            .execute()
        )
        logger.info(f"Created config file in Drive: {file.get('id')}")
    else:
        file = (
            service.files()
            .update(fileId=file_id, body=file_metadata, media_body=media)
            .execute()
        )
        logger.info(f"Updated config file in Drive: {file.get('id')}")


def upload_file_to_drive(file_bytes: bytes, filename: str, subfolder_name: str = "PurchaseRequests") -> str:
    """
    Uploads a file under DRIVE_ROOT_FOLDER_ID / subfolder_name.
    Returns: file id.
    """
    service = get_drive_service()

    # Ensure subfolder exists
    # 1. Look for subfolder
    query = (
        f"'{DRIVE_ROOT_FOLDER_ID}' in parents and "
        f"name = '{subfolder_name}' and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    results = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id, name)", pageSize=1)
        .execute()
    )
    files = results.get("files", [])
    if files:
        subfolder_id = files[0]["id"]
    else:
        # create subfolder
        folder_metadata = {
            "name": subfolder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [DRIVE_ROOT_FOLDER_ID],
        }
        folder = service.files().create(body=folder_metadata, fields="id").execute()
        subfolder_id = folder["id"]

    file_metadata = {
        "name": filename,
        "parents": [subfolder_id],
    }
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/octet-stream")

    file = service.files().create(
        body=file_metadata, media_body=media, fields="id"
    ).execute()
    file_id = file.get("id")
    logger.info(f"Uploaded file to Google Drive with id={file_id}")
    return file_id


# =========================
# ADMIN & PERMISSIONS
# =========================

def is_admin(user_id: int) -> bool:
    config = load_config()
    return user_id in config.get("admins", [])


async def ensure_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is admin. If not, reply and return False."""
    user = update.effective_user
    if user is None:
        return False
    if not is_admin(user.id):
        await update.effective_message.reply_text("❌ You are not an admin of this bot.")
        return False
    return True


# =========================
# TELEGRAM HANDLERS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    config = load_config()

    text = (
        "👋 *EEE Garage Innovators’ Track Bot*\n\n"
        "I can help with:\n"
        "• 🔁 Zoom update reminders with PIC (AY25/26 and earlier teams)\n"
        "• 📆 Quarterly reminders for PIC/Director\n"
        "• 📤 Uploading purchase request sheets to Google Drive\n"
        "• 🎤 Pitching Night & 👥 Sharing Session reminders\n\n"
        "If you're an admin, use /init (first time) or /setup to configure me.\n"
        "Teams can simply send purchase request files here in PM."
    )
    await update.effective_message.reply_markdown(text)

    # First-ever admin: if none exist yet, make this user the first admin
    if not config.get("admins"):
        if user:
            config["admins"] = [user.id]
            save_config(config)
            await update.effective_message.reply_text(
                f"✅ You ({user.id}) have been set as the *first admin* of this bot.\n"
                f"Use /setup to configure groups and dates."
            )


async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin setup instructions."""
    if not await ensure_admin(update, context):
        return

    text = (
        "🛠 *Admin Setup Menu*\n\n"
        "Run these commands in the correct places:\n\n"
        "1️⃣ In the AY25/26 PIC group:\n"
        "   → /set_pic_new\n\n"
        "2️⃣ In the PIC group for teams before AY25/26:\n"
        "   → /set_pic_old\n\n"
        "3️⃣ In the group/chat where quarterly reminders should go:\n"
        "   → /set_quarterly_here\n\n"
        "4️⃣ In the group where Pitching Night reminders should go:\n"
        "   → /set_pitch_here\n"
        "   Then in *PM with bot*:\n"
        "   → /set_pitch_time DD-MM-YYYY HH:MM\n\n"
        "5️⃣ In the group where Sharing Session reminders should go:\n"
        "   → /set_sharing_here\n"
        "   Then in *PM with bot*:\n"
        "   → /set_sharing_time DD-MM-YYYY HH:MM\n\n"
        "6️⃣ Admin management (PM with bot):\n"
        "   → /admins   (show current admins)\n"
        "   → /add_admin (as a reply to their message OR with id)\n"
        "   → /remove_admin (reply or give id)\n\n"
        "7️⃣ To see all saved settings:\n"
        "   → /settings\n"
    )
    await update.effective_message.reply_markdown(text)


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return
    config = load_config()
    text = (
        "*Current Settings:*\n\n"
        f"Admins: {config.get('admins', [])}\n\n"
        f"PIC (AY25/26) chat id: {config.get('pic_chat_id_new')}\n"
        f"PIC (before AY25/26) chat id: {config.get('pic_chat_id_old')}\n"
        f"Quarterly reminder chats: {config.get('quarterly_chat_ids', [])}\n\n"
        f"Pitch chat id: {config.get('pitch_chat_id')}\n"
        f"Pitch datetime: {config.get('pitch_datetime')}\n\n"
        f"Sharing chat id: {config.get('sharing_chat_id')}\n"
        f"Sharing datetime: {config.get('sharing_datetime')}\n"
    )
    await update.effective_message.reply_markdown(text)


async def admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return
    config = load_config()
    await update.effective_message.reply_text(f"👤 Admin user IDs: {config.get('admins', [])}")


async def add_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    config = load_config()
    admins = set(config.get("admins", []))

    # Prefer reply-based
    if update.effective_message.reply_to_message and update.effective_message.reply_to_message.from_user:
        new_admin_id = update.effective_message.reply_to_message.from_user.id
    else:
        # Try parse from argument
        if not context.args:
            await update.effective_message.reply_text(
                "Usage:\n"
                "• Reply to a message: /add_admin\n"
                "• Or: /add_admin <telegram_user_id>"
            )
            return
        try:
            new_admin_id = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("Invalid user id.")
            return

    admins.add(new_admin_id)
    config["admins"] = list(admins)
    save_config(config)
    await update.effective_message.reply_text(f"✅ Added admin: {new_admin_id}")


async def remove_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return

    config = load_config()
    admins = set(config.get("admins", []))

    if update.effective_message.reply_to_message and update.effective_message.reply_to_message.from_user:
        remove_id = update.effective_message.reply_to_message.from_user.id
    else:
        if not context.args:
            await update.effective_message.reply_text(
                "Usage:\n"
                "• Reply to a message: /remove_admin\n"
                "• Or: /remove_admin <telegram_user_id>"
            )
            return
        try:
            remove_id = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("Invalid user id.")
            return

    if remove_id in admins:
        admins.remove(remove_id)
        config["admins"] = list(admins)
        save_config(config)
        await update.effective_message.reply_text(f"✅ Removed admin: {remove_id}")
    else:
        await update.effective_message.reply_text("User is not an admin.")


# ===== GROUP SETUP COMMANDS (RUN IN TARGET GROUPS) =====

async def set_pic_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run this in AY25/26 PIC group."""
    if not await ensure_admin(update, context):
        return
    chat = update.effective_chat
    config = load_config()
    config["pic_chat_id_new"] = chat.id
    save_config(config)
    await update.effective_message.reply_text(
        f"✅ Set AY25/26 PIC chat id to {chat.id}"
    )


async def set_pic_old(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run this in PIC group for teams before AY25/26."""
    if not await ensure_admin(update, context):
        return
    chat = update.effective_chat
    config = load_config()
    config["pic_chat_id_old"] = chat.id
    save_config(config)
    await update.effective_message.reply_text(
        f"✅ Set pre-AY25/26 PIC chat id to {chat.id}"
    )


async def set_quarterly_here(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run this in any chat where quarterly reminder should appear."""
    if not await ensure_admin(update, context):
        return
    chat = update.effective_chat
    config = load_config()
    lst = set(config.get("quarterly_chat_ids", []))
    lst.add(chat.id)
    config["quarterly_chat_ids"] = list(lst)
    save_config(config)
    await update.effective_message.reply_text(
        f"✅ Added this chat ({chat.id}) to quarterly reminders."
    )


async def set_pitch_here(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return
    chat = update.effective_chat
    config = load_config()
    config["pitch_chat_id"] = chat.id
    save_config(config)
    await update.effective_message.reply_text(
        f"✅ Set Pitching Night reminders to this chat ({chat.id}).\n"
        "Now set the date/time in PM with:\n"
        "/set_pitch_time DD-MM-YYYY HH:MM"
    )


async def set_sharing_here(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return
    chat = update.effective_chat
    config = load_config()
    config["sharing_chat_id"] = chat.id
    save_config(config)
    await update.effective_message.reply_text(
        f"✅ Set Sharing Session reminders to this chat ({chat.id}).\n"
        "Now set the date/time in PM with:\n"
        "/set_sharing_time DD-MM-YYYY HH:MM"
    )


# ===== DATE/TIME COMMANDS (RUN IN PM) =====

def parse_datetime_str(dt_str: str) -> datetime:
    # Format: DD-MM-YYYY HH:MM
    return datetime.strptime(dt_str, "%d-%m-%Y %H:%M")


async def set_pitch_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /set_pitch_time DD-MM-YYYY HH:MM\nExample: /set_pitch_time 10-02-2026 18:00"
        )
        return
    dt_str = " ".join(context.args)
    try:
        dt = parse_datetime_str(dt_str)
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid format. Use: DD-MM-YYYY HH:MM")
        return

    config = load_config()
    config["pitch_datetime"] = dt.isoformat()
    save_config(config)

    # schedule or reschedule job
    schedule_pitch_job(context.application, dt)
    await update.effective_message.reply_text(f"✅ Pitching Night reminder scheduled at {dt.isoformat()}")


async def set_sharing_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_admin(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /set_sharing_time DD-MM-YYYY HH:MM\nExample: /set_sharing_time 15-03-2026 19:00"
        )
        return
    dt_str = " ".join(context.args)
    try:
        dt = parse_datetime_str(dt_str)
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid format. Use: DD-MM-YYYY HH:MM")
        return

    config = load_config()
    config["sharing_datetime"] = dt.isoformat()
    save_config(config)

    schedule_sharing_job(context.application, dt)
    await update.effective_message.reply_text(f"✅ Sharing Session reminder scheduled at {dt.isoformat()}")


# ===== PURCHASE REQUEST HANDLER (PM DOCUMENTS) =====

async def handle_purchase_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Any document sent in PRIVATE chat is treated as a purchase request sheet.
    """
    message = update.effective_message
    chat = update.effective_chat

    if chat.type != chat.PRIVATE:
        # ignore group docs for now
        return

    if not message or not message.document:
        return

    doc = message.document
    file_id = doc.file_id
    filename = doc.file_name or "purchase_request"

    await message.reply_text("📥 Downloading your file...")

    file = await context.bot.get_file(file_id)
    bio = io.BytesIO()
    await file.download_to_memory(out=bio)
    bio.seek(0)

    await message.reply_text("⬆️ Uploading to Google Drive...")
    drive_file_id = upload_file_to_drive(bio.read(), filename, subfolder_name="PurchaseRequests")
    drive_link = f"https://drive.google.com/file/d/{drive_file_id}/view"

    await message.reply_text(
        f"✅ Purchase request uploaded!\n\n"
        f"Filename: {filename}\n"
        f"Drive link: {drive_link}\n"
        "The committee can now review and process it."
    )


# =========================
# SCHEDULED JOBS
# =========================

async def job_zoom_new(application):
    """
    Reminder of Zoom update with PIC for AY25/26 teams onwards.
    """
    config = load_config()
    chat_id = config.get("pic_chat_id_new")
    if not chat_id:
        return
    text = (
        "📣 *Reminder: Innovators' Track Zoom update (AY25/26 teams onwards)*\n\n"
        "Please update your PIC on this week's progress, blockers, and next steps."
    )
    await application.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def job_zoom_old(application):
    """
    Reminder of Zoom update with PIC for teams before AY25/26.
    """
    config = load_config()
    chat_id = config.get("pic_chat_id_old")
    if not chat_id:
        return
    text = (
        "📣 *Reminder: Innovators' Track Zoom update (pre-AY25/26 teams)*\n\n"
        "Please update your PIC on your current progress and upcoming milestones."
    )
    await application.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def job_quarterly(application):
    """
    Quarterly reminder to PIC/Director (via Telegram chats, not email).
    """
    config = load_config()
    chat_ids = config.get("quarterly_chat_ids", [])
    if not chat_ids:
        return
    text = (
        "📆 *Quarterly Update Reminder*\n\n"
        "Please compile and share the quarterly update for Innovators’ Track teams:\n"
        "• Team progress\n"
        "• Achievements\n"
        "• Blockers & support needed\n"
        "• Upcoming milestones"
    )
    for cid in chat_ids:
        try:
            await application.bot.send_message(chat_id=cid, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error sending quarterly reminder to {cid}: {e}")


async def job_pitch(application):
    config = load_config()
    chat_id = config.get("pitch_chat_id")
    if not chat_id:
        return
    text = (
        "🎤 *Reminder: Pitching Night*\n\n"
        "Don't forget to attend Pitching Night! Be prepared with:\n"
        "• Updated slides\n"
        "• Demo (if any)\n"
        "• Clear problem, solution, and roadmap.\n"
    )
    await application.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def job_sharing(application):
    config = load_config()
    chat_id = config.get("sharing_chat_id")
    if not chat_id:
        return
    text = (
        "👥 *Reminder: Sharing Session*\n\n"
        "Friendly reminder to attend the upcoming sharing session. "
        "Come ready to learn from other teams and share your progress!"
    )
    await application.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


def schedule_recurring_jobs(application):
    """
    Weekly Zoom reminders + quarterly reminders.
    These jobs read the latest config each time they run.
    """
    # Weekly Zoom reminders
    scheduler.add_job(
        lambda: asyncio.create_task(job_zoom_new(application)),
        CronTrigger(day_of_week="mon", hour=20, minute=0),
        id="zoom_new",
        replace_existing=True,
    )

    scheduler.add_job(
        lambda: asyncio.create_task(job_zoom_old(application)),
        CronTrigger(day_of_week="tue", hour=20, minute=0),
        id="zoom_old",
        replace_existing=True,
    )

    # Quarterly reminders (Jan, Apr, Jul, Oct on 1st at 09:00)
    scheduler.add_job(
        lambda: asyncio.create_task(job_quarterly(application)),
        CronTrigger(month="1,4,7,10", day="1", hour=9, minute=0),
        id="quarterly",
        replace_existing=True,
    )


def schedule_pitch_job(application, dt: datetime):
    scheduler.add_job(
        lambda: asyncio.create_task(job_pitch(application)),
        DateTrigger(run_date=dt),
        id="pitch",
        replace_existing=True,
    )
    logger.info(f"Scheduled Pitching Night job at {dt.isoformat()}")


def schedule_sharing_job(application, dt: datetime):
    scheduler.add_job(
        lambda: asyncio.create_task(job_sharing(application)),
        DateTrigger(run_date=dt),
        id="sharing",
        replace_existing=True,
    )
    logger.info(f"Scheduled Sharing Session job at {dt.isoformat()}")


def restore_event_jobs_from_config(application):
    """
    On startup, read config and (re)schedule pitch/sharing jobs if dates exist.
    """
    config = load_config()
    if config.get("pitch_datetime"):
        try:
            dt = datetime.fromisoformat(config["pitch_datetime"])
            if dt > datetime.now(dt.tzinfo or None):
                schedule_pitch_job(application, dt)
        except Exception as e:
            logger.error(f"Error restoring pitch job: {e}")

    if config.get("sharing_datetime"):
        try:
            dt = datetime.fromisoformat(config["sharing_datetime"])
            if dt > datetime.now(dt.tzinfo or None):
                schedule_sharing_job(application, dt)
        except Exception as e:
            logger.error(f"Error restoring sharing job: {e}")


# =========================
# MAIN
# =========================

def main():
    port = int(os.environ.get("PORT", "8080"))

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setup", setup))
    application.add_handler(CommandHandler("settings", settings_cmd))

    # Admin management
    application.add_handler(CommandHandler("admins", admins_cmd))
    application.add_handler(CommandHandler("add_admin", add_admin_cmd))
    application.add_handler(CommandHandler("remove_admin", remove_admin_cmd))

    # Group config commands
    application.add_handler(CommandHandler("set_pic_new", set_pic_new))
    application.add_handler(CommandHandler("set_pic_old", set_pic_old))
    application.add_handler(CommandHandler("set_quarterly_here", set_quarterly_here))
    application.add_handler(CommandHandler("set_pitch_here", set_pitch_here))
    application.add_handler(CommandHandler("set_sharing_here", set_sharing_here))

    # Date/time commands (PM)
    application.add_handler(CommandHandler("set_pitch_time", set_pitch_time))
    application.add_handler(CommandHandler("set_sharing_time", set_sharing_time))

    # Purchase request documents in PM
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.Document.ALL,
            handle_purchase_document,
        )
    )

    # Scheduler jobs
    schedule_recurring_jobs(application)
    restore_event_jobs_from_config(application)
    scheduler.start()
    logger.info("Scheduler started.")

    if not WEBHOOK_URL:
        # Local testing mode: polling
        logger.info("Running in polling mode (no WEBHOOK_URL set).")
        application.run_polling()
    else:
        # Render / production: webhook
        logger.info(f"Running in webhook mode on port {port}, webhook={WEBHOOK_URL}")
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}",
        )


if __name__ == "__main__":
    main()