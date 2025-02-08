import os
import re
import threading
import datetime
import zipfile
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from PIL import Image as PILImage

from kivy.lang import Builder
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.uix.screenmanager import ScreenManager, Screen
from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog

KV = '''
#:import dp kivy.metrics.dp
#:import MDTopAppBar kivymd.uix.toolbar.MDTopAppBar
#:import MDRaisedButton kivymd.uix.button.MDRaisedButton
#:import MDTextField kivymd.uix.textfield.MDTextField
#:import MDProgressBar kivymd.uix.progressbar.MDProgressBar
#:import MDCard kivymd.uix.card.MDCard

ScreenManager:
    DownloadScreen:

<DownloadScreen>:
    name: "download"
    MDBoxLayout:
        orientation: "vertical"
        padding: dp(10)
        spacing: dp(10)
        
        MDTopAppBar:
            title: "Download Manga"
            elevation: 10
            
        MDBoxLayout:
            orientation: "vertical"
            padding: dp(20)
            spacing: dp(20)
            size_hint_y: None
            height: dp(200)
            
            MDCard:
                orientation: "vertical"
                padding: dp(15)
                spacing: dp(15)
                radius: [15,]
                elevation: 8
                
                MDTextField:
                    id: manga_url
                    hint_text: "Enter Manga URL"
                    mode: "rectangle"
                    size_hint_y: None
                    height: dp(50)
                MDRaisedButton:
                    id: download_button
                    text: "Start Download"
                    size_hint_y: None
                    height: dp(50)
                    on_release: app.download_manga(manga_url.text)
                    
        MDProgressBar:
            id: progress_bar
            value: 0
            max: 100
            type: "determinate"
            size_hint_y: None
            height: dp(10)
            
        Widget:
'''

class DownloadScreen(Screen):
    pass

class MangaApp(MDApp):
    def build(self):
        # Set up folder structure:
        #   <Downloads>/manga/       --> for storing final CBZ files
        #   <Downloads>/manga/temp/  --> temporary folder for downloaded images
        downloads_folder = os.path.join(os.path.expanduser("~"), "Downloads")
        self.base_dir = os.path.join(downloads_folder, "manga")
        self.temp_dir = os.path.join(self.base_dir, "temp")
        for folder in [self.base_dir, self.temp_dir]:
            if not os.path.exists(folder):
                os.makedirs(folder)
        
        self.theme_cls.theme_style = "Light"
        return Builder.load_string(KV)
    
    def disable_controls(self):
        """Disable the URL text field and download button."""
        screen = self.root.get_screen('download')
        screen.ids.manga_url.disabled = True
        screen.ids.download_button.disabled = True
        
    def enable_controls(self):
        """Re-enable the URL text field and download button."""
        screen = self.root.get_screen('download')
        screen.ids.manga_url.disabled = False
        screen.ids.download_button.disabled = False
    
    def download_manga(self, url):
        # Validate URL format.
        if not re.match(r'^(http|https)://', url):
            self.show_dialog("Invalid URL", "Please enter a valid manga URL.")
            return
        
        Clock.schedule_once(lambda dt: self.disable_controls())
        # Start the download process on a background thread.
        threading.Thread(target=self._download_manga, args=(url,), daemon=True).start()
    
    def _download_manga(self, url):
        try:
            response = requests.get(url)
        except Exception:
            Clock.schedule_once(lambda dt: self.show_dialog("Error", "Failed to retrieve URL."))
            Clock.schedule_once(lambda dt: self.enable_controls())
            return
        
        soup = BeautifulSoup(response.text, "html.parser")
        images = soup.find_all("img")
        # Filter images with valid extensions.
        valid_images = [
            img for img in images
            if img.get("src") and img.get("src").lower().endswith(("jpg", "jpeg", "png"))
        ]
        
        total_images = len(valid_images)
        # Update progress bar maximum.
        Clock.schedule_once(lambda dt: setattr(self.root.get_screen('download').ids.progress_bar, 'max', total_images))
        # Reset progress bar value.
        Clock.schedule_once(lambda dt: setattr(self.root.get_screen('download').ids.progress_bar, 'value', 0))
        progress = 0
        
        for image in valid_images:
            src = image.get("src")
            img_url = urljoin(url, src)
            local_filename = os.path.join(self.temp_dir, os.path.basename(src))
            try:
                img_data = requests.get(img_url).content
                with open(local_filename, "wb") as f:
                    f.write(img_data)
                # Convert (if needed) and re-save as JPEG.
                with PILImage.open(local_filename) as img:
                    img = img.convert("RGB")
                    img.save(local_filename, "JPEG", quality=85)
            except Exception:
                continue
            
            progress += 1
            Clock.schedule_once(lambda dt, prog=progress: self.update_progress_bar(prog))
        
        self.create_cbz_file()
        # Reset the progress bar after completion.
        Clock.schedule_once(lambda dt: setattr(self.root.get_screen('download').ids.progress_bar, 'value', 0))
        Clock.schedule_once(lambda dt: self.show_dialog("Download Complete", "Manga has been downloaded successfully."))
        Clock.schedule_once(lambda dt: self.enable_controls())
    
    def update_progress_bar(self, value):
        progress_bar = self.root.get_screen('download').ids.progress_bar
        progress_bar.value = value
    
    def create_cbz_file(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = os.path.join(self.base_dir, f"manga_{timestamp}.cbz")
        with zipfile.ZipFile(output_filename, 'w') as cbz:
            for filename in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, filename)
                if os.path.isfile(file_path) and filename.lower().endswith((".jpg", ".jpeg", ".png")):
                    cbz.write(file_path, arcname=filename)
        self.cleanup_temp()
    
    def cleanup_temp(self):
        # Delete all temporary image files.
        for filename in os.listdir(self.temp_dir):
            file_path = os.path.join(self.temp_dir, filename)
            try:
                os.remove(file_path)
            except Exception:
                pass
    
    def show_dialog(self, title, text):
        dialog = MDDialog(title=title, text=text)
        dialog.open()

if __name__ == "__main__":
    MangaApp().run()
