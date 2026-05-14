import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox, QLineEdit, QTableWidget
from PySide6.QtGui import QAction


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LeadFalcon – Italian Leather Prospector")
        
        # Create a toolbar at the top
        toolbar = self.addToolBar("Main Toolbar")
        
        # Create actions
        self.start_action = QAction("Start", self)
        self.start_action.triggered.connect(self.on_start)
        toolbar.addAction(self.start_action)
        
        self.pause_action = QAction("Pause", self)
        self.pause_action.triggered.connect(self.on_pause)
        toolbar.addAction(self.pause_action)
        
        self.stop_action = QAction("Stop", self)
        self.stop_action.triggered.connect(self.on_stop)
        toolbar.addAction(self.stop_action)
        
        self.settings_action = QAction("Settings", self)
        self.settings_action.triggered.connect(self.on_settings)
        toolbar.addAction(self.settings_action)
        
        self.export_action = QAction("Export", self)
        self.export_action.triggered.connect(self.on_export)
        toolbar.addAction(self.export_action)
        
        # Create central widget with QVBoxLayout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Create horizontal layout for filter controls
        filter_layout = QHBoxLayout()
        
        # City label and combo box
        city_label = QLabel("City:")
        filter_layout.addWidget(city_label)
        
        self.city_combo = QComboBox()
        self.city_combo.setObjectName("city_combo")
        filter_layout.addWidget(self.city_combo)
        
        # Min Score label and spin box
        score_label = QLabel("Min Score:")
        filter_layout.addWidget(score_label)
        
        self.score_spin = QSpinBox()
        self.score_spin.setObjectName("score_spin")
        self.score_spin.setRange(0, 100)
        self.score_spin.setValue(50)
        filter_layout.addWidget(self.score_spin)
        
        # Search label and line edit
        search_label = QLabel("Search:")
        filter_layout.addWidget(search_label)
        
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("search_edit")
        self.search_edit.setPlaceholderText("Search...")
        filter_layout.addWidget(self.search_edit)
        
        # Add filter layout to main layout
        layout.addLayout(filter_layout)
        
        # Create QTableWidget for leads
        self.leads_table = QTableWidget()
        self.leads_table.setObjectName("leads_table")
        self.leads_table.setColumnCount(6)
        self.leads_table.setHorizontalHeaderLabels(["Type", "Business / Person", "Role", "Email", "Phone", "Score"])
        self.leads_table.setRowCount(0)
        layout.addWidget(self.leads_table)
        
        # Add a status bar with "Ready" message
        self.statusBar().showMessage("Ready")
    
    def on_start(self):
        print("Start")
    
    def on_pause(self):
        print("Pause")
    
    def on_stop(self):
        print("Stop")
    
    def on_settings(self):
        print("Settings")
    
    def on_export(self):
        print("Export")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
