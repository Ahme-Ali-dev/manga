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
from threading import Thread

# Setup Flask server
def run_flask():
    app = Flask("")

    @app.route("/")
    def home():  # This function is required by Flask, even if not accessed
        return "Bot is running"

    try:
        app.run(host="0.0.0.0", port=8000)
    except Exception as e:
        print(f"Failed to start Flask server: {e}")

# Load the bot token from environment variables
TOKEN = os.environ["TOKEN"]
GROUP_CHAT_ID = int(os.environ["GROUP_CHAT_ID"])

# Use the current directory (root) for downloads instead of a subfolder.
# Note: Because we are mixing our code files and downloaded files, we use a prefix (e.g. "downloaded_")
# for all files that are created by the download process.
DOWNLOAD_DIR = "."  # current working directory

if not TOKEN:
    raise ValueError("No TELEGRAM_BOT_TOKEN environment variable set")

# Setup Telegram bot handlers
async def start(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id == GROUP_CHAT_ID:
        await update.message.reply_text("Welcome to the Manga Downloader Bot! Send me the URL of the manga chapter.")
    else:
        await update.message.reply_text("This bot is restricted to a specific group chat.")

async def get_url(update: Update, _context: ContextTypes.DEFAULT_TYPE):
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

        # Process each image found in the HTML
        for i, image in enumerate(images):
            src = image.get("src")
            if not src or not src.lower().endswith(("jpg", "jpeg", "png")):
                continue

            # Only download images whose filenames contain digits (as in your original logic)
            if not any(char.isdigit() for char in os.path.basename(src)):
                continue

            img_url = urljoin(url, src)
            # Prepend a prefix and a counter to avoid collisions
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

                    # Save as JPEG using the same prefix
                    compressed_filename = os.path.join(DOWNLOAD_DIR, f"downloaded_{i}_{os.path.splitext(base_name)[0]}.jpg")
                    img.save(compressed_filename, "JPEG", quality=85)

                    # Remove the original file if it differs from the compressed file
                    if local_filename != compressed_filename:
                        os.remove(local_filename)
                        local_filename = compressed_filename

                downloaded_images += 1
                progress = (downloaded_images / total_images) * 100
                await status_message.edit_text(f"Downloaded and optimized {os.path.basename(local_filename)}\nProgress: {progress:.2f}%")
            except Exception as e:
                await status_message.edit_text(f"Failed to download {os.path.basename(local_filename)}: {e}\nProgress: {progress:.2f}%")

        output_filename = create_cbz_file()
        await status_message.edit_text("Download and CBZ creation completed!")

        with open(output_filename, "rb") as cbz_file:
            await update.message.reply_document(document=InputFile(cbz_file, filename=output_filename))

    except Exception as e:
        await status_message.edit_text(f"An error occurred: {e}")
    finally:
        cleanup_files(output_filename)

def create_cbz_file():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # Save the CBZ file in the root
    output_filename = f"manga_{timestamp}.cbz"
    with zipfile.ZipFile(output_filename, 'w') as cbz:
        for filename in os.listdir(DOWNLOAD_DIR):
            # Only include files that were downloaded (our files start with "downloaded_")
            if filename.startswith("downloaded_"):
                file_path = os.path.join(DOWNLOAD_DIR, filename)
                cbz.write(file_path, arcname=filename)
    return output_filename

def cleanup_files(output_filename):
    """
    Clean up only files created during the current run.
    This function deletes files that start with 'downloaded_' or
    match the naming pattern of the CBZ files (e.g. manga_YYYYMMDD_HHMMSS.cbz).
    It leaves protected files such as main.py and requirements.txt untouched.
    """
    # Define a set of protected filenames (your code files)
    protected_files = {"main.py", "requirements.txt", os.path.basename(__file__)}
    # Also, protect the output file (CBZ) only until it is sent; then remove it explicitly.
    for filename in os.listdir(DOWNLOAD_DIR):
        # Do not remove protected files.
        if filename in protected_files:
            continue
        # Remove files that have our "downloaded_" prefix.
        if filename.startswith("downloaded_"):
            file_path = os.path.join(DOWNLOAD_DIR, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f"Failed to delete {file_path}: {e}")
        # Remove CBZ files that match our naming pattern.
        elif re.match(r'^manga_\d{8}_\d{6}\.cbz$', filename):
            file_path = os.path.join(DOWNLOAD_DIR, filename)
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Failed to delete {file_path}: {e}")

# Start the Flask server in a separate thread
flask_thread = Thread(target=run_flask)
flask_thread.start()

# Initialize the bot application
app = ApplicationBuilder().token(TOKEN).build()

# Add handlers to the bot
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_url))

# Start the bot (using polling)
def run_bot():
    app.run_polling()

run_bot()
