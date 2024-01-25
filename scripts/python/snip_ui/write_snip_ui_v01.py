import os
import json
from datetime import datetime
import hou
from PySide2 import QtWidgets, QtCore
from .config import DEFAULT_VERSION
from .logging_utils import logger

class WriteSnipUI(QtWidgets.QWidget):
    lib_path = hou.getenv("EFX")
    # CORE_PATH = f'{lib_path}/pyDump'
    # CORE_PATH = 

    def __init__(self):
        super(WriteSnipUI, self).__init__()

        # Initialize the UI window
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Write Snip UI")
        self.setGeometry(200, 200, 400, 500)  # Increased the height to accommodate new features

        # Create and initialize UI elements
        self.init_ui()

        # Connect the destroyed signal to the close method
        self.destroyed.connect(self.close)

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout()

        # Context
        context_layout = self.create_input_layout("Context:", ["SOP", "OBJ", "ROP", "SHOP", "Y DOP", "COP", "LOP", "VOP", "CHOP", "VOPNET", "TOP"], default_value="SOP", key="Context")
        layout.addLayout(context_layout)

        # Type
        type_layout = self.create_input_layout("Type:", self.get_existing_values('Type'), key="Type")
        layout.addLayout(type_layout)

        # Name
        name_layout = self.create_input_layout("Name:", self.get_existing_values('Name'), key="Name")
        layout.addLayout(name_layout)

        # Source
        source_layout = self.create_input_layout("Source:", self.get_existing_values('Source'), key="Source")
        layout.addLayout(source_layout)

        # Version Input
        version_layout = self.create_version_layout("Version:", default_value="1", key="Version")
        layout.addLayout(version_layout)

        # Description Section
        description_group = QtWidgets.QGroupBox("Description:")
        description_layout = self.create_description_layout()
        description_group.setLayout(description_layout)
        layout.addWidget(description_group)

        # File Name
        self.file_name_label = QtWidgets.QLabel("File Name:")
        layout.addWidget(self.file_name_label)

        # Save Button
        save_button = QtWidgets.QPushButton("Save", self)
        save_button.clicked.connect(self.save_clicked)
        layout.addWidget(save_button)

        self.setLayout(layout)

        # Ensure the necessary directories exist
        self.create_directories()

    def create_directories(self):
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        descriptions_dir = os.path.join(self.CORE_PATH, 'descriptions')

        # Ensure the user directory exists
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)

        # Ensure the descriptions directory exists
        if not os.path.exists(descriptions_dir):
            os.makedirs(descriptions_dir)

    def create_description_layout(self):
        description_layout = QtWidgets.QVBoxLayout()

        # Summary
        summary_label = QtWidgets.QLabel("Summary:")
        summary_text_edit = QtWidgets.QTextEdit()
        description_layout.addWidget(summary_label)
        description_layout.addWidget(summary_text_edit)

        # Hashtags/Keywords
        keywords_label = QtWidgets.QLabel("Hashtags/Keywords:")
        keywords_text_edit = QtWidgets.QTextEdit()
        description_layout.addWidget(keywords_label)
        description_layout.addWidget(keywords_text_edit)

        setattr(self, "Summary", summary_text_edit)
        setattr(self, "Keywords", keywords_text_edit)

        return description_layout

    def create_input_layout(self, label_text, dropdown_items=None, default_value="", key=""):
        label = QtWidgets.QLabel(label_text)
        input_line_edit = QtWidgets.QLineEdit(default_value)
        dropdown = QtWidgets.QComboBox()

        if dropdown_items:
            dropdown.addItems(dropdown_items)
            dropdown.currentIndexChanged.connect(lambda index, line_edit=input_line_edit, key=key: self.auto_fill_line_edit(index, line_edit, dropdown, key))

        input_line_edit.textChanged.connect(self.update_file_name)

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

        version_slider.setRange(1, 10)
        version_slider.valueChanged.connect(lambda value, input_field=version_input: input_field.setText(str(value).zfill(2)))
        version_input.textChanged.connect(lambda text, slider=version_slider: slider.setValue(int(text)) if text.isdigit() and 1 <= int(text) <= 10 else 1)

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
        context = self.Context.text() if hasattr(self, 'Context') and self.Context.text() else ''
        type_ = self.Type.text() if hasattr(self, 'Type') and self.Type.text() else ''
        name = self.Name.text() if hasattr(self, 'Name') and self.Name.text() else ''
        source = self.Source.text() if hasattr(self, 'Source') and self.Source.text() else ''

        version_checkbox = self.Version_checkbox
        version_input = self.Version_input

        if version_checkbox is not None and version_input is not None:
            version = version_input.text() if version_checkbox.isChecked() else "{:02d}".format(int(version_input.text()))
            file_name = f"{context}_{type_}_{name}_{source}_v{version}"
            self.file_name_label.setText(f"File Name: {file_name}")

    def save_clicked(self):
        context = self.Context.text() if hasattr(self, 'Context') and self.Context.text() else ''
        type_ = self.Type.text() if hasattr(self, 'Type') and self.Type.text() else ''
        name = self.Name.text() if hasattr(self, 'Name') and self.Name.text() else ''
        source = self.Source.text() if hasattr(self, 'Source') and self.Source.text() else ''

        version_checkbox = self.Version_checkbox
        version_input = self.Version_input

        if version_checkbox is not None and version_input is not None:
            version = version_input.text() if version_checkbox.isChecked() else "{:02d}".format(int(version_input.text()))

            user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
            final_path = os.path.join(user_dir, f"{context}_{type_}_{name}_{source}_v{version}")

            try:
                # Save selected nodes
                self.save_selected_nodes(final_path)

                # Save description data as JSON
                #self.save_description_data(final_path)

                # Update master JSON file
                self.update_master_json(final_path)

                print("File successfully saved.")
                self.close()  # Close the window on successful save
            except Exception as e:
                print(f"Error: {e}")

    def save_selected_nodes(self, file_name):
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        ext = '.uti'

        if not os.path.exists(user_dir):
            os.makedirs(user_dir)

        if len(hou.selectedNodes()) < 1:
            hou.ui.displayMessage("Nothing selected!")
        else:
            path = os.path.join(user_dir, file_name + ext)
            nodes = hou.selectedNodes()
            parent = nodes[0].parent()

            if not all(node.parent() == parent for node in nodes):
                raise Exception("Nodes must have the same parent.")

            parent.saveItemsToFile(nodes, path)

    # def save_description_data(self, file_name):
    #     user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
    #     core = os.path.join(user_dir, 'descriptions')
    #     ext = '.json'

    #     if not os.path.exists(core):
    #         os.makedirs(core)

    #     json_path = os.path.join(core, file_name + ext)

    #     description_data = {
    #         "Summary": self.Summary.toPlainText(),
    #         "Keywords": self.Keywords.toPlainText().splitlines(),
    #         "File Name": file_name,
    #         "Date": datetime.now().strftime("%Y-%m-%d"),
    #         "Time": datetime.now().strftime("%H:%M:%S"),
    #         "Size": self.calculate_size(json_path)
    #     }

    #     with open(json_path, 'w') as json_file:
    #         json.dump(description_data, json_file, indent=4)

    def calculate_size(self, file_path):
        if os.path.exists(file_path):
            return os.path.getsize(file_path)
        return 0

    def update_master_json(self, file_name):
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        core = os.path.join(user_dir, 'descriptions')
        master_json_path = os.path.join(core, 'master.json')

        if not os.path.exists(core):
            os.makedirs(core)

        # Read existing master JSON file
        master_data = []
        if os.path.exists(master_json_path):
            with open(master_json_path, 'r') as master_file:
                master_data = json.load(master_file)

        # Append the new file details to the master JSON data
        master_data.insert(0, {
            "Summary": self.Summary.toPlainText(),
            "Keywords": self.Keywords.toPlainText().splitlines(),
            "File Name": file_name,
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Time": datetime.now().strftime("%H:%M:%S"),
            "Size": self.calculate_size(os.path.join(core, file_name + '.json'))
        })

        # Update master JSON file
        with open(master_json_path, 'w') as master_file:
            json.dump(master_data, master_file, indent=4)

    def get_existing_values(self, field):
        user_dir = os.path.join(self.CORE_PATH, hou.getenv('USER'))
        ext = '.uti'

        existing_values = set()

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

# if __name__ == "__main__":
#     app = QtWidgets.QApplication.instance()
#     if app is None:
#         app = QtWidgets.QApplication([])

#     # Create an instance of WriteSnipUI
#     WriteSnipUI = WriteSnipUI()

#     # Show the UI
#     WriteSnipUI.show()

#     try:
#         # Run the application event loop
#         while True:
#             if not app.processEvents(QtCore.QEventLoop.AllEvents):
#                 break
#     except Exception as e:
#         print(f"Error: {e}")

#     # Close the application when the loop exits
#     app.quit()
