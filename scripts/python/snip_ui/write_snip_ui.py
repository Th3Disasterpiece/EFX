import os
import json
from datetime import datetime
import hou
from PySide2 import QtWidgets, QtCore, QtGui
import toolutils
import re
import subprocess


class WriteSnipUI(QtWidgets.QWidget):
    lib_path = hou.getenv("EFX")
    CORE_PATH = f'{lib_path}/pyDump'

    def __init__(self):
        super(WriteSnipUI, self).__init__()

        # Initialize the UI window
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Write Snip UI")
        self.setGeometry(200, 200, 400, 600)  # Increased the height to accommodate new features

        # Create and initialize UI elements
        self.init_ui()

        # Connect the destroyed signal to the close method
        self.destroyed.connect(self.close)

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout()

        # Select Save Path Button
        select_path_layout = QtWidgets.QHBoxLayout()
        self.save_path_label = QtWidgets.QLabel("Save Path:")
        self.save_path_label.setFont(QtGui.QFont("Arial", weight=QtGui.QFont.Bold))
        select_path_layout.addWidget(self.save_path_label)
        self.current_path_label = QtWidgets.QLabel(self.CORE_PATH)
        self.current_path_label.setStyleSheet("color: #00FF00;")  
        select_path_layout.addWidget(self.current_path_label)
        select_path_button = QtWidgets.QPushButton("Change Path", self)
        select_path_button.clicked.connect(self.select_save_path)
        select_path_layout.addWidget(select_path_button)
        layout.addLayout(select_path_layout)

        layout.addSpacing(10)

        # File Name Label
        self.file_name_label = QtWidgets.QLabel("File Name:")
        self.file_name_label.setFont(QtGui.QFont("Arial", weight=QtGui.QFont.Bold))
        self.file_name_label.setStyleSheet("color: #FFFF00;")  
        self.file_name_label.setToolTip("Enter the desired file name. Use Context, Type, Name, Source, and Version parameters to customize it.")
        layout.addWidget(self.file_name_label)
        layout.addSpacing(10)  

        # Context
        context_layout = self.create_input_layout("Context:", ["SOP", "OBJ", "ROP", "SHOP", "Y DOP", "COP", "LOP", "VOP", "CHOP", "VOPNET", "TOP"], default_value="SOP", key="Context")
        context_layout.itemAt(0).widget().setToolTip("Enter the context of nodes saved in, e.g., SOP, OBJ, SHOP, etc.")
        layout.addLayout(context_layout)

        # Type
        type_layout = self.create_input_layout("Type:", self.get_existing_values('Type'), key="Type")
        type_layout.itemAt(0).widget().setToolTip("Specify the general purpose of the node, e.g., pop, pyro, flip, trick, vex, prep, rnd, etc.")
        layout.addLayout(type_layout)

        # Name
        name_layout = self.create_input_layout("Name:", self.get_existing_values('Name'), key="Name")
        name_layout.itemAt(0).widget().setToolTip("Add a unique name for the snippet to be saved, e.g., smokeBasic, explosionSetup, waterfall, tornado, etc.")
        layout.addLayout(name_layout)

        # Source
        source_layout = self.create_input_layout("Source:", self.get_existing_values('Source'), key="Source")
        source_layout.itemAt(0).widget().setToolTip("Provide information about the source of the snippet being saved, e.g., your initials for custom setups, or the name of the creator if inspired by someone else.")
        layout.addLayout(source_layout)

        # Version Input
        version_layout = self.create_version_layout("Version:", default_value="1", key="Version")
        version_layout.itemAt(0).widget().setToolTip("Specify the version of the snippet being saved.")
        layout.addLayout(version_layout)

        # Description Section
        description_group = QtWidgets.QGroupBox("Description:")
        description_layout = self.create_description_layout()
        description_group.setLayout(description_layout)
        description_group.setToolTip("Enter a summary and keywords to describe the snippet.")
        layout.addWidget(description_group)

        # Save Preview Section
        save_preview_group = QtWidgets.QGroupBox("Save Preview")
        save_preview_layout = self.create_save_preview_layout()
        save_preview_group.setLayout(save_preview_layout)
        save_preview_group.setToolTip("Options to save a snapshot or a flipbook of the scene for preview reference.")
        layout.addWidget(save_preview_group)

        # Save Button
        save_button = QtWidgets.QPushButton("Save Snip", self)  # Change button text to "Save Snip"
        save_button.clicked.connect(self.save_clicked)
        save_button.setToolTip("Save the snip with the specified file name, including selected nodes and metadata.")
        save_button.setStyleSheet("background-color: #FFA500; font-size: 18px; padding: 10px;")  # Change the color, font size, and padding here
        layout.addWidget(save_button)

        self.setLayout(layout)

        # Ensure the necessary directories exist
        self.create_directories()

        # Connect the checkbox state change to the method that enables/disables Save Preview options
        self.save_preview_checkbox.stateChanged.connect(self.toggle_save_preview_options)

        # Update the file name label with the default file name based on initial inputs
        self.update_file_name()

    def toggle_save_preview_options(self, state):
        enabled = state == QtCore.Qt.Checked
        for button in [self.save_flipbook_button, self.save_snapshot_button]:
            button.setEnabled(enabled)

    def create_save_preview_layout(self):
        layout = QtWidgets.QHBoxLayout()

        # Checkbox to enable/disable Save Preview
        self.save_preview_checkbox = QtWidgets.QCheckBox("Enable Save Preview")
        layout.addWidget(self.save_preview_checkbox)

        # Button to save flipbook
        self.save_flipbook_button = QtWidgets.QPushButton("Save Flipbook")
        self.save_flipbook_button.setEnabled(False)  # Initially disabled
        self.save_flipbook_button.clicked.connect(self.verify_and_capture_flipbook)
        self.save_flipbook_button.setToolTip("This will save the flipbook of the viewport, and the flipbook will pick the settings from the flipbook default options")
        layout.addWidget(self.save_flipbook_button)

        # Button to save snapshot
        self.save_snapshot_button = QtWidgets.QPushButton("Save Snapshot")
        self.save_snapshot_button.setEnabled(False)  # Initially disabled
        self.save_snapshot_button.clicked.connect(self.save_snapshot)  # Connect to the save_snapshot method
        self.save_snapshot_button.setToolTip("This will save a snapshot of the viewport with the current camera view")
        layout.addWidget(self.save_snapshot_button)

        return layout
    

    def select_save_path(self):
        options = QtWidgets.QFileDialog.Options()
        selected_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Save Path", QtCore.QDir.homePath(), options=options)
        if selected_dir:
            # Update the save path label or any other necessary action
            self.CORE_PATH = selected_dir
            self.current_path_label.setText(selected_dir)
            print("Selected directory:", selected_dir)
            # Update the file name label with the new path
            self.update_file_name()


    def verify_and_capture_flipbook(self):
        # Extract File Name from the UI
        file_name = self.file_name_label.text().split(":")[1].strip()

        # Check if any filename parameters are empty
        if any(not getattr(self, param).text() for param in ['Context', 'Type', 'Name', 'Source']):
            hou.ui.displayMessage("Please fill in all filename parameters before saving a preview.", title="Error", severity=hou.severityType.Error)
            return

        # Check if File Name is empty
        if not file_name:
            # Display a message to complete the filename first
            hou.ui.displayMessage("Please specify a filename before saving a preview.", title="Error", severity=hou.severityType.Error)
            return

        # Check if the output directory already exists in the master JSON file
        flipbook_exists = self.check_flipbook_existence(file_name)
        print(f"Flipbook exists: {flipbook_exists}")  # Add this line for debugging

        # If flipbook already exists, bring a popup window
        if flipbook_exists:
            hou.ui.displayMessage("A flipbook with the same name already exists. Please choose a different name.",
                                title="Warning", severity=hou.severityType.Warning)
            return

        # Proceed with flipbook capture
        print("Capturing flipbook...")  # Add this line for debugging
        self.capture_flipbook()

        # Display a notification about the successful flipbook save and instructions to save the snippet
        hou.ui.displayMessage("Flipbook saved successfully. Please save the snippet to disk.", title="Flipbook Saved", severity=hou.severityType.Message)



    def check_flipbook_existence(self, file_name):
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        flipbook_folder = os.path.join(user_dir, "preview", "flipbook")
        flipbook_file_path = os.path.join(flipbook_folder, f"{file_name}.$F4.png")

        # Check if the flipbook file exists
        if os.path.exists(flipbook_file_path):
            print(f"Found existing flipbook: {flipbook_file_path}")  # For debugging
            return True
        else:
            print("No existing flipbook found")  # For debugging
            return False


    def capture_flipbook(self):
        # Get the current frame range from the Houdini timeline bar
        start_frame, end_frame = hou.playbar.playbackRange()

        # Extract File Name from the UI
        file_name = self.file_name_label.text().split(":")[1].strip()

        # Check if File Name is empty
        if not file_name:
            # Display a message to complete the filename first using Houdini's default pop-up window
            hou.ui.displayMessage("Please specify a filename before saving a preview.", severity=hou.severityType.Error)
            return

        flipbook_folder = os.path.join(self.CORE_PATH, hou.getenv('USER'), "preview", "flipbook", file_name)

        # Check if the output directory already exists
        if os.path.exists(flipbook_folder):
            # Prompt the user with a confirmation dialog using Houdini's displayConfirmation function
            if not hou.ui.displayConfirmation("A flipbook with the same name already exists. Do you want to overwrite?", suppress=hou.confirmType.OverwriteFile):
                return  # User chose not to overwrite, so return without proceeding with flipbook capture

        # If no existing files or user chose to overwrite, proceed with flipbook capture
        if not os.path.exists(flipbook_folder):
            os.makedirs(flipbook_folder)

        hou.hipFile.save()  # Save the current Houdini scene

        # Create a scene viewer
        scene_viewer = toolutils.sceneViewer()

        # Get the flipbook settings from the scene viewer
        flipbook_settings = scene_viewer.flipbookSettings()

        # Set the frame range as a list containing start and end frame
        flipbook_settings.frameRange([start_frame, end_frame])

        # Set the output directory with the name derived from File Name
        flipbook_settings.output(os.path.join(flipbook_folder, f"{file_name}.$F4.png"))

        # Trigger the flipbook rendering
        scene_viewer.flipbook(None, flipbook_settings)

    def save_snapshot(self):
        # Extract File Name from the UI
        file_name = self.file_name_label.text().split(":")[1].strip()

        # Check if any filename parameters are empty
        if any(not getattr(self, param).text() for param in ['Context', 'Type', 'Name', 'Source']):
            hou.ui.displayMessage("Please fill in all filename parameters before saving a snapshot.", title="Error", severity=hou.severityType.Error)
            return

        # Check if File Name is empty
        if not file_name:
            # Display a message to complete the filename first
            hou.ui.displayMessage("Please specify a filename before saving a snapshot.", title="Error", severity=hou.severityType.Error)
            return

        # Get the path to save the snapshot
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        snapshot_dir = os.path.join(user_dir, "preview", "snapshot")
        if not os.path.exists(snapshot_dir):
            os.makedirs(snapshot_dir)

        # Define the file path for the screenshot
        screenshot_path = os.path.join(snapshot_dir, f"{file_name}.png")

        # Check if snapshot already exists
        if os.path.exists(screenshot_path):
            # Display a warning message
            if not hou.ui.displayConfirmation("A snapshot with the same name already exists. Do you want to overwrite it?", suppress=hou.confirmType.OverwriteFile):
                return  # User chose not to overwrite, so return without saving

        # Capture the screenshot using the subprocess module
        try:
            subprocess.run(['screencapture', '-i', screenshot_path])
            # Inform the user that the screenshot has been captured
            # hou.ui.displayMessage("Screenshot captured successfully.", title="Screenshot Saved", severity=hou.severityType.Message)
        except Exception as e:
            # Inform the user if there was an error capturing the screenshot
            hou.ui.displayMessage(f"Error capturing screenshot: {e}", title="Error", severity=hou.severityType.Error)

        # Update master JSON file with the correct file path
        snapshot_path = os.path.join('Snapshot', f"{file_name}.png")
        #self.update_master_json(screenshot_path, snapshot_path)

        hou.ui.displayMessage(f"Snapshot saved successfully at: {screenshot_path}", title="Snapshot Saved", severity=hou.severityType.Message)


    def create_directories(self):
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        descriptions_dir = os.path.join(user_dir, 'descriptions')
        preview_dir = os.path.join(user_dir, 'preview')  # Directory for previews
        flipbook_dir = os.path.join(preview_dir, 'flipbook')  # Directory for flipbook previews
        snapshot_dir = os.path.join(preview_dir, 'snapshot')  # Directory for snapshot previews

        # Ensure the CORE_PATH directory exists
        if not os.path.exists(self.CORE_PATH):
            os.makedirs(self.CORE_PATH)

        # Ensure the user directory exists
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)

        # Ensure the descriptions directory exists
        if not os.path.exists(descriptions_dir):
            os.makedirs(descriptions_dir)

        # Ensure the preview directory exists
        if not os.path.exists(preview_dir):
            os.makedirs(preview_dir)

        # Ensure the flipbook directory exists
        if not os.path.exists(flipbook_dir):
            os.makedirs(flipbook_dir)

        # Ensure the snapshot directory exists
        if not os.path.exists(snapshot_dir):
            os.makedirs(snapshot_dir)




    def create_description_layout(self):
        description_layout = QtWidgets.QVBoxLayout()

        # Summary
        summary_label = QtWidgets.QLabel("Summary:")
        summary_text_edit = QtWidgets.QTextEdit()
        description_layout.addWidget(summary_label)
        description_layout.addWidget(summary_text_edit)

        # Keywords
        keywords_label = QtWidgets.QLabel("Keywords:\n(Enter each keyword on a new line)")
        keywords_text_edit = QtWidgets.QTextEdit()
        description_layout.addWidget(keywords_label)
        description_layout.addWidget(keywords_text_edit)

        setattr(self, "Summary", summary_text_edit)
        setattr(self, "Keywords", keywords_text_edit)

        return description_layout


    def create_input_layout(self, label_text, dropdown_items=None, default_value="", key=""):
        def validate_input(text):
            # Remove any non-word characters except whitespace and underscores
            return re.sub(r'[^\w\s]', '', text).replace('_', '')

        label = QtWidgets.QLabel(label_text)
        input_line_edit = QtWidgets.QLineEdit(default_value)
        dropdown = QtWidgets.QComboBox()

        if dropdown_items:
            dropdown.addItems(dropdown_items)
            dropdown.currentIndexChanged.connect(lambda index, line_edit=input_line_edit, key=key: self.auto_fill_line_edit(index, line_edit, dropdown, key))

        input_line_edit.textChanged.connect(self.update_file_name)
        input_line_edit.textChanged.connect(lambda text, line_edit=input_line_edit: line_edit.setText(validate_input(text)))

        sub_layout = QtWidgets.QHBoxLayout()
        sub_layout.addWidget(label)
        sub_layout.addWidget(input_line_edit)
        if dropdown_items:
            sub_layout.addWidget(dropdown)

        setattr(self, key, input_line_edit)

        return sub_layout


    def create_input_layout_with_dropdown(self, label_text, dropdown_items=None, key=""):
        label = QtWidgets.QLabel(label_text)
        input_line_edit = QtWidgets.QLineEdit()
        dropdown = QtWidgets.QComboBox()

        if dropdown_items:
            dropdown.addItems(dropdown_items)

        input_line_edit.textChanged.connect(lambda text, dropdown=dropdown: self.filter_dropdown(text, dropdown, dropdown_items))
        dropdown.currentIndexChanged.connect(lambda index, line_edit=input_line_edit, dropdown=dropdown, key=key: self.auto_fill_line_edit(index, line_edit, dropdown, key))

        sub_layout = QtWidgets.QHBoxLayout()
        sub_layout.addWidget(label)
        sub_layout.addWidget(input_line_edit)
        sub_layout.addWidget(dropdown)

        setattr(self, key, input_line_edit)

        return sub_layout

    def filter_dropdown(self, text, dropdown, all_items):
        dropdown.clear()

        matching_items = [item for item in all_items if text.lower() in item.lower()]
        dropdown.addItems(matching_items)

    def create_version_layout(self, label_text, default_value="", key=""):
        label = QtWidgets.QLabel(label_text)
        version_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        version_input = QtWidgets.QLineEdit(default_value)
        version_checkbox = QtWidgets.QCheckBox("Use Slider")
        version_checkbox.setChecked(True)

        # Set the range and tick interval for the slider
        version_slider.setRange(1, 10)
        version_slider.setTickInterval(1)  # Set the interval between ticks to 1
        version_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)  # Display ticks below the slider

        # Connect signals to update the file name
        version_slider.valueChanged.connect(lambda value, input_field=version_input: input_field.setText(str(value).zfill(2)))
        version_input.textChanged.connect(lambda text, slider=version_slider: slider.setValue(int(text)) if text.isdigit() and 1 <= int(text) <= 10 else 1)
        version_slider.valueChanged.connect(self.update_file_name)
        version_input.textChanged.connect(self.update_file_name)

        version_checkbox.stateChanged.connect(lambda state, slider=version_slider, input_field=version_input: self.toggle_version_input(state, slider, input_field))

        sub_layout = QtWidgets.QHBoxLayout()
        sub_layout.addWidget(label)
        sub_layout.addWidget(version_slider)
        sub_layout.addWidget(version_input)
        sub_layout.addWidget(version_checkbox)

        setattr(self, key + "_checkbox", version_checkbox)
        setattr(self, key + "_input", version_input)

        return sub_layout


    def toggle_version_input(self, state, slider, input_field):
        slider.setEnabled(state == QtCore.Qt.Checked)
        input_field.setEnabled(state != QtCore.Qt.Checked)
        self.update_file_name()

    def auto_fill_line_edit(self, index, line_edit, dropdown, key):
        line_edit.blockSignals(True)  # Block signals temporarily to avoid recursion

        selected_text = dropdown.itemText(index)
        line_edit.setText(selected_text)

        line_edit.blockSignals(False)  # Unblock signals after setting the text

        setattr(self, key, line_edit)
        self.update_file_name()

    def update_file_name(self):
        def capitalize_after_space(text):
            result = ""
            capitalize_next = False  # Start with False to allow the start of the field to be lowercase
            for char in text:
                if char.isspace():
                    capitalize_next = True
                elif capitalize_next:
                    result += char.upper()
                    capitalize_next = False
                else:
                    result += char
            return result

        context = capitalize_after_space(self.Context.text()) if hasattr(self, 'Context') and self.Context.text() else ''
        type_ = capitalize_after_space(self.Type.text()) if hasattr(self, 'Type') and self.Type.text() else ''
        name = capitalize_after_space(self.Name.text()) if hasattr(self, 'Name') and self.Name.text() else ''
        source = capitalize_after_space(self.Source.text()) if hasattr(self, 'Source') and self.Source.text() else ''

        version_checkbox = self.Version_checkbox
        version_input = self.Version_input

        if version_checkbox is not None and version_input is not None:
            version_text = version_input.text()
            if version_checkbox.isChecked():
                version = version_text.zfill(2)  # Pad with leading zeros if it's a single digit
            else:
                version = "{:02d}".format(int(version_text))
            file_name = f"{context}_{type_}_{name}_{source}_v{version}"
            file_name = file_name.replace(" ", "")  # Remove spaces from the file name
            self.file_name_label.setText(f"File Name: {file_name}")


    def save_clicked(self):
        # Check if any of the important fields are empty
        if not (self.Context.text() and self.Type.text() and self.Name.text() and self.Source.text()):
            # Display a Houdini UI message prompting the user to fill in the important fields
            hou.ui.displayMessage("Please fill in all filename parameters (Context, Type, Name, Source) before saving.", title="Error", severity=hou.severityType.Error)
            return  # Exit the method without saving

        # Get the filename from the UI
        file_name = self.file_name_label.text().split(":")[1].strip()

        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        final_path = os.path.join(user_dir, file_name)

        try:
            # Save selected nodes with the constructed fileName
            self.save_selected_nodes(final_path, file_name)

            # Save description data as JSON
            # self.save_description_data(final_path)

            # Define the snapshot path
            snapshot_path = os.path.join('snapshot', f"{file_name}.png")

            # Update master JSON file
            self.update_master_json(final_path, snapshot_path)

            print("File successfully saved.")
            self.close()  # Close the window on successful save
        except Exception as e:
            print(f"Error: {e}")

    def save_selected_nodes(self, final_path, file_name):
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        ext = '.uti'

        if not os.path.exists(user_dir):
            os.makedirs(user_dir)

        if len(hou.selectedNodes()) < 1:
            hou.ui.displayMessage("Nothing selected!")
        else:
            path = os.path.join(user_dir, file_name + ext)  # Add the .uti extension
            nodes = hou.selectedNodes()
            parent = nodes[0].parent()

            if not all(node.parent() == parent for node in nodes):
                raise Exception("Nodes must have the same parent.")

            if os.path.exists(path):
                # Ask for confirmation before overwriting
                if not hou.ui.displayConfirmation("A file with the same name already exists. Do you want to overwrite it?", suppress=hou.confirmType.OverwriteFile):
                    return  # User chose not to overwrite, so return without saving

            parent.saveItemsToFile(nodes, path)
            
            # Print the file path where it's successfully saved
            print(f"File successfully saved at: {path}")



    def calculate_size(self, file_path):
        if os.path.exists(file_path):
            return os.path.getsize(file_path)
        return 0

    # Update master JSON file
    def update_master_json(self, file_name, snapshot_path):
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        core = os.path.join(user_dir, 'descriptions')
        master_json_path = os.path.join(core, 'master.json')

        if not os.path.exists(core):
            os.makedirs(core)

        # Read existing master JSON file if it exists
        master_data = []
        if os.path.exists(master_json_path):
            with open(master_json_path, 'r') as master_file:
                master_data = json.load(master_file)

        # Remove old entries with the exact same name and path, if they exist
        master_data = [entry for entry in master_data if entry["File Name"] != os.path.basename(file_name) or entry["Path"] != os.path.dirname(file_name)]

        # Append the new file details to the master JSON data
        master_data.insert(0, {
            "Path": os.path.dirname(file_name),
            "User" : f"{hou.getenv('USER')}",
            "File Name": os.path.basename(file_name),
            "Ext": "uti",
            "Flipbook": f"/preview/flipbook/{os.path.basename(file_name)}.$F4.png",
            "Snap": f"/preview/{snapshot_path}",
            "Summary": self.Summary.toPlainText(),
            "Keywords": self.Keywords.toPlainText().splitlines(),
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Time": datetime.now().strftime("%H:%M:%S"),
            "Size": self.calculate_size(os.path.join(core, file_name + '.json')),
        })

        # Update master JSON file
        with open(master_json_path, 'w') as master_file:
            json.dump(master_data, master_file, indent=4)

        
    def get_existing_values(self, field):
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        ext = '.uti'

        existing_values = set()

        # Ensure the user directory exists
        if not os.path.exists(user_dir):
            return []

        for file_name in os.listdir(user_dir):
            if file_name.endswith(ext):
                parts = file_name.replace(ext, '').split('_')
                if len(parts) >= 4:
                    if field == 'Type':
                        existing_values.add(parts[1])
                    elif field == 'Name':
                        existing_values.add(parts[2])
                    elif field == 'Source':
                        existing_values.add(parts[3])

        return list(existing_values)


if __name__ == "__main__":
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])

    # Create an instance of WriteSnipUI
    write_snip_ui_instance = WriteSnipUI()

    # Show the UI
    write_snip_ui_instance.show()

    try:
        # Run the application event loop
        while True:
            if not app.processEvents(QtCore.QEventLoop.AllEvents):
                break
    except Exception as e:
        print(f"Error: {e}")

    # Close the application when the loop exits
    app.quit()
