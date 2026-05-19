import time
import sqlite3
import groq
import json
from PySide6.QtCore import QObject, Signal, QThread
from duckduckgo_search import DDGS
from curl_cffi import requests
import random
import re
from email_validator import validate_email, EmailNotValidError
import phonenumbers
import database
from urllib.parse import urlparse
from datetime import datetime
from bs4 import BeautifulSoup

DEBUG = True

def debug_print(msg):
    if DEBUG:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

PLANNER_PROMPT = """
You are an expert lead-generation planner for Italian leather goods businesses. For the given city, generate a list of 20–30 search queries that will find retailers, boutiques, wholesalers, and artisans of leather bags, wallets, belts, and accessories. 
- Use Italian keywords extensively: pelletteria, borse in pelle, accessori moda, articoli da regalo, negozio di pelletteria, rivenditore, artigiano, produzione pelle, etc.
- Include queries that combine these with the city name and phrases like "telefono", "email", "contatti", "partita iva", "indirizzo".
- PRIORITISE Italian business directories ABOVE ALL OTHERS: site:paginegialle.it, site:kompass.it, site:infobel.com, site:yelp.it, site:infobel.it, site:italia-industria.it, site:paginebianche.it, site:telefonino.net. These must comprise at least 50% of all queries.
- Generate at least 5 queries that target individual owner/manager names, e.g., "titolare pelletteria Roma", "proprietario negozio borse Milano", "CEO pelletteria Firenze", "direttore negozio pelle Napoli", "fondatore pelletteria artigianale Torino".
- Avoid generic informational pages; focus ONLY on pages that could contain email/phone numbers (contact pages, directory listings, business profiles, "contatti" pages).
- Return ONLY a JSON array of strings, no other text. Example: ["pelletteria Roma telefono", "borse in pelle Milano contatti", "site:paginegialle.it pelletteria Torino", "titolare pelletteria Bologna", ...]
"""


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

    def _mark_city_done(self, city_id):
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE cities SET status = 'done' WHERE id = ?", (city_id,))
        conn.commit()
        conn.close()
        self.status_updated.emit("City marked as done.")

    def _extract_domain(self, url):
        parsed = urlparse(url)
        netloc = parsed.netloc
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        if ':' in netloc:
            netloc = netloc.split(':')[0]
        return netloc

    def _save_organization_lead(self, city, business_name, website, emails, phones, lead_score=None, role=None, linkedin_url=None):
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        email = emails[0] if emails else None
        phone = phones[0] if phones else None
        lead_id = None
        score = lead_score if lead_score is not None else 70
        debug_print(f"SAVE ORG: {business_name} | email={email} | phone={phone} | website={website}")
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO leads (record_type, business_name, email, phone, website, city, lead_score, role, linkedin_url) VALUES ('ORGANIZATION', ?, ?, ?, ?, ?, ?, ?, ?)",
                (business_name, email, phone, website, city, score, role, linkedin_url)
            )
            if cursor.rowcount > 0:
                lead_id = cursor.lastrowid
                print(f"[save_organization_lead] Business: {business_name}, Status: saved")
                self.lead_found.emit({
                    'record_type': 'ORGANIZATION',
                    'business_name': business_name,
                    'role': role or '',
                    'email': email,
                    'phone': phone,
                    'lead_score': score,
                    'linkedin_url': linkedin_url or '',
                    'source_urls': website
                })
            # Fetch the lead_id (for duplicate case)
            if lead_id is None:
                if email:
                    cursor.execute("SELECT lead_id FROM leads WHERE email = ? AND record_type='ORGANIZATION'", (email,))
                elif website:
                    cursor.execute("SELECT lead_id FROM leads WHERE business_name = ? AND city = ? AND website = ? AND record_type='ORGANIZATION'", (business_name, city, website))
                else:
                    cursor.execute("SELECT lead_id FROM leads WHERE business_name = ? AND city = ? AND website IS NULL AND record_type='ORGANIZATION'", (business_name, city))
                row = cursor.fetchone()
                if row:
                    lead_id = row[0]
                    print(f"[save_organization_lead] Business: {business_name}, Status: duplicate")
            return lead_id
        except Exception as e:
            self.status_updated.emit(f"Error saving organization lead: {e}")
            return None
        finally:
            conn.commit()
            conn.close()


    def _generate_and_store_plan(self, city_id, city_name):
        """Generate a list of 20-30 search queries for the given city and store in DB."""
        return self._generate_and_store_plan_with_message(city_id, city_name, f"City: {city_name}, Italy.")
    
    def _generate_and_store_plan_with_message(self, city_id, city_name, user_message):
        """Generate a list of search queries for the given city with a custom user message and store in DB."""
        self._ensure_groq_client()
        if self.groq_client is None:
            return []
        
        debug_print(f"Calling Groq for city: {city_name}")
        
        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-70b-versatile",
                messages=[
                    {"role": "system", "content": PLANNER_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=1000,
                temperature=0.8
            )
            content = response.choices[0].message.content
            debug_print(f"Groq raw response: {content[:200]}...")
            queries = json.loads(content)
            if not isinstance(queries, list):
                self.status_updated.emit("Invalid plan format: not a list")
                return []
        except Exception as e:
            self.status_updated.emit(f"Error generating plan: {e}")
            return []
        
        # Store plan in database (replace existing plan)
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE cities SET plan = ? WHERE id = ?", (json.dumps(queries), city_id))
        conn.commit()
        conn.close()
        debug_print(f"Parsed queries: {queries[:3]}... (total {len(queries)})")
        print(f"[_generate_and_store_plan] Queries generated: {len(queries)}, First 3: {queries[:3]}")
        return queries

    def run(self):
        self.status_updated.emit("Agent started.")
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, region, plan FROM cities WHERE status = 'pending' ORDER BY id")
        rows = cursor.fetchall()
        conn.close()
        debug_print(f"Pending cities in DB: {len(rows)}")

        if not rows:
            self.status_updated.emit("No pending cities.")
            self.finished.emit()
            return

        for city_row in rows:
            if self._stopped:
                break
            self.wait_if_paused()
            city_id, city_name, region, plan_json = city_row
            self.status_updated.emit(f"Processing city: {city_name}")
            debug_print(f"CITY PROGRESS: Starting {city_name} (region: {region})")
            
            # FIRST: Scrape Pagine Gialle as primary lead source
            debug_print(f"CITY PROGRESS: Calling scrape_pagine_gialle for {city_name}")
            pg_businesses = self.scrape_pagine_gialle(city_name, keyword="pelletteria")
            debug_print(f"PAGINE GIALLE RESULTS: Found {len(pg_businesses)} businesses on Pagine Gialle for {city_name}")
            
            # Save each business found on Pagine Gialle
            for biz in pg_businesses:
                if self._stopped:
                    break
                self.wait_if_paused()
                lead_id = self._save_organization_lead(
                    city=city_name,
                    business_name=biz.get("name", ""),
                    website=biz.get("website", ""),
                    emails=[],
                    phones=[biz.get("phone", "")] if biz.get("phone") else []
                )
                if lead_id and biz.get("website"):
                    domain = self._extract_domain(biz["website"])
                    if domain:
                        self._discover_employees(domain, lead_id)
                time.sleep(random.uniform(0.5, 1.5))
            
            # Fallback for small towns: if Pagine Gialle returns 0 results, try Google Maps via DuckDuckGo
            if len(pg_businesses) == 0:
                debug_print(f"FALLBACK: Pagine Gialle returned 0 results for {city_name}, trying Google Maps search")
                maps_query = f'site:google.com/maps "pelletteria {city_name}"'
                debug_print(f"FALLBACK search query: {maps_query}")
                maps_results = self.search_web(maps_query, max_results=5)
                for result in maps_results[:5]:
                    if self._stopped:
                        break
                    self.wait_if_paused()
                    contacts = self.extract_contacts_from_page(result['url'])
                    if contacts.get('emails') or contacts.get('phones'):
                        business_name = result.get('title', '')
                        website = result.get('url', '')
                        lead_id = self._save_organization_lead(
                            city=city_name,
                            business_name=business_name,
                            website=website,
                            emails=contacts.get('emails', []),
                            phones=contacts.get('phones', [])
                        )
                        if lead_id and website:
                            domain = self._extract_domain(website)
                            if domain:
                                self._discover_employees(domain, lead_id)
                    time.sleep(random.uniform(1, 3))
            
            # Parse existing plan or generate new one (secondary source, runs after Pagine Gialle)
            queries = []
            if plan_json:
                try:
                    queries = json.loads(plan_json)
                    if not isinstance(queries, list):
                        queries = []
                except json.JSONDecodeError:
                    queries = []
            
            if not queries:
                self.status_updated.emit("Generating search plan...")
                queries = self._generate_and_store_plan(city_id, city_name)
                if not queries:
                    self.status_updated.emit("No queries generated, marking city done.")
                    self._mark_city_done(city_id)
                    # Still emit progress for this city even with no queries
                    conn_progress = sqlite3.connect(database.DB_PATH)
                    cursor_progress = conn_progress.cursor()
                    cursor_progress.execute("SELECT COUNT(*) FROM leads WHERE city = ?", (city_name,))
                    row_progress = cursor_progress.fetchone()
                    leads_count_for_city = row_progress[0] if row_progress else 0
                    cursor_progress.execute("SELECT COUNT(*) FROM leads")
                    total_row = cursor_progress.fetchone()
                    total_leads = total_row[0] if total_row else 0
                    conn_progress.close()
                    self.progress_updated.emit(city_name, leads_count_for_city, total_leads)
                    continue
            
            # Execute each query deterministically
            for query in queries:
                if self._stopped:
                    break
                self.wait_if_paused()
                self.status_updated.emit(f"Searching: {query}")
                results = self.search_web(query)
                
                # Process first 5 results per query
                for result in results[:5]:
                    if self._stopped:
                        break
                    self.wait_if_paused()
                    contacts = self.extract_contacts_from_page(result['url'])
                    if contacts.get('emails') or contacts.get('phones'):
                        business_name = result.get('title', '')
                        website = result.get('url', '')
                        lead_id = self._save_organization_lead(
                            city=city_name,
                            business_name=business_name,
                            website=website,
                            emails=contacts.get('emails', []),
                            phones=contacts.get('phones', [])
                        )
                        # Discover employees if we have a domain
                        if lead_id and website:
                            domain = self._extract_domain(website)
                            if domain:
                                self._discover_employees(domain, lead_id)
                    time.sleep(random.uniform(1, 3))
                
                time.sleep(2)  # Between queries
            
            # Check how many leads found for this city
            conn_check = sqlite3.connect(database.DB_PATH)
            cursor_check = conn_check.cursor()
            cursor_check.execute("SELECT COUNT(*) FROM leads WHERE city = ?", (city_name,))
            row_check = cursor_check.fetchone()
            leads_count_for_city = row_check[0] if row_check else 0
            conn_check.close()
            
            # Fallback strategy: if less than 3 leads, generate new queries
            if leads_count_for_city < 3:
                self.status_updated.emit(f"Only {leads_count_for_city} leads found for {city_name}. Generating new queries with different angles...")
                fallback_msg = "The previous plan yielded very few leads. Please generate 10 new queries, focusing on different angles such as artisanal shops, wholesalers, and regional directories."
                new_queries = self._generate_and_store_plan_with_message(city_id, city_name, fallback_msg)
                
                # Re-run search loop for additional queries if new queries were generated
                if new_queries:
                    for query in new_queries:
                        if self._stopped:
                            break
                        self.wait_if_paused()
                        self.status_updated.emit(f"Searching (fallback): {query}")
                        results = self.search_web(query)
                        
                        for result in results[:5]:
                            if self._stopped:
                                break
                            self.wait_if_paused()
                            contacts = self.extract_contacts_from_page(result['url'])
                            if contacts.get('emails') or contacts.get('phones'):
                                business_name = result.get('title', '')
                                website = result.get('url', '')
                                lead_id = self._save_organization_lead(
                                    city=city_name,
                                    business_name=business_name,
                                    website=website,
                                    emails=contacts.get('emails', []),
                                    phones=contacts.get('phones', [])
                                )
                                if lead_id and website:
                                    domain = self._extract_domain(website)
                                    if domain:
                                        self._discover_employees(domain, lead_id)
                            time.sleep(random.uniform(1, 3))
                        
                        time.sleep(2)
            
            # Simple fallback: if still zero leads, perform last-ditch search with generic query
            conn_check2 = sqlite3.connect(database.DB_PATH)
            cursor_check2 = conn_check2.cursor()
            cursor_check2.execute("SELECT COUNT(*) FROM leads WHERE city = ?", (city_name,))
            row_check2 = cursor_check2.fetchone()
            leads_count_for_city = row_check2[0] if row_check2 else 0
            conn_check2.close()
            
            if leads_count_for_city == 0:
                self.status_updated.emit(f"Zero leads found for {city_name}. Performing last-ditch fallback search...")
                fallback_query = f"pelletteria {city_name}"
                debug_print(f"FALLBACK search for {city_name}: '{fallback_query}'")
                print(f"[run] Fallback query: {fallback_query}")
                fallback_results = self.search_web(fallback_query, max_results=5)
                
                for result in fallback_results:
                    if self._stopped:
                        break
                    self.wait_if_paused()
                    contacts = self.extract_contacts_from_page(result['url'])
                    if contacts.get('emails') or contacts.get('phones'):
                        business_name = result.get('title', '')
                        website = result.get('url', '')
                        lead_id = self._save_organization_lead(
                            city=city_name,
                            business_name=business_name,
                            website=website,
                            emails=contacts.get('emails', []),
                            phones=contacts.get('phones', [])
                        )
                        if lead_id and website:
                            domain = self._extract_domain(website)
                            if domain:
                                self._discover_employees(domain, lead_id)
                    time.sleep(random.uniform(1, 3))
            
            # Print total leads found for this city
            conn_final = sqlite3.connect(database.DB_PATH)
            cursor_final = conn_final.cursor()
            cursor_final.execute("SELECT COUNT(*) FROM leads WHERE city = ?", (city_name,))
            row_final = cursor_final.fetchone()
            leads_count_for_city = row_final[0] if row_final else 0
            conn_final.close()
            debug_print(f"CITY COMPLETE: {city_name} → {leads_count_for_city} leads saved in DB")
            print(f"[city] {city_name}: total leads found = {leads_count_for_city}")
            
            # Mark city done
            self._mark_city_done(city_id)
            
            # Emit progress
            conn = sqlite3.connect(database.DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM leads WHERE city = ?", (city_name,))
            row = cursor.fetchone()
            leads_count_for_city = row[0] if row else 0
            cursor.execute("SELECT COUNT(*) FROM leads")
            total_row = cursor.fetchone()
            total_leads = total_row[0] if total_row else 0
            conn.close()
            self.progress_updated.emit(city_name, leads_count_for_city, total_leads)

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
        debug_print(f"SEARCH: '{query}' → returned {len(results)} results")
        if len(results) > 0:
            debug_print(f"First result: {results[0]['title'][:80]} | {results[0]['url'][:80]}")
        print(f"[search_web] Query: {query}, Results: {len(results)}")
        if len(results) == 0:
            print(f"[search_web] Warning: No results returned for query '{query}'")
        time.sleep(2)
        return results

    def fetch_url(self, url):
        self.status_updated.emit(f"Fetching: {url}")
        try:
            response = requests.get(url, impersonate="chrome", timeout=10)
            debug_print(f"FETCH: {url} → status {response.status_code}")
            print(f"[fetch_url] URL: {url}, Status: {response.status_code}")
            if response.status_code == 200:
                return response.text
            else:
                self.status_updated.emit(f"Warning: Received status code {response.status_code}")
                return None
        except Exception as e:
            debug_print(f"FETCH: {url} → status ERROR")
            self.status_updated.emit(f"Error fetching URL: {e}")
            return None
        finally:
            time.sleep(random.uniform(1, 3))

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
        try:
            self.groq_client = groq.Client(api_key=key)
        except Exception as e:
            self.status_updated.emit(f"Error creating Groq client: {e}")
            self.groq_client = None
            return


    def extract_contacts_from_text(self, text):
        emails = set()
        phones = set()
        
        # Find all email addresses using regex
        email_pattern = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
        found_emails = re.findall(email_pattern, text)
        
        for email in found_emails:
            try:
                valid = validate_email(email)
                emails.add(valid.email)
            except EmailNotValidError:
                pass
        
        # Find all Italian phone numbers
        for match in phonenumbers.PhoneNumberMatcher(text, "IT"):
            formatted = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
            phones.add(formatted)
        
        return {"emails": list(emails), "phones": list(phones)}

    def extract_contacts_from_page(self, url):
        html = self.fetch_url(url)
        if html is None:
            debug_print(f"EXTRACT from {url}: emails=0, phones=0")
            print(f"[extract_contacts_from_page] URL: {url}, No contacts found (fetch failed)")
            return {"emails": [], "phones": []}
        contacts = self.extract_contacts_from_text(html)
        emails = contacts.get('emails', [])
        phones = contacts.get('phones', [])
        debug_print(f"EXTRACT from {url}: emails={len(emails)}, phones={len(phones)}")
        if emails:
            debug_print(f"  Sample email: {emails[0]}")
        if phones:
            debug_print(f"  Sample phone: {phones[0]}")
        if emails or phones:
            print(f"[extract_contacts_from_page] URL: {url}, Emails: {emails}, Phones: {phones}")
        else:
            print(f"[extract_contacts_from_page] URL: {url}, No contacts found")
        return contacts


    def scrape_pagine_gialle(self, city_name, keyword="pelletteria"):
        """Scrape Pagine Gialle for businesses in a given city."""
        debug_print(f"PAGINE GIALLE: Searching for '{keyword}' in {city_name}")
        url = f"https://www.paginegialle.it/ricerca/{keyword}/{city_name}"
        
        try:
            response = requests.get(url, impersonate="chrome", timeout=15)
            debug_print(f"PAGINE GIALLE: URL {url} → status {response.status_code}")
            
            # Check for CAPTCHA or error
            if response.status_code != 200:
                debug_print(f"PAGINE GIALLE: Error - status code {response.status_code}")
                return []
            
            # Check for CAPTCHA indicators in content
            if "captcha" in response.text.lower() or "verifica" in response.text.lower():
                debug_print(f"PAGINE GIALLE: CAPTCHA detected, returning empty list")
                return []
            
            time.sleep(3)  # 3-second sleep after request
            
            soup = BeautifulSoup(response.text, 'html.parser')
            businesses = []
            
            # Try to find listings using various common patterns
            # Look for elements with class containing "listing", "result", or structured data
            listing_containers = soup.find_all(class_=lambda x: x and any(word in x.lower() for word in ['listing', 'result', 'business', 'azienda']))
            
            # If no specific containers found, try finding all h2/h3 tags which often contain business names
            if not listing_containers:
                listing_containers = soup.find_all(['h2', 'h3'])
            
            for container in listing_containers:
                try:
                    biz_data = {"name": "", "phone": "", "address": "", "website": ""}
                    
                    # Extract business name from h2/h3 tags or title attributes
                    name_elem = container.find(['h2', 'h3', 'a'], class_=lambda x: x and any(word in x.lower() for word in ['title', 'name', 'business']))
                    if name_elem:
                        biz_data["name"] = name_elem.get_text(strip=True)
                    else:
                        # Try title attribute
                        title_attr = container.get('title', '')
                        if title_attr:
                            biz_data["name"] = title_attr
                        else:
                            # Try direct text content
                            biz_data["name"] = container.get_text(strip=True)[:100]
                    
                    if not biz_data["name"]:
                        continue
                    
                    # Extract phone number - look for tel: links or phone icon near text
                    phone_link = container.find('a', href=lambda x: x and x.startswith('tel:'))
                    if phone_link:
                        biz_data["phone"] = phone_link['href'].replace('tel:', '').strip()
                    else:
                        # Look for phone number patterns near phone icons
                        phone_icon = container.find(class_=lambda x: x and 'phone' in x.lower())
                        if phone_icon:
                            biz_data["phone"] = phone_icon.get_text(strip=True)
                    
                    # Extract address - look for structured address text
                    addr_elem = container.find(class_=lambda x: x and any(word in x.lower() for word in ['address', 'indirizzo', 'via', 'street']))
                    if addr_elem:
                        biz_data["address"] = addr_elem.get_text(strip=True)
                    else:
                        # Try to find address-like text (often contains Via, street numbers)
                        addr_match = re.search(r'(Via|Viale|Piazza|Corso)\s+[A-Za-z0-9\s]+,\s*\d+', container.get_text(), re.IGNORECASE)
                        if addr_match:
                            biz_data["address"] = addr_match.group(0)
                    
                    # Extract website URL - look for "Visita il sito" link
                    website_link = container.find('a', href=lambda x: x and ('visita' in x.lower() or 'sito' in x.lower() or 'website' in x.lower()))
                    if website_link:
                        biz_data["website"] = website_link['href']
                    else:
                        # Look for external links that might be websites
                        for link in container.find_all('a', href=True):
                            href = link['href']
                            if 'http' in href and 'paginegialle' not in href:
                                biz_data["website"] = href
                                break
                    
                    # Only add if we have at least a name
                    if biz_data["name"]:
                        businesses.append(biz_data)
                        debug_print(f"  Found: {biz_data['name'][:50]} | phone={biz_data['phone'][:20] if biz_data['phone'] else 'N/A'}")
                
                except Exception as e:
                    debug_print(f"PAGINE GIALLE: Error parsing listing: {e}")
                    continue
            
            debug_print(f"PAGINE GIALLE: Found {len(businesses)} businesses in {city_name}")
            return businesses
            
        except Exception as e:
            debug_print(f"PAGINE GIALLE: Exception occurred: {e}")
            return []


    def _save_person_lead(self, org_lead_id, email, domain, person_full_name=None, role=None, linkedin_url=None):
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO leads (record_type, parent_org_id, person_full_name, email, lead_score, source_urls, role, linkedin_url) VALUES ('PERSON', ?, ?, ?, 60, '', ?, ?)",
                (org_lead_id, person_full_name or '', email, role, linkedin_url)
            )
            if cursor.rowcount > 0:
                self.lead_found.emit({
                    'record_type': 'PERSON',
                    'parent_org_id': org_lead_id,
                    'person_full_name': person_full_name or '',
                    'role': role or '',
                    'email': email,
                    'lead_score': 60,
                    'linkedin_url': linkedin_url or '',
                    'source_urls': ''
                })
        finally:
            conn.commit()
            conn.close()

    def _discover_employees(self, domain, org_lead_id):
        query = f'"@{domain}"'
        snippets = self.search_web(query, max_results=10)
        concatenated_text = '\n'.join([s.get('snippet', '') for s in snippets])
        extracted = self.extract_contacts_from_text(concatenated_text)
        emails = extracted.get('emails', [])
        
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        try:
            for email in emails:
                # Check if email already exists in leads table
                cursor.execute("SELECT lead_id FROM leads WHERE email = ?", (email,))
                if cursor.fetchone():
                    continue
                # Insert as person lead
                self._save_person_lead(org_lead_id, email, domain)
        finally:
            conn.close()
        time.sleep(2)


if __name__ == "__main__":
    pass
