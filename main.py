import sys
import sqlite3
import json
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox, QLineEdit, QTableWidget, QDialog, QFormLayout, QTextEdit, QDialogButtonBox, QTableWidgetItem
from PySide6.QtGui import QAction
from PySide6.QtCore import QThread

import database
from agent import LeadAgent

SETTINGS_FILE = "settings.json"


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LeadFalcon – Italian Leather Prospector")
        
        # Load settings from file
        try:
            with open(SETTINGS_FILE, 'r') as f:
                self.app_settings = json.load(f)
        except FileNotFoundError:
            self.app_settings = {}
        
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
        
        # Populate city_combo from loaded settings if present
        if 'cities' in self.app_settings:
            self.city_combo.addItems(self.app_settings['cities'])
        
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
        
        # Create agent thread and agent
        self.agent_thread = QThread()
        self.agent = LeadAgent(settings=self.app_settings)
        self.agent.moveToThread(self.agent_thread)
        
        # Connect signals
        self.agent_thread.started.connect(self.agent.run)
        self.agent.finished.connect(self.agent_thread.quit)
        self.agent.finished.connect(self.on_agent_finished)
        self.agent_thread.finished.connect(self.agent_thread.deleteLater)
        self.agent.status_updated.connect(lambda msg: self.statusBar().showMessage(msg))
        self.agent.lead_found.connect(self.on_lead_found)
    
    def closeEvent(self, event):
        if hasattr(self, 'agent') and hasattr(self, 'agent_thread'):
            self.agent.stop()
            self.agent_thread.quit()
            self.agent_thread.wait()
        event.accept()
    
    def on_start(self):
        if not self.agent_thread.isRunning():
            self.agent.start()
            self.agent_thread.start()
    
    def on_pause(self):
        if self.agent_thread.isRunning():
            self.agent.pause()
    
    def on_stop(self):
        self.agent.stop()
        self.agent_thread.quit()
        self.agent_thread.wait()
    
    def on_lead_found(self, lead_dict):
        row = self.leads_table.rowCount()
        self.leads_table.insertRow(row)
        
        record_type = lead_dict.get('record_type', '')
        business_name = lead_dict.get('business_name', '')
        person_full_name = lead_dict.get('person_full_name', '')
        role = lead_dict.get('role', '')
        email = lead_dict.get('email', '')
        phone = lead_dict.get('phone', '')
        lead_score = lead_dict.get('lead_score', '')
        
        business_or_person = business_name if business_name else person_full_name
        
        self.leads_table.setItem(row, 0, QTableWidgetItem(str(record_type)))
        self.leads_table.setItem(row, 1, QTableWidgetItem(str(business_or_person)))
        self.leads_table.setItem(row, 2, QTableWidgetItem(str(role)))
        self.leads_table.setItem(row, 3, QTableWidgetItem(str(email)))
        self.leads_table.setItem(row, 4, QTableWidgetItem(str(phone)))
        self.leads_table.setItem(row, 5, QTableWidgetItem(str(lead_score)))
        
        self.leads_table.scrollToBottom()
    
    def on_agent_finished(self):
        self.statusBar().showMessage("Finished")
        print("Agent finished")
    
    def on_settings(self):
        self.settings_dialog = SettingsDialog(self)
        if self.settings_dialog.exec() == QDialog.Accepted:
            self.app_settings = self.settings_dialog.settings
            self.city_combo.clear()
            self.city_combo.addItems(self.app_settings['cities'])
            if self.app_settings['cities']:
                self.city_combo.setCurrentIndex(0)
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(self.app_settings, f)
    
    def on_export(self):
        print("Export")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Ensure database exists on startup
    database.initialize_db()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
