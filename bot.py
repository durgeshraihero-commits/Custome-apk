import os
import shutil
import subprocess
import tempfile
import logging
import requests
import zipfile
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
        file_size = os.path.getsize('magnet.apk')
        logger.info(f"Base APK already exists ({file_size} bytes)")
        
        # Verify it's a valid ZIP/APK file
        try:
            with zipfile.ZipFile('magnet.apk', 'r') as zip_ref:
                logger.info("Base APK is valid")
                return True
        except zipfile.BadZipFile:
            logger.warning("Existing APK is corrupted, re-downloading...")
            os.remove('magnet.apk')
    
    apk_url = os.environ.get('APK_URL')
    if not apk_url:
        logger.error("APK_URL environment variable not set!")
        return False
    
    try:
        logger.info(f"Downloading base APK from Google Drive...")
        
        # Extract file ID from URL
        if '/d/' in apk_url:
            file_id = apk_url.split('/d/')[1].split('/')[0]
        elif 'id=' in apk_url:
            file_id = apk_url.split('id=')[1].split('&')[0]
        else:
            logger.error("Invalid Google Drive URL format")
            return False
        
        logger.info(f"File ID: {file_id}")
        
        # Use direct download URL
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        session = requests.Session()
        
        # First request to get the file or confirmation page
        logger.info("Making initial request...")
        response = session.get(download_url, stream=True)
        
        # Check if we need to confirm (large files)
        token = None
        for key, value in response.cookies.items():
            if key.startswith('download_warning'):
                token = value
                break
        
        if token:
            logger.info("Large file detected, using confirmation token...")
            params = {'id': file_id, 'confirm': token}
            response = session.get(download_url, params=params, stream=True)
        
        # Alternative method: check for confirm parameter in response
        if response.status_code == 200:
            # Check if we got HTML (confirmation page) instead of binary
            content_start = response.content[:1000] if hasattr(response, 'content') else b''
            
            if b'<!DOCTYPE html>' in content_start or b'<html>' in content_start:
                logger.info("Received HTML page, trying alternative download method...")
                
                # Try with virus scan bypass
                download_url_alt = f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
                response = session.get(download_url_alt, stream=True)
        
        # Download the file
        logger.info("Starting download...")
        total_size = 0
        chunk_count = 0
        
        with open('magnet.apk', 'wb') as f:
            for chunk in response.iter_content(chunk_size=32768):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)
                    chunk_count += 1
                    
                    # Log progress every 100 chunks (~3MB)
                    if chunk_count % 100 == 0:
                        logger.info(f"Downloaded {total_size / 1024 / 1024:.2f} MB...")
        
        logger.info(f"Download complete: {total_size} bytes ({total_size / 1024 / 1024:.2f} MB)")
        
        # Verify it's a valid APK
        if total_size < 100000:  # Less than 100KB is suspicious
            logger.error(f"Downloaded file is too small ({total_size} bytes). Likely an error page.")
            
            # Check if it's HTML
            with open('magnet.apk', 'rb') as f:
                content_start = f.read(1000)
                if b'<!DOCTYPE html>' in content_start or b'<html>' in content_start:
                    logger.error("Downloaded file is HTML, not an APK. Google Drive link may be restricted.")
                    os.remove('magnet.apk')
                    return False
        
        # Verify ZIP structure
        try:
            with zipfile.ZipFile('magnet.apk', 'r') as zip_ref:
                file_list = zip_ref.namelist()
                logger.info(f"APK is valid! Contains {len(file_list)} files")
                
                # Check for AndroidManifest.xml (all APKs have this)
                if 'AndroidManifest.xml' not in file_list:
                    logger.warning("APK doesn't contain AndroidManifest.xml - might be invalid")
                
                return True
        except zipfile.BadZipFile as e:
            logger.error(f"Downloaded file is not a valid APK/ZIP: {str(e)}")
            os.remove('magnet.apk')
            return False
        
    except Exception as e:
        logger.error(f"Failed to download APK: {str(e)}")
        if os.path.exists('magnet.apk'):
            os.remove('magnet.apk')
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data['user_id'] = user_id
    
    await update.message.reply_text(
        f"✨ *Welcome to APK Generator Bot!*\n\n"
        f"Your user ID: `{user_id}`\n\n"
        "Please send me the website URL you want to embed in the app.\n\n"
        "Example: `https://example.com`",
        parse_mode='Markdown'
    )
    return WAITING_FOR_URL

