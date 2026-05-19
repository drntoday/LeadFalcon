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

# ColdReach import with fallback
try:
    from coldreach import EmailFinder
    COLDREACH_AVAILABLE = True
except ImportError:
    COLDREACH_AVAILABLE = False
    EmailFinder = None

# metaURL import with fallback
try:
    import metaurl
    METAURL_AVAILABLE = True
except ImportError:
    METAURL_AVAILABLE = False
    metaurl = None


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
        self.yelp_key = self.settings.get('yelp_key', '')
        self.openapi_key = self.settings.get('openapi_key', '')
        self.scala_key = self.settings.get('scala_key', '')
        self.serper_key = self.settings.get('serper_key', '')
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

    def search_serper(self, query: str) -> list:
        """Search Google via Serper.dev API."""
        if not self.serper_key:
            return []
        
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": self.serper_key,
            "Content-Type": "application/json"
        }
        payload = {"q": query, "gl": "it", "hl": "it", "num": 10}
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            time.sleep(1)  # Respect 1-second delay between calls
            
            if response.status_code == 200:
                data = response.json()
                organic_results = data.get("organic", [])
                results = []
                for item in organic_results:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", "")
                    })
                return results
            else:
                print(f"[{time.strftime('%H:%M:%S')}] Serper API error: status {response.status_code}")
                return []
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Serper search error: {e}")
            return []

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

    def query_bizdata(self, city: str, category: str = "leather") -> list[dict]:
        """Query BizData API for businesses in Italy."""
        url = f"https://bizdata-web.vercel.app/api/businesses?location={city}+Italy&category={category}&limit=200&radius_km=20"
        headers = {"User-Agent": "LeadFalcon/1.0"}
        results = []
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            businesses = data if isinstance(data, list) else data.get("businesses", [])
            
            for biz in businesses:
                name = biz.get("name") or biz.get("business_name")
                if not name:
                    continue
                
                lead = {
                    "name": name,
                    "phone": biz.get("phone", ""),
                    "website": biz.get("website", ""),
                    "email": biz.get("email", ""),
                    "address": biz.get("address", ""),
                    "city": city,
                    "source": "bizdata"
                }
                results.append(lead)
                
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] BizData error for {city}: {e}")
            return []
        
        return results

    def query_yelp(self, city: str, category: str = "leather goods") -> list[dict]:
        """Query Yelp Fusion API for businesses in Italy."""
        if not self.yelp_key:
            return []
        
        url = f"https://api.yelp.com/v3/businesses/search?term={category}&location={city}+Italy&limit=50"
        headers = {"Authorization": f"Bearer {self.yelp_key}", "User-Agent": "LeadFalcon/1.0"}
        results = []
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            businesses = data.get("businesses", [])
            
            for biz in businesses:
                name = biz.get("name")
                if not name:
                    continue
                
                phone = biz.get("phone", "")
                # Format Yelp phone number if present
                if phone and len(phone) > 4:
                    phone = phone.replace("+", "").replace("-", "").replace(" ", "")
                    phone = "+" + phone if not phone.startswith("+") else phone
                
                address_lines = biz.get("location", {}).get("address1", "")
                city_from_yelp = biz.get("location", {}).get("city", "")
                
                lead = {
                    "name": name,
                    "phone": phone,
                    "website": biz.get("url", ""),
                    "address": address_lines,
                    "city": city_from_yelp if city_from_yelp else city,
                    "source": "yelp"
                }
                results.append(lead)
                
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Yelp error for {city}: {e}")
            return []
        
        return results

    def query_gleif(self, city: str) -> list[dict]:
        """Query GLEIF API for company records in Italy by city."""
        url = f"https://api.gleif.org/api/v1/lei-records?filter[entity.legalAddress.city]={city}&filter[entity.legalAddress.country]=IT&page[size]=200"
        headers = {"User-Agent": "LeadFalcon/1.0"}
        results = []
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            records = data.get("data", [])
            
            for record in records:
                attributes = record.get("attributes", {})
                entity = attributes.get("entity", {})
                legal_address = entity.get("legalAddress", {})
                
                company_name = ""
                if "legalName" in entity:
                    legal_name = entity["legalName"]
                    company_name = legal_name.get("name", "") if isinstance(legal_name, dict) else str(legal_name)
                
                if not company_name:
                    continue
                
                street = legal_address.get("addressLines", [""])[0] if legal_address.get("addressLines") else legal_address.get("street", "")
                region = legal_address.get("region", "")
                
                # Extract registration authority ID (VAT-like)
                validated_reg_auth_id = ""
                registration = attributes.get("registration", {})
                if registration:
                    validated_reg_auth_id = registration.get("validatedRegistrationAuthorityID", "")
                
                lead = {
                    "name": company_name,
                    "phone": "",
                    "email": "",
                    "website": "",
                    "address": street,
                    "city": city,
                    "region": region,
                    "vat_like_id": validated_reg_auth_id,
                    "source": "gleif"
                }
                results.append(lead)
                
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] GLEIF error for {city}: {e}")
            return []
        
        return results

    def query_openregistry(self, company_name: str) -> dict:
        """Query OpenAPI free search for company details by name."""
        if not self.openapi_key:
            return {}
        
        import urllib.parse
        encoded_name = urllib.parse.quote(company_name)
        url = f"https://api.openapi.com/v1/aziende?denominazione={encoded_name}"
        headers = {"X-API-Key": self.openapi_key, "User-Agent": "LeadFalcon/1.0"}
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            companies = data if isinstance(data, list) else data.get("aziende", [])
            
            if companies:
                company = companies[0]
                return {
                    "ragione_sociale": company.get("ragione_sociale", ""),
                    "telefono": company.get("telefono", ""),
                    "email": company.get("email", ""),
                    "sito_web": company.get("sito_web", ""),
                    "indirizzo": company.get("indirizzo", ""),
                    "source": "openapi"
                }
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] OpenRegistry error for {company_name}: {e}")
        
        return {}

    def query_scala(self, vat_number: str) -> dict:
        """Query S.C.A.L.A. Score API for company info by VAT number."""
        if not self.scala_key:
            return {}
        
        url = f"https://api.get-scala.com/score/v1/company/{vat_number}"
        headers = {"X-API-Key": self.scala_key, "User-Agent": "LeadFalcon/1.0"}
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            return {
                "company_name": data.get("company_name", ""),
                "registered_address": data.get("registered_address", {}),
                "employees_range": data.get("employees_range", ""),
                "revenue": data.get("revenue", ""),
                "ateco_description": data.get("ateco_description", ""),
                "source": "scala"
            }
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] SCALA error for VAT {vat_number}: {e}")
        
        return {}

    def find_emails_coldreach(self, domain: str, first_name: str = "", last_name: str = "") -> list[str]:
        """Find emails using ColdReach library or fallback regex extraction."""
        if COLDREACH_AVAILABLE and EmailFinder:
            try:
                finder = EmailFinder(domain)
                result = finder.find(first_name=first_name, last_name=last_name)
                if result and result.get("email"):
                    return [result["email"]]
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] ColdReach error for {domain}: {e}")
        
        # Fallback: return empty list (email will be extracted from website via extract_contacts_from_page)
        return []

    def extract_social_profiles(self, url: str) -> dict:
        """Extract social profiles and contacts using metaURL or fallback regex."""
        result = {
            "emails": [],
            "phones": [],
            "facebook": "",
            "instagram": "",
            "linkedin": "",
            "twitter": ""
        }
        
        if METAURL_AVAILABLE and metaurl:
            try:
                extracted = metaurl.extract(url)
                if extracted:
                    result["emails"] = extracted.get("emails", [])
                    result["phones"] = extracted.get("phones", [])
                    result["facebook"] = extracted.get("facebook", "")
                    result["instagram"] = extracted.get("instagram", "")
                    result["linkedin"] = extracted.get("linkedin", "")
                    result["twitter"] = extracted.get("twitter", "")
                    return result
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] metaURL error for {url}: {e}")
        
        # Fallback: extract from page HTML using existing method
        contacts = self.extract_contacts_from_page(url)
        result["emails"] = contacts.get("emails", [])
        result["phones"] = contacts.get("phones", [])
        
        return result

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
            
            # 1. Query Overpass API
            results = self.query_overpass(name)
            print(f"[{time.strftime('%H:%M:%S')}] Overpass found {len(results)} businesses in {name}")
            
            # 2. Query BizData API (2s delay between cities)
            time.sleep(2)
            bizdata_results = self.query_bizdata(name)
            print(f"[{time.strftime('%H:%M:%S')}] BizData found {len(bizdata_results)} results for {name}")
            
            # 3. Query Yelp API (if key present, 1s delay)
            yelp_results = []
            if self.yelp_key:
                time.sleep(1)
                yelp_results = self.query_yelp(name)
                print(f"[{time.strftime('%H:%M:%S')}] Yelp found {len(yelp_results)} results for {name}")
            
            # 4. Query GLEIF API (no delay needed)
            gleif_results = self.query_gleif(name)
            print(f"[{time.strftime('%H:%M:%S')}] GLEIF found {len(gleif_results)} results for {name}")
            
            # Web fallback if Overpass empty
            web_results = []
            if len(results) == 0:
                self.status_updated.emit("Overpass empty, trying web search...")
                print(f"[{time.strftime('%H:%M:%S')}] Overpass empty for {name}, trying web search...")
                web_results = self.search_web_fallback(name)
                print(f"[{time.strftime('%H:%M:%S')}] Web search found {len(web_results)} results for {name}")
            
            # 5. Query OpenAPI Imprese to enrich results (2s delay)
            time.sleep(2)
            openapi_results = self.query_openapi_imprese(name)
            print(f"[{time.strftime('%H:%M:%S')}] OpenAPI found {len(openapi_results)} results for {name}")
            
            # 6. Serper fallback if fewer than 3 leads from previous sources
            serper_results = []
            total_leads_so_far = len(results) + len(bizdata_results) + len(yelp_results) + len(gleif_results) + len(web_results) + len(openapi_results)
            if total_leads_so_far < 3 and self.serper_key:
                self.status_updated.emit(f"Fewer than 3 leads for {name}, trying Serper search...")
                print(f"[{time.strftime('%H:%M:%S')}] Fewer than 3 leads for {name}, trying Serper search...")
                serper_query = f"pelletteria {name} telefono email"
                serper_results = self.search_serper(serper_query)
                print(f"[{time.strftime('%H:%M:%S')}] Serper found {len(serper_results)} results for {name}")
            
            # Collect all raw leads from all sources into a single list
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
            
            # Process BizData results
            for biz in bizdata_results:
                if self._stopped:
                    break
                self.wait_if_paused()
                
                lead = {
                    "type": "ORGANIZATION",
                    "name": biz.get("name", ""),
                    "phone": biz.get("phone", ""),
                    "email": biz.get("email", ""),
                    "website": biz.get("website", ""),
                    "address": biz.get("address", ""),
                    "city": biz.get("city", name),
                    "source": "bizdata"
                }
                all_leads.append(lead)
            
            # Process Yelp results
            for biz in yelp_results:
                if self._stopped:
                    break
                self.wait_if_paused()
                
                lead = {
                    "type": "ORGANIZATION",
                    "name": biz.get("name", ""),
                    "phone": biz.get("phone", ""),
                    "email": "",
                    "website": biz.get("website", ""),
                    "address": biz.get("address", ""),
                    "city": biz.get("city", name),
                    "source": "yelp"
                }
                all_leads.append(lead)
            
            # Process GLEIF results
            for biz in gleif_results:
                if self._stopped:
                    break
                self.wait_if_paused()
                
                lead = {
                    "type": "ORGANIZATION",
                    "name": biz.get("name", ""),
                    "phone": "",
                    "email": "",
                    "website": "",
                    "address": biz.get("address", ""),
                    "city": name,
                    "region": biz.get("region", ""),
                    "vat_like_id": biz.get("vat_like_id", ""),
                    "source": "gleif"
                }
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
            
            # Process Serper results
            for serper_item in serper_results:
                if self._stopped:
                    break
                self.wait_if_paused()
                
                # Extract contacts from snippet
                snippet_contacts = self.extract_contacts_from_text(serper_item['snippet'])
                
                # Also try to fetch the page
                page_contacts = {}
                if serper_item.get('url'):
                    page_contacts = self.extract_contacts_from_page(serper_item['url'])
                
                # Merge contacts
                emails = list(set(snippet_contacts.get('emails', []) + page_contacts.get('emails', [])))
                phones = list(set(snippet_contacts.get('phones', []) + page_contacts.get('phones', [])))
                
                lead = {
                    "type": "ORGANIZATION",
                    "name": serper_item.get("title", ""),
                    "phone": phones[0] if phones else "",
                    "email": emails[0] if emails else "",
                    "website": serper_item.get("url", ""),
                    "city": name,
                    "source": "serper"
                }
                
                all_leads.append(lead)
            
            # Merge duplicates by normalized name + city
            merged = self._merge_leads(all_leads)
            
            # Enrich leads missing phone/email using OpenRegistry, ColdReach, metaURL
            enriched_count = 0
            for lead in merged:
                if self._stopped:
                    break
                self.wait_if_paused()
                
                needs_enrichment = not lead.get("phone") or not lead.get("email")
                
                # Try OpenRegistry enrichment for companies without phone/email
                if needs_enrichment and self.openapi_key and lead.get("name"):
                    time.sleep(2)  # Throttle OpenRegistry calls
                    registry_data = self.query_openregistry(lead["name"])
                    if registry_data:
                        if registry_data.get("telefono") and not lead.get("phone"):
                            lead["phone"] = registry_data["telefono"]
                        if registry_data.get("email") and not lead.get("email"):
                            lead["email"] = registry_data["email"]
                        if registry_data.get("sito_web") and not lead.get("website"):
                            lead["website"] = registry_data["sito_web"]
                        enriched_count += 1
                
                # Try ColdReach for email finding if website exists but no email
                if lead.get("website") and not lead.get("email"):
                    try:
                        from urllib.parse import urlparse
                        domain = urlparse(lead["website"]).netloc.replace("www.", "")
                        if domain:
                            emails = self.find_emails_coldreach(domain)
                            if emails:
                                lead["email"] = emails[0]
                                enriched_count += 1
                    except Exception as e:
                        print(f"[{time.strftime('%H:%M:%S')}] ColdReach domain parse error: {e}")
                
                # Try metaURL for social profiles and additional contacts
                if lead.get("website"):
                    social_data = self.extract_social_profiles(lead["website"])
                    if social_data.get("emails") and not lead.get("email"):
                        lead["email"] = social_data["emails"][0]
                    if social_data.get("phones") and not lead.get("phone"):
                        lead["phone"] = social_data["phones"][0]
                    # Add social profile links if present
                    social_links = []
                    if social_data.get("facebook"):
                        social_links.append(social_data["facebook"])
                    if social_data.get("instagram"):
                        social_links.append(social_data["instagram"])
                    if social_data.get("linkedin"):
                        social_links.append(social_data["linkedin"])
                    if social_data.get("twitter"):
                        social_links.append(social_data["twitter"])
                    if social_links:
                        lead["social_profiles"] = ", ".join(social_links)
            
            if enriched_count > 0:
                print(f"[{time.strftime('%H:%M:%S')}] Enriched {enriched_count} leads for {name}")
            
            # Score each merged lead with Groq AI
            scored_leads = [self._score_lead(lead) for lead in merged]
            
            # Save only leads with score >= 40
            saved = 0
            for lead in scored_leads:
                if lead.get('score', 50) >= 40:
                    self._save_lead(lead)
                    saved += 1
            
            # Emit progress with city name, leads found, total leads
            self.status_updated.emit(f"{name}: Raw={len(all_leads)}, Merged={len(merged)}, Saved={saved}")
            
            if len(results) == 0 and len(web_results) == 0 and len(openapi_results) == 0 and len(bizdata_results) == 0:
                print(f"[{time.strftime('%H:%M:%S')}] No leads found in {name}")
            
            print(f"[{time.strftime('%H:%M:%S')}] [{name}] Raw: {len(all_leads)}, Merged: {len(merged)}, Saved: {saved}")
            
            time.sleep(3)
        
        self.status_updated.emit("All cities processed.")
        self.finished.emit()
