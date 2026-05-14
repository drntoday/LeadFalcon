import time
import sqlite3
import hashlib
import groq
from PySide6.QtCore import QObject, Signal, Slot, QThread
from duckduckgo_search import DDGS
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
        self.groq_client = None

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
            keywords = self.generate_keywords_for_city(city_name)
            for keyword in keywords:
                self.wait_if_paused()
                results = self.search_web(keyword)
                print(len(results))

        if not self._stopped:
            self.status_updated.emit("All cities processed.")
            self.finished.emit()

    def search_web(self, query, max_results=10):
        self.status_updated.emit(f"Searching: {query}")
        try:
            results = []
            with DDGS() as ddgs:
                for result in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "snippet": result.get("body", "")
                    })
                    if len(results) >= max_results:
                        break
        except Exception as e:
            self.status_updated.emit(f"Search error: {e}")
            return []
        time.sleep(2)
        return results

    def wait_if_paused(self):
        while self._paused and not self._stopped:
            QThread.msleep(100)

    def _ensure_groq_client(self):
        if self.groq_client is not None:
            return
        key = self.settings.get("groq_key")
        if not key:
            self.status_updated.emit("Groq API key not set.")
            self.groq_client = None
            return
        self.groq_client = groq.Client(api_key=key)

    def generate_keywords_for_city(self, city_name):
        self._ensure_groq_client()
        if self.groq_client is None:
            return []
        prompt = f"Generate 8 search queries to find Italian leather goods retailers, boutiques, and wholesalers in {city_name}. Use Italian words like 'pelletteria', 'borse in pelle', 'negozio accessori moda', and 'rivenditore'. Return only a JSON array of strings, no explanation."
        response = self.groq_client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500
        )
        try:
            import json
            keywords = json.loads(response.choices[0].message.content)
            return keywords
        except Exception:
            self.status_updated.emit("Failed to parse keyword response.")
            return []

    def _get_or_create_keyword(self, city_id, keyword_text):
        keyword_hash = hashlib.sha256(f"{city_id}{keyword_text}".encode()).hexdigest()
        conn = None
        try:
            conn = sqlite3.connect(database.DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM keywords WHERE keyword_hash = ?", (keyword_hash,))
            row = cursor.fetchone()
            if row:
                return row[0]
            cursor.execute("INSERT INTO keywords (city_id, keyword_hash, keyword_text) VALUES (?, ?, ?)",
                           (city_id, keyword_hash, keyword_text))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            self.status_updated.emit(f"Keyword error: {e}")
            return None
        finally:
            if conn:
                conn.close()
