import sys
import sqlite3
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox, QLineEdit, QTableWidget, QDialog, QFormLayout, QTextEdit, QDialogButtonBox
from PySide6.QtGui import QAction

import database


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


class SettingsDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Settings")
        
        # Main layout
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        
        # Form layout
        form_layout = QFormLayout()
        
        # Groq API Key
        self.groq_key_edit = QLineEdit()
        self.groq_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.groq_key_edit.setObjectName("groq_key")
        form_layout.addRow("Groq API Key", self.groq_key_edit)
        
        # Google Places API Key
        self.places_key_edit = QLineEdit()
        self.places_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.places_key_edit.setObjectName("places_key")
        form_layout.addRow("Google Places API Key", self.places_key_edit)
        
        # Scraping Speed
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["Polite", "Aggressive"])
        self.speed_combo.setObjectName("speed_combo")
        form_layout.addRow("Scraping Speed", self.speed_combo)
        
        # Cities
        self.cities_edit = QTextEdit()
        self.cities_edit.setObjectName("cities_edit")
        self.cities_edit.setFixedHeight(150)
        cities_text = """Roma
Milano
Napoli
Torino
Palermo
Genova
Bologna
Firenze
Catania
Bari
Venezia
Verona"""
        self.cities_edit.setPlainText(cities_text)
        form_layout.addRow("Cities", self.cities_edit)
        
        # Add form layout to main layout
        main_layout.addLayout(form_layout)
        
        # Button box
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.on_accepted)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
    
    def on_accepted(self):
        self.settings = {
            "groq_key": self.groq_key_edit.text(),
            "places_key": self.places_key_edit.text(),
            "speed": self.speed_combo.currentText(),
            "cities": [line for line in self.cities_edit.toPlainText().split("\n") if line.strip()]
        }
        self.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Ensure database exists on startup
    database.initialize_db()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
