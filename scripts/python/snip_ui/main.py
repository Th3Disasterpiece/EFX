# main.py
from PySide2 import QtWidgets, QtCore
from write_snip_ui_v01 import WriteSnipUI

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
