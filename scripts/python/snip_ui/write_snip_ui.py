import json
import logging
from pathlib import Path
from typing import List, Optional, Union
import re
from datetime import datetime
import os
import hou
from PySide2 import QtWidgets, QtCore, QtGui
from PySide2.QtGui import QMovie, QPixmap
import toolutils
import platform
import subprocess
from PIL import Image
import glob
from PySide2.QtWidgets import (
    QButtonGroup, QRadioButton, QHBoxLayout, QVBoxLayout,
    QWidget, QToolButton, QScrollArea, QSizePolicy, QFrame,
    QTabWidget, QWidget, QGroupBox
)
from PySide2.QtCore import Qt, QParallelAnimationGroup, QPropertyAnimation, QAbstractAnimation

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load configuration
CONFIG = {
    "MAX_VERSION": 10,
    "CONTEXTS": ["SOP", "OBJ", "ROP", "DOP", "COP", "LOP", "VOP", "CHOP", "VOPNET", "TOP"],
    "COLORS": {
        "BACKGROUND": "#2b2b2b",
        "TEXT": "#e0e0e0",
        "ACCENT": "#4a90e2",
        "INPUT_BG": "#333333",
        "BUTTON_BG": "#3a3a3a",
        "BUTTON_TEXT": "#ffffff",
        "BUTTON_HOVER": "#4a4a4a",
        "GROUP_BG": "#2f2f2f",
        "BORDER": "#555555",
    },
    "FONTS": {
        "MAIN": "Roboto, Arial, sans-serif",
        "SIZE": {
            "SMALL": "11px",
            "MEDIUM": "13px",
            "LARGE": "15px",
        },
    },
}

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'write_snip_ui_settings.json')

class StyledWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(self.get_base_style())

    def get_base_style(self):
        return f"""
            QWidget {{
                background-color: {CONFIG['COLORS']['BACKGROUND']};
                color: {CONFIG['COLORS']['TEXT']};
                font-family: {CONFIG['FONTS']['MAIN']};
                font-size: {CONFIG['FONTS']['SIZE']['MEDIUM']};
            }}
            QLabel {{
                font-size: {CONFIG['FONTS']['SIZE']['MEDIUM']};
                margin-bottom: 2px;
            }}
            QLineEdit, QComboBox, QTextEdit {{
                background-color: {CONFIG['COLORS']['INPUT_BG']};
                color: {CONFIG['COLORS']['TEXT']};
                border: 1px solid {CONFIG['COLORS']['BORDER']};
                border-radius: 3px;
                padding: 4px;
                margin-bottom: 8px;
            }}
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
                border: 1px solid {CONFIG['COLORS']['ACCENT']};
            }}
            QPushButton {{
                background-color: {CONFIG['COLORS']['BUTTON_BG']};
                color: {CONFIG['COLORS']['BUTTON_TEXT']};
                border: 1px solid {CONFIG['COLORS']['BORDER']};
                padding: 6px 12px;
                border-radius: 4px;
                margin: 4px;
            }}
            QPushButton:hover {{
                background-color: {CONFIG['COLORS']['BUTTON_HOVER']};
                border: 1px solid {CONFIG['COLORS']['ACCENT']};
            }}
            QComboBox {{
                min-width: 140px;
            }}
            QComboBox:hover {{
                border: 1px solid {CONFIG['COLORS']['ACCENT']};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: none;
            }}
            QComboBox::down-arrow {{
                image: none;
            }}
        """

class CollapsibleBox(QWidget):
    def __init__(self, title="", parent=None):
        super(CollapsibleBox, self).__init__(parent)

        self.toggle_button = QToolButton(text=title, checkable=True, checked=False)
        self.toggle_button.setStyleSheet("QToolButton { border: none; }")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.RightArrow)
        self.toggle_button.pressed.connect(self.on_pressed)

        self.toggle_animation = QParallelAnimationGroup(self)

        self.content_area = QScrollArea(maximumHeight=0, minimumHeight=0)
        self.content_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.content_area.setFrameShape(QFrame.NoFrame)

        lay = QVBoxLayout(self)
        lay.setSpacing(0)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.toggle_button)
        lay.addWidget(self.content_area)

        self.toggle_animation.addAnimation(QPropertyAnimation(self, b"minimumHeight"))
        self.toggle_animation.addAnimation(QPropertyAnimation(self, b"maximumHeight"))
        self.toggle_animation.addAnimation(QPropertyAnimation(self.content_area, b"maximumHeight"))

    def on_pressed(self):
        checked = self.toggle_button.isChecked()
        self.toggle_button.setArrowType(Qt.DownArrow if not checked else Qt.RightArrow)
        self.toggle_animation.setDirection(QAbstractAnimation.Forward if not checked else QAbstractAnimation.Backward)
        self.toggle_animation.start()

    def setContentLayout(self, layout):
        lay = self.content_area.layout()
        del lay
        self.content_area.setLayout(layout)
        collapsed_height = self.sizeHint().height() - self.content_area.maximumHeight()
        content_height = layout.sizeHint().height()
        for i in range(self.toggle_animation.animationCount()):
            animation = self.toggle_animation.animationAt(i)
            animation.setDuration(300)
            animation.setStartValue(collapsed_height)
            animation.setEndValue(collapsed_height + content_height)

        content_animation = self.toggle_animation.animationAt(self.toggle_animation.animationCount() - 1)
        content_animation.setDuration(300)
        content_animation.setStartValue(0)
        content_animation.setEndValue(content_height)

