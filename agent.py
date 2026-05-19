import requests
import time
import json
import sqlite3
import re
import random
import curl_cffi.requests as cffi_requests
from email_validator import validate_email
import phonenumbers
from PySide6.QtCore import QObject, Signal, QThread

import database


class OSMAgent(QObject):
    status_updated = Signal(str)
    lead_found = Signal(dict)  # dict keys: type, name, phone, email, website, city, source
    finished = Signal()

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or {}
        self._stopped = False
        self._paused = False
        self.db_path = database.DB_PATH

    def start(self):
        self._stopped = False
        self._paused = False
        self.status_updated.emit("Agent started")

    def pause(self):
        self._paused = True
        self.status_updated.emit("Agent paused")

    def stop(self):
        self._stopped = True
        self.status_updated.emit("Agent stopped")

    def resume(self):
        self._paused = False
        self.status_updated.emit("Agent resumed")

    def wait_if_paused(self):
        while self._paused and not self._stopped:
            QThread.msleep(100)

    def _geocode(self, city: str) -> tuple:
        """Geocode a city in Italy using Nominatim."""
        url = f"https://nominatim.openstreetmap.org/search?q={city}+Italy&format=json&limit=1"
        headers = {"User-Agent": "LeadFalcon/1.0"}
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if data:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                return (lat, lon)
        except Exception:
            pass
        
        time.sleep(1)
        return (None, None)

    def query_overpass(self, city: str, radius: int = 15000) -> list:
        """Query Overpass API for leather/bags/accessories/fashion shops."""
        lat, lon = self._geocode(city)
        
        if lat is None or lon is None:
            self.status_updated.emit(f"Could not geocode city: {city}")
            return []
        
        query = (
            f"[out:json];"
            f"(node[shop~\"leather|bags|accessories|fashion\"](around:{radius},{lat},{lon});"
            f"way[shop~\"leather|bags|accessories|fashion\"](around:{radius},{lat},{lon}););"
            f"out center;"
        )
        
        url = "https://overpass-api.de/api/interpreter"
        headers = {"User-Agent": "LeadFalcon/1.0"}
        
        try:
            response = requests.post(url, data={"data": query}, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for element in data.get("elements", []):
                tags = element.get("tags", {})
                name = tags.get("name")
                
                if not name:
                    continue
                
                result = {
                    "name": name,
                    "phone": tags.get("phone"),
                    "website": tags.get("website"),
                    "street": tags.get("addr:street"),
                    "city": tags.get("addr:city")
                }
                results.append(result)
            
            return results
        except Exception as e:
            self.status_updated.emit(f"Overpass query failed: {e}")
            return []
        finally:
            time.sleep(2)

    def extract_contacts_from_page(self, url: str) -> dict:
        """Extract emails and Italian phone numbers from a webpage."""
        try:
            response = cffi_requests.get(url, impersonate="chrome", timeout=10)
            
            if response.status_code != 200:
                return {}
            
            text = response.text
            
            # Extract and validate emails
            email_pattern = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
            raw_emails = re.findall(email_pattern, text)
            valid_emails = set()
            
            for email in raw_emails:
                try:
                    validated = validate_email(email)
                    valid_emails.add(validated.email)
                except Exception:
                    continue
            
            # Extract Italian phone numbers
            phones = set()
            for match in phonenumbers.PhoneNumberMatcher(text, "IT"):
                try:
                    e164 = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
                    phones.add(e164)
                except Exception:
                    continue
            
            return {"emails": list(valid_emails), "phones": list(phones)}
        except Exception:
            return {}

    def _save_lead(self, lead: dict):
        """Save a lead to the database if it doesn't already exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT OR IGNORE INTO leads (type, name, phone, email, website, city, source) VALUES (?,?,?,?,?,?,?)",
            (lead.get("type", ""), lead.get("name", ""), lead.get("phone", ""), 
             lead.get("email", ""), lead.get("website", ""), lead.get("city", ""), 
             lead.get("source", ""))
        )
        
        if cursor.rowcount > 0:
            self.lead_found.emit(lead)
        
        conn.commit()
        conn.close()

    def run(self):
        """Main execution method - process all Italian cities."""
        self.status_updated.emit("Agent started. Loading cities...")
        
        cities = database.get_cities()
        
        if not cities:
            self.status_updated.emit("No cities to process.")
            self.finished.emit()
            return
        
        for city_id, name, region in cities:
            if self._stopped:
                break
            self.wait_if_paused()
            
            self.status_updated.emit(f"Processing: {name} ({region})")
            
            results = self.query_overpass(name)
            self.status_updated.emit(f"Found {len(results)} businesses in {name}")
            
            for biz in results:
                if self._stopped:
                    break
                self.wait_if_paused()
                
                lead = {
                    "type": "ORGANIZATION",
                    "name": biz["name"],
                    "phone": biz.get("phone", ""),
                    "email": "",
                    "website": biz.get("website", ""),
                    "city": name,
                    "source": "overpass"
                }
                
                if biz.get("website"):
                    contacts = self.extract_contacts_from_page(biz["website"])
                    if contacts.get("emails"):
                        lead["email"] = contacts["emails"][0]
                    if contacts.get("phones") and not lead["phone"]:
                        lead["phone"] = contacts["phones"][0]
                
                self._save_lead(lead)
                
                time.sleep(random.uniform(0.5, 1.5))
            
            time.sleep(3)
        
        self.status_updated.emit("All cities processed.")
        self.finished.emit()
