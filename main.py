import sys
import sqlite3
import json
import os
from openpyxl import Workbook

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QToolBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QStatusBar,
    QFileDialog,
    QMessageBox,
    QAction
)
from PySide6.QtCore import QThread

from agent import OSMAgent


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("LeadFalcon – Leather Leads")
        self.resize(1000, 600)
        
        # Create toolbar
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)
        
        # Toolbar actions
        self.start_action = QAction("Start", self)
        self.start_action.triggered.connect(self.on_start)
        toolbar.addAction(self.start_action)
        
        self.pause_action = QAction("Pause", self)
        self.pause_action.triggered.connect(self.on_pause)
        toolbar.addAction(self.pause_action)
        
        self.stop_action = QAction("Stop", self)
        self.stop_action.triggered.connect(self.on_stop)
        toolbar.addAction(self.stop_action)
        
        self.export_action = QAction("Export", self)
        self.export_action.triggered.connect(self.on_export)
        toolbar.addAction(self.export_action)
        
        # Central widget with table
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(7)
        self.table_widget.setHorizontalHeaderLabels([
            "Type", "Name", "Phone", "Email", "Website", "City", "Source"
        ])
        
        header = self.table_widget.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Stretch)
        
        layout.addWidget(self.table_widget)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
        # Keep references to thread and agent
        self.thread = None
        self.agent = None

    def on_lead_found(self, lead: dict):
        """Add a new lead to the table."""
        row_position = self.table_widget.rowCount()
        self.table_widget.insertRow(row_position)
        
        self.table_widget.setItem(row_position, 0, QTableWidgetItem(lead.get("type", "")))
        self.table_widget.setItem(row_position, 1, QTableWidgetItem(lead.get("name", "")))
        self.table_widget.setItem(row_position, 2, QTableWidgetItem(lead.get("phone", "")))
        self.table_widget.setItem(row_position, 3, QTableWidgetItem(lead.get("email", "")))
        self.table_widget.setItem(row_position, 4, QTableWidgetItem(lead.get("website", "")))
        self.table_widget.setItem(row_position, 5, QTableWidgetItem(lead.get("city", "")))
        self.table_widget.setItem(row_position, 6, QTableWidgetItem(lead.get("source", "")))
        
        self.table_widget.scrollToBottom()

    def on_start(self):
        """Start the agent in a new thread."""
        if self.thread is not None and self.thread.isRunning():
            self.status_bar.showMessage("Agent already running")
            return
        
        self.thread = QThread()
        self.agent = OSMAgent(settings={})
        
        self.agent.moveToThread(self.thread)
        
        # Connect signals
        self.thread.started.connect(self.agent.run)
        self.agent.finished.connect(self.thread.quit)
        self.agent.finished.connect(self.agent.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        
        self.agent.status_updated.connect(self.status_bar.showMessage)
        self.agent.lead_found.connect(self.on_lead_found)
        
        self.thread.start()
        self.status_bar.showMessage("Agent starting...")

    def on_pause(self):
        """Pause the agent."""
        if self.agent:
            self.agent.pause()

    def on_stop(self):
        """Stop the agent and thread."""
        if self.agent:
            self.agent.stop()
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
            self.agent = None
        self.status_bar.showMessage("Agent stopped")

    def on_export(self):
        """Export table data to Excel."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export to Excel",
            "",
            "Excel Files (*.xlsx)"
        )
        
        if not file_path:
            return
        
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Leads"
            
            # Write headers
            headers = ["Type", "Name", "Phone", "Email", "Website", "City", "Source"]
            for col, header in enumerate(headers, 1):
                ws.cell(row=1, column=col, value=header)
            
            # Write data
            for row in range(self.table_widget.rowCount()):
                for col in range(self.table_widget.columnCount()):
                    item = self.table_widget.item(row, col)
                    value = item.text() if item else ""
                    ws.cell(row=row + 2, column=col + 1, value=value)
            
            wb.save(file_path)
            self.status_bar.showMessage(f"Exported to {file_path}")
            QMessageBox.information(self, "Export Complete", f"Data exported to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
