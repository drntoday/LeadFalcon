import time
from PySide6.QtCore import QObject, Signal, Slot, QThread


class LeadAgent(QObject):
    status_updated = Signal(str)
    lead_found = Signal(dict)
    progress_updated = Signal(str, int, int)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paused = False
        self._stopped = False

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
        print("Agent running...")
        time.sleep(2)
        self.finished.emit()

    def wait_if_paused(self):
        while self._paused and not self._stopped:
            QThread.msleep(100)
