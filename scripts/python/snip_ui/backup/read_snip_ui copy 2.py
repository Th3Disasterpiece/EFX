import hou
import os
import json
import glob
import re
import logging
import shutil
import platform
import subprocess
import asyncio
import traceback
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from PIL import Image
import toolutils

from PySide2 import QtWidgets, QtCore, QtGui
from PySide2.QtCore import Qt, QTimer, QSize, QSettings
from PySide2.QtGui import QMovie, QPixmap, QImage, QPainter, QWheelEvent, QIcon, QFont
from PySide2.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, 
                               QProgressDialog, QApplication, QMainWindow, QTreeWidget)

# Constants
SUPPORTED_EXTENSIONS = ['.uti']
MAX_PREVIEW_SIZE = QtCore.QSize(400, 300)
FLIPBOOK_FRAME_RATE = 24  # fps

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class FileManager:
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)

    def get_users(self) -> List[str]:
        pyDump_path = self.base_path / 'pyDump'
        if pyDump_path.exists():
            return [d.name for d in pyDump_path.iterdir() if d.is_dir()]
        logger.warning(f"pyDump directory not found at {pyDump_path}")
        return [hou.getenv("USER")]

    def load_json_data(self):
        user = self.user_combo.currentText()
        master_json_path = Path(self.base_path) / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'
        logger.debug(f"Loading JSON data from: {master_json_path}")
        try:
            with master_json_path.open('r') as f:
                self.json_data = json.load(f)
            if not isinstance(self.json_data, list):
                raise ValueError("JSON data is not a list")
            logger.info(f"Loaded JSON data for user {user}: {len(self.json_data)} entries")
            logger.debug(f"First few entries: {self.json_data[:3]}")
        except Exception as e:
            logger.error(f"Failed to load JSON data: {e}")
            self.json_data = []

    def get_preview_base_path(self, user: str) -> Path:
        preview_path = self.base_path / 'pyDump' / user / 'Snips' / 'preview'
        if not preview_path.exists():
            logger.warning(f"Warning: Preview path does not exist: {preview_path}")
        return preview_path

