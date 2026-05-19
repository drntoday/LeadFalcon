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
import groq

import database

# DDGS import with fallback
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None


class OSMAgent(QObject):
    status_updated = Signal(str)
    lead_found = Signal(dict)  # dict keys: type, name, phone, email, website, city, source
    finished = Signal()

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or {}
        self.margo_key = self.settings.get('margo_key', '')
        self.use_margo = self.settings.get('use_margo', False)
        self.groq_key = self.settings.get('groq_key', '')
        self.groq_client = groq.Client(api_key=self.groq_key) if self.groq_key else None
        self.margo_calls_today = 0
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
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Geocode error for {city}: {e}")
            return (None, None)
        
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
            print(f"[{time.strftime('%H:%M:%S')}] Overpass error for {city}: {e}")
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

    def extract_contacts_from_text(self, text: str) -> dict:
        """Extract emails and Italian phone numbers from a text string."""
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

    def search_web_fallback(self, city: str, keyword: str = "pelletteria") -> list:
        """Search the web for businesses when Overpass returns empty results."""
        if DDGS is None:
            print(f"[{time.strftime('%H:%M:%S')}] DDGS not available, skipping web search for {city}")
            return []
        
        query = f"{keyword} {city} contatti telefono email"
        results = []
        
        try:
            with DDGS() as ddgs:
                search_results = ddgs.text(query, max_results=10)
                
                for result in search_results:
                    title = result.get("title", "")
                    snippet = result.get("body", "")
                    url = result.get("href", "")
                    
                    # Extract contacts from snippet
                    contacts = self.extract_contacts_from_text(snippet)
                    
                    # Also try to fetch the page
                    if url:
                        page_contacts = self.extract_contacts_from_page(url)
                        # Merge results
                        if page_contacts.get("emails"):
                            contacts["emails"] = list(set(contacts.get("emails", []) + page_contacts["emails"]))
                        if page_contacts.get("phones"):
                            contacts["phones"] = list(set(contacts.get("phones", []) + page_contacts["phones"]))
                    
                    lead = {
                        "name": title,
                        "phone": contacts["phones"][0] if contacts.get("phones") else "",
                        "email": contacts["emails"][0] if contacts.get("emails") else "",
                        "website": url,
                        "source": "web"
                    }
                    results.append(lead)
                    
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Web search error for {city}: {e}")
            return []
        
        return results

    def query_openapi_imprese(self, city: str) -> list[dict]:
        """Query the official Italian business register API (Openapi Imprese)."""
        headers = {"User-Agent": "LeadFalcon/1.0"}
        results = []
        
        # First try with categoria=pelletteria
        url_specific = f"https://openapi.it/v1/aziende?comune={city}&categoria=pelletteria&formato=json"
        
        try:
            response = requests.get(url_specific, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, list) and len(data) > 0:
                companies = data
            else:
                # Try broader search without category filter
                url_broad = f"https://openapi.it/v1/aziende?comune={city}&formato=json"
                response = requests.get(url_broad, headers=headers, timeout=15)
                response.raise_for_status()
                data = response.json()
                companies = data if isinstance(data, list) else []
            
            for company in companies:
                name = company.get("ragione_sociale") or company.get("denominazione")
                
                if not name:
                    continue
                
                lead = {
                    "name": name,
                    "phone": company.get("telefono", ""),
                    "email": company.get("email", ""),
                    "website": company.get("sito_web") or company.get("url", ""),
                    "city": city,
                    "source": "openapi"
                }
                results.append(lead)
                
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] OpenAPI error for {city}: {e}")
            return []
        
        return results

    def _enrich_with_margo(self, company_name: str, website: str) -> dict:
        """Enrich lead data using Margo API.
        
        Returns dict with 'email' and 'phone' keys (empty strings if not found or on error).
        """
        if not self.use_margo or not self.margo_key:
            return {"email": "", "phone": ""}
        
        if self.margo_calls_today >= 20:
            self.status_updated.emit("Margo daily limit reached (20 calls). Stopping enrichment for this session.")
            print(f"[{time.strftime('%H:%M:%S')}] Margo daily limit reached (20 calls). Stopping enrichment.")
            return {"email": "", "phone": ""}
        
        try:
            import urllib.parse
            encoded_name = urllib.parse.quote(company_name)
            encoded_website = urllib.parse.quote(website) if website else ""
            url = f"https://api.margo.io/v1/company/enrich?name={encoded_name}&website={encoded_website}"
            headers = {"X-API-Key": self.margo_key}
            
            response = requests.get(url, headers=headers, timeout=15)
            self.margo_calls_today += 1
            
            if response.status_code == 200:
                data = response.json()
                email = data.get("email", "") or ""
                phone = data.get("phone", "") or ""
                return {"email": email, "phone": phone}
            else:
                print(f"[{time.strftime('%H:%M:%S')}] Margo API error: status {response.status_code}")
                return {"email": "", "phone": ""}
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Margo enrichment error: {e}")
            return {"email": "", "phone": ""}

    def _update_lead_enrichment(self, lead: dict, enrichment: dict):
        """Update a lead in the database with enrichment data from Margo."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Update email and/or phone if enrichment provides them
        updates = []
        params = []
        
        if enrichment.get("email"):
            updates.append("email = ?")
            params.append(enrichment["email"])
        if enrichment.get("phone"):
            updates.append("phone = ?")
            params.append(enrichment["phone"])
        
        if updates:
            params.extend([lead.get("name", ""), lead.get("city", "")])
            query = f"UPDATE leads SET {', '.join(updates)} WHERE name = ? AND city = ?"
            cursor.execute(query, params)
            conn.commit()
            
            # Emit updated lead
            updated_lead = lead.copy()
            if enrichment.get("email"):
                updated_lead["email"] = enrichment["email"]
            if enrichment.get("phone"):
                updated_lead["phone"] = enrichment["phone"]
            self.lead_found.emit(updated_lead)
        
        conn.close()

    def _score_lead(self, lead: dict) -> dict:
        """Score a lead from 0-100 using Groq AI if available."""
        if self.groq_client is None:
            lead['score'] = 50
            return lead
        
        try:
            prompt = f"You are a lead quality analyst for Italian leather goods. Score this business from 0-100 based on how likely it is to be a genuine leather goods retailer, boutique, or wholesaler. Consider the name, phone presence, email presence, and website. Business: {json.dumps(lead)}. Return ONLY the integer score, nothing else."
            
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.3
            )
            
            score_text = response.choices[0].message.content.strip()
            # Extract integer from response
            import re as re_module
            match = re_module.search(r'\d+', score_text)
            if match:
                score = int(match.group())
            else:
                score = 50
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Groq scoring error: {e}")
            score = 50
        
        lead['score'] = score
        return lead

    def _merge_leads(self, leads: list) -> list:
        """Merge duplicate leads by normalized name + city."""
        import string
        
        def normalize_key(lead):
            name = lead.get('name', '').lower().strip()
            city = lead.get('city', '').lower().strip()
            # Remove punctuation
            name = ''.join(c for c in name if c not in string.punctuation)
            city = ''.join(c for c in city if c not in string.punctuation)
            return f"{name}|{city}"
        
        groups = {}
        for lead in leads:
            key = normalize_key(lead)
            if key not in groups:
                groups[key] = []
            groups[key].append(lead)
        
        merged = []
        for key, group in groups.items():
            # Merge leads in this group
            names = [l.get('name', '') for l in group]
            longest_name = max(names, key=len) if names else ''
            
            phones = set()
            emails = set()
            websites = []
            sources = []
            cities = set()
            
            for l in group:
                if l.get('phone'):
                    phones.add(l['phone'])
                if l.get('email'):
                    emails.add(l['email'])
                if l.get('website') and l['website'] not in websites:
                    websites.append(l['website'])
                if l.get('source'):
                    sources.append(l['source'])
                if l.get('city'):
                    cities.add(l['city'])
            
            merged_lead = {
                'type': 'ORGANIZATION',
                'name': longest_name,
                'phone': ', '.join(list(phones)) if phones else '',
                'email': ', '.join(list(emails)) if emails else '',
                'website': websites[0] if websites else '',
                'city': list(cities)[0] if cities else '',
                'source': '+'.join(sources)
            }
            merged.append(merged_lead)
        
        return merged

    def _save_lead(self, lead: dict):
        """Save a lead to the database if it doesn't already exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT OR IGNORE INTO leads (type, name, phone, email, website, city, source, score) VALUES (?,?,?,?,?,?,?,?)",
            (lead.get("type", ""), lead.get("name", ""), lead.get("phone", ""), 
             lead.get("email", ""), lead.get("website", ""), lead.get("city", ""), 
             lead.get("source", ""), lead.get("score", 50))
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
            print(f"[{time.strftime('%H:%M:%S')}] Processing: {name} ({region})")
            
            results = self.query_overpass(name)
            print(f"[{time.strftime('%H:%M:%S')}] Overpass found {len(results)} businesses in {name}")
            
            web_results = []
            if len(results) == 0:
                self.status_updated.emit("Overpass empty, trying web search...")
                print(f"[{time.strftime('%H:%M:%S')}] Overpass empty for {name}, trying web search...")
                web_results = self.search_web_fallback(name)
                print(f"[{time.strftime('%H:%M:%S')}] Web search found {len(web_results)} results for {name}")
            
            # Query OpenAPI Imprese to enrich results
            time.sleep(2)  # Respect 2-second delay between API calls
            openapi_results = self.query_openapi_imprese(name)
            print(f"[{time.strftime('%H:%M:%S')}] OpenAPI found {len(openapi_results)} results for {name}")
            
            # Collect all raw leads from Overpass, web, and Openapi into a single list
            all_leads = []
            
            # Process Overpass results
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
                
                all_leads.append(lead)
            
            # Process web fallback results
            for web_lead in web_results:
                if self._stopped:
                    break
                self.wait_if_paused()
                
                lead = {
                    "type": "ORGANIZATION",
                    "name": web_lead["name"],
                    "phone": web_lead.get("phone", ""),
                    "email": web_lead.get("email", ""),
                    "website": web_lead.get("website", ""),
                    "city": name,
                    "source": web_lead.get("source", "web")
                }
                
                all_leads.append(lead)
            
            # Process OpenAPI results
            for api_lead in openapi_results:
                if self._stopped:
                    break
                self.wait_if_paused()
                
                lead = {
                    "type": "ORGANIZATION",
                    "name": api_lead["name"],
                    "phone": api_lead.get("phone", ""),
                    "email": api_lead.get("email", ""),
                    "website": api_lead.get("website", ""),
                    "city": name,
                    "source": api_lead.get("source", "openapi")
                }
                
                all_leads.append(lead)
            
            # Merge duplicates
            merged = self._merge_leads(all_leads)
            
            # Score each merged lead
            scored_leads = [self._score_lead(lead) for lead in merged]
            
            # Save only leads with score >= 40
            saved = 0
            for lead in scored_leads:
                if lead.get('score', 50) >= 40:
                    self._save_lead(lead)
                    saved += 1
            
            # Emit progress with city name, leads found, total leads
            self.status_updated.emit(f"{name}: Raw={len(all_leads)}, Merged={len(merged)}, Saved={saved}")
            
            if len(results) == 0 and len(web_results) == 0 and len(openapi_results) == 0:
                print(f"[{time.strftime('%H:%M:%S')}] No leads found in {name}")
            
            print(f"[{time.strftime('%H:%M:%S')}] [{name}] Raw: {len(all_leads)}, Merged: {len(merged)}, Saved: {saved}")
            
            time.sleep(3)
        
        self.status_updated.emit("All cities processed.")
        self.finished.emit()
