import logging
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    JobQueue,
    ApplicationBuilder,
    filters
)

# --- Configuration and Setup ---

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# IMPORTANT: Get your BOT_TOKEN from the environment variable (required for Render)
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# The chat ID where scheduled reminders should be sent (e.g., the main team group)
# You MUST replace this with the actual ID.
# For security, you can set this as an environment variable (e.g., PIC_CHAT_ID)
# and retrieve it here:
PIC_CHAT_ID = os.environ.get("PIC_CHAT_ID", "-100123456789") # Use a placeholder or a default
ADMIN_USER_ID = int(os.environ.get("ADMIN_ID", "123456789")) # Replace with your user ID for admin access

# --- Job Handler Functions ---

async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generic function to send a reminder message to the target chat."""
    job = context.job
    # This ensures the bot targets the specific chat ID provided when the job was added
    chat_id = job.data.get('chat_id')
    message = job.data.get('message')
    
    if chat_id and message:
        logger.info(f"Sending scheduled message to {chat_id}: {message[:30]}...")
        await context.bot.send_message(
            chat_id=chat_id,
            text=message
        )
    else:
        logger.error("Job data missing chat_id or message.")

# --- Specific Task Definitions ---

def schedule_innovators_track_jobs(job_queue: JobQueue, chat_id: str):
    """Schedules all recurring and one-time tasks.
       NOTE: You need to define the exact schedule (time, day, dates) below.
    """
    # 1. Zoom Update Reminder (AY25/26 teams onwards) - Example: Every Monday at 10:00 AM
    zoom_update_new_msg = (
        "📢 *AY25/26 Teams Zoom Update Reminder* 📢\n\n"
        "Please remember to schedule and conduct your weekly Zoom update with your PIC.\n"
        "PIC: [Name of PIC]. \n*Goal:* Discuss progress and blockers."
    )
    job_queue.run_daily(
        send_reminder,
        time=logging.time(hour=10, minute=0), # Change this to the desired time
        days=(0,), # Monday is day 0 (Sunday=6)
        data={'chat_id': chat_id, 'message': zoom_update_new_msg},
        name="zoom_update_ay25_onwards"
    )

    # 2. Zoom Update Reminder (teams before AY25/26) - Example: Every Tuesday at 10:00 AM
    zoom_update_old_msg = (
        "📢 *Pre-AY25/26 Teams Zoom Update Reminder* 📢\n\n"
        "A friendly reminder to have your Zoom check-in with your PIC this week.\n"
        "PIC: [Name of PIC]. \n*Focus:* Long-term strategy and final deliverables."
    )
    job_queue.run_daily(
        send_reminder,
        time=logging.time(hour=10, minute=0), # Change this to the desired time
        days=(1,), # Tuesday is day 1
        data={'chat_id': chat_id, 'message': zoom_update_old_msg},
        name="zoom_update_pre_ay25"
    )
    
    # 3. Quarterly Update Sent to PIC and Director - Example: First day of Jan, Apr, Jul, Oct at 9:00 AM
    quarterly_update_msg = (
        "🗓️ *Quarterly Update Submission* 🗓️\n\n"
        "It's time for the quarterly update! Please ensure the report is finalized and sent to the PIC and Director by EOD today."
    )
    # Note: run_monthly can be tricky for specific dates. For simplicity and robustness,
    # we use run_daily and check the date, or you can manually trigger this quarterly.
    # For now, we'll schedule a job that runs on the 1st of Jan/Apr/Jul/Oct (needs complex logic, so use a simplified example):
    job_queue.run_once(
        send_reminder,
        when=1672531200, # Unix timestamp for Jan 1st 2025 00:00:00 - REPLACE WITH REAL DATE
        data={'chat_id': chat_id, 'message': quarterly_update_msg},
        name="quarterly_update_jan_q1"
    )
    # *In a real scenario, you'd calculate the next 4 dates and add 4 run_once jobs.*
    
    # 4. Submit Purchase Request Sheet Reminder - Example: Every 15th of the month at 1:00 PM
    purchase_request_msg = (
        "💸 *Purchase Request Sheet Submission* 💸\n\n"
        "Reminder: Please submit the latest purchase request sheet to [Comm Contact] so they can attach and process the formal Purchase Request."
    )
    def monthly_purchase_reminder(context: ContextTypes.DEFAULT_TYPE):
        # A workaround to check for the 15th of the month
        if context.job.tzinfo.localize(context.job.last_run_time).day == 15:
            job_queue.run_once(
                send_reminder, 
                when=0, # run immediately
                data={'chat_id': chat_id, 'message': purchase_request_msg}
            )
            
    # Run a check daily to see if it's the 15th
    # job_queue.run_daily(
    #     monthly_purchase_reminder,
    #     time=logging.time(hour=13, minute=0), # 1:00 PM
    #     name="monthly_purchase_request"
    # )
    # Simpler: just run_daily and add the day check within the handler.

    # 5. Reminder of attending Pitching Night - One-time event
    pitching_night_msg = (
        "🎤 *Pitching Night Reminder* 🎤\n\n"
        "Don't forget to attend the Pitching Night! Your attendance is mandatory to support your peers. \n"
        "Date: [Date] | Time: [Time] | Location: [Venue/Zoom Link]"
    )
    job_queue.run_once(
        send_reminder,
        when=1672531200, # Unix timestamp for the event date - REPLACE WITH REAL DATE
        data={'chat_id': chat_id, 'message': pitching_night_msg},
        name="pitching_night_reminder"
    )

    # 6. Reminder of attending Sharing Session - One-time event
    sharing_session_msg = (
        "💡 *Sharing Session Reminder* 💡\n\n"
        "Join the upcoming Sharing Session to learn new skills from industry experts. See you there!\n"
        "Date: [Date] | Time: [Time] | Location: [Venue/Zoom Link]"
    )
    job_queue.run_once(
        send_reminder,
        when=1672531200, # Unix timestamp for the event date - REPLACE WITH REAL DATE
        data={'chat_id': chat_id, 'message': sharing_session_msg},
        name="sharing_session_reminder"
    )

    logger.info(f"All Innovators' Track jobs have been successfully scheduled for chat ID: {chat_id}")
    return len(job_queue.jobs())


# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and shows the main commands."""
    await update.message.reply_text(
        "Welcome to the Innovators' Track Reminder Bot!\n"
        "Use /get_id to find the chat ID for scheduling.\n"
        "Use /set_schedule to activate all standard reminders (Admin only).\n"
        "Use /show_jobs to see currently active scheduled jobs (Admin only)."
    )

