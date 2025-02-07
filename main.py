import datetime
import os
import shutil
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import zipfile
from PIL import Image  # Pillow library for image processing
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import re
from flask import Flask, request
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
TOKEN = os.environ["TOKEN"]
GROUP_CHAT_ID = int(os.environ["GROUP_CHAT_ID"])
# Get the public URL from the environment variable named "WEBHOOK"
PUBLIC_URL = os.environ.get("WEBHOOK")
if not PUBLIC_URL:
    raise ValueError("WEBHOOK environment variable not set.")

# Use /tmp as the download directory since Koyeb's root filesystem is read-only
DOWNLOAD_DIR = "/tmp"

# -------------------------------
# Telegram Bot Handlers
# -------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id == GROUP_CHAT_ID:
        await update.message.reply_text("Welcome to the Manga Downloader Bot! Send me the URL of the manga chapter.")
    else:
        await update.message.reply_text("This bot is restricted to a specific group chat.")

async def get_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != GROUP_CHAT_ID:
        await update.message.reply_text("This bot is restricted to a specific group chat.")
        return

    url = update.message.text
    if not re.match(r'^(http|https)://', url):
        await update.message.reply_text("The provided text is not a valid URL. Please send a valid URL.")
        return

    status_message = await update.message.reply_text(f"URL received: {url}\nStarting download...")

    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        images = soup.find_all("img")
        total_images = len(images)
        downloaded_images = 0

        for i, image in enumerate(images):
            src = image.get("src")
            if not src or not src.lower().endswith(("jpg", "jpeg", "png")):
                continue

            # Only download images whose filenames contain digits (as per your logic)
            if not any(char.isdigit() for char in os.path.basename(src)):
                continue

            img_url = urljoin(url, src)
            base_name = os.path.basename(src)
            local_filename = os.path.join(DOWNLOAD_DIR, f"downloaded_{i}_{base_name}")

            try:
                img_data = requests.get(img_url).content
                with open(local_filename, "wb") as f:
                    f.write(img_data)

                with Image.open(local_filename) as img:
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    new_width = int(img.width * 0.8)
                    new_height = int(img.height * 0.8)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    compressed_filename = os.path.join(DOWNLOAD_DIR, f"downloaded_{i}_{os.path.splitext(base_name)[0]}.jpg")
                    img.save(compressed_filename, "JPEG", quality=85)
                    if local_filename != compressed_filename:
                        os.remove(local_filename)
                        local_filename = compressed_filename

                downloaded_images += 1
                progress = (downloaded_images / total_images) * 100
                await status_message.edit_text(
                    f"Downloaded and optimized {os.path.basename(local_filename)}\nProgress: {progress:.2f}%"
                )
            except Exception as e:
                await status_message.edit_text(
                    f"Failed to download {os.path.basename(local_filename)}: {e}\nProgress: {progress:.2f}%"
                )

        output_filename = create_cbz_file()
        await status_message.edit_text("Download and CBZ creation completed!")

        with open(output_filename, "rb") as cbz_file:
            await update.message.reply_document(document=InputFile(cbz_file, filename=os.path.basename(output_filename)))
    except Exception as e:
        await status_message.edit_text(f"An error occurred: {e}")
    finally:
        cleanup_files(output_filename)

def create_cbz_file():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = os.path.join(DOWNLOAD_DIR, f"manga_{timestamp}.cbz")
    with zipfile.ZipFile(output_filename, 'w') as cbz:
        for filename in os.listdir(DOWNLOAD_DIR):
            if filename.startswith("downloaded_"):
                file_path = os.path.join(DOWNLOAD_DIR, filename)
                cbz.write(file_path, arcname=filename)
    return output_filename

def cleanup_files(output_filename):
    """
    Delete files created during the download process from the DOWNLOAD_DIR.
    Since our code files reside elsewhere, there is no risk here.
    """
    for filename in os.listdir(DOWNLOAD_DIR):
        if filename.startswith("downloaded_") or re.match(r'^manga_\d{8}_\d{6}\.cbz$', filename):
            file_path = os.path.join(DOWNLOAD_DIR, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logging.error(f"Failed to delete {file_path}: {e}")

# -------------------------------
# Setting Up the Bot with Webhooks
# -------------------------------

app_bot = ApplicationBuilder().token(TOKEN).build()
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_url))

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is running!"

@app_flask.route('/webhook', methods=["POST"])
def webhook_handler():
    update = Update.de_json(request.get_json(force=True), app_bot.bot)
    app_bot.process_update(update)
    return "OK", 200

if __name__ == '__main__':
    # Construct the full webhook URL using PUBLIC_URL from the environment variable
    full_webhook_url = f"{PUBLIC_URL}/webhook"
    app_bot.bot.set_webhook(full_webhook_url)
    port = int(os.environ.get("PORT", 8000))
    app_flask.run(host="0.0.0.0", port=port)
