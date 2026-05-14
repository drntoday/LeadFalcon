import sys
import sqlite3
import json
import os
from openpyxl import Workbook
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QTableWidget, QDialog, QFormLayout, QDialogButtonBox, QTableWidgetItem, QFileDialog, QPushButton, QLineEdit, QComboBox, QCheckBox
from PySide6.QtGui import QAction
from PySide6.QtCore import QThread, QTimer, QObject, Signal

import database
from agent import LeadAgent

SETTINGS_FILE = "settings.json"


class MunicipalityLoader(QObject):
    """Worker class to load municipalities from CSV in a background thread."""
    
    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(int)  # new_rows
    
    def __init__(self, csv_path):
        super().__init__()
        self.csv_path = csv_path
    
    def _on_progress(self, current, total):
        """Internal callback that emits the progress signal."""
        self.progress.emit(current, total, f"Loading municipalities: {current}/{total}")
    
    def load(self):
        """Load municipalities from CSV and emit progress/finished signals."""
        try:
            new_rows = database.import_comuni_from_csv(self.csv_path, progress_callback=self._on_progress)
            self.finished.emit(new_rows)
        except Exception as e:
            self.progress.emit(0, 0, f"Error loading municipalities: {e}")
            self.finished.emit(0)


class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_settings=None):
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
        if current_settings and "groq_key" in current_settings:
            self.groq_key_edit.setText(current_settings["groq_key"])
        form_layout.addRow("Groq API Key", self.groq_key_edit)
        
        # Scraping Speed
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["Polite", "Aggressive"])
        self.speed_combo.setObjectName("speed")
        if current_settings and "speed" in current_settings:
            idx = self.speed_combo.findText(current_settings["speed"])
            if idx >= 0:
                self.speed_combo.setCurrentIndex(idx)
        form_layout.addRow("Scraping Speed", self.speed_combo)
        
        # Auto-start checkbox
        self.auto_start_check = QCheckBox("Auto-start scraping on launch")
        self.auto_start_check.setObjectName("auto_start")
        if current_settings and current_settings.get("auto_start", False):
            self.auto_start_check.setChecked(True)
        form_layout.addRow("", self.auto_start_check)
        
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
            "speed": self.speed_combo.currentText(),
            "auto_start": self.auto_start_check.isChecked()
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
        
        # Create central widget with QVBoxLayout - only the leads table
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Create QTableWidget for leads - occupies all space
        self.leads_table = QTableWidget()
        self.leads_table.setObjectName("leads_table")
        self.leads_table.setColumnCount(6)
        self.leads_table.setHorizontalHeaderLabels(["Type", "Business / Person", "Role", "Email", "Phone", "Score"])
        self.leads_table.setRowCount(0)
        layout.addWidget(self.leads_table)
        
        # Add a status bar with "Ready" message
        self.statusBar().showMessage("Ready")
        
        # Initialize database
        database.initialize_db()
        
        # Check if municipalities need to be loaded
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cities")
        count = cursor.fetchone()[0]
        conn.close()
        
        if count == 0:
            # Show loading status and start background loader
            self.statusBar().showMessage("Loading municipalities...")
            
            csv_path = os.path.join(os.path.dirname(__file__), "comuni.csv")
            
            # Create thread and loader for background loading
            self.load_thread = QThread()
            self.municipality_loader = MunicipalityLoader(csv_path)
            self.municipality_loader.moveToThread(self.load_thread)
            
            # Connect signals
            self.municipality_loader.progress.connect(self.on_load_progress)
            self.municipality_loader.finished.connect(self.on_load_finished)
            self.load_thread.started.connect(self.municipality_loader.load)
            self.municipality_loader.finished.connect(self.load_thread.quit)
            self.load_thread.finished.connect(self.load_thread.deleteLater)
            
            # Start the thread
            self.load_thread.start()
        
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
        
        # Auto-start scraping if enabled in settings
        if self.app_settings.get("auto_start", False):
            QTimer.singleShot(0, self.on_start)
    
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
    
    def on_load_progress(self, current, total, message):
        """Slot for municipality loading progress updates."""
        self.statusBar().showMessage(f"Loading municipalities: {current}/{total}")
    
    def on_load_finished(self, new_rows):
        """Slot for when municipality loading is complete."""
        self.statusBar().showMessage(f"{new_rows} municipalities loaded.")
        # If auto-start is enabled, trigger agent start after loading completes
        if self.app_settings.get("auto_start", False) and not self.agent_thread.isRunning():
            QTimer.singleShot(500, self.on_start)
    
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
        self.settings_dialog = SettingsDialog(self, self.app_settings)
        if self.settings_dialog.exec() == QDialog.Accepted:
            self.app_settings = self.settings_dialog.settings
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(self.app_settings, f)
            # Update agent settings
            self.agent.settings = self.app_settings
    
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
