#!/usr/bin/env python3
"""
Telegram Bot - Paid Background Remover (Open Source, Multi-core)
"""

import io
import json
import os
import logging
import time
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from PIL import Image
import asyncio
from concurrent.futures import ProcessPoolExecutor

# ============== SETTINGS ==============
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6274087977"))
PRICE = "25"
CURRENCY = "US$"
PAYMENT_METHOD = "DM the owner: @Sasha12711"
DB_FILE = "approved_users.json"
USER_RATE_LIMIT = 200    # Per hour

# =========== LOGGING ==============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== MODEL MULTIPROCESS ==========
CPUS = os.cpu_count() or 2
executor = ProcessPoolExecutor(max_workers=CPUS)

def load_approved_users():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_approved_users(users):
    with open(DB_FILE, 'w') as f:
        json.dump(list(users), f)

approved_users = load_approved_users()
pending_users = {}
usage_stats = defaultdict(int)
user_last_times = defaultdict(list)

def is_approved(user_id):
    return user_id in approved_users or user_id == ADMIN_ID

def check_rate_limit(user_id):
    now = time.time()
    window = 3600  # 1 hour
    user_last_times[user_id] = [t for t in user_last_times[user_id] if now - t < window]
    if len(user_last_times[user_id]) >= USER_RATE_LIMIT:
        return False, int(window - (now - user_last_times[user_id][0]))
    user_last_times[user_id].append(now)
    return True, None

# ========== AI REMOVAL TASK (multiprocess safe) ==========
def remove_bg_process(image_bytes):
    import io
    from PIL import Image
    from transparent_background import Remover
    remover = Remover(mode='base')
    input_image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    output_image = remover.process(input_image, type='rgba')
    output_buffer = io.BytesIO()
    output_image.save(output_buffer, format='PNG', quality=100)
    output_buffer.seek(0)
    return output_buffer.getvalue()

# ========== HANDLERS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_approved(user_id):
        await update.message.reply_text(
            "✅ You have access!\n\n"
            "Send me any image and I'll remove the background.\n\n"
            "💡 *Send as File* for the highest quality!"
            "\nType /help for tips."
        , parse_mode='Markdown')
    else:
        keyboard = [
            [InlineKeyboardButton("💳 I've Paid - Request Access", callback_data="request_access")],
            [InlineKeyboardButton("💰 See Payment Details", callback_data="show_payment")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"👋 Welcome to *HD Background Remover Bot*!\n\n"
            f"🖼️ Remove backgrounds from any image with AI!\n\n"
            f"💰 Price: {CURRENCY}{PRICE} (one-time, lifetime access)\n\n"
            f"📱 Click below to get started:",
            reply_markup=reply_markup, parse_mode='Markdown'
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name or "Unknown"
    if query.data == "show_payment":
        await query.message.reply_text(
            f"💳 *Payment Details*\n\n"
            f"*Price:* {CURRENCY}{PRICE}\n\n"
            f"Send payment to:\n"
            f"{PAYMENT_METHOD}\n\n"
            f"⚠️ Please include your Telegram username in the payment note!\n\n"
            f"After paying, click 'I've Paid' to request access.", parse_mode='Markdown'
        )
    elif query.data == "request_access":
        if is_approved(user_id):
            await query.message.reply_text("✅ You already have access! Send an image.")
            return
        if user_id in pending_users:
            await query.message.reply_text(
                "⏳ Your request is already pending! Please wait for admin approval."
            )
            return
        pending_users[user_id] = {'username': username}
        admin_keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"deny_{user_id}")
            ]
        ]
        admin_markup = InlineKeyboardMarkup(admin_keyboard)
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💰 New Payment Request!\n\n"
                 f"👤 User: {username}\n"
                 f"🆔 ID: {user_id}"
                 f"\nPaid {CURRENCY}{PRICE}?",
            reply_markup=admin_markup
        )
        await query.message.reply_text(
            "✅ Access requested! The admin will verify your payment soon.\n"
            "You'll receive a message when approved!"
        )
    elif query.data.startswith("approve_"):
        if user_id != ADMIN_ID:
            return
        target_user_id = int(query.data.split("_")[1])
        approved_users.add(target_user_id)
        save_approved_users(approved_users)
        if target_user_id in pending_users:
            del pending_users[target_user_id]
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="🎉 *Access Granted!*\nThank you for your payment!\nYou can now send images to remove backgrounds.\nJust send any image! 📸",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Could not notify user {target_user_id}: {str(e)}")
        await query.message.edit_text(
            f"✅ Approved!\n\nUser {target_user_id} now has access."
        )
    elif query.data.startswith("deny_"):
        if user_id != ADMIN_ID:
            return
        target_user_id = int(query.data.split("_")[1])
        if target_user_id in pending_users:
            del pending_users[target_user_id]
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="❌ Access Denied\n\nYour payment could not be verified.\n"
                     "Please double-check and try again.\n\n"
                     f"Payment details: {PAYMENT_METHOD}"
            )
        except:
            pass
        await query.message.edit_text(
            f"❌ Denied\n\nUser {target_user_id} was not approved."
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👑 Admin Commands:\n\n"
            "/users - List approved users\n"
            "/pending - List pending requests\n"
            "/adduser <id> - Manually add user\n"
            "/removeuser <id> - Remove user\n"
            "/stats - Show statistics"
        )
    else:
        await update.message.reply_text(
            "🆘 *Help*\n\n"
            "Just send any image as file or photo and I'll remove the background!\n\n"
            "💡 *For best results:* send as file, use high-res, clear backgrounds, good lighting.\n",
            parse_mode='Markdown'
        )

