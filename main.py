import sys
import sqlite3
import json
import os
from openpyxl import Workbook
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox, QLineEdit, QTableWidget, QDialog, QFormLayout, QTextEdit, QDialogButtonBox, QTableWidgetItem, QFileDialog, QMessageBox, QCheckBox, QPushButton
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
        
        # Use all Italian municipalities checkbox
        self.comuni_checkbox = QCheckBox("Use all Italian municipalities")
        self.comuni_checkbox.setObjectName("comuni_checkbox")
        main_layout.addWidget(self.comuni_checkbox)
        
        # Load Municipalities button
        load_muni_button = QPushButton("Load Municipalities")
        load_muni_button.setObjectName("load_muni_button")
        load_muni_button.clicked.connect(self.on_load_municipalities)
        main_layout.addWidget(load_muni_button)
        
        # Button box
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.on_accepted)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
    
    def on_load_municipalities(self):
        csv_path = database.DB_PATH.replace("leadfalcon.db", "comuni.csv")
        if not os.path.exists(csv_path):
            csv_path = os.path.join(os.path.dirname(__file__), "comuni.csv")
        result = database.import_comuni_from_csv(csv_path)
        if result >= 0:
            QMessageBox.information(self, "Municipalities Loaded", f"Inserted {result} new municipalities.")
        else:
            QMessageBox.critical(self, "Error", "Failed to load municipalities.")
    
    def on_accepted(self):
        self.settings = {
            "groq_key": self.groq_key_edit.text(),
            "places_key": self.places_key_edit.text(),
            "speed": self.speed_combo.currentText(),
            "cities": [line for line in self.cities_edit.toPlainText().split("\n") if line.strip()],
            "use_all_comuni": self.comuni_checkbox.isChecked()
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
        
        # Populate city_combo based on use_all_comuni setting
        use_all_comuni = self.app_settings.get('use_all_comuni', False)
        if use_all_comuni:
            # Load cities from database
            conn = sqlite3.connect(database.DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM cities WHERE status != 'done' ORDER BY id")
            rows = cursor.fetchall()
            conn.close()
            cities = [row[0] for row in rows]
            self.city_combo.addItems(cities)
        else:
            # Use user-defined list from settings
            cities = self.app_settings.get('cities', [])
            if cities:
                self.city_combo.addItems(cities)
        
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
        self.agent.progress_updated.connect(self.on_progress_updated)
        
        # Load existing leads from database on startup
        self.load_leads()
    
    def load_leads(self):
        """Load existing leads from the database and display them in the table."""
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT record_type, business_name, person_full_name, role, email, phone, lead_score FROM leads ORDER BY lead_score DESC")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            self.add_lead_to_table(row)
    
    def add_lead_to_table(self, row):
        """Add a lead row to the table.
        
        Args:
            row: tuple (record_type, business_name, person_full_name, role, email, phone, lead_score)
        """
        record_type, business_name, person_full_name, role, email, phone, lead_score = row
        
        row_idx = self.leads_table.rowCount()
        self.leads_table.insertRow(row_idx)
        
        # Column 0: Type
        self.leads_table.setItem(row_idx, 0, QTableWidgetItem(record_type if record_type else ""))
        
        # Column 1: Business / Person
        display_name = business_name if record_type == 'ORGANIZATION' else person_full_name
        self.leads_table.setItem(row_idx, 1, QTableWidgetItem(display_name if display_name else ""))
        
        # Column 2: Role
        self.leads_table.setItem(row_idx, 2, QTableWidgetItem(role if role else ""))
        
        # Column 3: Email
        self.leads_table.setItem(row_idx, 3, QTableWidgetItem(email if email else ""))
        
        # Column 4: Phone
        self.leads_table.setItem(row_idx, 4, QTableWidgetItem(phone if phone else ""))
        
        # Column 5: Score
        self.leads_table.setItem(row_idx, 5, QTableWidgetItem(str(lead_score) if lead_score else "0"))
    
    def _lead_dict_to_tuple(self, lead_dict):
        """Convert a lead dictionary to a tuple matching the database row format."""
        return (
            lead_dict.get('record_type', ''),
            lead_dict.get('business_name', ''),
            lead_dict.get('person_full_name', ''),
            lead_dict.get('role', ''),
            lead_dict.get('email', ''),
            lead_dict.get('phone', ''),
            lead_dict.get('lead_score', 0)
        )
    
    def on_lead_found(self, lead_dict):
        row = self._lead_dict_to_tuple(lead_dict)
        self.add_lead_to_table(row)
    
    def on_progress_updated(self, city, leads_city, total_leads):
        self.statusBar().showMessage(f"{city}: {leads_city} leads found, {total_leads} total")
    
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
    
    def on_agent_finished(self):
        self.statusBar().showMessage("Finished")
        print("Agent finished")
    
    def on_settings(self):
        self.settings_dialog = SettingsDialog(self)
        # Pre-populate checkbox state from settings
        if 'use_all_comuni' in self.app_settings:
            self.settings_dialog.comuni_checkbox.setChecked(self.app_settings.get('use_all_comuni', False))
        if self.settings_dialog.exec() == QDialog.Accepted:
            self.app_settings = self.settings_dialog.settings
            self.city_combo.clear()
            use_all_comuni = self.app_settings.get('use_all_comuni', False)
            if use_all_comuni:
                # Load cities from database
                conn = sqlite3.connect(database.DB_PATH)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM cities WHERE status != 'done' ORDER BY id")
                rows = cursor.fetchall()
                conn.close()
                cities = [row[0] for row in rows]
                self.city_combo.addItems(cities)
            else:
                cities = self.app_settings.get('cities', [])
                if cities:
                    self.city_combo.addItems(cities)
            if self.city_combo.count() > 0:
                self.city_combo.setCurrentIndex(0)
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(self.app_settings, f)
    
    def on_export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Leads", "", "Excel Files (*.xlsx)")
        if not path:
            return
        try:
            wb = Workbook()
            ws = wb.active
            # Write headers
            for col in range(self.leads_table.columnCount()):
                header_item = self.leads_table.horizontalHeaderItem(col)
                header_text = header_item.text() if header_item else ""
                ws.cell(row=1, column=col + 1, value=header_text)
            # Write data rows
            for row in range(self.leads_table.rowCount()):
                for col in range(self.leads_table.columnCount()):
                    item = self.leads_table.item(row, col)
                    cell_value = item.text() if item else ""
                    ws.cell(row=row + 2, column=col + 1, value=cell_value)
            wb.save(path)
            self.statusBar().showMessage(f"Exported to {path}")
        except Exception as e:
            self.statusBar().showMessage(f"Export failed: {str(e)}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Ensure database exists on startup
    database.initialize_db()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
