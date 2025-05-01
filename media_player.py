import os
import sys
import json
import random
import logging
import concurrent.futures
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QPushButton, QLabel, QSlider, QFileDialog, QMessageBox,
    QSizePolicy, QStyle, QProgressBar, QListWidgetItem
)
from PyQt5.QtCore import (
    Qt, QUrl, QDir, QTime, QSize, QThread, pyqtSignal, QEvent, QFileInfo
)
from PyQt5.QtGui import QIcon
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget

# Desteklenen dosya formatları
SUPPORTED_FORMATS = ['mp3', 'mp4', 'avi', 'mkv', 'wav', 'mov', 'flac']

# Loglama ayarları
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# BASE_DIR ayarı
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class CustomVideoWidget(QVideoWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.title_label = QLabel(self)  # Doğrudan self'e bağlı
        self.title_label.setFixedHeight(40)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 200);
            color: white;
            font-size: 16px;
            padding: 8px;
            border-radius: 4px;
        """)
        self.title_label.hide()  # Başlangıçta gizli
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Başlık etiketini videonun alt kısmına sabitle
        self.title_label.setGeometry(0, self.height() - 40, self.width(), 40)

# =============================================================================
# Medya Yükleyici: Medya dosyasını arka planda yükler
# =============================================================================
class MediaLoader(QThread):
    loaded = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, media_path):
        super().__init__()
        self.media_path = media_path

    def run(self):
        try:
            logger.debug(f"Medya yükleniyor: {self.media_path}")
            media_content = QMediaContent(QUrl.fromLocalFile(self.media_path))
            self.loaded.emit(media_content)
        except Exception as e:
            logger.error(f"Medya yükleme hatası: {e}")
            self.error.emit(f"Yükleme hatası: {str(e)}")
        self.quit()


# =============================================================================
# Metadata Yükleyici: Medya dosyalarının süresini hesaplar (arka plan)
# =============================================================================
class MetadataLoader(QThread):
    metadataLoaded = pyqtSignal(list)

    def __init__(self, media_files):
        super().__init__()
        self.media_files = media_files

    def run(self):
        logger.debug("Metadata yüklemesi başlatılıyor")
        try:
            from mutagen import File as MutagenFile
        except ImportError:
            logger.warning("Mutagen yüklü değil; metadata hesaplanamıyor")
            for media in self.media_files:
                media['duration'] = 0
            self.metadataLoaded.emit(self.media_files)
            return

        def get_duration(path):
            try:
                media = MutagenFile(path)
                if media and media.info:
                    duration = int(media.info.length * 1000)
                    logger.debug(f"{path} süresi: {duration} ms")
                    return duration
            except Exception as e:
                logger.error(f"Metadata hatası ({path}): {e}")
            return 0

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {executor.submit(get_duration, media['path']): media for media in self.media_files}
            for future in concurrent.futures.as_completed(futures):
                media = futures[future]
                media['duration'] = future.result()
        logger.debug("Metadata hesaplaması tamamlandı")
        self.metadataLoaded.emit(self.media_files)


# =============================================================================
# Medya Tarayıcı: Seçilen klasördeki medya dosyalarını arka planda tarar
# =============================================================================
class MediaScanner(QThread):
    scanCompleted = pyqtSignal(list)

    def __init__(self, folder):
        super().__init__()
        self.folder = folder

    def run(self):
        logger.debug(f"Klasör taraması başlatılıyor: {self.folder}")
        media_files = []
        for root, dirs, files in os.walk(self.folder):
            for file in files:
                ext = file.split('.')[-1].lower()
                if ext in SUPPORTED_FORMATS:
                    media_path = os.path.join(root, file)
                    try:
                        size = os.path.getsize(media_path)
                    except Exception as e:
                        logger.error(f"{media_path} dosya boyutu okunurken hata: {e}")
                        size = 0
                    media_files.append({
                        'path': media_path,
                        'name': file,
                        'duration': 0,
                        'size': size
                    })
        logger.debug(f"{len(media_files)} adet medya dosyası bulundu")
        self.scanCompleted.emit(media_files)


# =============================================================================
# Ana Uygulama Sınıfı: Medya Kütüphanesi
# =============================================================================
class MediaLibrary(QMainWindow):
    def __init__(self):
        super().__init__()
        # İş parçacığı ve medya yönetimi için değişkenler
        self.media_loader = None
        self.metadata_loader = None
        self.scanner = None
        self.current_folder = ""
        self.media_files = []
        self.original_order = []
        self.current_media = None
        self.last_highlighted_item = None

        # Cache klasörü oluşturuluyor
        self.cache_dir = os.path.join(BASE_DIR, "data", ".media_player_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Medya oynatıcı ve video widget kurulumu
        self.media_player = QMediaPlayer()
        self.video_widget = CustomVideoWidget()
        # QVideoWidget’in native pencere modunu kapatın:
        self.video_widget.setAttribute(Qt.WA_NativeWindow, False)
        self.media_player.setVideoOutput(self.video_widget)

        # Video başlık etiketini oluşturuyoruz:
        self.video_title_label = self.video_widget.title_label
        self.video_title_label.setFixedHeight(40)  # Sabit yükseklik
        self.video_title_label.setAlignment(Qt.AlignCenter)
        # Görünürlüğü artırmak için arka plan rengi ayarlanıyor:
        self.video_title_label.setStyleSheet(
            "background-color: rgba(0,0,0,150); color: white; font-size: 16px; padding: 8px; border-radius: 4px;"
        )
        self.video_title_label.setText("Video Başlığı")  # Test için metin
        self.video_title_label.raise_()  # Etiketi en üste çıkarın
        self.video_title_label.show()

        # CustomVideoWidget'in title_label referansını ayarlıyoruz:
        self.video_widget.title_label = self.video_title_label
        self.video_widget.installEventFilter(self)
        self.playback_modes = {'repeat': False, 'shuffle': False}
 

        # UI oluşturuluyor
        self.init_ui()
        self.apply_styles()

        # Sinyaller: stateChanged yerine mediaStatusChanged kullanıyoruz.
        self.media_player.mediaStatusChanged.connect(self.handle_media_status_changed)
        self.media_player.positionChanged.connect(self.update_time_and_highlight)
        self.media_player.durationChanged.connect(self.update_duration)

    # -------------------------------------------------------------------------
    # Cache işlemleri
    # -------------------------------------------------------------------------
    def get_cache_path(self, folder_path):
        folder_hash = abs(hash(folder_path)) % (10 ** 8)
        return os.path.join(self.cache_dir, f"{folder_hash}.json")

    def read_from_cache(self, folder_path):
        cache_path = self.get_cache_path(folder_path)
        try:
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                    if data['last_modified'] == os.path.getmtime(folder_path):
                        logger.debug("Cache'den medya dosyaları yüklendi")
                        return data['media_files']
        except Exception as e:
            logger.error(f"Cache okuma hatası: {e}")
        return None

    def write_to_cache(self, folder_path, media_files):
        cache_path = self.get_cache_path(folder_path)
        try:
            data = {
                'last_modified': os.path.getmtime(folder_path),
                'media_files': media_files
            }
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug("Cache dosyası güncellendi")
        except Exception as e:
            logger.error(f"Cache yazma hatası: {e}")

    # -------------------------------------------------------------------------
    # Video widget ve etiket olayları
    # -------------------------------------------------------------------------
    def video_resized(self, event):
        self.video_title_label.resize(self.video_widget.width(), 40)
        self.video_title_label.move(0, self.video_widget.height() - 40)
        super(CustomVideoWidget, self.video_widget).resizeEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.video_widget:
            if event.type() == QEvent.Enter:
                self.show_video_title()
            elif event.type() == QEvent.Leave:
                self.hide_video_title()
        return super().eventFilter(obj, event)

    def show_video_title(self):
        if self.current_media:
            self.video_title_label.setText(self.current_media['name'])
            self.video_title_label.show()  # Sadece görünür yap

    def hide_video_title(self):
        self.video_title_label.hide()

    # -------------------------------------------------------------------------
    # Zaman ve vurgulama güncellemeleri
    # -------------------------------------------------------------------------
    def update_time_and_highlight(self, position):
        self.update_time(position)
        self.update_highlight()

    def update_time(self, position):
        duration = self.media_player.duration()
        current_time = QTime(0, 0).addMSecs(position).toString('mm:ss')
        total_time = QTime(0, 0).addMSecs(duration).toString('mm:ss') if duration > 0 else '00:00'
        self.lbl_time.setText(f"{current_time} / {total_time}")
        self.time_slider.setValue(position)

    def update_highlight(self):
        if self.last_highlighted_item and self.media_list.row(self.last_highlighted_item) >= 0:
            self.last_highlighted_item.setBackground(Qt.transparent)
        if self.current_media:
            for index in range(self.media_list.count()):
                item = self.media_list.item(index)
                if item.data(Qt.UserRole) == self.current_media['name']:
                    item.setBackground(Qt.darkGray)
                    self.last_highlighted_item = item 
                    return
            logger.debug("Vurgulanacak medya bulunamadı")

    # -------------------------------------------------------------------------
    # UI Bileşenleri
    # -------------------------------------------------------------------------
    def init_ui(self):
        self.setWindowTitle('Ultimate Media Player')
        self.setGeometry(100, 100, 1280, 720)
        self.setWindowIcon(QIcon('media_icon.png'))

        main_splitter = QSplitter(Qt.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)

        self.btn_open = QPushButton('Open Folder')
        self.btn_open.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.btn_open.clicked.connect(self.select_folder)

        self.media_list = QListWidget()
        self.media_list.itemDoubleClicked.connect(self.play_selected)

        left_layout.addWidget(self.btn_open)
        left_layout.addWidget(self.media_list)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(10)

        self.video_widget.setMinimumSize(640, 360)
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.sliderMoved.connect(self.set_position)

        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_prev = self.create_control_button(QStyle.SP_MediaSkipBackward)
        self.btn_play = self.create_control_button(QStyle.SP_MediaPlay)
        self.btn_pause = self.create_control_button(QStyle.SP_MediaPause)
        self.btn_stop = self.create_control_button(QStyle.SP_MediaStop)
        self.btn_next = self.create_control_button(QStyle.SP_MediaSkipForward)

        self.btn_play.clicked.connect(self.play_media)
        self.btn_pause.clicked.connect(self.pause_media)
        self.btn_stop.clicked.connect(self.stop_media)
        self.btn_prev.clicked.connect(self.prev_media)
        self.btn_next.clicked.connect(self.next_media)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self.set_volume)

        self.lbl_time = QLabel('00:00 / 00:00')
        self.lbl_time.setAlignment(Qt.AlignCenter)

        self.btn_shuffle = self.create_control_button(QStyle.SP_FileDialogDetailedView)
        self.btn_repeat = self.create_control_button(QStyle.SP_BrowserReload)
        self.btn_shuffle.clicked.connect(self.toggle_shuffle)
        self.btn_repeat.clicked.connect(self.toggle_repeat)

        control_layout.addWidget(self.btn_prev)
        control_layout.addWidget(self.btn_play)
        control_layout.addWidget(self.btn_pause)
        control_layout.addWidget(self.btn_stop)
        control_layout.addWidget(self.btn_next)
        control_layout.addWidget(QLabel('🔊'))
        control_layout.addWidget(self.volume_slider)
        control_layout.addSpacing(20)
        control_layout.addWidget(self.lbl_time)
        control_layout.addSpacing(20)
        control_layout.addWidget(self.btn_shuffle)
        control_layout.addWidget(self.btn_repeat)

        right_layout.addWidget(self.video_widget, 3)
        right_layout.addWidget(self.time_slider)
        right_layout.addWidget(control_panel) 

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([300, 980])
        main_splitter.setHandleWidth(10)

        self.setCentralWidget(main_splitter)

    def create_control_button(self, icon_style):
        btn = QPushButton()
        btn.setIcon(self.style().standardIcon(icon_style))
        btn.setCheckable(True)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return btn

    # -------------------------------------------------------------------------
    # Medya Tarama, Cache ve Metadata İşlemleri
    # -------------------------------------------------------------------------
    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", QDir.homePath())
        if folder:
            self.current_folder = folder
            cached_data = self.read_from_cache(folder)
            if cached_data:
                self.media_files = cached_data
                self.populate_media_list()
                logger.debug("Medya dosyaları cache'den yüklendi")
                self.start_metadata_loading()
            else:
                self.scanner = MediaScanner(folder)
                self.scanner.scanCompleted.connect(self.on_scan_completed)
                self.scanner.start()

    def on_scan_completed(self, media_files):
        self.media_files = media_files
        self.populate_media_list()
        self.write_to_cache(self.current_folder, self.media_files)
        logger.debug("Klasör taraması tamamlandı, cache güncellendi")
        self.start_metadata_loading()

    def start_metadata_loading(self):
        self.metadata_loader = MetadataLoader(self.media_files)
        self.metadata_loader.metadataLoaded.connect(self.on_metadata_loaded)
        self.metadata_loader.start()

    def on_metadata_loaded(self, media_files):
        self.media_files = media_files
        self.write_to_cache(self.current_folder, self.media_files)
        self.populate_media_list()
        logger.debug("Metadata güncellendi, medya listesi yenilendi")

    def format_duration(self, ms):
        seconds = ms // 1000
        return f"{seconds//60:02}:{seconds%60:02}"

    def populate_media_list(self):
        self.media_list.clear()
        self.last_highlighted_item = None
        for media in self.media_files:
            file_info = QFileInfo(media['path'])
            size_mb = file_info.size() / (1024 * 1024)
            duration = self.format_duration(media.get('duration', 0))
            item = QListWidgetItem()
            widget = QWidget()
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 5, 5, 5)
            layout.setSpacing(10)
            layout.setAlignment(Qt.AlignLeft)
            icon = QLabel()
            icon.setPixmap(self.style().standardIcon(QStyle.SP_FileIcon).pixmap(24, 24))
            layout.addWidget(icon)
            details = QVBoxLayout()
            details.setAlignment(Qt.AlignLeft)
            title = QLabel(media['name'])
            title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold; padding-bottom: 2px;")
            sub_info = QLabel(f"{duration} | {size_mb:.2f} MB")
            sub_info.setStyleSheet("color: #aaaaaa; font-size: 12px;")
            details.addWidget(title)
            details.addWidget(sub_info)
            layout.addLayout(details)
            item.setSizeHint(QSize(200, 60))
            item.setData(Qt.UserRole, media['name'])
            self.media_list.addItem(item)
            self.media_list.setItemWidget(item, widget)

    # -------------------------------------------------------------------------
    # Medya Oynatma İşlemleri
    # -------------------------------------------------------------------------
    def play_selected(self, item):
        try:
            if item:
                media_name = item.data(Qt.UserRole)
                self.current_media = next((m for m in self.media_files if m['name'] == media_name), None)
                if self.current_media:
                    self.stop_media()
                    self.play_media()
                    self.update_highlight()
                    self.show_video_title()  # Ensure the title is updated when media is selected
                else:
                    logger.error("Seçilen medya bulunamadı")
        except Exception as e:
            logger.error(f"Oynatma hatası: {e}")
    def play_media(self):
        if not self.current_media:
            QMessageBox.warning(self, 'Uyarı', 'Lütfen bir medya dosyası seçin!')
            return

        # If media is already loaded and paused, resume playback
        if self.media_player.mediaStatus() == QMediaPlayer.LoadedMedia and self.media_player.state() == QMediaPlayer.PausedState:
            self.media_player.play()
            self.btn_play.setVisible(False)
            self.btn_pause.setVisible(True)
            logger.debug("Medya duraklatılmış durumdan devam ediyor")
            return

        # If media is not loaded or needs to be reloaded
        media_path = self.current_media['path']
        if self.media_loader and self.media_loader.isRunning():
            self.media_loader.quit()
            self.media_loader.wait()
            self.media_loader.deleteLater()

        self.set_controls_enabled(False)
        self.media_loader = MediaLoader(media_path)
        self.media_loader.loaded.connect(self.on_media_loaded_play)
        self.media_loader.error.connect(self.on_media_error)
        self.media_loader.finished.connect(self.cleanup_loader)
        self.media_loader.start()
        logger.debug(f"Medya oynatmaya başlandı: {media_path}")


    def cleanup_loader(self):
        sender = self.sender()
        if sender:
            sender.deleteLater()
        self.media_loader = None

    def on_media_loaded_play(self, media_content):
        self.media_player.setMedia(media_content)
        self.media_player.play()
        self.video_widget.show()
        self.btn_play.setVisible(False)
        self.btn_pause.setVisible(True)
        self.update_highlight()
        self.set_controls_enabled(True)
        logger.debug("Medya yüklendi, oynatılıyor")

    def on_media_error(self, error_msg):
        self.show_error(error_msg)
        self.set_controls_enabled(True) 

    def set_controls_enabled(self, enabled):
        self.btn_play.setEnabled(enabled)
        self.btn_pause.setEnabled(enabled)
        self.btn_stop.setEnabled(enabled)
        self.btn_prev.setEnabled(enabled)
        self.btn_next.setEnabled(enabled)

    def show_error(self, message):
        QMessageBox.critical(self, "Hata", message)
        self.stop_media()

    def pause_media(self):
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.btn_play.setVisible(True)
            self.btn_pause.setVisible(False)
            logger.debug("Medya duraklatıldı")

    def stop_media(self):
        self.media_player.stop()
        self.media_player.setMedia(QMediaContent())  # Unload the media
        self.btn_play.setVisible(True)
        self.btn_pause.setVisible(False)
        self.video_widget.show()
        logger.debug("Medya durduruldu ve kaldırıldı")

    def set_volume(self, value):
        self.media_player.setVolume(value)

    # -------------------------------------------------------------------------
    # Önceki/sonraki medya geçişleri
    # -------------------------------------------------------------------------
    def next_media(self):
        if not self.current_media:
            return
        current_index = self.media_files.index(self.current_media)
        new_index = current_index + 1 if current_index < len(self.media_files) - 1 else 0
        self.current_media = self.media_files[new_index]
        self.stop_media()
        self.play_media()
        self.update_highlight()
        self.show_video_title()  # Ensure the title is updated when media changes
        logger.debug(f"Sonraki medya oynatılıyor: {self.current_media['name']}")

    def prev_media(self):
        if self.current_media:
            current_index = self.media_files.index(self.current_media)
            if current_index > 0:
                self.current_media = self.media_files[current_index - 1]
                self.stop_media()
                self.play_media()
                self.update_highlight()
                self.show_video_title()  # Ensure the title is updated when media changes
                logger.debug(f"Önceki medya oynatılıyor: {self.current_media['name']}")

    def set_position(self, position):
        self.media_player.setPosition(position)

    def update_duration(self, duration):
        self.time_slider.setRange(0, duration)

    # -------------------------------------------------------------------------
    # Medya oynatıcısının durum değişikliği: mediaStatusChanged üzerinden EndOfMedia kontrolü
    # -------------------------------------------------------------------------
    def handle_media_status_changed(self, status):
        from PyQt5.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.EndOfMedia:
            if self.playback_modes['repeat']:
                self.play_media()
            else:
                self.next_media()
            self.show_video_title()  # Ensure the title is updated when media status changes

    def toggle_shuffle(self):
        self.playback_modes['shuffle'] = not self.playback_modes['shuffle']
        self.btn_shuffle.setChecked(self.playback_modes['shuffle'])
        if self.playback_modes['shuffle']:
            self.original_order = self.media_files.copy()
            random.shuffle(self.media_files)
        else:
            self.media_files = self.original_order.copy()
        self.populate_media_list()

    def toggle_repeat(self):
        self.playback_modes['repeat'] = not self.playback_modes['repeat']
        self.btn_repeat.setChecked(self.playback_modes['repeat'])

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0a0a0a;
                border: 1px solid #2a2a2a;
            }
            QWidget {
                color: #e0e0e0;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton {
                background-color: #363636;
                color: #ffffff;
                border-radius: 5px;
                padding: 10px;
                min-width: 45px;
                border: 1px solid #4a4a4a;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border: 1px solid #5e5e5e;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
            QListWidget {
                background-color: #1a1a1a;
                border: 2px solid #2a2a2a;
                border-radius: 6px;
                font-size: 14px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 0px;
                margin: 2px;
                border-bottom: 1px solid #2a2a2a;
                background-color: #1a1a1a;
                min-height: 60px;
            }
            QListWidget::item:hover {
                background-color: #2a2a2a;
            }
            QListWidget::item:selected {
                background-color: #2a2a2a;
                border-left: 4px solid #00a8ff;
                color: #e0e0e0;
            }
            QSlider::groove:horizontal {
                background: #2a2a2a;
                height: 16px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #00a8ff;
                width: 20px;
                height: 20px;
                margin: -8px 0;
                border-radius: 10px;
                border: 2px solid #ffffff;
            }
            QLabel#timeLabel {
                font-size: 14px;
                font-weight: bold;
                color: #00a8ff;
                background-color: #1a1a1a;
                padding: 6px 12px;
                border-radius: 4px;
            }
            CustomVideoWidget {
                background-color: #000000;
                border: 2px solid #3a3a3a;
                border-radius: 6px;
            }
            QScrollBar:vertical {
                background: #1a1a1a;
                width: 12px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #404040;
                min-height: 30px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: #505050;
            }
            QScrollBar::handle:vertical:pressed {
                background: #606060;
            }
            QScrollBar::add-line:vertical, 
            QScrollBar::sub-line:vertical {
                background: none;
                height: 0px;
            }
            QScrollBar::add-page:vertical, 
            QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                height: 0px;
            }
            QPushButton:checked {
                background-color: #00a8ff;
                border: 1px solid #0099e6;
            }
            QPushButton:checked:hover {
                background-color: #0099e6;
            }
        """)
        self.lbl_time.setObjectName("timeLabel")
        self.btn_open.setStyleSheet("""
            QPushButton {
                background-color: #00a8ff;
                color: #ffffff;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #0099e6;
            }
            QPushButton:pressed {
                background-color: #0088cc;
            }
        """)
        self.btn_open.setIconSize(QSize(24, 24))
        self.btn_shuffle.setIconSize(QSize(24, 24))
        self.btn_repeat.setIconSize(QSize(24, 24))
        for btn in [self.btn_play, self.btn_pause, self.btn_stop, self.btn_prev, self.btn_next]:
            btn.setIconSize(QSize(32, 32))
        self.video_title_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 180);
            color: white;
            font-size: 14px;
            padding: 4px;
            border-radius: 3px;
        """)
        self.video_title_label.resize(self.video_widget.width(), 30)
        self.video_title_label.move(0, self.video_widget.height() - 35)
        self.video_title_label.show()

    # -------------------------------------------------------------------------
    # Uygulama kapanışı: İş parçacıkları düzgün kapatılsın
    # -------------------------------------------------------------------------
    def closeEvent(self, event):
        if self.media_loader and self.media_loader.isRunning():
            self.media_loader.quit()
            self.media_loader.wait()
        if self.scanner and self.scanner.isRunning():
            self.scanner.quit()
            self.scanner.wait()
        if self.metadata_loader and self.metadata_loader.isRunning():
            self.metadata_loader.quit()
            self.metadata_loader.wait()
        event.accept()


# =============================================================================
# Uygulama Başlatma
# =============================================================================
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    player = MediaLibrary()
    player.show()
    sys.exit(app.exec_())