async def admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    text = update.message.text
    if text.startswith("/adduser "):
        try:
            target_id = int(text.split()[1])
            approved_users.add(target_id)
            save_approved_users(approved_users)
            await update.message.reply_text(f"✅ Added user {target_id}")
        except:
            await update.message.reply_text("Usage: /adduser <user_id>")
    elif text.startswith("/removeuser "):
        try:
            target_id = int(text.split()[1])
            approved_users.discard(target_id)
            save_approved_users(approved_users)
            await update.message.reply_text(f"✅ Removed user {target_id}")
        except:
            await update.message.reply_text("Usage: /removeuser <user_id>")
    elif text == "/users":
        if approved_users:
            users_list = "\n".join([f"• {uid}" for uid in approved_users])
            await update.message.reply_text(
                f"👥 Approved Users ({len(approved_users)}):\n\n{users_list}"
            )
        else:
            await update.message.reply_text("No approved users yet.")
    elif text == "/pending":
        if pending_users:
            pending_list = "\n".join([f"• {info['username']} ({uid})" for uid, info in pending_users.items()])
            await update.message.reply_text(
                f"⏳ Pending Requests ({len(pending_users)}):\n\n{pending_list}"
            )
        else:
            await update.message.reply_text("No pending requests.")
    elif text == "/stats":
        count_images = sum(usage_stats.values())
        await update.message.reply_text(
            f"📊 Bot Stats\n\n"
            f"✅ Approved users: {len(approved_users)}\n"
            f"⏳ Pending requests: {len(pending_users)}\n"
            f"📷 Images processed: {count_images}"
        )

async def remove_background(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_approved(user_id):
        keyboard = [[InlineKeyboardButton("💳 Get Access", callback_data="show_payment")]]
        await update.message.reply_text(
            f"🔒 Access Required\n\n"
            f"Pay {CURRENCY}{PRICE} for unlimited background removal!\n\n"
            f"Send /start for payment details.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    allowed, wait_secs = check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(
            f"⏳ Please wait {int(wait_secs/60)+1} minutes before sending more images (limit {USER_RATE_LIMIT}/hr)."
        )
        return

    processing_msg = await update.message.reply_text("🔄 Processing... ⏳")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        await processing_msg.edit_text("🤖 Removing background on separate core (fast)...")

        loop = asyncio.get_running_loop()
        output_bytes = await loop.run_in_executor(
            executor, remove_bg_process, image_bytes
        )
        output_buffer = io.BytesIO(output_bytes)

        usage_stats[user_id] += 1

        await processing_msg.delete()
        await update.message.reply_document(
            document=output_buffer,
            filename="no_background.png",
            caption="✅ Done! For best results, send as file."
        )
        logger.info(f"Processed image for user {user_id}")

    except Exception as e:
        logger.exception(f"Error: {e}")
        await processing_msg.edit_text(f"❌ Error: {str(e)}\nIf this keeps happening, contact support.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_approved(user_id):
        await update.message.reply_text(
            f"🔒 Access Required.\nSend /start for payment details."
        )
        return

    document = update.message.document
    if document.mime_type and document.mime_type.startswith('image/'):
        processing_msg = await update.message.reply_text("🔄 Processing HD image...")
        try:
            file = await context.bot.get_file(document.file_id)
            image_bytes = await file.download_as_bytearray()
            await processing_msg.edit_text("🤖 Removing background on separate core...")

            loop = asyncio.get_running_loop()
            output_bytes = await loop.run_in_executor(
                executor, remove_bg_process, image_bytes
            )
            output_buffer = io.BytesIO(output_bytes)
            usage_stats[user_id] += 1

            await processing_msg.delete()
            await update.message.reply_document(
                document=output_buffer,
                filename="no_background.png",
                caption="✅ Done! (Multiprocess)"
            )
            logger.info(f"Processed doc image for user {user_id}")
        except Exception as e:
            logger.exception(f"Error [file]: {e}")
            await processing_msg.edit_text(f"❌ Error: {str(e)}\nTry a different image or contact support.")
    else:
        await update.message.reply_text("⚠️ Please send an image file!")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if user_id == ADMIN_ID and text.startswith("/"):
        await admin_commands(update, context)
        return
    if is_approved(user_id):
        await update.message.reply_text(
            "🖼️ Send an image (preferably as File) and I'll remove the background."
        )
    else:
        await update.message.reply_text(
            f"🔒 You need access first!\nSend /start for payment details."
        )

def main():
    if not BOT_TOKEN:  # ✅ Correct check
        print("❌ Add your bot token!")
        return

    print("🤖 Starting Paid Background Remover Bot (Multi-core)...")
    print(f"💰 Price: {CURRENCY}{PRICE}")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"✅ Approved users: {len(approved_users)}")
    print(f"🚀 Max parallel removals: {CPUS}")
    print("=" * 45)

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    # Admin access
    application.add_handler(CommandHandler("users", admin_commands))
    application.add_handler(CommandHandler("pending", admin_commands))
    application.add_handler(CommandHandler("stats", admin_commands))
    application.add_handler(CommandHandler("adduser", admin_commands))
    application.add_handler(CommandHandler("removeuser", admin_commands))
    # UI
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, remove_background))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Bot running! Send yourself or users to start")
    print("⏹️  Ctrl+C to stop")
    print("=" * 45)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()