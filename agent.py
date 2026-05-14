import time
import sqlite3
from PySide6.QtCore import QObject, Signal, Slot, QThread
import database


class LeadAgent(QObject):
    status_updated = Signal(str)
    lead_found = Signal(dict)
    progress_updated = Signal(str, int, int)
    finished = Signal()

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self._paused = False
        self._stopped = False
        self.settings = settings if settings is not None else {}

    def start(self):
        self._paused = False
        self._stopped = False
        self.status_updated.emit("Agent started.")

    def pause(self):
        self._paused = True
        self.status_updated.emit("Paused.")

    def resume(self):
        self._paused = False
        self.status_updated.emit("Resumed.")

    def stop(self):
        self._stopped = True
        self._paused = False
        self.status_updated.emit("Stopped.")

    def run(self):
        self.status_updated.emit("Connecting to database...")
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, region FROM cities WHERE status = 'pending'")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            self.status_updated.emit("No pending cities.")
            self.finished.emit()
            return

        for city in rows:
            if self._stopped:
                break
            self.wait_if_paused()
            city_id, city_name, region = city
            self.status_updated.emit(f"Processing {city_name}...")
            time.sleep(1)

        if not self._stopped:
            self.status_updated.emit("All cities processed.")
            self.finished.emit()

    def wait_if_paused(self):
        while self._paused and not self._stopped:
            QThread.msleep(100)
