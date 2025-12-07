import os
import shutil
import subprocess
import tempfile
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States
WAITING_FOR_URL = 1

def download_base_apk():
    """Download base APK from Google Drive if it doesn't exist"""
    if os.path.exists('magnet.apk'):
        logger.info("Base APK already exists")
        return True
    
    apk_url = os.environ.get('APK_URL')
    if not apk_url:
        logger.error("APK_URL environment variable not set!")
        return False
    
    try:
        logger.info(f"Downloading base APK from Google Drive...")
        
        # Handle Google Drive download
        session = requests.Session()
        response = session.get(apk_url, stream=True)
        
        # Check if we need to confirm download (large files)
        if 'confirm' in response.text.lower():
            # Extract confirmation token
            for key, value in response.cookies.items():
                if key.startswith('download_warning'):
                    params = {'confirm': value, 'id': apk_url.split('id=')[1]}
                    response = session.get(apk_url, params=params, stream=True)
                    break
        
        # Download the file
        with open('magnet.apk', 'wb') as f:
            for chunk in response.iter_content(chunk_size=32768):
                if chunk:
                    f.write(chunk)
        
        file_size = os.path.getsize('magnet.apk')
        logger.info(f"Base APK downloaded successfully ({file_size} bytes)")
        return True
        
    except Exception as e:
        logger.error(f"Failed to download APK: {str(e)}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data['user_id'] = user_id
    
    await update.message.reply_text(
        f"✨ Welcome! Your user ID is: `{user_id}`\n\n"
        "Please send me the website URL you want to embed in the app:",
        parse_mode='Markdown'
    )
    return WAITING_FOR_URL

async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    user_id = context.user_data['user_id']
    
    await update.message.reply_text("⚙️ Processing your APK... This may take 1-2 minutes.")
    
    try:
        apk_path = create_custom_apk(user_id, url)
        
        with open(apk_path, 'rb') as apk_file:
            await update.message.reply_document(
                document=apk_file,
                filename=f"magnet_{user_id}.apk",
                caption="✅ Your custom APK is ready!\n\n"
                        "📱 You can now install this on your Android device.\n"
                        "⚠️ Make sure to enable 'Install from Unknown Sources' in your settings."
            )
        
        # Cleanup
        if os.path.exists(apk_path):
            os.remove(apk_path)
        
        logger.info(f"APK created successfully for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error creating APK: {str(e)}")
        await update.message.reply_text(f"❌ Error creating APK: {str(e)}\n\nPlease try again or contact support.")
    
    return ConversationHandler.END

def create_custom_apk(user_id: int, url: str):
    """Modifies the base APK with user-specific data"""
    temp_dir = tempfile.mkdtemp()
    base_apk = "magnet.apk"
    
    try:
        logger.info(f"Starting APK creation for user {user_id}")
        
        # 1. Decompile APK
        decompiled_dir = os.path.join(temp_dir, "decompiled")
        logger.info("Decompiling APK...")
        subprocess.run([
            "apktool", "d", base_apk, "-o", decompiled_dir, "-f"
        ], check=True, capture_output=True)
        
        # 2. Modify assets files
        assets_dir = os.path.join(decompiled_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        
        with open(os.path.join(assets_dir, "id.txt"), "w") as f:
            f.write(str(user_id))
        
        with open(os.path.join(assets_dir, "url.txt"), "w") as f:
            f.write(url)
        
        logger.info("Assets modified successfully")
        
        # 3. Rebuild APK
        unsigned_apk = os.path.join(temp_dir, "unsigned.apk")
        logger.info("Rebuilding APK...")
        subprocess.run([
            "apktool", "b", decompiled_dir, "-o", unsigned_apk
        ], check=True, capture_output=True)
        
        # 4. Sign APK
        logger.info("Signing APK...")
        subprocess.run([
            "uber-apk-signer", "-a", unsigned_apk, "-o", temp_dir, "--allowResign"
        ], check=True, capture_output=True)
        
        # Find the signed APK
        signed_apk = None
        for file in os.listdir(temp_dir):
            if file.endswith("-aligned-debugSigned.apk"):
                signed_apk = os.path.join(temp_dir, file)
                break
        
        if not signed_apk or not os.path.exists(signed_apk):
            raise Exception("Signed APK not found")
        
        # Move to final location
        final_apk = os.path.join(temp_dir, f"magnet_{user_id}.apk")
        shutil.move(signed_apk, final_apk)
        
        logger.info("APK created successfully")
        return final_apk
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Subprocess error: {e.stderr if e.stderr else str(e)}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise Exception(f"APK processing failed: {str(e)}")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *APK Generator Bot*\n\n"
        "Commands:\n"
        "/start - Start the APK creation process\n"
        "/cancel - Cancel current operation\n"
        "/help - Show this help message\n\n"
        "This bot creates a custom APK with your user ID and chosen URL.",
        parse_mode='Markdown'
    )

def main():
    # Get bot token from environment variable
    token = os.environ.get('BOT_TOKEN')
    
    if not token:
        logger.error("BOT_TOKEN environment variable not set!")
        return
    
    # Download base APK if needed
    if not download_base_apk():
        logger.error("Failed to get base APK!")
        return
    
    application = Application.builder().token(token).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    
    logger.info("Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