class WriteSnipUI(StyledWidget):
    snip_created = QtCore.Signal()

    def __init__(self):
        super().__init__()
        
        self.base_path = Path(hou.getenv("EFX", ""))
        if not self.base_path.exists():
            raise EnvironmentError("$EFX environment variable is not set or invalid")
        
        self.CORE_PATH = self.base_path / "pyDump"
        
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Write Snip UI")
        self.init_ui()
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self.update_snip_path()
        self.populate_existing_values()

        show_dialogs = self.load_dialog_preference()
        self.show_dialogs_checkbox.setChecked(show_dialogs)

        self.setFixedWidth(650)

        self.flipbook_saved = False
        self.snapshot_saved = False
        self.snip_saved = False

        self.current_flipbook_path = None
        self.current_snapshot_path = None

        self.update_file_name()

    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)

        # Remove the tab widget and create a single layout for Snips
        snips_layout = QtWidgets.QVBoxLayout()
        self.setup_snip_ui(snips_layout)
        main_layout.addLayout(snips_layout)

    def setup_snip_ui(self, layout):
        self.setup_user_selection(layout)
        self.setup_file_name_parameters(layout)
        self.setup_description_section(layout)
        self.setup_snip_info_section(layout)
        self.setup_save_preview_section(layout)
        self.setup_show_dialogs_checkbox(layout)

    def setup_user_selection(self, layout):
        user_layout = QtWidgets.QHBoxLayout()
        user_layout.addStretch(1)
        user_layout.addWidget(QtWidgets.QLabel("User:"))
        self.user_combo = QtWidgets.QComboBox()
        self.user_combo.setMaximumWidth(200)
        self.populate_user_combo()
        self.user_combo.currentTextChanged.connect(self.on_user_changed)
        user_layout.addWidget(self.user_combo)
        layout.addLayout(user_layout)

    def setup_file_name_parameters(self, layout):
        params_layout = QtWidgets.QHBoxLayout()
        params_layout.setSpacing(15)

        params = [
            ("Context:", "Context", CONFIG["CONTEXTS"]),
            ("Type:", "Type", [], "e.g., flip, pop, util"),
            ("Name:", "Name", [], "e.g., setupName"),
            ("Source:", "Source", [], "e.g., userName, author"),
            ("Version:", "Version", [], "1")
        ]

        for label_text, key, *args in params:
            column_layout = QtWidgets.QVBoxLayout()
            column_layout.setSpacing(5)

            label = QtWidgets.QLabel(label_text)
            label.setStyleSheet(f"""
                font-family: {CONFIG['FONTS']['MAIN']};
                font-size: {CONFIG['FONTS']['SIZE']['MEDIUM']};
                color: {CONFIG['COLORS']['TEXT']};
            """)
            column_layout.addWidget(label)

            if key == "Version":
                widget = QtWidgets.QLineEdit(args[1] if args else "1")
                widget.setValidator(QtGui.QIntValidator(1, CONFIG["MAX_VERSION"]))
                widget.setFixedWidth(50)
                widget.textChanged.connect(self.update_file_name)
            else:
                widget = QtWidgets.QComboBox()
                if args and isinstance(args[0], list):
                    widget.addItems(args[0])
                widget.setEditable(True)
                widget.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
                widget.lineEdit().setAlignment(QtCore.Qt.AlignLeft)
                widget.setMinimumWidth(140)
                
                if len(args) > 1 and isinstance(args[1], str):
                    widget.lineEdit().setPlaceholderText(args[1])
                
                widget.lineEdit().textEdited.connect(self.update_file_name)

            widget.setStyleSheet(f"""
                font-family: {CONFIG['FONTS']['MAIN']};
                font-size: {CONFIG['FONTS']['SIZE']['MEDIUM']};
                color: {CONFIG['COLORS']['TEXT']};
                background-color: {CONFIG['COLORS']['INPUT_BG']};
                border: 1px solid {CONFIG['COLORS']['BORDER']};
                border-radius: 3px;
                padding: 2px 5px;
            """)

            column_layout.addWidget(widget)
            params_layout.addLayout(column_layout)
            setattr(self, key, widget)

        layout.addLayout(params_layout)

    def setup_description_section(self, layout):
        description_layout = QtWidgets.QVBoxLayout()
        description_layout.addWidget(QtWidgets.QLabel("Summary:"))
        self.description_text = QtWidgets.QTextEdit()
        self.description_text.setPlaceholderText("Enter a brief description of the snip...")
        self.description_text.setTabChangesFocus(True)
        
        current_height = self.description_text.sizeHint().height()
        self.description_text.setFixedHeight(current_height // 2)
        
        description_layout.addWidget(self.description_text)
        layout.addLayout(description_layout)

    def setup_snip_info_section(self, layout):
        self.snip_info_box = CollapsibleBox("Snip Info")
        snip_info_layout = QtWidgets.QVBoxLayout()
        
        self.file_name_label = QtWidgets.QLabel()
        self.file_name_label.setStyleSheet(f"""
            color: {CONFIG['COLORS']['TEXT']};
            font-size: {CONFIG['FONTS']['SIZE']['MEDIUM']};
            font-family: {CONFIG['FONTS']['MAIN']};
        """)
        snip_info_layout.addWidget(self.file_name_label)
        
        path_layout = QtWidgets.QHBoxLayout()
        path_label = QtWidgets.QLabel("Snip Path:")
        path_label.setStyleSheet(f"""
            color: {CONFIG['COLORS']['TEXT']};
            font-size: {CONFIG['FONTS']['SIZE']['MEDIUM']};
            font-family: {CONFIG['FONTS']['MAIN']};
        """)
        path_layout.addWidget(path_label)
        
        self.current_path_label = QtWidgets.QLabel()
        self.current_path_label.setStyleSheet(f"""
            color: {CONFIG['COLORS']['TEXT']};
            font-size: {CONFIG['FONTS']['SIZE']['MEDIUM']};
            font-family: {CONFIG['FONTS']['MAIN']};
        """)
        path_layout.addWidget(self.current_path_label, 1)
        
        change_path_button = QtWidgets.QPushButton("Change")
        change_path_button.setStyleSheet(f"""
            padding: 2px 8px;
            font-size: {CONFIG['FONTS']['SIZE']['SMALL']};
            font-family: {CONFIG['FONTS']['MAIN']};
        """)
        change_path_button.clicked.connect(self.change_snip_path)
        path_layout.addWidget(change_path_button)
        
        snip_info_layout.addLayout(path_layout)

        # Create a QGroupBox for previews
        preview_group = QtWidgets.QGroupBox("Previews")
        preview_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {CONFIG['COLORS']['BORDER']};
                border-radius: 5px;
                margin-top: 10px;
                padding: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }}
        """)
        preview_layout = QtWidgets.QHBoxLayout()
        preview_layout.setSpacing(20)
        
        # Flipbook preview
        flipbook_layout = QtWidgets.QVBoxLayout()
        flipbook_layout.setSpacing(5)
        
        flipbook_label = QtWidgets.QLabel("Flipbook:")
        flipbook_layout.addWidget(flipbook_label)
        
        self.flipbook_preview = QtWidgets.QLabel()
        self.flipbook_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.flipbook_preview.setFixedSize(200, 150)
        self.flipbook_preview.setStyleSheet(f"""
            border: 1px solid {CONFIG['COLORS']['BORDER']};
            border-radius: 3px;
            background-color: {CONFIG['COLORS']['BACKGROUND']};
        """)
        flipbook_layout.addWidget(self.flipbook_preview)
        
        radio_layout = QHBoxLayout()
        self.preview_button_group = QButtonGroup(self)
        
        self.png_radio = QRadioButton("PNG")
        self.gif_radio = QRadioButton("GIF")
        
        self.preview_button_group.addButton(self.png_radio)
        self.preview_button_group.addButton(self.gif_radio)
        
        radio_layout.addWidget(self.png_radio)
        radio_layout.addWidget(self.gif_radio)
        radio_layout.addStretch()
        
        flipbook_layout.addLayout(radio_layout)
        
        preview_layout.addLayout(flipbook_layout)
        
        # Snapshot preview
        snapshot_layout = QtWidgets.QVBoxLayout()
        snapshot_layout.setSpacing(5)
        
        snapshot_label = QtWidgets.QLabel("Snapshot:")
        snapshot_layout.addWidget(snapshot_label)
        
        self.snapshot_preview = QtWidgets.QLabel()
        self.snapshot_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.snapshot_preview.setFixedSize(200, 150)
        self.snapshot_preview.setStyleSheet(f"""
            border: 1px solid {CONFIG['COLORS']['BORDER']};
            border-radius: 3px;
            background-color: {CONFIG['COLORS']['BACKGROUND']};
        """)
        snapshot_layout.addWidget(self.snapshot_preview)
        
        # Add a hidden placeholder to align with the radio buttons
        placeholder_layout = QHBoxLayout()
        placeholder_label = QtWidgets.QLabel()
        placeholder_label.setFixedHeight(self.png_radio.sizeHint().height())
        placeholder_layout.addWidget(placeholder_label)
        placeholder_layout.addStretch()
        
        snapshot_layout.addLayout(placeholder_layout)
        
        preview_layout.addLayout(snapshot_layout)
        
        preview_group.setLayout(preview_layout)
        snip_info_layout.addWidget(preview_group)

        self.snip_info_box.setContentLayout(snip_info_layout)
        layout.addWidget(self.snip_info_box)

        self.png_radio.setChecked(True)
        self.preview_mode = "png"
        self.preview_button_group.buttonClicked.connect(self.toggle_preview_mode)

        self.current_frame = 0
        self.png_timer = QtCore.QTimer(self)
        self.png_timer.timeout.connect(self.update_png_frame)

    def change_snip_path(self):
        new_path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Snip Directory", str(self.current_snip_path))
        if new_path:
            self.current_snip_path = Path(new_path)
            self.current_path_label.setText(str(self.current_snip_path))

    def setup_save_preview_section(self, layout):
        save_group = QtWidgets.QGroupBox("Save")
        save_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {CONFIG['COLORS']['BORDER']};
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }}
        """)
        
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(6)
        
        self.save_flipbook_button = QtWidgets.QPushButton("Flipbook")
        self.save_flipbook_button.clicked.connect(self.verify_and_capture_flipbook)
        button_layout.addWidget(self.save_flipbook_button)
        
        self.save_snapshot_button = QtWidgets.QPushButton("Snapshot")
        self.save_snapshot_button.clicked.connect(self.save_snapshot)
        button_layout.addWidget(self.save_snapshot_button)
        
        snip_button = QtWidgets.QPushButton("Snip")
        snip_button.clicked.connect(self.save_clicked)
        snip_button.setStyleSheet(f"""
            background-color: {CONFIG['COLORS']['ACCENT']};
            color: {CONFIG['COLORS']['BUTTON_TEXT']};
            font-weight: bold;
            padding: 5px 10px;
            border-radius: 4px;
        """)
        button_layout.addWidget(snip_button)
        
        save_group.setLayout(button_layout)
        layout.addWidget(save_group)

    def setup_show_dialogs_checkbox(self, layout):
        self.show_dialogs_checkbox = QtWidgets.QCheckBox("Show information dialogs")
        self.show_dialogs_checkbox.setStyleSheet(f"""
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid {CONFIG['COLORS']['BORDER']};
        """)
        self.show_dialogs_checkbox.stateChanged.connect(self.save_dialog_preference)
        layout.addWidget(self.show_dialogs_checkbox)

        self.load_dialog_preference()

    def save_dialog_preference(self):
        preference = self.show_dialogs_checkbox.isChecked()
        try:
            pref_file = Path(hou.expandString('$HOUDINI_USER_PREF_DIR')) / 'snip_ui_preferences.json'
            with pref_file.open('w') as f:
                json.dump({'show_dialogs': preference}, f)
        except Exception as e:
            print(f"Error saving dialog preference: {e}")

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
            print(f"Error loading dialog preference: {e}")
            return True

    def closeEvent(self, event: QtGui.QCloseEvent):
        self.cleanup()
        self.save_dialog_preference()
        super().closeEvent(event)

    def populate_user_combo(self):
        users = self.get_users()
        self.user_combo.clear()
        self.user_combo.addItems(users)
        
        current_user = hou.getenv("USER", "deepak")
        if current_user in users:
            self.user_combo.setCurrentText(current_user)
        elif "deepak" in users:
            self.user_combo.setCurrentText("deepak")
        elif users:
            self.user_combo.setCurrentText(users[0])

    def get_users(self) -> List[str]:
        pyDump_path = Path(self.CORE_PATH)
        return [d.name for d in pyDump_path.iterdir() if d.is_dir()]

    def on_user_changed(self):
        self.update_snip_path()
        self.update_file_name()

    def update_snip_path(self):
        user = self.user_combo.currentText()
        self.current_snip_path = self.CORE_PATH / user / "Snips"
        if hasattr(self, 'current_path_label'):
            self.current_path_label.setText(str(self.current_snip_path))

    def populate_existing_values(self):
        user = self.user_combo.currentText()
        master_json_path = self.CORE_PATH / user / "Snips" / "descriptions" / "master.json"
        if master_json_path.exists():
            try:
                with open(master_json_path, 'r') as f:
                    data = json.load(f)
                
                types = set()
                names = set()
                sources = set()
                
                for item in data:
                    file_name = item.get('File Name', '')
                    parts = file_name.split('_')
                    if len(parts) >= 4:
                        types.add(parts[1])
                        names.add(parts[2])
                        sources.add(parts[3])
                
                current_type = self.Type.currentText()
                current_name = self.Name.currentText()
                current_source = self.Source.currentText()

                self.Type.clear()
                self.Type.addItems(sorted(types))
                self.Name.clear()
                self.Name.addItems(sorted(names))
                self.Source.clear()
                self.Source.addItems(sorted(sources))

                self.Type.setCurrentText(current_type if current_type in types else "")
                self.Name.setCurrentText(current_name if current_name in names else "")
                self.Source.setCurrentText(current_source if current_source in sources else "")

            except json.JSONDecodeError:
                logger.error(f"Error decoding JSON from {master_json_path}")
            except Exception as e:
                logger.error(f"Error populating existing values: {e}")
        else:
            logger.warning(f"Master JSON file not found: {master_json_path}")
            self.Type.clear()
            self.Name.clear()
            self.Source.clear()

    @staticmethod
    def to_camel_case(text):
        text = re.sub(r'[^\w\-_\. ]', '', text).replace(' ', '_')
        words = text.split('_')
        return words[0].lower() + ''.join(word.capitalize() for word in words[1:])

    def update_file_name(self):
        context = self.to_camel_case(self.Context.currentText())
        type_ = self.to_camel_case(self.Type.currentText())
        name = self.to_camel_case(self.Name.currentText())
        source = self.to_camel_case(self.Source.currentText())
        version = self.Version.text().zfill(2)

        file_name = f"{context}_{type_}_{name}_{source}_v{version}"
        file_name = self.sanitize_filename(file_name)
        self.file_name_label.setText(f"Snip Name: {file_name}")

        # Check if this Snip already exists and update previews if it does
        self.check_existing_snip(file_name)

    def check_existing_snip(self, file_name: str):
        user = self.user_combo.currentText()
        snip_path = self.CORE_PATH / user / "Snips" / f"{file_name}.uti"
        
        if snip_path.exists():
            # Snip exists, update previews
            self.update_existing_previews(file_name)
        else:
            # Snip doesn't exist, clear previews
            self.clear_previews()

    def update_existing_previews(self, file_name: str):
        user = self.user_combo.currentText()
        flipbook_base_folder = self.CORE_PATH / user / "Snips" / "preview" / "flipbook" / file_name
        snapshot_path = self.CORE_PATH / user / "Snips" / "preview" / "snapshot" / f"{file_name}.png"

        # Update flipbook preview
        if flipbook_base_folder.exists():
            self.current_flipbook_path = flipbook_base_folder / f"{file_name}.$F4.png"
            self.update_flipbook_preview()
        else:
            self.flipbook_preview.setText("No existing flipbook")

        # Update snapshot preview
        if snapshot_path.exists():
            self.update_snapshot_preview(snapshot_path)
        else:
            self.snapshot_preview.setText("No existing snapshot")

    def clear_previews(self):
        self.flipbook_preview.setText("No preview available")
        self.snapshot_preview.setText("No preview available")
        self.current_flipbook_path = None
        self.current_snapshot_path = None

    def sanitize_filename(self, filename: str) -> str:
        return re.sub(r'[^\w\-_\. ]', '', filename).replace(' ', '_')

    def verify_and_capture_flipbook(self):
        print("Flipbook button clicked")
        file_name = self.file_name_label.text().split(":")[1].strip()
        if any(not getattr(self, param).currentText() for param in ['Context', 'Type', 'Name', 'Source']):
            print("Error: Please fill in all filename parameters before saving a preview.")
            return
        if not file_name:
            print("Error: Please specify a filename before saving a preview.")
            return

        user = self.user_combo.currentText()
        flipbook_base_folder = self.CORE_PATH / user / "Snips" / "preview" / "flipbook"
        flipbook_sequence_folder = flipbook_base_folder / file_name
        flipbook_path = flipbook_sequence_folder / f"{file_name}.$F4.png"

        if flipbook_sequence_folder.exists() and any(str(file.name).startswith(file_name) for file in flipbook_sequence_folder.iterdir()):
            if self.show_dialogs_checkbox.isChecked():
                reply = QtWidgets.QMessageBox.question(self, "Overwrite Flipbook", 
                                                       "A flipbook with the same name already exists. Do you want to overwrite it?",
                                                       QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if reply == QtWidgets.QMessageBox.No:
                    return
            else:
                print("Existing flipbook will be overwritten (dialogs disabled)")
        
        if self.show_dialogs_checkbox.isChecked():
            message = "Save a flipbook of the current viewport?\n\nEnsure camera and timeframe are set correctly."
            reply = QtWidgets.QMessageBox.question(self, "Save Flipbook", message,
                                                   QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.Yes:
                self.capture_flipbook(flipbook_path)
        else:
            self.capture_flipbook(flipbook_path)

    def capture_flipbook(self, flipbook_path: Path):
        start_frame, end_frame = hou.playbar.playbackRange()
        
        start_frame = int(start_frame)
        end_frame = int(end_frame)
        
        if start_frame >= end_frame:
            print("Error: Start frame must be less than end frame.")
            return
        
        flipbook_sequence_folder = flipbook_path.parent
        flipbook_sequence_folder.mkdir(parents=True, exist_ok=True)
        
        try:
            hou.hipFile.save()
            scene_viewer = toolutils.sceneViewer()
            flipbook_settings = scene_viewer.flipbookSettings()
            flipbook_settings.frameRange((start_frame, end_frame))
            flipbook_settings.output(str(flipbook_path))
            
            progress = QtWidgets.QProgressDialog("Capturing Flipbook...", "Cancel", start_frame, end_frame, self)
            progress.setWindowModality(QtCore.Qt.WindowModal)
            progress.show()

            scene_viewer.flipbook(settings=flipbook_settings)
            
            progress.setValue(end_frame)
            QtWidgets.QApplication.processEvents()
            
            progress.close()
            
            if any(flipbook_sequence_folder.iterdir()):
                if self.show_dialogs_checkbox.isChecked():
                    QtWidgets.QMessageBox.information(self, "Flipbook Saved", f"Flipbook saved successfully at:\n{flipbook_sequence_folder}")
                print(f"Flipbook saved successfully at: {flipbook_sequence_folder}")
                
                self.create_gif_from_flipbook(flipbook_sequence_folder, flipbook_path)
                self.flipbook_saved = True
            else:
                if self.show_dialogs_checkbox.isChecked():
                    QtWidgets.QMessageBox.warning(self, "Flipbook Not Saved", "No flipbook files were created. The operation may have been cancelled.")
                print("No flipbook files were created. The operation may have been cancelled.")
        except Exception as e:
            print(f"Error capturing flipbook: {e}")
            if self.show_dialogs_checkbox.isChecked():
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to capture flipbook: {e}")

    def create_gif_from_flipbook(self, flipbook_folder: Path, flipbook_path: Path):
        try:
            png_files = sorted(flipbook_folder.glob('*.png'))
            
            if not png_files:
                print("No PNG files found in the flipbook folder.")
                return
            
            images = []
            for png_file in png_files:
                img = Image.open(png_file)
                img.thumbnail((200, 150), Image.LANCZOS)
                images.append(img)
            
            images = images[:50]
            
            gif_path = flipbook_path.with_suffix('.gif')
            images[0].save(gif_path, save_all=True, append_images=images[1:], duration=100, loop=0)
            
            print(f"GIF created successfully at: {gif_path}")
            if self.show_dialogs_checkbox.isChecked():
                QtWidgets.QMessageBox.information(self, "GIF Created", f"GIF created successfully at:\n{gif_path}")
            
            self.current_flipbook_path = flipbook_path
            self.update_flipbook_preview()
        
        except Exception as e:
            print(f"Error creating GIF: {e}")
            if self.show_dialogs_checkbox.isChecked():
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to create GIF: {e}")

    def update_flipbook_preview(self):
        if not self.current_flipbook_path:
            self.flipbook_preview.setText("No preview available")
            return

        if self.preview_mode == "png":
            self.update_png_preview()
        else:
            self.update_gif_preview()

    def update_gif_preview(self):
        gif_path = self.current_flipbook_path.with_suffix('.gif')
        if gif_path.exists():
            movie = QMovie(str(gif_path))
            movie.setScaledSize(self.flipbook_preview.size())
            self.flipbook_preview.setMovie(movie)
            movie.start()
        else:
            self.flipbook_preview.setText("No GIF preview available")

    def update_png_preview(self):
        if self.current_flipbook_path:
            png_files = sorted(self.current_flipbook_path.parent.glob('*.png'))
            if png_files:
                self.png_files = png_files
                self.current_frame = 0
                self.update_png_frame()
                self.png_timer.start(100)
            else:
                self.flipbook_preview.setText("No PNG sequence available")
        else:
            self.flipbook_preview.setText("No preview available")

    def update_png_frame(self):
        if self.png_files:
            pixmap = QPixmap(str(self.png_files[self.current_frame]))
            pixmap = pixmap.scaled(self.flipbook_preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.flipbook_preview.setPixmap(pixmap)
            self.current_frame = (self.current_frame + 1) % len(self.png_files)

    def toggle_preview_mode(self, button):
        if button == self.png_radio:
            self.preview_mode = "png"
            self.png_timer.start(100)
        else:
            self.preview_mode = "gif"
            self.png_timer.stop()
        self.update_flipbook_preview()

    def update_snapshot_preview(self, snapshot_path: Path):
        if snapshot_path and snapshot_path.exists():
            pixmap = QPixmap(str(snapshot_path))
            pixmap = pixmap.scaled(self.snapshot_preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.snapshot_preview.setPixmap(pixmap)
            self.current_snapshot_path = snapshot_path
        else:
            self.snapshot_preview.setText("No snapshot available")
            self.current_snapshot_path = None

    def save_snapshot(self):
        print("Snapshot button clicked")
        file_name = self.file_name_label.text().split(":")[1].strip()
        if not file_name:
            print("Error: Please specify a filename before saving a snapshot.")
            return
        
        user = self.user_combo.currentText()
        snapshot_dir = self.CORE_PATH / user / "Snips" / "preview" / "snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        screenshot_path = snapshot_dir / f"{file_name}.png"
        
        if screenshot_path.exists():
            if self.show_dialogs_checkbox.isChecked():
                reply = QtWidgets.QMessageBox.question(self, "Overwrite Snapshot", 
                                                       "A snapshot with the same name already exists. Do you want to overwrite it?",
                                                       QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if reply == QtWidgets.QMessageBox.No:
                    return
            else:
                print("Existing snapshot will be overwritten (dialogs disabled)")
        
        if self.show_dialogs_checkbox.isChecked():
            message = "Capture a snapshot of your node network for quick reference?"
            reply = QtWidgets.QMessageBox.question(self, "Save Snapshot", message, 
                                                   QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.Yes:
                QtCore.QTimer.singleShot(100, lambda: self.perform_snapshot(screenshot_path))
        else:
            QtCore.QTimer.singleShot(100, lambda: self.perform_snapshot(screenshot_path))

    def perform_snapshot(self, screenshot_path: Path):
        try:
            self.hide()
            main_window = hou.qt.mainWindow()
            main_window.raise_()
            main_window.activateWindow()
            QtCore.QTimer.singleShot(500, lambda: self.capture_screenshot(screenshot_path))
        except Exception as e:
            print(f"Error preparing for screenshot: {e}")
            if self.show_dialogs_checkbox.isChecked():
                QtWidgets.QMessageBox.critical(self, "Error", f"Error preparing for screenshot: {e}")
            self.show()

    def capture_screenshot(self, screenshot_path: Path):
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
            
            print(f"Snapshot saved successfully at: {screenshot_path}")
            self.update_snapshot_preview(screenshot_path)
            if self.show_dialogs_checkbox.isChecked():
                QtWidgets.QMessageBox.information(self, "Snapshot Saved", f"Snapshot saved successfully at:\n{screenshot_path}")
            self.snapshot_saved = True
        except subprocess.CalledProcessError as e:
            print(f"Error capturing screenshot: {e}")
            if self.show_dialogs_checkbox.isChecked():
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to capture screenshot: {e}")
        except Exception as e:
            print(f"Unexpected error capturing screenshot: {e}")
            if self.show_dialogs_checkbox.isChecked():
                QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error capturing screenshot: {e}")
        finally:
            self.show()

    def create_directories(self):
        user = self.user_combo.currentText()
        user_dir = self.CORE_PATH / user
        snips_dir = user_dir / 'Snips'
        descriptions_dir = snips_dir / 'descriptions'
        preview_dir = snips_dir / 'preview'
        flipbook_dir = preview_dir / 'flipbook'
        snapshot_dir = preview_dir / 'snapshot'

        for directory in [self.CORE_PATH, user_dir, snips_dir, descriptions_dir, preview_dir, flipbook_dir, snapshot_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def calculate_size(self, file_path: Path) -> int:
        return file_path.stat().st_size if file_path.exists() else 0

    def update_master_json(self, file_name: Path, snapshot_path: Path):
        user = self.user_combo.currentText()
        master_json_path = self.CORE_PATH / user / "Snips" / "descriptions" / "master.json"
        
        master_json_path.parent.mkdir(parents=True, exist_ok=True)

        master_data = []
        if master_json_path.exists():
            try:
                with open(master_json_path, 'r') as master_file:
                    master_data = json.load(master_file)
            except json.JSONDecodeError:
                logger.error(f"Error decoding JSON from {master_json_path}")
            except Exception as e:
                logger.error(f"Error reading master JSON: {e}")

        base_file_name = file_name.stem
        master_data = [entry for entry in master_data if entry["File Name"] != base_file_name]

        new_entry = {
            "Path": str(self.CORE_PATH / user),
            "User": user,
            "File Name": base_file_name,
            "Ext": "uti",
            "Flipbook": f"/preview/flipbook/{base_file_name}.$F4.png",
            "Snap": f"/preview/snapshot/{base_file_name}.png",
            "Summary": self.description_text.toPlainText(),
            "Keywords": self.generate_keywords(),
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Time": datetime.now().strftime("%H:%M:%S"),
            "Size": self.calculate_size(file_name),
        }
        master_data.insert(0, new_entry)

        try:
            with open(master_json_path, 'w') as master_file:
                json.dump(master_data, master_file, indent=4)
        except Exception as e:
            logger.error(f"Error writing to master JSON: {e}")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to update master JSON: {e}")

    def generate_keywords(self):
        keywords = []
        summary = self.description_text.toPlainText().lower()
        # Add some basic keywords based on the summary
        keywords.extend(word for word in summary.split() if len(word) > 3)
        # Add keywords based on the file name components
        keywords.extend([
            self.Context.currentText().lower(),
            self.Type.currentText().lower(),
            self.Name.currentText().lower(),
            self.Source.currentText().lower()
        ])
        # Remove duplicates and sort
        return sorted(set(keywords))

    def save_selected_nodes(self, final_path: Path, file_name: str):
        ext = '.uti'
        path = final_path.with_suffix(ext)

        nodes = hou.selectedNodes()
        if not nodes:
            raise ValueError("Nothing selected!")

        parent = nodes[0].parent()

        if not all(node.parent() == parent for node in nodes):
            raise ValueError("Nodes must have the same parent.")

        if path.exists():
            if self.show_dialogs_checkbox.isChecked():
                reply = QtWidgets.QMessageBox.question(self, "Overwrite File", 
                                                       "A file with the same name already exists. Do you want to overwrite it?",
                                                       QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if reply == QtWidgets.QMessageBox.No:
                    return
            else:
                logger.warning(f"Overwriting existing file: {path}")

        parent.saveItemsToFile(nodes, str(path))
        logger.info(f"File successfully saved at: {path}")

    def save_clicked(self):
        print("Save button clicked")
        
        # Get the file name
        file_name = self.file_name_label.text().split(":")[1].strip()
        if not file_name:
            print("Error: Please specify a filename before saving.")
            return

        # Create necessary directories
        self.create_directories()

        # Get the user and set up paths
        user = self.user_combo.currentText()
        snip_path = self.CORE_PATH / user / "Snips" / f"{file_name}.uti"
        snapshot_path = self.CORE_PATH / user / "Snips" / "preview" / "snapshot" / f"{file_name}.png"

        # Save the snip file
        try:
            self.save_selected_nodes(snip_path, file_name)
            print(f"Snip saved successfully at: {snip_path}")

            # Update the master JSON
            self.update_master_json(snip_path, snapshot_path)

            # Show success message
            if self.show_dialogs_checkbox.isChecked():
                QtWidgets.QMessageBox.information(self, "Snip Saved", f"Snip saved successfully at:\n{snip_path}")

            # Emit the snip_created signal
            self.snip_created.emit()

            self.snip_saved = True

            # Close the UI
            self.close()

        except Exception as e:
            error_message = f"Error saving snip: {e}"
            print(error_message)
            if self.show_dialogs_checkbox.isChecked():
                QtWidgets.QMessageBox.critical(self, "Error", error_message)

        # Don't call populate_existing_values() here as it resets the UI
        # Instead, we'll update only the necessary parts
        self.update_file_name()

    def cleanup(self):
        if not self.snip_saved:
            if self.flipbook_saved:
                self.delete_flipbook()
            if self.snapshot_saved:
                self.delete_snapshot()

    def delete_flipbook(self):
        if self.current_flipbook_path:
            flipbook_folder = self.current_flipbook_path.parent
            try:
                for file in flipbook_folder.glob('*'):
                    file.unlink()
                flipbook_folder.rmdir()
                print(f"Deleted flipbook folder: {flipbook_folder}")
            except Exception as e:
                print(f"Error deleting flipbook folder: {e}")

    def delete_snapshot(self):
        if self.current_snapshot_path and self.current_snapshot_path.exists():
            try:
                self.current_snapshot_path.unlink()
                print(f"Deleted snapshot: {self.current_snapshot_path}")
            except Exception as e:
                print(f"Error deleting snapshot: {e}")

    def closeEvent(self, event: QtGui.QCloseEvent):
        self.cleanup()
        self.save_dialog_preference()
        super().closeEvent(event)

def create_write_snip_ui(callback: Optional[callable] = None):
    dialog = WriteSnipUI()
    if callback:
        dialog.snip_created.connect(callback)
    dialog.show()
    return dialog

if __name__ == "__main__":
    create_write_snip_ui()