class PreviewManager:
    def __init__(self, max_preview_size: QtCore.QSize):
        self.max_preview_size = max_preview_size
        self.flipbook_frames = []
        self.current_frame = 0

    def load_flipbook(self, flipbook_path: str) -> List[QtGui.QPixmap]:
        self.flipbook_frames = []
        
        logger.debug(f"Loading flipbook from: {flipbook_path}")
        
        directory = Path(flipbook_path).parent
        if not directory.exists():
            logger.warning(f"Directory does not exist: {directory}")
            return self.flipbook_frames

        image_files = self._get_image_files(flipbook_path)

        logger.debug(f"Found {len(image_files)} image files")
        if not image_files:
            logger.warning(f"No image files found in directory: {directory}")
            return self.flipbook_frames

        self.flipbook_frames = self._load_flipbook_frames(image_files)

        logger.debug(f"Loaded {len(self.flipbook_frames)} frames for flipbook")
        return self.flipbook_frames

    def _get_image_files(self, flipbook_path: str) -> List[Path]:
        path = Path(flipbook_path)
        if '$F' in flipbook_path:
            file_pattern = path.name.replace('$F4', '*').replace('$F', '*')
            return sorted(path.parent.glob(file_pattern))
        elif path.is_file():
            return [path]
        elif path.is_dir():
            return sorted(path.glob('*.[pj][np][gg]'))
        return []

    def _load_flipbook_frames(self, image_files: List[Path]) -> List[QtGui.QPixmap]:
        frames = []
        for image_file in image_files:
            pixmap = QtGui.QPixmap(str(image_file))
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(self.max_preview_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                frames.append(scaled_pixmap)
                logger.debug(f"Loaded image: {image_file}")
            else:
                logger.warning(f"Failed to load image: {image_file}")
        return frames

    def load_snapshot(self, snapshot_path: str) -> Optional[QtGui.QPixmap]:
        if Path(snapshot_path).exists():
            pixmap = QtGui.QPixmap(snapshot_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(self.max_preview_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                logger.debug(f"Loaded snapshot: {snapshot_path}")
                return scaled_pixmap
            else:
                logger.warning(f"Failed to load snapshot: {snapshot_path}")
        else:
            logger.warning(f"Snapshot file not found: {snapshot_path}")
        return None

class CheckableComboBox(QtWidgets.QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view().pressed.connect(self.handle_item_pressed)
        self.setModel(QtGui.QStandardItemModel(self))

    def handle_item_pressed(self, index):
        item = self.model().itemFromIndex(index)
        if item.isCheckable():
            check_state = QtCore.Qt.Unchecked if item.checkState() == QtCore.Qt.Checked else QtCore.Qt.Checked
            item.setCheckState(check_state)
        self.view().update()

    def hidePopup(self):
        # Prevent the popup from hiding when an item is clicked
        pass

    def showPopup(self):
        super().showPopup()
        # Set a minimum width for the popup
        self.view().setMinimumWidth(self.view().sizeHintForColumn(0) + 20)

class ClickableLabel(QtWidgets.QLabel):
    clicked = QtCore.Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

class LargePreviewWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Large Preview")
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint)
        
        self.layout = QtWidgets.QVBoxLayout(self)
        
        self.path_line_edit = QtWidgets.QLineEdit()
        self.path_line_edit.setReadOnly(True)
        self.path_line_edit.setAlignment(QtCore.Qt.AlignCenter)
        self.path_line_edit.setStyleSheet("""
            QLineEdit {
                background-color: #2b2b2b;
                color: #ffffff;
                border: none;
                padding: 5px;
                selection-background-color: #4a90d9;
            }
        """)
        self.layout.addWidget(self.path_line_edit)
        
        self.graphics_view = QGraphicsView(self)
        self.graphics_scene = QGraphicsScene(self)
        self.graphics_view.setScene(self.graphics_scene)
        self.graphics_view.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        self.graphics_view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.layout.addWidget(self.graphics_view)

        bottom_layout = QtWidgets.QHBoxLayout()
        
        zoom_layout = QtWidgets.QHBoxLayout()
        self.zoom_in_button = self.create_icon_button("\u2795", "Zoom In")
        self.zoom_out_button = self.create_icon_button("\u2796", "Zoom Out")
        self.zoom_in_button.clicked.connect(self.zoom_in)
        self.zoom_out_button.clicked.connect(self.zoom_out)
        zoom_layout.addWidget(self.zoom_in_button)
        zoom_layout.addWidget(self.zoom_out_button)
        bottom_layout.addLayout(zoom_layout)
        
        bottom_layout.addStretch()
        
        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.setFixedSize(QSize(60, 24))
        self.close_button.clicked.connect(self.close)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 2px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
            QPushButton:pressed {
                background-color: #1e1e1e;
            }
        """)
        bottom_layout.addWidget(self.close_button)
        
        self.layout.addLayout(bottom_layout)

        screen_rect = QtWidgets.QApplication.desktop().screenGeometry()
        self.setMinimumSize(screen_rect.width() // 2, screen_rect.height() // 2)

        self.flipbook_frames = []
        self.current_frame = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_flipbook_frame)
        self.frame_rate = 24

    def create_icon_button(self, text, tooltip):
        button = QtWidgets.QPushButton(text)
        button.setToolTip(tooltip)
        button.setFixedSize(QSize(24, 24))
        font = QFont()
        font.setPointSize(14)
        button.setFont(font)
        button.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 2px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
            QPushButton:pressed {
                background-color: #1e1e1e;
            }
        """)
        return button

    def zoom_in(self):
        self.scale_view(1.2)

    def zoom_out(self):
        self.scale_view(1 / 1.2)

    def scale_view(self, factor):
        current_scale = self.graphics_view.transform().m11()
        if 0.1 < current_scale * factor < 10:
            self.graphics_view.scale(factor, factor)

    def set_window_size(self, width, height):
        screen_rect = QtWidgets.QApplication.desktop().screenGeometry()
        max_width = int(screen_rect.width() * 0.9)
        max_height = int(screen_rect.height() * 0.9)
        
        window_width = min(int(width * 1.2), max_width)
        window_height = min(int(height * 1.2), max_height)
        
        window_height += self.path_line_edit.sizeHint().height() + self.close_button.sizeHint().height() + 20
        
        self.resize(window_width, window_height)

    def set_snapshot(self, image_path):
        self.path_line_edit.setText(f"Image: {image_path}")
        pixmap = QtGui.QPixmap(image_path)
        if not pixmap.isNull():
            self.graphics_scene.clear()
            pixmap_item = QGraphicsPixmapItem(pixmap)
            self.graphics_scene.addItem(pixmap_item)
            self.graphics_scene.setSceneRect(pixmap.rect())
            self.set_window_size(pixmap.width(), pixmap.height())
        else:
            print(f"Failed to load image: {image_path}")

    def set_flipbook(self, flipbook_folder):
        self.path_line_edit.setText(f"Flipbook: {flipbook_folder}")
        self.flipbook_frames.clear()
        self.current_frame = 0
        
        image_files = sorted(Path(flipbook_folder).glob('*.png'))
        if not image_files:
            print(f"No image files found in flipbook folder: {flipbook_folder}")
            return

        first_frame = QtGui.QPixmap(str(image_files[0]))
        if not first_frame.isNull():
            self.flipbook_frames.append(first_frame)
            self.graphics_scene.clear()
            self.pixmap_item = QGraphicsPixmapItem(first_frame)
            self.graphics_scene.addItem(self.pixmap_item)
            self.graphics_scene.setSceneRect(first_frame.rect())
            self.set_window_size(first_frame.width(), first_frame.height())
            
            progress = QProgressDialog("Loading frames...", "Cancel", 0, len(image_files) - 1, self)
            progress.setWindowModality(QtCore.Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            
            QtCore.QTimer.singleShot(0, lambda: self.load_remaining_frames(image_files[1:], progress))
            
            self.timer.start(1000 // self.frame_rate)
        else:
            print(f"Failed to load first frame: {image_files[0]}")

    def load_remaining_frames(self, image_files, progress):
        for i, image_file in enumerate(image_files):
            if progress.wasCanceled():
                break
            pixmap = QtGui.QPixmap(str(image_file))
            if not pixmap.isNull():
                self.flipbook_frames.append(pixmap)
            else:
                print(f"Failed to load image: {image_file}")
            progress.setValue(i + 1)
        progress.close()
        print(f"Loaded {len(self.flipbook_frames)} frames")

    def update_flipbook_frame(self):
        if self.flipbook_frames:
            num_frames = len(self.flipbook_frames)
            if num_frames > 0:
                self.current_frame = (self.current_frame + 1) % num_frames
                self.pixmap_item.setPixmap(self.flipbook_frames[self.current_frame])
            else:
                print("Flipbook has no frames.")
                self.clear_flipbook()
        else:
            print("No flipbook frames available.")
            self.clear_flipbook()

    def clear_flipbook(self):
        if hasattr(self, 'flipbook_timer'):
            self.flipbook_timer.stop()
        self.flipbook_preview.clear()
        self.flipbook_preview.setText("No flipbook available")
        self.flipbook_preview.setFixedSize(self.MAX_PREVIEW_SIZE)
        self.flipbook_new_button.setEnabled(True)
        self.flipbook_delete_button.setEnabled(False)
        self.preview_manager.current_frame = 0
        self.preview_manager.flipbook_frames = []

    def closeEvent(self, event):
        global _shelf_tool_ui_instance
        _shelf_tool_ui_instance = None
        self.save_settings()
        super().closeEvent(event)

class NameEditorDelegate(QtWidgets.QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QtWidgets.QLineEdit):
            editor.editingFinished.connect(lambda: self.commitAndCloseEditor(editor))
        return editor

    def commitAndCloseEditor(self, editor):
        self.commitData.emit(editor)
        self.closeEditor.emit(editor)

class EditableTreeWidget(QtWidgets.QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(NameEditorDelegate(self))
        self.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)

    def handle_double_click(self, item, column):
        if item.flags() & QtCore.Qt.ItemIsEditable:
            self.editItem(item, column)

    def get_next_selectable_item(self, current_item, key):
        if key == Qt.Key_Down:
            iterator = self.iter_items(current_item, self.itemBelow)
        else:  # Qt.Key_Up
            iterator = self.iter_items(current_item, self.itemAbove)

        for item in iterator:
            if item.flags() & Qt.ItemIsSelectable:
                return item
        return None

    def iter_items(self, start_item, get_next_item):
        item = get_next_item(start_item)
        while item:
            yield item
            item = get_next_item(item)

class NameEditorDelegate(QtWidgets.QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QtWidgets.QLineEdit):
            editor.editingFinished.connect(lambda: self.commitAndCloseEditor(editor))
        return editor

    def commitAndCloseEditor(self, editor):
        self.commitData.emit(editor)
        self.closeEditor.emit(editor)

class MyShelfToolUI(QtWidgets.QWidget):
    instances = []

    @classmethod
    def close_existing_windows(cls):
        global _shelf_tool_ui_instance
        for instance in cls.instances:
            try:
                instance.close()
                instance.deleteLater()
            except:
                pass
        cls.instances.clear()
        _shelf_tool_ui_instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)



        self.base_path = Path(hou.getenv("EFX", ""))
        if not self.base_path.exists():
            raise ValueError("EFX environment variable is not set or invalid")

        self.file_manager = FileManager(str(self.base_path))
        self.preview_manager = PreviewManager(MAX_PREVIEW_SIZE)

        self.preview_visible = True  # or False, depending on your default preference
        self.flipbook_timer = QtCore.QTimer(self)
        self.flipbook_timer.timeout.connect(self.update_flipbook_frame)

        self.current_snapshot_path = None  # Initialize the attribute

        self.file_groups = {}  # Initialize file_groups here

        self.setup_ui()
        self.connect_signals()
        self.load_settings()
        self.load_json_data()
        self.update_file_list()
        # Initialize settings
        self.settings = QSettings("YourCompany", "SnipLibraryUI")
        self.json_cache = {}
        self.preview_cache = {}
        self.thread_pool = ThreadPoolExecutor(max_workers=4)

        self.progress_dialog = None
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.force_close_progress_dialog)

        self.cache_timer = QtCore.QTimer(self)
        self.cache_timer.timeout.connect(self.clear_cache)
        self.cache_timer.start(300000)  # Clear cache every 5 minutes (300,000 ms)

        self.update_preview_timer = QtCore.QTimer()
        self.update_preview_timer.setSingleShot(True)
        self.update_preview_timer.timeout.connect(self._update_preview)
        self.current_file_path = None
        self.preview_semaphore = asyncio.Semaphore(1)
        self.current_task = None

        self.loading_movie = QMovie(":/icons/loading_spinner.gif")  # Adjust path as needed
        self.loading_movie.setScaledSize(QtCore.QSize(32, 32))

        self.file_list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.file_list_widget.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.file_list_widget.setHeaderLabels(["Context", "Type", "Name", "Source", "Version"])
        self.file_list_widget.itemChanged.connect(self.on_item_changed)
        self.file_list_widget.itemSelectionChanged.connect(self.on_selection_changed)
        self.file_list_widget.itemSelectionChanged.connect(self.update_preview)

    # def log_widget_hierarchy(widget, level=0):
    #     logger.debug(f"{'  ' * level}{widget.__class__.__name__}: {widget.objectName()}")
    #     for child in widget.children():
    #         if isinstance(child, QtWidgets.QWidget):
    #             log_widget_hierarchy(child, level + 1)


    def clear_cache(self):
        self.json_cache.clear()
        self.preview_cache.clear()
        logger.info("Application cache automatically cleared")

    def show_progress_dialog(self, title, message, maximum):
        self.progress_dialog = QProgressDialog(message, "Cancel", 0, maximum, self)
        self.progress_dialog.setWindowTitle(title)
        self.progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        self.progress_dialog.show()
        QApplication.processEvents()
        
    def update_progress(self, value):
        if self.progress_dialog:
            self.progress_dialog.setValue(value)
            QApplication.processEvents()

    def close_progress_dialog(self):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

    def force_close_progress_dialog(self):
        logger.debug("Forcing progress dialog closure")
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
            logger.debug("Progress dialog forcibly closed")
        else:
            logger.warning("No progress dialog to close")
        QApplication.processEvents()
        self.activateWindow()
        self.raise_()

    def setup_ui(self):
        self.setWindowTitle("My Snip Library")
        self.setMinimumSize(1200, 800)

        main_layout = QtWidgets.QVBoxLayout(self)
        
        content_layout = QtWidgets.QHBoxLayout()
        left_layout = self.create_left_layout()
        right_layout = self.create_right_layout()

        content_layout.addLayout(left_layout, 2)
        content_layout.addLayout(right_layout, 1)

        main_layout.addLayout(content_layout)

        # Connect signals for saving settings
        self.user_checkbox.stateChanged.connect(self.save_settings)
        self.user_combo.currentTextChanged.connect(self.save_settings)
        self.group_checkbox.stateChanged.connect(self.save_settings)
        self.group_combo.currentTextChanged.connect(self.save_settings)
        self.source_checkbox.stateChanged.connect(self.save_settings)
        self.source_filter_combo.model().dataChanged.connect(self.save_settings)
        self.filter_line_edit.textChanged.connect(self.save_settings)
        self.file_list_widget.itemSelectionChanged.connect(self.on_selection_changed)

        # Connect group combo box to on_group_changed method
        self.group_combo.currentTextChanged.connect(self.on_group_changed)

        self.file_list_widget.setStyleSheet("""
            QTreeWidget::item:selected {
                background-color: #3399ff;
                color: #ffffff;
            }
            QTreeWidget::item:selected:active {
                background-color: #3399ff;
            }
            QTreeWidget::item:selected:!active {
                background-color: #3399ff;
            }
        """)

    def on_selection_changed(self):
        selected_items = self.file_list_widget.selectedItems()
        if selected_items and not selected_items[0].childCount():
            selected_item = selected_items[0]
            file_path = selected_item.data(0, Qt.UserRole)
            self.update_preview(file_path)
            # Ensure the item remains selected
            self.file_list_widget.setCurrentItem(selected_item)
        else:
            # Only clear preview if no valid item is selected
            if not selected_items:
                self.clear_preview()
        self.file_list_widget.setFocus()
        self.file_list_widget.repaint()

    def create_left_layout(self):
        layout = QtWidgets.QVBoxLayout()

        # Create a layout for filters
        filter_layout = QtWidgets.QHBoxLayout()

        # User filter
        user_layout = QtWidgets.QHBoxLayout()
        self.user_checkbox = QtWidgets.QCheckBox("User:")
        self.user_checkbox.setChecked(True)
        self.user_checkbox.stateChanged.connect(self.on_user_filter_toggled)
        self.user_combo = QtWidgets.QComboBox()
        self.populate_user_combo()
        self.user_combo.currentTextChanged.connect(self.on_user_changed)
        user_layout.addWidget(self.user_checkbox)
        user_layout.addWidget(self.user_combo)
        filter_layout.addLayout(user_layout)

        # Group by filter
        group_layout = QtWidgets.QHBoxLayout()
        self.group_checkbox = QtWidgets.QCheckBox("Group by:")
        self.group_checkbox.setChecked(True)
        self.group_checkbox.stateChanged.connect(self.on_group_filter_toggled)
        self.group_combo = QtWidgets.QComboBox()
        self.group_combo.addItems(["Type", "Context", "Source"])
        self.group_combo.setCurrentText("Type")  # Set default grouping
        self.group_combo.currentTextChanged.connect(self.on_group_changed)
        group_layout.addWidget(self.group_checkbox)
        group_layout.addWidget(self.group_combo)
        filter_layout.addLayout(group_layout)

        # Source filter
        source_layout = QtWidgets.QHBoxLayout()
        self.source_checkbox = QtWidgets.QCheckBox("Source:")
        self.source_checkbox.setChecked(True)
        self.source_checkbox.stateChanged.connect(self.on_source_filter_toggled)
        self.source_filter_combo = CheckableComboBox()
        self.source_filter_combo.setEditable(True)
        self.source_filter_combo.lineEdit().setReadOnly(True)
        self.source_filter_combo.lineEdit().setPlaceholderText("Select Sources")
        self.populate_source_filter()
        self.source_filter_combo.model().dataChanged.connect(self.on_source_filter_changed)
        source_layout.addWidget(self.source_checkbox)
        source_layout.addWidget(self.source_filter_combo)
        filter_layout.addLayout(source_layout)

        # Add filter layout to main layout
        layout.addLayout(filter_layout)

        # Add some spacing
        layout.addSpacing(10)

        # Add filter files search bar
        search_layout = QtWidgets.QHBoxLayout()
        search_label = QtWidgets.QLabel("Filter Files:")
        self.filter_line_edit = QtWidgets.QLineEdit()
        self.filter_line_edit.setPlaceholderText("Enter search term...")
        self.filter_line_edit.textChanged.connect(self.filter_files)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.filter_line_edit)

        layout.addLayout(search_layout)

        self.toggle_preview_checkbox = QtWidgets.QCheckBox("Enable Preview", checked=True)
        self.file_list_widget = EditableTreeWidget(self)
        self.file_list_widget.setHeaderLabels(["Context", "Type", "Name", "Source", "Version", "Date Modified", "Size"])
        self.file_list_widget.itemSelectionChanged.connect(self.update_preview)
        self.file_list_widget.itemChanged.connect(self.on_item_changed)

        # Create buttons
        button_layout = QtWidgets.QGridLayout()
        
        self.load_button = QtWidgets.QPushButton("Load")
        self.load_button.clicked.connect(self.load_action)
        button_layout.addWidget(self.load_button, 0, 0)

        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected_file)
        button_layout.addWidget(self.delete_button, 0, 1)

        self.edit_button = QtWidgets.QPushButton("Edit")
        self.edit_button.clicked.connect(lambda: self.edit_item_name())
        button_layout.addWidget(self.edit_button, 0, 2)

        self.new_snip_button = QtWidgets.QPushButton("New Snip")
        self.new_snip_button.clicked.connect(self.open_write_snip_ui)
        button_layout.addWidget(self.new_snip_button, 1, 0)

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_ui)
        button_layout.addWidget(self.refresh_button, 1, 1)

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button, 1, 2)

        # Add widgets to layout
        layout.addWidget(self.toggle_preview_checkbox)
        layout.addWidget(self.file_list_widget)
        layout.addLayout(button_layout)

        return layout

    def edit_selected_item_name(self):
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            self.show_warning_dialog("Invalid Selection", "Please select a valid file to edit its name.")
            return

        selected_item = selected_items[0]
        current_name = selected_item.text(2)  # Assuming the name is in the third column

        new_name, ok = QtWidgets.QInputDialog.getText(self, "Edit Name", "Enter new name:", QtWidgets.QLineEdit.Normal, current_name)
        if ok and new_name:
            formatted_name = self.format_name(new_name)
            selected_item.setText(2, formatted_name)
            self.on_item_changed(selected_item, 2)
            
    def edit_item_name(self):
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            QtWidgets.QMessageBox.warning(self, "Invalid Selection", "Please select a valid file to edit its name.")
            return

        selected_item = selected_items[0]
        current_name = selected_item.text(2)  # Assuming the name is in the third column

        new_name, ok = QtWidgets.QInputDialog.getText(self, "Edit Name", "Enter new name:", QtWidgets.QLineEdit.Normal, current_name)
        if ok and new_name:
            formatted_name = self.format_name(new_name)
            selected_item.setText(2, formatted_name)
            self.on_item_changed(selected_item, 2)

    def create_right_layout(self):
        layout = QtWidgets.QVBoxLayout()

        self.description_label = self.create_styled_label("Description")
        self.description_widget = QtWidgets.QTextEdit()
        self.description_widget.setReadOnly(True)
        self.description_widget.setStyleSheet("""
            QTextEdit[readOnly="true"] {
                background-color: #2b2b2b;
                color: #cccccc;
            }
            QTextEdit[readOnly="false"] {
                background-color: #3c3c3c;
                color: #ffffff;
            }
        """)

        # Add edit and save buttons for description
        description_button_layout = QtWidgets.QHBoxLayout()
        self.description_edit_button = QtWidgets.QPushButton("Edit")
        self.description_edit_button.clicked.connect(self.toggle_edit_mode)
        self.description_save_button = QtWidgets.QPushButton("Save")
        self.description_save_button.clicked.connect(self.save_description)
        self.description_save_button.setEnabled(False)
        description_button_layout.addWidget(self.description_edit_button)
        description_button_layout.addWidget(self.description_save_button)

        # Flipbook section
        self.flipbook_label = self.create_styled_label("Flipbook")
        self.flipbook_preview = ClickableLabel()
        self.flipbook_preview.clicked.connect(self.show_large_flipbook_preview)
        self.flipbook_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.flipbook_preview.setMinimumHeight(350)
        self.flipbook_preview.setFrameStyle(QtWidgets.QFrame.Box | QtWidgets.QFrame.Sunken)
        self.flipbook_preview.setStyleSheet("""
            QLabel {
                border: 1px solid #555;
                background-color: #2b2b2b;
            }
        """)

        flipbook_button_layout = QtWidgets.QHBoxLayout()
        self.flipbook_upload_button = QtWidgets.QPushButton("Upload Seq")
        self.flipbook_upload_button.clicked.connect(self.edit_flipbook)
        self.flipbook_new_button = QtWidgets.QPushButton("New Flipbook")
        self.flipbook_new_button.clicked.connect(self.save_flipbook)
        self.flipbook_delete_button = QtWidgets.QPushButton("Delete")
        self.flipbook_delete_button.clicked.connect(self.delete_flipbook)
        flipbook_button_layout.addWidget(self.flipbook_upload_button)
        flipbook_button_layout.addWidget(self.flipbook_new_button)
        flipbook_button_layout.addWidget(self.flipbook_delete_button)

        # Create a container for flipbook preview and buttons
        flipbook_container = QtWidgets.QWidget()
        flipbook_container_layout = QtWidgets.QVBoxLayout(flipbook_container)
        flipbook_container_layout.addWidget(self.flipbook_preview)
        flipbook_container_layout.addLayout(flipbook_button_layout)
        flipbook_container_layout.setContentsMargins(0, 0, 0, 0)

        # Snapshot section
        self.snapshot_label = self.create_styled_label("Snapshot")
        self.snapshot_preview = ClickableLabel()
        self.snapshot_preview.clicked.connect(self.show_large_snapshot_preview)
        self.snapshot_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.snapshot_preview.setMinimumSize(200, 150)
        self.snapshot_preview.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.snapshot_preview.setScaledContents(False)
        self.snapshot_preview.setFrameStyle(QtWidgets.QFrame.Box | QtWidgets.QFrame.Sunken)
        self.snapshot_preview.setStyleSheet("""
            QLabel {
                border: 1px solid #555;
                background-color: #2b2b2b;
            }
        """)

        # Create a container widget for the snapshot preview
        snapshot_container = QtWidgets.QWidget()
        snapshot_container.setMinimumHeight(200)
        snapshot_container_layout = QtWidgets.QVBoxLayout(snapshot_container)
        snapshot_container_layout.addWidget(self.snapshot_preview, alignment=QtCore.Qt.AlignCenter)
        snapshot_container_layout.setContentsMargins(0, 0, 0, 0)

        snapshot_button_layout = QtWidgets.QHBoxLayout()
        self.snapshot_edit_button = QtWidgets.QPushButton("Upload Snapshot")
        self.snapshot_edit_button.clicked.connect(self.edit_snapshot)
        self.snapshot_save_button = QtWidgets.QPushButton("Take New Snapshot")
        self.snapshot_save_button.clicked.connect(self.save_snapshot)
        self.snapshot_delete_button = QtWidgets.QPushButton("Delete")
        self.snapshot_delete_button.clicked.connect(self.delete_snapshot)
        snapshot_button_layout.addWidget(self.snapshot_edit_button)
        snapshot_button_layout.addWidget(self.snapshot_save_button)
        snapshot_button_layout.addWidget(self.snapshot_delete_button)

        layout.addWidget(self.description_label)
        layout.addWidget(self.description_widget)
        layout.addLayout(description_button_layout)
        layout.addSpacing(20)
        layout.addWidget(self.flipbook_label)
        layout.addWidget(flipbook_container)
        layout.addSpacing(20)
        layout.addWidget(self.snapshot_label)
        layout.addWidget(snapshot_container)
        layout.addLayout(snapshot_button_layout)

        # Add the show dialogs checkbox at the bottom of the right layout
        layout.addStretch()
        layout.addWidget(self.setup_show_dialogs_checkbox())

        return layout

    def connect_signals(self):
        self.user_combo.currentTextChanged.connect(self.on_user_changed)
        self.group_combo.currentTextChanged.connect(self.on_group_changed)
        self.filter_line_edit.textChanged.connect(self.filter_files)
        self.load_button.clicked.connect(self.load_action)
        self.delete_button.clicked.connect(self.delete_selected_file)
        self.refresh_button.clicked.connect(self.refresh_ui)
        self.close_button.clicked.connect(self.close)
        self.toggle_preview_checkbox.stateChanged.connect(self.toggle_preview)

    def populate_user_combo(self):
        users = self.file_manager.get_users()
        self.user_combo.clear()
        self.user_combo.addItems(users)
        current_user = hou.getenv("USER")
        if current_user in users:
            self.user_combo.setCurrentText(current_user)
        elif users:
            self.user_combo.setCurrentText(users[0])

    async def update_preview_async(self):
        selected_items = self.file_list_widget.selectedItems()
        if selected_items and not selected_items[0].childCount():
            selected_item = selected_items[0]
            file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
            
            json_data = await self.load_json_data_async(file_path.stem)
            if json_data:
                self.format_preview_text(json_data)
                await self.load_preview_assets_async(json_data)
            else:
                self.clear_preview()

    def on_item_changed(self, item, column):
        if not item or item.childCount() > 0:  # Ignore group items
            return

        try:
            old_full_name = Path(item.data(0, QtCore.Qt.UserRole)).stem
            parts = old_full_name.split('_')
            
            if len(parts) != 5:
                self.show_error_dialog("Invalid Name Format", "The file name does not follow the expected format.")
                return

            new_value = item.text(column)
            formatted_value = self.format_name(new_value)

            new_parts = parts.copy()
            if column == 0:  # Context
                new_parts[0] = formatted_value.upper()
            elif column == 1:  # Type
                new_parts[1] = formatted_value
            elif column == 2:  # Name
                new_parts[2] = formatted_value
            elif column == 3:  # Source
                new_parts[3] = formatted_value
            elif column == 4:  # Version
                new_parts[4] = formatted_value.lower()

            new_full_name = '_'.join(new_parts)
            
            # Only update if the name has actually changed
            if new_full_name != old_full_name:
                self.update_item_name(item, new_full_name, column)
            else:
                # If no change, just update the displayed text to the formatted version
                item.setText(column, new_parts[column])

        except Exception as e:
            self.show_error_dialog("Update Failed", f"An error occurred while updating the item: {str(e)}")

    def update_item_name(self, item, new_full_name, updated_column):
        old_file_path = Path(item.data(0, QtCore.Qt.UserRole))
        old_full_name = old_file_path.stem
        user = self.user_combo.currentText()
        
        # Update the file name
        new_file_path = old_file_path.with_name(f"{new_full_name}{old_file_path.suffix}")
        try:
            old_file_path.rename(new_file_path)
        except Exception as e:
            self.show_error_dialog("Rename Failed", f"Failed to rename file: {e}")
            # Revert the name change in the UI
            old_parts = old_full_name.split('_')
            item.setText(updated_column, old_parts[updated_column])
            return

        # Update flipbook directory and image sequence
        old_flipbook_dir = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'flipbook' / old_full_name
        new_flipbook_dir = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'flipbook' / new_full_name
        if old_flipbook_dir.exists():
            try:
                # Rename image sequence files
                for old_file in old_flipbook_dir.glob(f"{old_full_name}.*"):
                    frame_number = old_file.stem.split('.')[-1]
                    new_file_name = f"{new_full_name}.{frame_number}{old_file.suffix}"
                    old_file.rename(old_flipbook_dir / new_file_name)
                
                # Rename the directory
                old_flipbook_dir.rename(new_flipbook_dir)
            except Exception as e:
                self.show_error_dialog("Flipbook Update Failed", f"Failed to update flipbook: {e}")

        # Update snapshot
        old_snapshot_path = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'snapshot' / f"{old_full_name}.png"
        new_snapshot_path = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'snapshot' / f"{new_full_name}.png"
        if old_snapshot_path.exists():
            try:
                old_snapshot_path.rename(new_snapshot_path)
            except Exception as e:
                self.show_error_dialog("Snapshot Update Failed", f"Failed to update snapshot: {e}")

        # Update the item's data
        item.setData(0, QtCore.Qt.UserRole, str(new_file_path))

        self.show_info_dialog("Name Updated", f"Successfully updated the {['Context', 'Type', 'Name', 'Source', 'Version'][updated_column]}")
        self.refresh_ui()

    def format_name(self, input_string):
        # Remove special characters and spaces
        cleaned = re.sub(r'[^a-zA-Z0-9 ]', '', input_string)
        
        # Split the string into words
        words = cleaned.split()
        
        # Capitalize the first letter of each word except the first one
        formatted = words[0].lower() + ''.join(word.capitalize() for word in words[1:])
        
        return formatted

    def show_large_flipbook_preview(self):
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
        file_name = file_path.stem

        user = self.user_combo.currentText()
        flipbook_folder = self.base_path / 'pyDump' / user / "Snips" / "preview" / "flipbook" / file_name

        if not flipbook_folder.exists():
            return

        preview_window = LargePreviewWindow(self)
        preview_window.set_flipbook(str(flipbook_folder))
        preview_window.show()
        preview_window.raise_()  # Bring the window to the front
        preview_window.activateWindow()  # Activate the window

    def show_large_snapshot_preview(self):
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
        file_name = file_path.stem

        user = self.user_combo.currentText()
        snapshot_path = self.base_path / 'pyDump' / user / "Snips" / "preview" / "snapshot" / f"{file_name}.png"

        if not snapshot_path.exists():
            return

        preview_window = LargePreviewWindow(self)
        preview_window.set_snapshot(str(snapshot_path))
        preview_window.show()
        preview_window.raise_()  # Bring the window to the front
        preview_window.activateWindow()  # Activate the window

    def delete_flipbook(self):
        logger.debug("Delete Flipbook button clicked")
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            self.show_warning_dialog("Invalid Selection", "Please select a valid file to delete its flipbook.")
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
        file_name = file_path.stem

        user = self.user_combo.currentText()
        flipbook_folder = self.base_path / 'pyDump' / user / "Snips" / "preview" / "flipbook" / file_name

        if not flipbook_folder.exists():
            self.show_warning_dialog("No Flipbook", "There is no flipbook to delete for this file.")
            return

        reply = self.show_question_dialog("Delete Flipbook", 
                                          "Are you sure you want to delete this flipbook?",
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                          QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                shutil.rmtree(flipbook_folder)
                logger.info(f"Flipbook deleted successfully: {flipbook_folder}")
                self.update_flipbook_path_in_json(file_name, "")
                self.show_info_dialog("Flipbook Deleted", "The flipbook has been successfully deleted.")
                self.refresh_ui()
                self.reselect_file(file_path)
            except Exception as e:
                logger.error(f"Error deleting flipbook: {e}")
                self.show_error_dialog("Flipbook Deletion Failed", f"Failed to delete flipbook: {e}")

    def delete_snapshot(self):
        logger.debug("Delete Snapshot button clicked")
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            self.show_warning_dialog("Invalid Selection", "Please select a valid file to delete its snapshot.")
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
        file_name = file_path.stem

        user = self.user_combo.currentText()
        snapshot_path = self.base_path / 'pyDump' / user / "Snips" / "preview" / "snapshot" / f"{file_name}.png"

        if not snapshot_path.exists():
            self.show_warning_dialog("No Snapshot", "There is no snapshot to delete for this file.")
            return

        reply = self.show_question_dialog("Delete Snapshot", 
                                          "Are you sure you want to delete this snapshot?",
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                          QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                snapshot_path.unlink()
                logger.info(f"Snapshot deleted successfully: {snapshot_path}")
                self.update_snapshot_path_in_json(file_name, "")
                self.show_info_dialog("Snapshot Deleted", "The snapshot has been successfully deleted.")
                self.refresh_ui()
                self.reselect_file(file_path)
            except Exception as e:
                logger.error(f"Error deleting snapshot: {e}")
                self.show_error_dialog("Snapshot Deletion Failed", f"Failed to delete snapshot: {e}")

    def update_snapshot_preview(self, snapshot):
        logger.debug(f"Updating snapshot preview with: {snapshot}")
        if isinstance(snapshot, str) or isinstance(snapshot, Path):
            if Path(snapshot).exists():
                pixmap = QtGui.QPixmap(str(snapshot))
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(self.snapshot_preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                    self.snapshot_preview.setPixmap(scaled_pixmap)
                    self.current_snapshot_path = snapshot
                else:
                    logger.warning(f"Failed to load snapshot: {snapshot}")
                    self.snapshot_preview.setText("Failed to load snapshot")
                    self.current_snapshot_path = None
            else:
                logger.warning(f"Snapshot file not found: {snapshot}")
                self.clear_snapshot()
        elif isinstance(snapshot, QtGui.QPixmap):
            scaled_pixmap = snapshot.scaled(self.snapshot_preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.snapshot_preview.setPixmap(scaled_pixmap)
            self.current_snapshot_path = None  # We don't have a file path in this case
        else:
            logger.error(f"Invalid snapshot type: {type(snapshot)}")
            self.clear_snapshot()

    def scale_pixmap_to_fit(self, pixmap: QtGui.QPixmap, target_size: QtCore.QSize) -> QtGui.QPixmap:
        # Scale the pixmap to fit within the target size while maintaining aspect ratio
        scaled_pixmap = pixmap.scaled(target_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        
        # Create a new pixmap with the target size and transparent background
        result_pixmap = QtGui.QPixmap(target_size)
        result_pixmap.fill(QtCore.Qt.transparent)
        
        # Create a painter to draw on the result pixmap
        painter = QtGui.QPainter(result_pixmap)
        
        # Calculate the position to center the scaled pixmap
        x = (target_size.width() - scaled_pixmap.width()) // 2
        y = (target_size.height() - scaled_pixmap.height()) // 2
        
        # Draw the scaled pixmap centered on the result pixmap
        painter.drawPixmap(x, y, scaled_pixmap)
        painter.end()
        
        return result_pixmap

    def resizeEvent(self, event: QtGui.QResizeEvent):
        super().resizeEvent(event)
        # Update the snapshot preview when the window is resized
        if hasattr(self, 'snapshot_preview') and self.current_snapshot_path:
            self.update_snapshot_preview(self.current_snapshot_path)

    def setup_show_dialogs_checkbox(self):
        self.show_dialogs_checkbox = QtWidgets.QCheckBox("Show information dialogs")
        self.show_dialogs_checkbox.setStyleSheet("""
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #555555;
        """)
        self.show_dialogs_checkbox.stateChanged.connect(self.save_dialog_preference)
        return self.show_dialogs_checkbox

    def save_dialog_preference(self):
        preference = self.show_dialogs_checkbox.isChecked()
        try:
            pref_file = Path(hou.expandString('$HOUDINI_USER_PREF_DIR')) / 'snip_ui_preferences.json'
            with pref_file.open('w') as f:
                json.dump({'show_dialogs': preference}, f)
        except Exception as e:
            logger.error(f"Error saving dialog preference: {e}")

    def load_dialog_preference(self):
        try:
            pref_file = Path(hou.expandString('$HOUDINI_USER_PREF_DIR')) / 'snip_ui_preferences.json'
            if pref_file.exists():
                with pref_file.open('r') as f:
                    prefs = json.load(f)
                    return prefs.get('show_dialogs', True)
            else:
                return True
        except Exception as e:
            logger.error(f"Error loading dialog preference: {e}")
            return True

    def show_info_dialog(self, title: str, message: str):
        if self.show_dialogs_checkbox.isChecked():
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            logger.info(f"{title}: {message}")

    def show_warning_dialog(self, title, message):
        if self.show_dialogs_checkbox.isChecked():
            QtWidgets.QMessageBox.warning(self, title, message)
        else:
            logger.warning(f"{title}: {message}")

    def show_info_dialog(self, title: str, message: str):
        if self.show_dialogs_checkbox.isChecked():
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            logger.info(f"{title}: {message}")

    def show_error_dialog(self, title: str, message: str):
        if self.show_dialogs_checkbox.isChecked():
            QtWidgets.QMessageBox.critical(self, title, message)
        else:
            logger.error(f"{title}: {message}")

    def show_question_dialog(self, title: str, message: str, buttons=QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, default_button=QtWidgets.QMessageBox.No):
        if self.show_dialogs_checkbox.isChecked():
            return QtWidgets.QMessageBox.question(self, title, message, buttons, default_button)
        else:
            logger.info(f"{title}: {message} (Automatically choosing 'Yes')")
            return QtWidgets.QMessageBox.Yes  # Always return 'Yes' when dialogs are off

    def closeEvent(self, event: QtGui.QCloseEvent):
        self.save_settings()
        super().closeEvent(event)

    def connect_signals(self):
        self.user_combo.currentTextChanged.connect(self.on_user_changed)
        self.group_combo.currentTextChanged.connect(self.on_group_changed)
        self.filter_line_edit.textChanged.connect(self.filter_files)
        self.load_button.clicked.connect(self.load_action)
        self.delete_button.clicked.connect(self.delete_selected_file)
        self.refresh_button.clicked.connect(self.refresh_ui)
        self.close_button.clicked.connect(self.close)
        self.toggle_preview_checkbox.stateChanged.connect(self.toggle_preview)

    def populate_user_combo(self):
        users = self.file_manager.get_users()
        self.user_combo.clear()
        self.user_combo.addItems(users)
        current_user = hou.getenv("USER")
        if current_user in users:
            self.user_combo.setCurrentText(current_user)
        elif users:
            self.user_combo.setCurrentText(users[0])

    def on_user_changed(self):
        self.load_json_data()
        logger.info(f"Loaded JSON data for user {self.user_combo.currentText()}: {len(self.json_data)}")
        self.update_ui_for_new_user()
        self.update_file_list()
        self.populate_source_filter()
        self.clear_preview()

    def on_group_changed(self):
        self.update_file_list()
   
    def update_file_list(self):
        logger.info("Starting update_file_list")
        selected_user = self.user_combo.currentText() if self.user_checkbox.isChecked() else None
        selected_group = self.group_combo.currentText() if self.group_checkbox.isChecked() else None
        selected_sources = self.get_selected_sources() if self.source_checkbox.isChecked() else None

        logger.info(f"Selected user: {selected_user}, group: {selected_group}, sources: {selected_sources}")

        current_item = self.file_list_widget.currentItem()
        current_file_path = current_item.data(0, QtCore.Qt.UserRole) if current_item else None

        self.file_list_widget.clear()
        self.file_groups = {}  # Reset file_groups here

        category_path = self.base_path / 'pyDump' / selected_user / 'Snips' if selected_user else None
        logger.info(f"Category path: {category_path}")

        if category_path and category_path.exists():
            all_files = list(category_path.glob('*'))
            logger.info(f"Found {len(all_files)} files")
            for file_path in all_files:
                if file_path.suffix in SUPPORTED_EXTENSIONS:
                    logger.info(f"Processing file: {file_path}")
                    try:
                        self.populate_file_item(file_path, selected_group, selected_sources)
                    except Exception as e:
                        logger.error(f"Error processing file {file_path}: {str(e)}")

        # Sort the groups
        for group_item in self.file_groups.values():
            group_item.sortChildren(0, QtCore.Qt.AscendingOrder)

        # Expand all groups
        self.file_list_widget.expandAll()

        # Restore the previous selection if possible
        if current_file_path:
            items = self.file_list_widget.findItems(Path(current_file_path).stem, QtCore.Qt.MatchContains | QtCore.Qt.MatchRecursive)
            if items:
                self.file_list_widget.setCurrentItem(items[0])
                self.file_list_widget.scrollToItem(items[0])

        logger.info(f"Finished updating file list for user {selected_user}")
        logger.info(f"Total top-level items: {self.file_list_widget.topLevelItemCount()}")
        for i in range(self.file_list_widget.topLevelItemCount()):
            top_level_item = self.file_list_widget.topLevelItem(i)
            logger.info(f"Top-level item {i}: {top_level_item.text(0)}, Child count: {top_level_item.childCount()}")

    @staticmethod
    def camel_case_to_words(name: str) -> str:
        pattern = re.compile(r'(?<!^)(?=[A-Z])')
        words = pattern.sub(' ', name).split()
        return ' '.join(word.capitalize() for word in words)

    def populate_file_item(self, file_path, selected_group, selected_sources):
        logger.debug(f"Populating file item: {file_path}")
        parts = file_path.stem.split('_')
        if len(parts) >= 5:
            context, file_type, *name_parts, source, version = parts
            name = '_'.join(name_parts)
            display_name = self.camel_case_to_words(name)

            if selected_sources and source not in selected_sources:
                logger.info(f"Skipping file {file_path} due to source filter")
                return  # Skip files from unselected sources

            if selected_group == "Type":
                group_key = file_type
            elif selected_group == "Context":
                group_key = context
            elif selected_group == "Source":
                group_key = source
            else:
                group_key = "All"

            if group_key not in self.file_groups:
                logger.info(f"Creating new group: {group_key}")
                group_item = QtWidgets.QTreeWidgetItem([group_key])
                group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
                self.file_list_widget.addTopLevelItem(group_item)
                self.file_groups[group_key] = group_item

            date_modified = file_path.stat().st_mtime
            size = file_path.stat().st_size

            date_modified_str = QtCore.QDateTime.fromSecsSinceEpoch(int(date_modified)).toString("yyyy-MM-dd hh:mm:ss")

            file_item = QtWidgets.QTreeWidgetItem([context, file_type, display_name, source, version, date_modified_str, f"{size / 1024:.2f} KB"])
            file_item.setData(0, QtCore.Qt.UserRole, str(file_path))
            file_item.setFlags(file_item.flags() | QtCore.Qt.ItemIsEditable)
            self.file_groups[group_key].addChild(file_item)
            logger.info(f"Added file item: {display_name} to group {group_key}")
        else:
            logger.warning(f"Skipping file {file_path} due to incorrect name format")

    def populate_file_list(self, base_directory: Path, file_list_widget: QtWidgets.QTreeWidget, selected_group: str, selected_sources: List[str]):
        file_list_widget.clear()
        if not base_directory.exists():
            logger.warning(f"Directory {base_directory} does not exist.")
            return

        all_files = [f for f in base_directory.iterdir() if f.suffix in SUPPORTED_EXTENSIONS]

        file_list_widget.setHeaderLabels(["Context", "Type", "Name", "Source", "Version", "Date Modified", "Size"])
        file_list_widget.setSortingEnabled(True)

        self.file_groups = {}

        for file_path in all_files:
            self.populate_file_item(file_path, selected_group, selected_sources)

        for group_item in self.file_groups.values():
            group_item.setExpanded(True)

        for i in range(file_list_widget.columnCount()):
            file_list_widget.resizeColumnToContents(i)

    def setup_custom_sorting(self, file_list_widget: QtWidgets.QTreeWidget):
        header = file_list_widget.header()
        header.setSectionsClickable(True)
        for i in range:
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.ResizeToContents)
            header.sectionClicked.connect(partial(self.sort_column, file_list_widget))

    def sort_column(self, file_list_widget: QtWidgets.QTreeWidget, column: int):
        header = file_list_widget.header()
        current_sort_column = header.sortIndicatorSection()
        current_order = header.sortIndicatorOrder()

        new_order = QtCore.Qt.DescendingOrder if column == current_sort_column and current_order == QtCore.Qt.AscendingOrder else QtCore.Qt.AscendingOrder
        file_list_widget.sortItems(column, new_order)

        root = file_list_widget.invisibleRootItem()
        for i in range(root.childCount()):
            root.child(i).setExpanded(True)

        header.setSortIndicator(column, new_order)

    def filter_files(self):
        filter_text = self.filter_line_edit.text().lower()
        
        for i in range(self.file_list_widget.topLevelItemCount()):
            group_item = self.file_list_widget.topLevelItem(i)
            group_visible = False
            
            for j in range(group_item.childCount()):
                file_item = group_item.child(j)
                item_visible = any(filter_text in file_item.text(col).lower() for col in range(file_item.columnCount()))
                file_item.setHidden(not item_visible)
                group_visible = group_visible or item_visible
            
            group_item.setHidden(not group_visible)

    def update_preview(self, file_path=None):
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()

        self.current_task = asyncio.create_task(self._update_preview(file_path))

    async def _update_preview(self, file_path=None):
        logger.debug("_update_preview called")
        if hasattr(self, 'toggle_preview_checkbox') and hasattr(self, 'preview_visible'):
            logger.debug(f"Preview checkbox checked: {self.toggle_preview_checkbox.isChecked()}, Preview visible: {self.preview_visible}")
            if self.toggle_preview_checkbox.isChecked() and self.preview_visible:
                if file_path is None:
                    selected_items = self.file_list_widget.selectedItems()
                    logger.debug(f"Number of selected items: {len(selected_items)}")
                    if selected_items:
                        logger.debug(f"First selected item child count: {selected_items[0].childCount()}")
                    if selected_items and not selected_items[0].childCount():
                        selected_item = selected_items[0]
                        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
                
                if file_path:
                    logger.debug(f"Selected file: {file_path}")
                    
                    # Always read fresh data from json_data
                    json_data = next((item for item in self.json_data if item['File Name'] == file_path.stem), None)
                    
                    logger.debug(f"JSON data: {json_data}")
                    
                    if json_data:
                        self.format_preview_text(json_data)
                        self.description_widget.setReadOnly(True)
                        self.description_edit_button.setText("Edit")
                        self.description_save_button.setEnabled(False)
                        
                        # Asynchronously load preview assets
                        await self.load_preview_assets_async(json_data)
                    else:
                        logger.warning(f"No JSON data found for {file_path.stem}")
                        self.description_widget.setPlainText("No additional information available for this file.")
                        self.clear_preview_assets()
                else:
                    logger.debug("No valid item selected")
                    self.clear_preview()
            else:
                logger.debug("Preview not visible or checkbox not checked")
                self.clear_preview()
        else:
            logger.warning("Preview attributes not properly initialized") 

    async def load_preview_assets_async(self, json_data: Dict):
        try:
            async with self.preview_semaphore:
                # Check if the task has been cancelled
                if asyncio.current_task().cancelled():
                    return

                logger.debug(f"Loading preview assets for: {json_data.get('File Name', 'Unknown')}")
                flipbook_path = json_data.get('Flipbook', '')
                snapshot_path = json_data.get('Snap', '')
                
                logger.debug(f"Flipbook path: {flipbook_path}")
                logger.debug(f"Snapshot path: {snapshot_path}")
                
                self.show_progress_dialog("Loading Previews", "Loading preview assets...", 100)

                progress = 0
                flipbook_frames = []
                snapshot_pixmap = None

                if flipbook_path:
                    filename = Path(flipbook_path).stem.split('.')[0]
                    full_flipbook_path = self.file_manager.get_preview_base_path(self.user_combo.currentText()) / 'flipbook' / filename / f"{filename}.$F4.png"
                    logger.debug(f"Full flipbook path: {full_flipbook_path}")
                    if not full_flipbook_path.parent.exists():
                        full_flipbook_path.parent.mkdir(parents=True, exist_ok=True)
                        logger.info(f"Created flipbook directory: {full_flipbook_path.parent}")
                    if full_flipbook_path.parent.exists():
                        flipbook_frames = await self.load_flipbook_async(str(full_flipbook_path))
                        self.update_flipbook_preview(flipbook_frames)
                    else:
                        logger.warning(f"Failed to create flipbook directory: {full_flipbook_path.parent}")
                    progress += 50
                    self.update_progress(progress)

                if snapshot_path:
                    full_snapshot_path = self.file_manager.get_preview_base_path(self.user_combo.currentText()) / 'snapshot' / Path(snapshot_path).name
                    logger.debug(f"Full snapshot path: {full_snapshot_path}")
                    snapshot_pixmap = await self.load_snapshot_async(str(full_snapshot_path))
                    if snapshot_pixmap:
                        self.update_snapshot_preview(snapshot_pixmap)
                    else:
                        logger.warning(f"Failed to load snapshot: {full_snapshot_path}")
                    progress += 50
                    self.update_progress(progress)

                self.preview_cache[json_data['File Name']] = {
                    'json_data': json_data,
                    'flipbook_frames': flipbook_frames,
                    'snapshot_pixmap': snapshot_pixmap
                }
        except asyncio.CancelledError:
            logger.debug("Preview loading task was cancelled")
        except Exception as e:
            logger.error(f"Error loading preview assets: {e}")
        finally:
            self.close_progress_dialog()

    def update_preview_widgets(self, flipbook_frames, snapshot_pixmap):
        if flipbook_frames:
            self.preview_manager.flipbook_frames = flipbook_frames
            self.preview_manager.current_frame = 0
            self.start_flipbook_animation()
            self.flipbook_new_button.setEnabled(True)
        else:
            self.clear_flipbook()

        if snapshot_pixmap:
            self.snapshot_preview.setPixmap(snapshot_pixmap)
            self.snapshot_preview.setFixedSize(snapshot_pixmap.size())
            self.snapshot_save_button.setEnabled(True)
            self.current_snapshot_path = str(snapshot_pixmap.fileName())
        else:
            self.clear_snapshot()

    async def load_flipbook_async(self, flipbook_path: str) -> List[QtGui.QPixmap]:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(self.thread_pool, self.preview_manager.load_flipbook, flipbook_path)
        except Exception as e:
            logger.error(f"Error loading flipbook: {e}")
            return []

    async def load_snapshot_async(self, snapshot_path: str) -> Optional[QtGui.QPixmap]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, self.preview_manager.load_snapshot, snapshot_path)

    def format_preview_text(self, json_data: Dict):
        description = json_data.get('Summary', 'No description available.')
        logger.debug(f"Description content: {description}")
        self.description_widget.setPlainText(description)
        self.description_widget.repaint()

    def format_preview_text(self, json_data: Dict):
        description = json_data.get('Summary', 'No description available.')
        logger.debug(f"Description content: {description}")
        self.description_widget.setPlainText(description)
        self.description_widget.repaint()

    def load_json_data(self):
        user = self.user_combo.currentText()
        master_json_path = Path(self.base_path) / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'
        try:
            with master_json_path.open('r') as f:
                self.json_data = json.load(f)
            if not isinstance(self.json_data, list):
                raise ValueError("JSON data is not a list")
            logger.info(f"Loaded JSON data for user {user}: {len(self.json_data)} entries")
        except Exception as e:
            logger.error(f"Failed to load JSON data: {e}")
            self.json_data = []

    def read_json_data(self, file_name: str) -> Optional[Dict]:
        return next((item for item in self.json_data if item['File Name'] == file_name), None)

    def start_flipbook_animation(self):
        if self.preview_manager.flipbook_frames:
            self.flipbook_timer.start(1000 // FLIPBOOK_FRAME_RATE)
            self.flipbook_preview.setFixedSize(self.preview_manager.flipbook_frames[0].size())

    def clear_preview(self):
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
        self.description_widget.clear()
        self.clear_preview_assets()

    def clear_preview_assets(self):
        self.clear_flipbook()
        self.clear_snapshot()

    def clear_flipbook(self):
        if hasattr(self, 'flipbook_timer'):
            self.flipbook_timer.stop()
        self.flipbook_preview.clear()
        self.flipbook_preview.setText("No flipbook available")
        self.flipbook_preview.setFixedSize(MAX_PREVIEW_SIZE)
        self.flipbook_new_button.setEnabled(True)
        self.preview_manager.current_frame = 0
        self.preview_manager.flipbook_frames = []

    def clear_snapshot(self):
        self.snapshot_preview.clear()
        self.snapshot_preview.setText("No snapshot available")
        self.snapshot_preview.setFixedSize(MAX_PREVIEW_SIZE)
        self.snapshot_save_button.setEnabled(True)
        self.current_snapshot_path = None


    def update_flipbook_frame(self):
        if self.preview_manager.flipbook_frames:
            num_frames = len(self.preview_manager.flipbook_frames)
            if num_frames > 0:
                self.preview_manager.current_frame = self.preview_manager.current_frame % num_frames
                self.flipbook_preview.setPixmap(self.preview_manager.flipbook_frames[self.preview_manager.current_frame])
                self.preview_manager.current_frame = (self.preview_manager.current_frame + 1) % num_frames
            else:
                logger.warning("Flipbook has no frames.")
                self.clear_flipbook()
        else:
            logger.warning("No flipbook frames available.")
            self.clear_flipbook()

    def update_flipbook_preview(self, flipbook_frames):
        logger.debug(f"Updating flipbook preview with {len(flipbook_frames)} frames")
        if flipbook_frames:
            self.flipbook_preview.setPixmap(flipbook_frames[0])
            self.flipbook_preview.setFixedSize(flipbook_frames[0].size())
            self.start_flipbook_animation()
            self.flipbook_delete_button.setEnabled(True)
        else:
            self.clear_flipbook()
            logger.warning("No flipbook frames available to display")

    def load_selected_file(self):
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            self.show_warning_dialog("No Selection", "Please select a file to load.")
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
        user = self.user_combo.currentText()
        full_path = self.base_path / 'pyDump' / user / 'Snips' / file_path.name

        if not full_path.exists():
            self.show_error_dialog("File Not Found", f"The file {file_path.name} does not exist.")
            return

        exec_network = self.get_current_network_tab()
        if not exec_network:
            self.show_error_dialog("No Network Editor", "No network editor tab found to load into.")
            return

        parent = exec_network.pwd()
        try:
            parent.loadItemsFromFile(str(full_path))
            self.show_info_dialog("File Loaded", f"Successfully loaded {file_path.name}")
            self.close()  # Close the UI after successful load
        except hou.OperationFailed as e:
            self.show_error_dialog("Load Failed", f"Failed to load {file_path.name}: {str(e)}")

    @staticmethod
    def get_current_network_tab() -> Optional[hou.NetworkEditor]:
        network_tabs = [t for t in hou.ui.paneTabs() if t.type() == hou.paneTabType.NetworkEditor]
        return next((tab for tab in network_tabs if tab.isCurrentTab()), None)

    def load_action(self):
        logger.debug("Load button clicked")
        self.load_selected_file()

    def toggle_preview(self, state: int):
        self.preview_visible = state == QtCore.Qt.Checked
        self.description_label.setVisible(self.preview_visible)
        self.description_widget.setVisible(self.preview_visible)
        self.flipbook_label.setVisible(self.preview_visible)
        self.flipbook_preview.setVisible(self.preview_visible)
        self.snapshot_label.setVisible(self.preview_visible)
        self.snapshot_preview.setVisible(self.preview_visible)
        self.update_preview()

    @staticmethod
    def create_styled_label(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 14px;
                color: white;
                background-color: #2c3e50;
                padding: 5px 10px;
                border-radius: 3px;
                margin-bottom: 10px;
            }
        """)
        label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        return label

    def update_ui_for_new_user(self):
        selected_user = self.user_combo.currentText()
        if not self.json_data:
            message = f"No data found for user: {selected_user}. Please check if the master.json file exists."
            self.description_widget.setPlainText(message)
            self.show_warning_dialog("No User Data", message)

    def delete_selected_file(self):
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            self.show_warning_dialog("Invalid Selection", "Please select a valid file to delete.")
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))

        reply = self.show_question_dialog("Confirm Deletion", 
                                          f"Are you sure you want to delete {file_path.name}?",
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                          QtWidgets.QMessageBox.No)
        
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                user = self.user_combo.currentText()
                
                # Delete the main file
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Deleted file: {file_path}")
                else:
                    logger.warning(f"File not found: {file_path}")

                # Delete associated flipbook directory
                flipbook_dir = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'flipbook' / file_path.stem
                if flipbook_dir.exists():
                    shutil.rmtree(flipbook_dir)
                    logger.info(f"Deleted flipbook directory: {flipbook_dir}")
                else:
                    logger.warning(f"Flipbook directory not found: {flipbook_dir}")

                # Delete associated snapshot
                snapshot_path = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'snapshot' / f"{file_path.stem}.png"
                if snapshot_path.exists():
                    snapshot_path.unlink()
                    logger.info(f"Deleted snapshot: {snapshot_path}")
                else:
                    logger.warning(f"Snapshot not found: {snapshot_path}")

                # Remove entry from master.json
                master_json_path = self.base_path / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'
                if master_json_path.exists():
                    with master_json_path.open('r') as f:
                        master_data = json.load(f)
                    
                    master_data = [entry for entry in master_data if entry['File Name'] != file_path.stem]
                    
                    with master_json_path.open('w') as f:
                        json.dump(master_data, f, indent=4)
                    
                    logger.info(f"Updated master.json: removed entry for {file_path.stem}")
                else:
                    logger.warning(f"master.json not found: {master_json_path}")

                # Remove item from the tree widget
                parent = selected_item.parent()
                if parent:
                    parent.removeChild(selected_item)
                else:
                    index = self.file_list_widget.indexOfTopLevelItem(selected_item)
                    self.file_list_widget.takeTopLevelItem(index)

                # Clear the caches
                self.json_cache.pop(file_path.stem, None)
                self.preview_cache.pop(file_path.stem, None)

                # Update local json_data
                self.json_data = [entry for entry in self.json_data if entry['File Name'] != file_path.stem]

                self.show_info_dialog("File Deleted", f"{file_path.name} and its associated files have been deleted.")
                
                # Refresh the UI
                self.refresh_ui()
                
            except Exception as e:
                logger.error(f"Error deleting file: {e}", exc_info=True)
                self.show_error_dialog("Deletion Failed", f"Failed to delete file: {e}")
        else:
            self.show_info_dialog("Deletion Cancelled", "The file was not deleted.")

    def delete_file(self, item: QtWidgets.QTreeWidgetItem):
        file_path = Path(item.data(0, QtCore.Qt.UserRole))
        reply = self.show_question_dialog(
            'Confirm Delete',
            f"Are you sure you want to delete '{file_path.name}' and all associated data?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                user = self.user_combo.currentText()
                
                # Construct correct paths
                uti_file_path = self.base_path / 'pyDump' / user / 'Snips' / file_path.name
                master_json_path = self.base_path / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'
                flipbook_dir_path = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'flipbook' / file_path.stem
                snapshot_path = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'snapshot' / f"{file_path.stem}.png"

                # Delete the .uti file
                if uti_file_path.exists():
                    uti_file_path.unlink()
                    logger.info(f"Deleted .uti file: {uti_file_path}")
                else:
                    logger.warning(f".uti file not found: {uti_file_path}")

                # Delete flipbook directory
                if flipbook_dir_path.exists():
                    shutil.rmtree(flipbook_dir_path)
                    logger.info(f"Deleted flipbook directory: {flipbook_dir_path}")
                else:
                    logger.warning(f"Flipbook directory not found: {flipbook_dir_path}")

                # Delete snapshot
                if snapshot_path.exists():
                    snapshot_path.unlink()
                    logger.info(f"Deleted snapshot: {snapshot_path}")
                else:
                    logger.warning(f"Snapshot not found: {snapshot_path}")

                # Update master.json
                if master_json_path.exists():
                    with master_json_path.open('r') as f:
                        master_data = json.load(f)

                    master_data = [entry for entry in master_data if entry['File Name'] != file_path.stem]

                    with master_json_path.open('w') as f:
                        json.dump(master_data, f, indent=4)
                        logger.info(f"Updated master.json: {master_json_path}")
                else:
                    logger.warning(f"master.json not found: {master_json_path}")
                
                self.show_info_dialog("File Deleted", f"Successfully deleted {file_path.name} and associated data")
                
                # Clear the caches
                self.json_cache.pop(file_path.stem, None)
                cache_keys_to_remove = [key for key in self.preview_cache if file_path.stem in key]
                for key in cache_keys_to_remove:
                    del self.preview_cache[key]

                # Refresh the UI
                self.refresh_ui()
            except Exception as e:
                self.show_error_dialog("Deletion Failed", f"Failed to delete file and associated data: {e}")
                logger.error(f"Error deleting file and associated data: {e}", exc_info=True)

    def refresh_ui(self):
        logger.debug("Refresh UI called")
        try:
            current_item = self.file_list_widget.currentItem()
            current_file_path = current_item.data(0, QtCore.Qt.UserRole) if current_item else None

            self.load_json_data()
            self.update_file_list()
            self.populate_source_filter()

            # Restore the previous selection if possible
            if current_file_path:
                self.reselect_file(Path(current_file_path))
            else:
                self.clear_preview()
        except Exception as e:
            logger.error(f"Error refreshing UI: {e}", exc_info=True)
            self.show_error_dialog("Refresh Failed", f"Failed to refresh UI: {e}")

    def reselect_file(self, file_path: Path):
        for i in range(self.file_list_widget.topLevelItemCount()):
            group_item = self.file_list_widget.topLevelItem(i)
            for j in range(group_item.childCount()):
                file_item = group_item.child(j)
                if Path(file_item.data(0, QtCore.Qt.UserRole)) == file_path:
                    self.file_list_widget.setCurrentItem(file_item)
                    self.update_preview()
                return
        logger.warning(f"Could not find item to reselect: {file_path}")
        self.clear_preview()

    def populate_source_filter(self):
        self.source_filter_combo.clear()
        sources = set()
        category_path = self.base_path / 'pyDump' / self.user_combo.currentText() / 'Snips'
        if category_path.exists():
            for file_path in category_path.glob('*'):
                parts = file_path.stem.split('_')
                if len(parts) >= 5:
                    sources.add(parts[-2])  # Assuming source is the second-to-last part
        
        model = self.source_filter_combo.model()
        model.clear()
        saved_sources = self.settings.value("selected_sources", [])
        for source in sorted(sources):
            item = QtGui.QStandardItem(source)
            item.setCheckable(True)
            item.setCheckState(QtCore.Qt.Checked if source in saved_sources else QtCore.Qt.Unchecked)
            model.appendRow(item)
        
        self.update_source_filter_text()

    def update_source_filter_text(self):
        selected_sources = self.get_selected_sources()
        if len(selected_sources) == self.source_filter_combo.model().rowCount():
            self.source_filter_combo.setEditText("All Sources")
        elif len(selected_sources) == 0:
            self.source_filter_combo.setEditText("No Sources")
        else:
            self.source_filter_combo.setEditText(f"{len(selected_sources)} Sources")

    def on_source_filter_changed(self):
        self.update_source_filter_text()
        self.update_file_list()

    def get_selected_sources(self):
        model = self.source_filter_combo.model()
        return [model.item(i).text() for i in range(model.rowCount()) if model.item(i).checkState() == QtCore.Qt.Checked]

    def save_settings(self):
        try:
            if hasattr(self, 'user_checkbox'):
                self.settings.setValue("user_filter_enabled", self.user_checkbox.isChecked())
            if hasattr(self, 'user_combo'):
                self.settings.setValue("selected_user", self.user_combo.currentText())
            if hasattr(self, 'group_checkbox'):
                self.settings.setValue("group_filter_enabled", self.group_checkbox.isChecked())
            if hasattr(self, 'group_combo'):
                self.settings.setValue("selected_group", self.group_combo.currentText())
            if hasattr(self, 'source_checkbox'):
                self.settings.setValue("source_filter_enabled", self.source_checkbox.isChecked())
            if hasattr(self, 'source_filter_combo'):
                self.settings.setValue("selected_sources", self.get_selected_sources())
            if hasattr(self, 'filter_line_edit'):
                self.settings.setValue("filter_text", self.filter_line_edit.text())
            
            logger.info("Settings saved successfully")
        except Exception as e:
            logger.error(f"Error saving settings: {str(e)}")

    def load_settings(self):
        # Load user preference
        saved_user = self.settings.value("user", "")
        if saved_user and saved_user in self.file_manager.get_users():
            self.user_combo.setCurrentText(saved_user)
        
        # Load group preference
        saved_group = self.settings.value("group", "")
        if saved_group:
            index = self.group_combo.findText(saved_group)
            if index >= 0:
                self.group_combo.setCurrentIndex(index)
        
        # Load source filter preference
        saved_sources = self.settings.value("sources", [])
        if saved_sources:
            for i in range(self.source_filter_combo.count()):
                item = self.source_filter_combo.model().item(i)
                if item.text() in saved_sources:
                    item.setCheckState(QtCore.Qt.Checked)
        
        # Load search filter
        saved_filter = self.settings.value("filter", "")
        self.filter_line_edit.setText(saved_filter)
        
        # Update file list without progress dialog
        self.update_file_list_without_progress()

    def update_file_list_without_progress(self):
        selected_user = self.user_combo.currentText() if self.user_checkbox.isChecked() else None
        selected_group = self.group_combo.currentText() if self.group_checkbox.isChecked() else None
        selected_sources = self.get_selected_sources() if self.source_checkbox.isChecked() else None

        self.file_list_widget.clear()

        category_path = self.base_path / 'pyDump' / selected_user / 'Snips' if selected_user else None
        if category_path and category_path.exists():
            for file_path in category_path.glob('*'):
                if file_path.suffix in SUPPORTED_EXTENSIONS:
                    self.populate_file_item(file_path, selected_group, selected_sources)

        logger.info(f"Updated file list for user {selected_user}")

    def on_user_filter_toggled(self, state):
        self.user_combo.setEnabled(state == QtCore.Qt.Checked)
        self.update_file_list()

    def on_group_filter_toggled(self, state):
        self.group_combo.setEnabled(state == QtCore.Qt.Checked)
        self.update_file_list()

    def on_source_filter_toggled(self, state):
        self.source_filter_combo.setEnabled(state == QtCore.Qt.Checked)
        self.update_file_list()

    def toggle_edit_mode(self):
        logging.debug("Toggle edit mode called")
        is_editable = self.description_widget.isReadOnly()
        self.description_widget.setReadOnly(not is_editable)
        self.description_edit_button.setText("Cancel" if is_editable else "Edit")
        self.description_save_button.setEnabled(is_editable)

        if is_editable:
            logging.debug("Entering edit mode")
            self.description_widget.setStyleSheet("""
                background-color: #3c3c3c;
                color: #ffffff;
                border: 2px solid #5a5a5a;
            """)
        else:
            logging.debug("Exiting edit mode")
            self.description_widget.setStyleSheet("""
                background-color: #2b2b2b;
                color: #cccccc;
                border: 1px solid #3a3a3a;
            """)
            self.update_preview()

        logging.debug(f"Description widget readonly: {self.description_widget.isReadOnly()}")

    def save_description(self):
        logger.debug("Save description called")
        try:
            selected_items = self.file_list_widget.selectedItems()
            if not selected_items or selected_items[0].childCount():
                logger.warning("No valid item selected for saving description")
                return

            selected_item = selected_items[0]
            file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
            new_description = self.description_widget.toPlainText()

            user = self.user_combo.currentText()
            master_json_path = self.base_path / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'

            with master_json_path.open('r') as f:
                master_data = json.load(f)

            updated = False
            for entry in master_data:
                if entry['File Name'] == file_path.stem:
                    entry['Summary'] = new_description
                    updated = True
                    break

            if not updated:
                new_entry = {
                    "File Name": file_path.stem,
                    "Summary": new_description,
                }
                master_data.append(new_entry)

            with master_json_path.open('w') as f:
                json.dump(master_data, f, indent=4)

            # Update the local json_data cache
            for entry in self.json_data:
                if entry['File Name'] == file_path.stem:
                    entry['Summary'] = new_description
                    break
            else:
                self.json_data.append(new_entry)

            # Update the description widget
            self.description_widget.setPlainText(new_description)
            self.description_widget.setReadOnly(True)
            self.description_edit_button.setText("Edit")
            self.description_save_button.setEnabled(False)

            # Clear the json_cache for this item to ensure fresh data on next load
            self.json_cache.pop(file_path.stem, None)

            self.show_info_dialog("Description Saved", "The description has been successfully updated.")
            logger.info(f"Description updated for {file_path.stem}")

        except Exception as e:
            logger.error(f"Error saving description: {e}", exc_info=True)
            self.show_error_dialog("Save Failed", f"Failed to save description: {e}")

        finally:
            # Refresh the UI to reflect the changes
            self.update_preview()

    def refresh_and_reselect(self, file_path: Path):
        self.refresh_ui()
        self.reselect_file(file_path)

    def reselect_file(self, file_path: Path):
        for i in range(self.file_list_widget.topLevelItemCount()):
            group_item = self.file_list_widget.topLevelItem(i)
            for j in range(group_item.childCount()):
                file_item = group_item.child(j)
                if Path(file_item.data(0, QtCore.Qt.UserRole)) == file_path:
                    self.file_list_widget.setCurrentItem(file_item)
                    self.update_preview()
                    return
        logger.warning(f"Could not find item to reselect: {file_path}")
        self.clear_preview()

    def open_write_snip_ui(self):
        logger.debug("Opening WriteSnipUI")
        try:
            from .write_snip_ui import create_write_snip_ui
            create_write_snip_ui(callback=self.update_file_list)
        except Exception as e:
            logger.error(f"Error opening WriteSnipUI: {str(e)}")
            self.show_error_dialog(f"Error opening New Snip UI: {str(e)}", severity=hou.severityType.Error)

    def edit_flipbook(self):
        logger.debug("Upload Seq button clicked")
        try:
            selected_items = self.file_list_widget.selectedItems()
            if not selected_items or selected_items[0].childCount() > 0:
                self.show_warning_dialog("Invalid Selection", "Please select a valid file to edit its flipbook.")
                return

            selected_item = selected_items[0]
            file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))

            new_flipbook_dir = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Select New Flipbook Directory", str(self.file_manager.get_preview_base_path(self.user_combo.currentText()))
            )

            if not new_flipbook_dir:
                logger.info("No directory selected for new flipbook.")
                return

            new_flipbook_path = Path(new_flipbook_dir)

            if not new_flipbook_path.exists() or not any(new_flipbook_path.glob('*.png')):
                self.show_warning_dialog("Invalid Directory", "Selected directory does not contain PNG files.")
                return

            dest_flipbook_folder = self.file_manager.get_preview_base_path(self.user_combo.currentText()) / 'flipbook' / file_path.stem

            
            try:
                if dest_flipbook_folder.exists():
                    shutil.rmtree(dest_flipbook_folder)
                    logger.info(f"Deleted existing flipbook folder: {dest_flipbook_folder}")

                dest_flipbook_folder.mkdir(parents=True, exist_ok=True)

                # Rename and copy the image sequence
                png_files = sorted(new_flipbook_path.glob('*.png'))
                for i, png_file in enumerate(png_files):
                    new_name = f"{file_path.stem}.{i:04d}.png"
                    shutil.copy(png_file, dest_flipbook_folder / new_name)

                logger.info(f"Copied and renamed new flipbook images to: {dest_flipbook_folder}")

                # Update master.json with the correct path format
                self.update_flipbook_path_in_json(file_path.stem, f"{file_path.stem}.$F4.png")

                # Clear the cache for this file
                cache_keys_to_remove = [key for key in self.preview_cache if file_path.stem in key]
                for key in cache_keys_to_remove:
                    del self.preview_cache[key]

                # Refresh the UI and reselect the item
                self.refresh_ui()
                self.reselect_file(file_path)

            except Exception as e:
                logger.error(f"Error updating flipbook: {e}", exc_info=True)
                self.show_error_dialog("Flipbook Update Failed", f"Failed to update flipbook: {e}")
        except Exception as e:
            logger.error(f"Error updating flipbook: {e}", exc_info=True)
            self.show_error_dialog("Flipbook Update Failed", f"Failed to update flipbook: {e}")

    def edit_snapshot(self):
        logger.debug("Edit Snapshot button clicked")
        try:
            selected_items = self.file_list_widget.selectedItems()
            if not selected_items or selected_items[0].childCount() > 0:
                self.show_warning_dialog("Invalid Selection", "Please select a valid file to edit its snapshot.")
                return

            selected_item = selected_items[0]
            file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))

            new_snapshot_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select New Snapshot Image", str(self.file_manager.get_preview_base_path(self.user_combo.currentText()) / 'snapshot'),
                "Images (*.png *.jpg *.jpeg *.bmp)"
            )

            if not new_snapshot_path:
                logger.info("No snapshot image selected.")
                return

            new_snapshot = Path(new_snapshot_path)

            if not new_snapshot.exists() or new_snapshot.suffix.lower() not in ['.png', '.jpg', '.jpeg', '.bmp']:
                self.show_warning_dialog("Invalid Image", "Selected file is not a valid image.")
                return

            dest_snapshot_path = self.file_manager.get_preview_base_path(self.user_combo.currentText()) / 'snapshot' / f"{file_path.stem}.png"

            try:
                if dest_snapshot_path.exists():
                    dest_snapshot_path.unlink()
                    logger.info(f"Deleted existing snapshot: {dest_snapshot_path}")

                if new_snapshot.suffix.lower() != '.png':
                    pixmap = QPixmap(str(new_snapshot))
                    if pixmap.isNull():
                        raise ValueError("Failed to load the selected image.")
                    pixmap.save(str(dest_snapshot_path), 'PNG')
                    logger.info(f"Converted and saved new snapshot as PNG: {dest_snapshot_path}")
                else:
                    shutil.copy(new_snapshot, dest_snapshot_path)
                    logger.info(f"Copied new snapshot to: {dest_snapshot_path}")

                self.update_snapshot_path_in_json(file_path.stem, f"/preview/snapshot/{file_path.stem}.png")

                # Refresh the UI and reselect the item
                self.refresh_ui()
                self.reselect_file(file_path)

            except Exception as e:
                logger.error(f"Error updating snapshot: {e}", exc_info=True)
                self.show_error_dialog("Snapshot Update Failed", f"Failed to update snapshot: {e}")
        except Exception as e:
            logger.error(f"Error updating snapshot: {e}", exc_info=True)
            self.show_error_dialog("Snapshot Update Failed", f"Failed to update snapshot: {e}")

    def perform_snapshot(self, screenshot_path: Path, file_path: Path):
        try:
            self.hide()
            main_window = hou.qt.mainWindow()
            main_window.raise_()
            main_window.activateWindow()
            QtCore.QTimer.singleShot(500, lambda: self.capture_screenshot(screenshot_path, file_path))
        except Exception as e:
            logger.error(f"Error preparing for screenshot: {e}")
            self.show_error_dialog("Screenshot Preparation Failed", f"Error preparing for screenshot: {e}")
            self.show()

    def capture_screenshot(self, screenshot_path: Path, file_path: Path):
        try:
            if platform.system() == "Linux":
                subprocess.run(['import', str(screenshot_path)], check=True)
            elif platform.system() == "Windows":
                import win32gui
                import win32ui
                import win32con
                import win32api
                from ctypes import windll
                
                hwnd = win32gui.GetDesktopWindow()
                width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
                height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
                left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
                top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
                
                hwindc = win32gui.GetWindowDC(hwnd)
                srcdc = win32ui.CreateDCFromHandle(hwindc)
                memdc = srcdc.CreateCompatibleDC()
                bmp = win32ui.CreateBitmap()
                bmp.CreateCompatibleBitmap(srcdc, width, height)
                memdc.SelectObject(bmp)
                windll.user32.PrintWindow(hwnd, memdc.GetSafeHdc(), 0)
                bmp.SaveBitmapFile(memdc, str(screenshot_path))
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(['screencapture', '-i', str(screenshot_path)], check=True)
            else:
                raise OSError(f"Unsupported operating system: {platform.system()}")
            
            logger.info(f"Snapshot saved successfully at: {screenshot_path}")
            self.update_snapshot_preview(screenshot_path)
            self.update_snapshot_path_in_json(screenshot_path.stem, f"/preview/snapshot/{screenshot_path.name}")
            
            # Refresh the UI and reselect the item
            self.refresh_ui()
            self.reselect_file(file_path)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error capturing screenshot: {e}")
            self.show_error_dialog("Screenshot Capture Failed", f"Failed to capture screenshot: {e}")
        except Exception as e:
            logger.error(f"Unexpected error capturing screenshot: {e}")
            self.show_error_dialog("Screenshot Capture Failed", f"Unexpected error capturing screenshot: {e}")
        finally:
            self.show()

    def update_flipbook_path_in_json(self, file_name: str, new_flipbook_path: str):
        logger.debug(f"Updating flipbook path for {file_name} to {new_flipbook_path}")
        user = self.user_combo.currentText()
        master_json_path = self.base_path / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'

        try:
            with master_json_path.open('r') as f:
                master_data = json.load(f)

            updated = False
            for entry in master_data:
                if entry['File Name'] == file_name:
                    entry['Flipbook'] = f"/preview/flipbook/{file_name}/{new_flipbook_path}"
                    updated = True
                    break

            if not updated:
                logger.warning(f"No existing entry found for {file_name}. This should not happen.")
                return

            with master_json_path.open('w') as f:
                json.dump(master_data, f, indent=4)

            # Update the local json_data cache
            for entry in self.json_data:
                if entry['File Name'] == file_name:
                    entry['Flipbook'] = f"/preview/flipbook/{file_name}/{new_flipbook_path}"
                    break

            logger.info(f"Successfully updated flipbook path for {file_name}")

        except Exception as e:
            logger.error(f"Error updating flipbook path in JSON: {e}", exc_info=True)
            self.show_error_dialog("Update Failed", f"Failed to update flipbook path: {e}")

    def update_snapshot_path_in_json(self, file_name: str, new_snapshot_path: str):
        try:
            user = self.user_combo.currentText()
            master_json_path = self.file_manager.base_path / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'
            if not master_json_path.exists():
                logger.warning(f"master.json not found at {master_json_path}. Creating a new one.")
                master_data = []
            else:
                with master_json_path.open('r') as f:
                    master_data = json.load(f)

            for entry in master_data:
                if entry['File Name'] == file_name:
                    entry['Snap'] = new_snapshot_path
                    break
            else:
                # If the file entry doesn't exist, create one
                new_entry = {
                    "File Name": file_name,
                    "Snap": new_snapshot_path,
                    # Add other necessary fields if required
                }
                master_data.append(new_entry)

            with master_json_path.open('w') as f:
                json.dump(master_data, f, indent=4)
            logger.info(f"Updated Snapshot path in master.json for {file_name}")

        except Exception as e:
            logger.error(f"Error updating Snapshot path in master.json: {e}", exc_info=True)
            self.show_error_dialog("Snapshot Path Update Failed", f"Failed to update Snapshot path in master.json: {e}")

    def save_flipbook(self):
        logger.debug("New Flipbook button clicked")
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            self.show_warning_dialog("Invalid Selection", "Please select a valid file to create a new flipbook.")
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
        file_name = file_path.stem

        user = self.user_combo.currentText()
        flipbook_base_folder = self.file_manager.get_preview_base_path(user) / "flipbook"
        flipbook_sequence_folder = flipbook_base_folder / file_name
        flipbook_path = flipbook_sequence_folder / f"{file_name}.$F4.png"

        if flipbook_sequence_folder.exists() and any(str(file.name).startswith(file_name) for file in flipbook_sequence_folder.iterdir()):
            reply = self.show_question_dialog("Overwrite Flipbook", 
                                                   "A flipbook with the same name already exists. Do you want to overwrite it?",
                                                   QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                                   QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.No:
                return

        message = "Save a flipbook of the current viewport?\n\nEnsure camera and timeframe are set correctly."
        reply = self.show_question_dialog("Save Flipbook", message,
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                               QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            if self.capture_flipbook(flipbook_path):
                # Update the JSON file with the new flipbook path
                self.update_flipbook_path_in_json(file_name, f"{file_name}.$F4.png")
                # Refresh the UI and reselect the item after capturing
                self.refresh_ui()
                self.reselect_file(file_path)

    def capture_flipbook(self, flipbook_path: Path):
        start_frame, end_frame = hou.playbar.playbackRange()
        
        start_frame = int(start_frame)
        end_frame = int(end_frame)
        
        if start_frame >= end_frame:
            self.show_error_dialog("Invalid Timeframe", "Start frame must be less than end frame.")
            return False
        
        flipbook_sequence_folder = flipbook_path.parent
        flipbook_sequence_folder.mkdir(parents=True, exist_ok=True)
        
        try:
            hou.hipFile.save()
            scene_viewer = toolutils.sceneViewer()
            flipbook_settings = scene_viewer.flipbookSettings()
            flipbook_settings.frameRange((start_frame, end_frame))
            flipbook_settings.output(str(flipbook_path))
            
            scene_viewer.flipbook(settings=flipbook_settings)
            
            if any(flipbook_sequence_folder.iterdir()):
                self.show_info_dialog("Flipbook Saved", f"Flipbook saved successfully at:\n{flipbook_sequence_folder}")
                logger.info(f"Flipbook saved successfully at: {flipbook_sequence_folder}")
                
                self.create_gif_from_flipbook(flipbook_sequence_folder, flipbook_path)
                return True
            else:
                self.show_warning_dialog("Flipbook Not Saved", "No flipbook files were created. The operation may have been cancelled.")
                logger.warning("No flipbook files were created. The operation may have been cancelled.")
                return False
        except Exception as e:
            logger.error(f"Error capturing flipbook: {e}")
            self.show_error_dialog("Flipbook Capture Failed", f"Failed to capture flipbook: {e}")
            return False

    def create_gif_from_flipbook(self, flipbook_folder: Path, flipbook_path: Path):
        try:
            png_files = sorted(flipbook_folder.glob('*.png'))
            
            if not png_files:
                logger.warning("No PNG files found in the flipbook folder.")
                return
            
            images = []
            for png_file in png_files:
                img = Image.open(png_file)
                img.thumbnail((200, 150), Image.LANCZOS)
                images.append(img)
            
            images = images[:50]
            
            gif_path = flipbook_path.with_suffix('.gif')
            images[0].save(gif_path, save_all=True, append_images=images[1:], duration=100, loop=0)
            
            logger.info(f"GIF created successfully at: {gif_path}")
            self.show_info_dialog("GIF Created", f"GIF created successfully at:\n{gif_path}")
            
        except Exception as e:
            logger.error(f"Error creating GIF: {e}")
            self.show_error_dialog("GIF Creation Failed", f"Failed to create GIF: {e}")

    def save_snapshot(self):
        logger.debug("Take New Snapshot button clicked")
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            self.show_warning_dialog("Invalid Selection", "Please select a valid file to create a new snapshot.")
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
        file_name = file_path.stem

        user = self.user_combo.currentText()
        snapshot_dir = self.file_manager.get_preview_base_path(user) / "snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        screenshot_path = snapshot_dir / f"{file_name}.png"
        
        if screenshot_path.exists():
            reply = self.show_question_dialog("Overwrite Snapshot", 
                                                   "A snapshot with the same name already exists. Do you want to overwrite it?",
                                                   QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                                   QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.No:
                return

        message = "Capture a snapshot of your node network for quick reference?"
        reply = self.show_question_dialog("Save Snapshot", message, 
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                               QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            QtCore.QTimer.singleShot(100, lambda: self.perform_snapshot(screenshot_path, file_path))

    def perform_snapshot(self, screenshot_path: Path, file_path: Path):
        try:
            self.hide()
            main_window = hou.qt.mainWindow()
            main_window.raise_()
            main_window.activateWindow()
            QtCore.QTimer.singleShot(500, lambda: self.capture_screenshot(screenshot_path, file_path))
        except Exception as e:
            logger.error(f"Error preparing for screenshot: {e}")
            self.show_error_dialog("Screenshot Preparation Failed", f"Error preparing for screenshot: {e}")
            self.show()

    def capture_screenshot(self, screenshot_path: Path, file_path: Path):
        try:
            if platform.system() == "Linux":
                subprocess.run(['import', str(screenshot_path)], check=True)
            elif platform.system() == "Windows":
                import win32gui
                import win32ui
                import win32con
                import win32api
                from ctypes import windll
                
                hwnd = win32gui.GetDesktopWindow()
                width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
                height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
                left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
                top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
                
                hwindc = win32gui.GetWindowDC(hwnd)
                srcdc = win32ui.CreateDCFromHandle(hwindc)
                memdc = srcdc.CreateCompatibleDC()
                bmp = win32ui.CreateBitmap()
                bmp.CreateCompatibleBitmap(srcdc, width, height)
                memdc.SelectObject(bmp)
                windll.user32.PrintWindow(hwnd, memdc.GetSafeHdc(), 0)
                
                bmp.SaveBitmapFile(memdc, str(screenshot_path))
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(['screencapture', '-i', str(screenshot_path)], check=True)
            else:
                raise OSError(f"Unsupported operating system: {platform.system()}")
            
            logger.info(f"Snapshot saved successfully at: {screenshot_path}")
            self.update_snapshot_preview(screenshot_path)
            self.update_snapshot_path_in_json(screenshot_path.stem, f"/preview/snapshot/{screenshot_path.name}")
            
            # Refresh the UI and reselect the item
            self.refresh_ui()
            self.reselect_file(file_path)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error capturing screenshot: {e}")
            self.show_error_dialog("Screenshot Capture Failed", f"Failed to capture screenshot: {e}")
        except Exception as e:
            logger.error(f"Unexpected error capturing screenshot: {e}")
            self.show_error_dialog("Screenshot Capture Failed", f"Unexpected error capturing screenshot: {e}")
        finally:
            self.show()

    def delete_flipbook(self):
        logger.debug("Delete Flipbook button clicked")
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            self.show_warning_dialog("Invalid Selection", "Please select a valid file to delete its flipbook.")
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
        user = self.user_combo.currentText()

        reply = self.show_question_dialog("Confirm Flipbook Deletion", 
                                          f"Are you sure you want to delete the flipbook for {file_path.stem}?",
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                          QtWidgets.QMessageBox.No)
        
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                # Delete flipbook directory
                flipbook_dir = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'flipbook' / file_path.stem
                if flipbook_dir.exists():
                    shutil.rmtree(flipbook_dir)
                    logger.info(f"Deleted flipbook directory: {flipbook_dir}")
                else:
                    logger.warning(f"Flipbook directory not found: {flipbook_dir}")

                # Update master.json
                master_json_path = self.base_path / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'
                if master_json_path.exists():
                    with master_json_path.open('r') as f:
                        master_data = json.load(f)
                    
                    for entry in master_data:
                        if entry['File Name'] == file_path.stem:
                            if 'Flipbook' in entry:
                                del entry['Flipbook']
                                logger.info(f"Removed Flipbook entry for {file_path.stem} in master.json")
                            break
                    
                    with master_json_path.open('w') as f:
                        json.dump(master_data, f, indent=4)
                else:
                    logger.warning(f"master.json not found: {master_json_path}")

                # Clear the caches
                self.json_cache.pop(file_path.stem, None)
                self.preview_cache.pop(file_path.stem, None)

                # Update local json_data
                for entry in self.json_data:
                    if entry['File Name'] == file_path.stem:
                        if 'Flipbook' in entry:
                            del entry['Flipbook']
                        break

                self.show_info_dialog("Flipbook Deleted", f"Flipbook for {file_path.stem} has been deleted.")
                
                # Refresh the UI and reselect the item
                self.refresh_ui()
                self.reselect_file(file_path)
                
            except Exception as e:
                logger.error(f"Error deleting flipbook: {e}", exc_info=True)
                self.show_error_dialog("Flipbook Deletion Failed", f"Failed to delete flipbook: {e}")
        else:
            self.show_info_dialog("Deletion Cancelled", "The flipbook was not deleted.")

    def delete_snapshot(self):
        logger.debug("Delete Snapshot button clicked")
        selected_items = self.file_list_widget.selectedItems()
        if not selected_items or selected_items[0].childCount() > 0:
            self.show_warning_dialog("Invalid Selection", "Please select a valid file to delete its snapshot.")
            return

        selected_item = selected_items[0]
        file_path = Path(selected_item.data(0, QtCore.Qt.UserRole))
        file_name = file_path.stem

        user = self.user_combo.currentText()
        snapshot_path = self.file_manager.get_preview_base_path(user) / "snapshot" / f"{file_name}.png"

        if not snapshot_path.exists():
            self.show_warning_dialog("No Snapshot", "There is no snapshot to delete for this file.")
            return

        reply = self.show_question_dialog("Delete Snapshot", 
                                          "Are you sure you want to delete this snapshot?",
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                          QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                snapshot_path.unlink()
                logger.info(f"Snapshot deleted successfully: {snapshot_path}")
                self.update_snapshot_path_in_json(file_name, "")
                self.show_info_dialog("Snapshot Deleted", "The snapshot has been successfully deleted.")
                
                # Refresh the UI and reselect the item
                self.refresh_ui()
                self.reselect_file(file_path)
            except Exception as e:
                logger.error(f"Error deleting snapshot: {e}")
                self.show_error_dialog("Snapshot Deletion Failed", f"Failed to delete snapshot: {e}")

    def preload_nearby_items(self):
        current_item = self.file_list_widget.currentItem()
        if current_item:
            index = self.file_list_widget.indexOfTopLevelItem(current_item)
            for i in range(max(0, index-2), min(self.file_list_widget.topLevelItemCount(), index+3)):
                item = self.file_list_widget.topLevelItem(i)
                if item and not item.childCount():
                    file_path = Path(item.data(0, QtCore.Qt.UserRole))
                    if file_path.stem not in self.preview_cache:
                        asyncio.ensure_future(self.preload_item(file_path.stem))

    async def preload_item(self, file_stem):
        json_data = await self.load_json_data_async(file_stem)
        if json_data:
            await self.load_preview_assets_async(json_data)

    def format_name(self, input_string):
        # Remove special characters and spaces
        cleaned = re.sub(r'[^a-zA-Z0-9 ]', '', input_string)
        
        # Split the string into words
        words = cleaned.split()
        
        # Capitalize the first letter of each word except the first one
        formatted = words[0].lower() + ''.join(word.capitalize() for word in words[1:])
        
        return formatted

    def update_item_name(self, item, new_full_name, updated_column):
        old_file_path = Path(item.data(0, QtCore.Qt.UserRole))
        old_full_name = old_file_path.stem
        user = self.user_combo.currentText()
        
        # Update the file name
        new_file_path = old_file_path.with_name(f"{new_full_name}{old_file_path.suffix}")
        try:
            old_file_path.rename(new_file_path)
        except Exception as e:
            self.show_error_dialog("Rename Failed", f"Failed to rename file: {e}")
            return

        # Update flipbook directory and image sequence
        old_flipbook_dir = self.file_manager.get_preview_base_path(user) / 'flipbook' / old_full_name
        new_flipbook_dir = self.file_manager.get_preview_base_path(user) / 'flipbook' / new_full_name
        if old_flipbook_dir.exists():
            try:
                old_flipbook_dir.rename(new_flipbook_dir)
                # Rename individual flipbook frames
                for file in new_flipbook_dir.glob(f"{old_full_name}.*"):
                    new_file_name = file.name.replace(old_full_name, new_full_name)
                    file.rename(new_flipbook_dir / new_file_name)
            except Exception as e:
                self.show_error_dialog("Rename Failed", f"Failed to rename flipbook directory: {e}")
                return

        # Update snapshot file
        old_snapshot_path = self.file_manager.get_preview_base_path(user) / 'snapshot' / f"{old_full_name}.png"
        new_snapshot_path = self.file_manager.get_preview_base_path(user) / 'snapshot' / f"{new_full_name}.png"
        if old_snapshot_path.exists():
            try:
                old_snapshot_path.rename(new_snapshot_path)
            except Exception as e:
                self.show_error_dialog("Rename Failed", f"Failed to rename snapshot file: {e}")
                return

        # Update the JSON data
        self.update_json_data(old_full_name, new_full_name, new_flipbook_dir, new_snapshot_path)

        # Refresh the UI
        self.refresh_ui()
        self.reselect_file(new_file_path)

        self.show_info_dialog("Name Updated", f"Successfully updated the {['Context', 'Type', 'Name', 'Source', 'Version'][updated_column]}")

    def reselect_file(self, file_path: Path):
        for i in range(self.file_list_widget.topLevelItemCount()):
            group_item = self.file_list_widget.topLevelItem(i)
            for j in range(group_item.childCount()):
                file_item = group_item.child(j)
                if Path(file_item.data(0, QtCore.Qt.UserRole)) == file_path:
                    self.file_list_widget.setCurrentItem(file_item)
                    self.update_preview()
                    return
        logger.warning(f"Could not find item to reselect: {file_path}")

    def reselect_file(self, file_path: Path):
        for i in range(self.file_list_widget.topLevelItemCount()):
            group_item = self.file_list_widget.topLevelItem(i)
            for j in range(group_item.childCount()):
                file_item = group_item.child(j)
                if Path(file_item.data(0, QtCore.Qt.UserRole)) == file_path:
                    self.file_list_widget.setCurrentItem(file_item)
                    self.update_preview()
                    return
        logger.warning(f"Could not find item to reselect: {file_path}")
        
    def on_item_changed(self, item, column):
        if not item or item.childCount() > 0:  # Ignore group items
            return

        try:
            old_full_name = Path(item.data(0, QtCore.Qt.UserRole)).stem
            parts = old_full_name.split('_')
            
            if len(parts) != 5:
                self.show_error_dialog("Invalid Name Format", "The file name does not follow the expected format.")
                return

            new_value = item.text(column)
            formatted_value = self.format_name(new_value)

            new_parts = parts.copy()
            if column == 0:  # Context
                new_parts[0] = formatted_value.upper()
            elif column == 1:  # Type
                new_parts[1] = formatted_value
            elif column == 2:  # Name
                new_parts[2] = formatted_value
            elif column == 3:  # Source
                new_parts[3] = formatted_value
            elif column == 4:  # Version
                new_parts[4] = formatted_value.lower()

            new_full_name = '_'.join(new_parts)
            
            # Only update if the name has actually changed
            if new_full_name != old_full_name:
                self.update_item_name(item, new_full_name, column)
            else:
                # If no change, just update the displayed text to the formatted version
                item.setText(column, new_parts[column])

        except Exception as e:
            logger.error(f"Error in on_item_changed: {str(e)}", exc_info=True)
            self.show_error_dialog("Update Failed", f"An error occurred while updating the item: {str(e)}")

    def update_item_name(self, item, new_full_name, updated_column):
        old_file_path = Path(item.data(0, QtCore.Qt.UserRole))
        old_full_name = old_file_path.stem
        user = self.user_combo.currentText()
        
        # Update the file name
        new_file_path = old_file_path.with_name(f"{new_full_name}{old_file_path.suffix}")
        try:
            if old_file_path.exists():
                old_file_path.rename(new_file_path)
                logger.info(f"Renamed file from {old_file_path} to {new_file_path}")
            else:
                logger.warning(f"Old file does not exist: {old_file_path}")
                raise FileNotFoundError(f"Old file does not exist: {old_file_path}")

            # Update flipbook directory and image sequence
            old_flipbook_dir = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'flipbook' / old_full_name
            new_flipbook_dir = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'flipbook' / new_full_name
            if old_flipbook_dir.exists():
                try:
                    # Rename image sequence files
                    for old_file in old_flipbook_dir.glob(f"{old_full_name}.*"):
                        frame_number = old_file.stem.split('.')[-1]
                        new_file_name = f"{new_full_name}.{frame_number}{old_file.suffix}"
                        old_file.rename(old_flipbook_dir / new_file_name)
                    
                    # Rename the directory
                    old_flipbook_dir.rename(new_flipbook_dir)
                    logger.info(f"Renamed flipbook directory from {old_flipbook_dir} to {new_flipbook_dir}")
                except Exception as e:
                    logger.error(f"Error updating flipbook: {e}", exc_info=True)
                    self.show_error_dialog("Flipbook Update Failed", f"Failed to update flipbook: {e}")

            # Update snapshot
            old_snapshot_path = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'snapshot' / f"{old_full_name}.png"
            new_snapshot_path = self.base_path / 'pyDump' / user / 'Snips' / 'preview' / 'snapshot' / f"{new_full_name}.png"
            if old_snapshot_path.exists():
                try:
                    old_snapshot_path.rename(new_snapshot_path)
                    logger.info(f"Renamed snapshot from {old_snapshot_path} to {new_snapshot_path}")
                except Exception as e:
                    logger.error(f"Error updating snapshot: {e}", exc_info=True)
                    self.show_error_dialog("Snapshot Update Failed", f"Failed to update snapshot: {e}")

            # Update master.json
            master_json_path = self.base_path / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'
            try:
                with master_json_path.open('r') as f:
                    master_data = json.load(f)
                
                for entry in master_data:
                    if entry['File Name'] == old_full_name:
                        entry['File Name'] = new_full_name
                        if 'Flipbook' in entry:
                            entry['Flipbook'] = entry['Flipbook'].replace(old_full_name, new_full_name)
                        if 'Snap' in entry:
                            entry['Snap'] = entry['Snap'].replace(old_full_name, new_full_name)
                        break
                
                with master_json_path.open('w') as f:
                    json.dump(master_data, f, indent=4)
                
                logger.info(f"Updated master.json: renamed {old_full_name} to {new_full_name}")
            except Exception as e:
                logger.error(f"Error updating master.json: {e}", exc_info=True)
                self.show_error_dialog("JSON Update Failed", f"Failed to update master.json: {e}")

            # Update the item's data
            item.setData(0, QtCore.Qt.UserRole, str(new_file_path))

            # Update local json_data cache
            for entry in self.json_data:
                if entry['File Name'] == old_full_name:
                    entry['File Name'] = new_full_name
                    if 'Flipbook' in entry:
                        entry['Flipbook'] = entry['Flipbook'].replace(old_full_name, new_full_name)
                    if 'Snap' in entry:
                        entry['Snap'] = entry['Snap'].replace(old_full_name, new_full_name)
                    break

            # Clear the json_cache for this item
            self.json_cache.pop(old_full_name, None)

            self.show_info_dialog("Name Updated", f"Successfully updated the {['Context', 'Type', 'Name', 'Source', 'Version'][updated_column]}")
            self.refresh_ui()

        except Exception as e:
            logger.error(f"Error in update_item_name: {str(e)}", exc_info=True)
            self.show_error_dialog("Rename Failed", f"Failed to rename file: {e}")
            # Revert the name change in the UI
            old_parts = old_full_name.split('_')
            item.setText(updated_column, old_parts[updated_column])

            
    def update_json_data(self, old_name, new_name, new_flipbook_dir, new_snapshot_path):
        try:
            user = self.user_combo.currentText()
            master_json_path = self.base_path / 'pyDump' / user / 'Snips' / 'descriptions' / 'master.json'
            
            with master_json_path.open('r') as f:
                data = json.load(f)
            
            for item in data:
                if item['File Name'] == old_name:
                    item['File Name'] = new_name
                    if 'Flipbook' in item and new_flipbook_dir.exists():
                        item['Flipbook'] = f"/preview/flipbook/{new_name}/{new_name}.$F4.png"
                    if 'Snap' in item and new_snapshot_path.exists():
                        item['Snap'] = f"/preview/snapshot/{new_name}.png"
                    break
            
            with master_json_path.open('w') as f:
                json.dump(data, f, indent=4)
            
            logger.info(f"Updated JSON data: renamed {old_name} to {new_name}")
        except Exception as e:
            logger.error(f"Error updating JSON data: {e}", exc_info=True)
            self.show_error_dialog("JSON Update Failed", f"Failed to update JSON data: {e}")

        # Clear the cache for this item
        self.json_cache.pop(old_name, None)
        cache_keys_to_remove = [key for key in self.preview_cache if old_name in key]
        for key in cache_keys_to_remove:
            del self.preview_cache[key]

        # Refresh the UI
        self.refresh_ui()

# Global variable to keep a reference to the window
_shelf_tool_ui_instance = None

def show_my_shelf_tool_ui():
    global _shelf_tool_ui_instance
    
    try:
        logger.info("Initializing MyShelfToolUI")
        
        # Close existing window if it exists
        if _shelf_tool_ui_instance is not None:
            _shelf_tool_ui_instance.close()
            _shelf_tool_ui_instance = None
        
        # Create new instance
        _shelf_tool_ui_instance = MyShelfToolUI()
        
        logger.info("Setting up UI components")
        _shelf_tool_ui_instance.setup_ui()
        
        _shelf_tool_ui_instance.show()
        
        # Return the instance (optional, for debugging purposes)
        return _shelf_tool_ui_instance

    except Exception as e:
        logger.error(f"Error in show_my_shelf_tool_ui: {str(e)}")
        logger.error(traceback.format_exc())
        print(f"Error opening UI: {str(e)}")
        return None



# def show_my_shelf_tool_ui():
#     try:
#         import hou
#         from PySide2 import QtWidgets
        
#         app = QtWidgets.QApplication.instance()
#         if not app:
#             app = QtWidgets.QApplication([])
        
#         window = MyShelfToolUI()
#         window.show()
#         window.raise_()
        
#         return window
#     except Exception as e:
#         print(f"Error initializing MyShelfToolUI: {e}")
#         import traceback
#         traceback.print_exc()
#         return None
    
# ... (rest of the existing code) ...

# if __name__ == "__main__":
#     show_my_shelf_tool_ui()