async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    user_id = context.user_data['user_id']
    
    # Validate URL format
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text(
            "❌ Please send a valid URL starting with http:// or https://\n\n"
            "Example: https://example.com"
        )
        return WAITING_FOR_URL
    
    processing_msg = await update.message.reply_text(
        "⚙️ *Processing your custom APK...*\n\n"
        "This may take 1-3 minutes. Please wait...\n\n"
        "Steps:\n"
        "1️⃣ Decompiling base APK...\n"
        "2️⃣ Adding your data...\n"
        "3️⃣ Rebuilding APK...\n"
        "4️⃣ Signing APK...",
        parse_mode='Markdown'
    )
    
    try:
        apk_path = create_custom_apk(user_id, url)
        
        await processing_msg.edit_text("📤 Uploading your APK...")
        
        with open(apk_path, 'rb') as apk_file:
            await update.message.reply_document(
                document=apk_file,
                filename=f"magnet_{user_id}.apk",
                caption=(
                    "✅ *Your custom APK is ready!*\n\n"
                    f"👤 User ID: `{user_id}`\n"
                    f"🔗 URL: `{url}`\n\n"
                    "📱 *Installation Steps:*\n"
                    "1. Download the APK\n"
                    "2. Enable 'Unknown Sources' in Settings\n"
                    "3. Install and enjoy!\n\n"
                    "⚠️ Note: This is a debug-signed APK for personal use."
                ),
                parse_mode='Markdown'
            )
        
        await processing_msg.delete()
        
        # Cleanup
        if os.path.exists(apk_path):
            os.remove(apk_path)
        
        logger.info(f"✅ APK created successfully for user {user_id} with URL {url}")
        
    except Exception as e:
        logger.error(f"❌ Error creating APK: {str(e)}")
        await processing_msg.edit_text(
            f"❌ *Error creating APK*\n\n"
            f"Error: `{str(e)}`\n\n"
            "Please try again or contact support.\n\n"
            "Common issues:\n"
            "• Base APK download failed\n"
            "• Server memory limit reached\n"
            "• APK protection/obfuscation\n\n"
            "Try /start to restart.",
            parse_mode='Markdown'
        )
    
    return ConversationHandler.END

