import logging
import os
import asyncio
from datetime import timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables (for local testing)
load_dotenv()

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize message storage (per chat ID)
message_history = {}  # {chat_id: [{'text': str, 'timestamp': datetime, 'username': str}, ...]}

# Initialize OpenAI client
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")
client = OpenAI(api_key=openai_api_key)

# Get Telegram bot token from environment
telegram_bot_token = os.getenv("TOKEN")
if not telegram_bot_token:
    raise ValueError("TOKEN environment variable not set")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command."""
    chat_id = update.message.chat_id
    logger.info("Start command received in chat %s", chat_id)
    try:
        await asyncio.sleep(1)  # Avoid flood control
        await update.message.reply_text("Hi! I'm a summarization bot. Send /summarize to summarize the entire chat history with usernames and reminders.")
        logger.info("Sent start message to chat %s", chat_id)
    except Exception as e:
        logger.error("Failed to send start message to chat %s: %s", chat_id, e)

async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /summarize command."""
    chat_id = update.message.chat_id
    logger.info("Summarize command received in chat %s", chat_id)
    
    if chat_id not in message_history:
        logger.info("No messages stored for chat %s", chat_id)
        try:
            await asyncio.sleep(1)
            logger.info("Sending message to chat %s: %s", chat_id, "No messages stored for this chat yet.")
            response = await update.message.reply_text("No messages stored for this chat yet.")
            logger.info("Sent no-messages prompt to chat %s, response: %s", chat_id, response.to_dict())
        except Exception as e:
            logger.error("Failed to send no-messages prompt in chat %s: %s", chat_id, e)
        return

    # Use all messages in message_history
    relevant_messages = message_history[chat_id]
    logger.info("Relevant messages in chat %s: %s", chat_id, relevant_messages)

    if not relevant_messages:
        logger.info("No messages found in chat %s", chat_id)
        try:
            await asyncio.sleep(1)
            logger.info("Sending message to chat %s: %s", chat_id, "No messages found in chat.")
            response = await update.message.reply_text("No messages found in chat.")
            logger.info("Sent no-messages prompt to chat %s, response: %s", chat_id, response.to_dict())
        except Exception as e:
            logger.error("Failed to send no-messages prompt in chat %s: %s", chat_id, e)
        return

    # Format messages with usernames for summarization
    text_to_summarize = " ".join(f"[@{msg['username']}] {msg['text']}" for msg in relevant_messages)
    logger.info("Text to summarize in chat %s: %s", chat_id, text_to_summarize)

    if len(text_to_summarize) < 10:
        logger.info("Not enough text to summarize in chat %s", chat_id)
        try:
            await asyncio.sleep(1)
            logger.info("Sending message to chat %s: %s", chat_id, "Not enough text to summarize.")
            response = await update.message.reply_text("Not enough text to summarize.")
            logger.info("Sent not-enough-text prompt to chat %s, response: %s", chat_id, response.to_dict())
        except Exception as e:
            logger.error("Failed to send not-enough-text prompt in chat %s: %s", chat_id, e)
        return

    try:
        logger.info("Calling OpenAI API for summarization in chat %s", chat_id)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes text. Include usernames in the summary. Extract reminders, places to be, or events in bullet points."},
                {"role": "user", "content": f"Summarize the following text in 1-2 sentences (max 130 characters, include usernames). Then list any reminders, places to be, or events in bullet points:\n{text_to_summarize}"}
            ],
            max_tokens=150,
            temperature=0.5
        )
        summary = response.choices[0].message.content.strip()
        logger.info("Summary generated for chat %s: %s", chat_id, summary)

        # Format the response with proper line breaks
        await asyncio.sleep(1)
        response = await update.message.reply_text(f"Summary:\n{summary}")
        logger.info("Sent summary to chat %s, response: %s", chat_id, response.to_dict())
    except Exception as e:
        logger.error("Summarization error in chat %s: %s", chat_id, e)
        try:
            await asyncio.sleep(1)
            response = await update.message.reply_text("Failed to summarize messages. Please try again later.")
            logger.info("Sent summarization error message to chat %s, response: %s", chat_id, response.to_dict())
        except Exception as e:
            logger.error("Failed to send summarization error message to chat %s: %s", chat_id, e)

async def store_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store incoming text messages."""
    chat_id = update.message.chat_id
    logger.info("Received message in chat %s: %s", chat_id, update.message.to_dict())

    if not update.message.text:
        logger.info("Received non-text message in chat %s", chat_id)
        return

    if chat_id not in message_history:
        message_history[chat_id] = []

    # Get the username or first name of the sender
    sender = update.message.from_user
    username = sender.username if sender.username else sender.first_name

    message_history[chat_id].append({
        'text': update.message.text,
        'timestamp': update.message.date,
        'username': username
    })
    logger.info("Stored message in chat %s: %s", chat_id, update.message.text)

    # Limit history to last 100 messages or 1 hour
    cutoff_time = update.message.date - timedelta(hours=1)
    message_history[chat_id] = [
        msg for msg in message_history[chat_id]
        if msg['timestamp'] >= cutoff_time
    ][-100:]
    logger.info("Updated message history for chat %s: %s", chat_id, message_history[chat_id])

def main():
    """Run the bot."""
    try:
        logger.info("Building application with token: %s", telegram_bot_token)
        application = Application.builder().token(telegram_bot_token).build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("summarize", summarize))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, store_message))

        # Check if running on Heroku (webhook mode) or locally (polling mode)
        if "APP_NAME" in os.environ:
            # Heroku deployment using webhook
            port = int(os.environ.get("PORT", 8443))
            app_name = os.getenv("APP_NAME")
            webhook_path = "/webhook"  # Simplified path
            webhook_url = f"https://{app_name}.herokuapp.com{webhook_path}"
            logger.info("Setting webhook for Heroku: %s", webhook_url)
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=webhook_path,
                webhook_url=webhook_url
            )
        else:
            # Local testing using polling
            logger.info("Starting bot polling for local testing...")
            application.run_polling()

    except Exception as e:
        logger.error("Bot failed to start: %s", e)
        raise
    

if __name__ == '__main__':
    main()