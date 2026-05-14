import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LeadFalcon – Italian Leather Prospector")
        
        # Create an empty central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Add a status bar with "Ready" message
        self.statusBar().showMessage("Ready")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