async def get_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the Chat ID of the current conversation."""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"The Chat ID for this conversation is: `{chat_id}`\n"
        "Use this ID for the `PIC_CHAT_ID` environment variable.",
        parse_mode='Markdown'
    )
    logger.info(f"Chat ID requested: {chat_id}")

async def set_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to clear existing jobs and set up all default scheduled jobs."""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("🚫 Access Denied: Only the specified Admin can run this command.")
        return

    # 1. Clear existing jobs to prevent duplicates
    current_jobs = context.application.job_queue.get_jobs_by_name("zoom_update_ay25_onwards")
    current_jobs.extend(context.application.job_queue.get_jobs_by_name("zoom_update_pre_ay25"))
    current_jobs.extend(context.application.job_queue.get_jobs_by_name("quarterly_update_jan_q1"))
    current_jobs.extend(context.application.job_queue.get_jobs_by_name("pitching_night_reminder"))
    current_jobs.extend(context.application.job_queue.get_jobs_by_name("sharing_session_reminder"))

    for job in current_jobs:
        job.schedule_removal()
        logger.info(f"Removed old job: {job.name}")

    # 2. Schedule the new jobs
    try:
        jobs_count = schedule_innovators_track_jobs(context.application.job_queue, PIC_CHAT_ID)
        await update.message.reply_text(
            f"✅ Success! Cleared old jobs and scheduled {jobs_count} new reminders "
            f"to the target chat ID (`{PIC_CHAT_ID}`)."
        )
    except Exception as e:
        logger.error(f"Failed to set schedule: {e}")
        await update.message.reply_text(f"❌ Error setting up schedule: {e}")

async def show_jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to list all active jobs in the queue."""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("🚫 Access Denied: Only the specified Admin can run this command.")
        return

    job_queue = context.application.job_queue
    jobs = job_queue.jobs()
    
    if not jobs:
        message = "There are no jobs currently scheduled."
    else:
        message = "Current Scheduled Jobs:\n"
        for job in jobs:
            message += f"- *{job.name}* (Next Run: {job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')})\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the administrator."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    if update:
        error_message = f"An error occurred: `{context.error}`\nUpdate: `{update}`"
    else:
        error_message = f"An error occurred: `{context.error}`"
        
    # Attempt to notify the admin user
    try:
        await context.bot.send_message(chat_id=ADMIN_USER_ID, text=f"🚨 Bot Error Alert:\n{error_message}", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Could not send error notification to admin: {e}")


def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set. Cannot run bot.")
        return

    # Use ApplicationBuilder to easily configure and create the application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Get the job queue instance
    job_queue = application.job_queue

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("get_id", get_id_command))
    application.add_handler(CommandHandler("set_schedule", set_schedule_command))
    application.add_handler(CommandHandler("show_jobs", show_jobs_command))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Start polling
    logger.info("Bot is starting to poll...")
    # NOTE: The job queue starts automatically when the bot is run.
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