def create_custom_apk(user_id: int, url: str):
    """Modifies the base APK with user-specific data"""
    temp_dir = tempfile.mkdtemp()
    base_apk = "magnet.apk"
    
    try:
        logger.info(f"🚀 Starting APK creation for user {user_id}")
        
        # Verify base APK exists
        if not os.path.exists(base_apk):
            raise Exception("Base APK not found! Download may have failed.")
        
        apk_size = os.path.getsize(base_apk)
        logger.info(f"Base APK size: {apk_size / 1024 / 1024:.2f} MB")
        
        # 1. Decompile APK
        decompiled_dir = os.path.join(temp_dir, "decompiled")
        logger.info("📦 Decompiling APK...")
        
        result = subprocess.run([
            "apktool", "d", base_apk, "-o", decompiled_dir, "-f"
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            logger.error(f"Apktool stderr: {result.stderr}")
            raise Exception(f"Decompilation failed: {result.stderr}")
        
        logger.info("✅ Decompilation successful")
        
        # 2. Modify assets files
        assets_dir = os.path.join(decompiled_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        
        logger.info("📝 Writing user data...")
        
        with open(os.path.join(assets_dir, "id.txt"), "w", encoding='utf-8') as f:
            f.write(str(user_id))
        
        with open(os.path.join(assets_dir, "url.txt"), "w", encoding='utf-8') as f:
            f.write(url)
        
        logger.info("✅ Assets modified successfully")
        
        # 3. Rebuild APK
        unsigned_apk = os.path.join(temp_dir, "unsigned.apk")
        logger.info("🔨 Rebuilding APK...")
        
        result = subprocess.run([
            "apktool", "b", decompiled_dir, "-o", unsigned_apk
        ], capture_output=True, text=True, timeout=180)
        
        if result.returncode != 0:
            logger.error(f"Apktool build stderr: {result.stderr}")
            raise Exception(f"Build failed: {result.stderr}")
        
        logger.info("✅ APK rebuilt successfully")
        
        # 4. Sign APK
        logger.info("🔐 Signing APK...")
        
        result = subprocess.run([
            "uber-apk-signer", 
            "-a", unsigned_apk, 
            "-o", temp_dir, 
            "--allowResign"
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            logger.error(f"Signer stderr: {result.stderr}")
            raise Exception(f"Signing failed: {result.stderr}")
        
        logger.info("✅ APK signed successfully")
        
        # Find the signed APK
        signed_apk = None
        for file in os.listdir(temp_dir):
            if file.endswith("-aligned-debugSigned.apk"):
                signed_apk = os.path.join(temp_dir, file)
                break
        
        if not signed_apk or not os.path.exists(signed_apk):
            # List all files in temp_dir for debugging
            files = os.listdir(temp_dir)
            logger.error(f"Files in temp_dir: {files}")
            raise Exception("Signed APK not found in output directory")
        
        # Move to final location
        final_apk = os.path.join(temp_dir, f"magnet_{user_id}.apk")
        shutil.move(signed_apk, final_apk)
        
        final_size = os.path.getsize(final_apk)
        logger.info(f"✅ APK created successfully! Size: {final_size / 1024 / 1024:.2f} MB")
        
        return final_apk
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"⏱️ Process timeout: {str(e)}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise Exception(f"Process timed out: {str(e)}")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Subprocess error: {e.stderr if e.stderr else str(e)}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise Exception(f"APK processing failed: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Operation cancelled.\n\n"
        "Send /start to begin again."
    )
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *APK Generator Bot*\n\n"
        "*Commands:*\n"
        "/start - Start the APK creation process\n"
        "/cancel - Cancel current operation\n"
        "/help - Show this help message\n\n"
        "*How it works:*\n"
        "1. Send /start to begin\n"
        "2. Enter your website URL\n"
        "3. Wait 1-3 minutes for processing\n"
        "4. Download your custom APK!\n\n"
        "*Features:*\n"
        "• Embeds your user ID\n"
        "• Embeds your custom URL\n"
        "• Creates signed APK\n"
        "• Ready to install\n\n"
        "⚠️ *Note:* Debug-signed APKs are for personal use only.",
        parse_mode='Markdown'
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check bot status and base APK availability"""
    status_msg = "🤖 *Bot Status*\n\n"
    
    # Check if base APK exists
    if os.path.exists('magnet.apk'):
        size = os.path.getsize('magnet.apk')
        status_msg += f"✅ Base APK: Available ({size / 1024 / 1024:.2f} MB)\n"
        
        # Verify it's valid
        try:
            with zipfile.ZipFile('magnet.apk', 'r') as zip_ref:
                status_msg += f"✅ APK Validity: Valid\n"
        except:
            status_msg += f"❌ APK Validity: Corrupted\n"
    else:
        status_msg += "❌ Base APK: Not found\n"
    
    # Check environment variables
    if os.environ.get('BOT_TOKEN'):
        status_msg += "✅ Bot Token: Configured\n"
    else:
        status_msg += "❌ Bot Token: Missing\n"
    
    if os.environ.get('APK_URL'):
        status_msg += "✅ APK URL: Configured\n"
    else:
        status_msg += "❌ APK URL: Missing\n"
    
    status_msg += "\n📊 Ready to process APKs!"
    
    await update.message.reply_text(status_msg, parse_mode='Markdown')

def main():
    # Get bot token from environment variable
    token = os.environ.get('BOT_TOKEN')
    
    if not token:
        logger.error("❌ BOT_TOKEN environment variable not set!")
        return
    
    logger.info("🤖 Starting Telegram APK Generator Bot...")
    
    # Download base APK if needed
    logger.info("🔍 Checking for base APK...")
    if not download_base_apk():
        logger.error("❌ Failed to get base APK! Bot cannot function without it.")
        logger.error("Please check:")
        logger.error("1. APK_URL environment variable is set correctly")
        logger.error("2. Google Drive link is public (Anyone with link can view)")
        logger.error("3. File ID is correct")
        return
    
    logger.info("✅ Base APK ready!")
    
    # Build application
    application = Application.builder().token(token).build()
    
    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    
    logger.info("✅ Bot started successfully!")
    logger.info("📱 Ready to accept requests...")
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
