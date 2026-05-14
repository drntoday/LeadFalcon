import time
import sqlite3
import hashlib
import groq
import json
from PySide6.QtCore import QObject, Signal, Slot, QThread
from duckduckgo_search import DDGS
from curl_cffi import requests
import random
import re
from email_validator import validate_email, EmailNotValidError
import phonenumbers
import database
from urllib.parse import urlparse


SYSTEM_PROMPT = """
You are an expert Italian B2B lead researcher. Your goal is to find high-quality contact details (email, phone, owner name, buyer contacts) of leather-goods retailers, boutiques, and wholesalers in the current city. 

You have access to tools: 
- search_web: search for businesses, contact pages, directories.
- fetch_url: retrieve the full text of a webpage.
- extract_contacts_from_page: fetch a URL and automatically extract emails and phone numbers.
- query_db: run SELECT queries to check for duplicates, see existing leads, or check city/keyword status.
- save_lead: store a discovered lead (organization or person) after verifying it's not a duplicate.
- google_places_search: get structured business data (name, address, phone, website) from Google Places.
- mark_city_done: call this when you are confident you have exhausted the city.
- discover_employees: search for employee email addresses from an organization's domain and save them.

Strategy:
1. Start by searching the web with multiple Italian phrases (pelletteria, borse in pelle, negozio accessori moda, rivenditore, etc.) combined with the city name.
2. For promising URLs from search results, use extract_contacts_from_page to quickly get contacts. If a page has no contact info, skip it.
3. If you find a business website, save the organization lead with a score based on confidence (70-90). Then use discover_employees on its domain.
4. Also use google_places_search to find brick-and-mortar stores.
5. Always check for duplicates via query_db before saving. 
6. If a city yields very few results, try broader queries (e.g., "negozi abbigliamento {city}").
7. When you have tried multiple angles and found all reasonable leads, call mark_city_done.
"""


class LeadAgent(QObject):
    status_updated = Signal(str)
    lead_found = Signal(dict)
    progress_updated = Signal(str, int, int)
    finished = Signal()

    TOOLS = []

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self._paused = False
        self._stopped = False
        self.settings = settings if settings is not None else {}
        self.groq_client = None
        self._register_tools()

    def _register_tools(self):
        self.TOOLS = [
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Search the web for the given query and return a list of results with title, url, snippet.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "max_results": {"type": "integer", "default": 10}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "fetch_url",
                    "description": "Fetch the full HTML text of a given URL. Use this to extract contact details.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_contacts_from_page",
                    "description": "Fetch a URL and extract emails and phone numbers found on it. Returns a dictionary with 'emails' and 'phones' lists.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "query_db",
                    "description": "Execute a read-only SQL query on the local database and return results as JSON. Use this to check for duplicates or retrieve existing data.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string"}
                        },
                        "required": ["sql"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "save_lead",
                    "description": "Save a new lead (organization or person) to the database. Provide all available details. The method will deduplicate automatically. Returns success status.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "record_type": {"type": "string", "enum": ["ORGANIZATION", "PERSON"]},
                            "business_name": {"type": "string"},
                            "person_full_name": {"type": "string"},
                            "role": {"type": "string"},
                            "email": {"type": "string"},
                            "phone": {"type": "string"},
                            "website": {"type": "string"},
                            "linkedin_url": {"type": "string"},
                            "city": {"type": "string"},
                            "lead_score": {"type": "integer", "minimum": 0, "maximum": 100},
                            "parent_org_id": {"type": "integer"}
                        },
                        "required": ["record_type", "city", "lead_score"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "google_places_search",
                    "description": "Search Google Places for businesses matching a keyword in a city. Returns structured business data (name, address, phone, website).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "keyword": {"type": "string", "default": "pelletteria"}
                        },
                        "required": ["city"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "mark_city_done",
                    "description": "Mark a city as completed in the database.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city_id": {"type": "integer"}
                        },
                        "required": ["city_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "discover_employees",
                    "description": "Search for employee email addresses from a given domain (e.g., '@example.com') and save them as person leads linked to the organization lead ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string"},
                            "org_lead_id": {"type": "integer"}
                        },
                        "required": ["domain", "org_lead_id"]
                    }
                }
            }
        ]

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

    # UNUSED METHOD - commented out as per cleanup
    # def _mark_search_result_extracted(self, result_id):
    #     conn = sqlite3.connect(database.DB_PATH)
    #     cursor = conn.cursor()
    #     cursor.execute("UPDATE search_results SET extracted = 1 WHERE id = ?", (result_id,))
    #     conn.commit()
    #     conn.close()

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
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO leads (record_type, business_name, email, phone, website, city, lead_score, role, linkedin_url) VALUES ('ORGANIZATION', ?, ?, ?, ?, ?, ?, ?, ?)",
                (business_name, email, phone, website, city, score, role, linkedin_url)
            )
            if cursor.rowcount > 0:
                lead_id = cursor.lastrowid
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
            return lead_id
        except Exception as e:
            self.status_updated.emit(f"Error saving organization lead: {e}")
            return None
        finally:
            conn.commit()
            conn.close()

    # UNUSED METHOD - commented out as per cleanup
    # def _guess_business_name(self, title, url):
    #         if title:
    #             for sep in [' - ', ' | ', ' – ']:
    #                 if sep in title:
    #                     return title.split(sep)[0].strip()
    #             return title.strip()
    #         # Extract domain from URL
    #         domain = url
    #         domain = re.sub(r'^https?://', '', domain)
    #         domain = re.sub(r'^www\.', '', domain)
    #         domain = domain.split('/')[0]
    #         return domain

    def run(self):
        self.status_updated.emit("Agent started.")
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, region FROM cities WHERE status = 'pending' ORDER BY id")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            self.status_updated.emit("No pending cities.")
            self.finished.emit()
            return

        for city_row in rows:
            if self._stopped:
                break
            self.wait_if_paused()
            city_id, city_name, region = city_row
            self.status_updated.emit(f"Processing city: {city_name}")
            self.progress_updated.emit(city_name, 0, 0)

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Current city: {city_name} (ID: {city_id}). Find leather-related business leads. Start by checking if we already have keywords or search queries for this city, then proceed."}
            ]

            turn_counter = 0
            max_turns = 30

            while True:
                if self._stopped:
                    break
                self.wait_if_paused()

                turn_counter += 1
                if turn_counter > max_turns:
                    self.status_updated.emit("Max turns reached for city, moving on.")
                    break

                try:
                    response = self._groq_chat(messages)
                except (IndexError, KeyError, AttributeError) as e:
                    self.status_updated.emit(f"Invalid response from Groq: {str(e)}")
                    break
                if response is None:
                    break

                try:
                    message = response.choices[0].message
                except Exception as e:
                    self.status_updated.emit(f"Error accessing response message: {str(e)}")
                    break

                if message.content:
                    truncated_content = message.content[:80] + "..." if len(message.content) > 80 else message.content
                    self.status_updated.emit(f"Groq: {truncated_content}")

                if message.tool_calls:
                    assistant_message = {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": []
                    }
                    for tc in message.tool_calls:
                        assistant_message["tool_calls"].append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        })
                    messages.append(assistant_message)

                    for tool_call in message.tool_calls:
                        result_str = self._execute_tool_call(tool_call)
                        self.status_updated.emit(f"Tool {tool_call.function.name} executed.")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result_str
                        })
                else:
                    messages.append({"role": "user", "content": "What is your next action? Please use a tool."})

            self._mark_city_done(city_id)

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
        time.sleep(2)
        return results

    def fetch_url(self, url):
        self.status_updated.emit(f"Fetching: {url}")
        try:
            response = requests.get(url, impersonate="chrome", timeout=10)
            if response.status_code == 200:
                return response.text
            else:
                self.status_updated.emit(f"Warning: Received status code {response.status_code}")
                return None
        except Exception as e:
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

    def _groq_chat(self, messages):
        self._ensure_groq_client()
        if self.groq_client is None:
            return None
        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-70b-versatile",
                messages=messages,
                tools=(self.TOOLS if len(self.TOOLS) > 0 else None),
                tool_choice="auto",
                max_tokens=1000,
                temperature=0.7
            )
            return response
        except Exception as e:
            self.status_updated.emit(f"Groq API error: {str(e)}")
            return None

    # UNUSED METHOD - commented out as per cleanup
    # def generate_keywords_for_city(self, city_name):
    #         self._ensure_groq_client()
    #         if self.groq_client is None:
    #             return []
    #         prompt = f"Generate 8 search queries to find Italian leather goods retailers, boutiques, and wholesalers in {city_name}. Use Italian words like 'pelletteria', 'borse in pelle', 'negozio accessori moda', and 'rivenditore'. Return only a JSON array of strings, no explanation."
    #         response = self.groq_client.chat.completions.create(
    #             model="llama-3.1-70b-versatile",
    #             messages=[{"role": "user", "content": prompt}],
    #             temperature=0.7,
    #             max_tokens=500
    #         )
    #         try:
    #             import json
    #             keywords = json.loads(response.choices[0].message.content)
    #             return keywords
    #         except Exception:
    #             self.status_updated.emit("Failed to parse keyword response.")
    #             return []
    #


    # UNUSED METHOD - commented out as per cleanup
    # def _get_or_create_keyword(self, city_id, keyword_text):
    #         keyword_hash = hashlib.sha256(f"{city_id}{keyword_text}".encode()).hexdigest()
    #         conn = None
    #         try:
    #             conn = sqlite3.connect(database.DB_PATH)
    #             cursor = conn.cursor()
    #             cursor.execute("SELECT id FROM keywords WHERE keyword_hash = ?", (keyword_hash,))
    #             row = cursor.fetchone()
    #             if row:
    #                 return row[0]
    #             cursor.execute("INSERT INTO keywords (city_id, keyword_hash, keyword_text) VALUES (?, ?, ?)",
    #                            (city_id, keyword_hash, keyword_text))
    #             conn.commit()
    #             return cursor.lastrowid
    #         except Exception as e:
    #             self.status_updated.emit(f"Keyword error: {e}")
    #             return None
    #         finally:
    #             if conn:
    #                 conn.close()
    #


    # UNUSED METHOD - commented out as per cleanup
    # def _get_or_create_search_query(self, city_id, keyword_id):
    #         conn = None
    #         try:
    #             conn = sqlite3.connect(database.DB_PATH)
    #             cursor = conn.cursor()
    #             cursor.execute("SELECT id FROM search_queries WHERE keyword_id = ?", (keyword_id,))
    #             row = cursor.fetchone()
    #             if row:
    #                 self.status_updated.emit("Search query already recorded, skipping.")
    #                 return None
    #             cursor.execute("INSERT INTO search_queries (city_id, keyword_id, source) VALUES (?, ?, ?)",
    #                            (city_id, keyword_id, 'web'))
    #             conn.commit()
    #             return cursor.lastrowid
    #         except Exception as e:
    #             self.status_updated.emit(f"Search query error: {e}")
    #             return None
    #         finally:
    #             if conn:
    #                 conn.close()
    #


    # UNUSED METHOD - commented out as per cleanup
    # def _store_search_results(self, query_id, results):
    #         conn = None
    #         try:
    #             conn = sqlite3.connect(database.DB_PATH)
    #             cursor = conn.cursor()
    #             for result in results:
    #                 cursor.execute(
    #                     "INSERT OR IGNORE INTO search_results (query_id, url, title, snippet) VALUES (?, ?, ?, ?)",
    #                     (query_id, result.get("url", ""), result.get("title", ""), result.get("snippet", ""))
    #                 )
    #             conn.commit()
    #         except Exception as e:
    #             self.status_updated.emit(f"Failed to store search results: {e}")
    #         finally:
    #             if conn:
    #                 conn.close()
    #


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
            return {"emails": [], "phones": []}
        return self.extract_contacts_from_text(html)

    def search_google_places(self, city, query="pelletteria"):
        places_key = self.settings.get("places_key")
        if not places_key:
            self.status_updated.emit("Google Places API key not set.")
            return []
        
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": places_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.internationalPhoneNumber,places.websiteUri,places.id"
        }
        json_body = {"textQuery": f"{query} in {city}, Italy"}
        
        try:
            response = requests.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json=json_body,
                impersonate="chrome",
                timeout=15
            )
            
            if response.status_code != 200:
                self.status_updated.emit(f"Google Places API error: status {response.status_code}")
                return []
            
            data = response.json()
            results = []
            for place in data.get("places", []):
                display_name = place.get("displayName", {})
                results.append({
                    "name": display_name.get("text", ""),
                    "address": place.get("formattedAddress", ""),
                    "phone": place.get("internationalPhoneNumber", ""),
                    "website": place.get("websiteUri", ""),
                    "place_id": place.get("id", "")
                })
            
            self.status_updated.emit(f"Google Places: found {len(results)} results for {city}")
            return results
        except Exception as e:
            self.status_updated.emit(f"Google Places error: {e}")
            return []

    # UNUSED METHOD - commented out as per cleanup
    # def _process_google_places(self, city_name):
    #         places = self.search_google_places(city_name)
    #         for place in places:
    #             if self._stopped:
    #                 break
    #             self.wait_if_paused()
    #             org_lead_id = self._save_organization_lead(
    #                 city_name,
    #                 place["name"],
    #                 place["website"],
    #                 emails=[],
    #                 phones=[place["phone"]]
    #             )
    #             if org_lead_id is not None and place["website"]:
    #                 domain = self._extract_domain(place["website"])
    #                 if domain:
    #                     self._discover_employees(domain, org_lead_id)
    #             time.sleep(1)
    #


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

    def _execute_query(self, sql):
        """Execute a read-only SELECT query and return results as JSON."""
        if not sql.strip().upper().startswith("SELECT"):
            return json.dumps({"error": "Only SELECT queries are allowed"})
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            return json.dumps([list(row) for row in rows])
        except Exception as e:
            return json.dumps({"error": str(e)})
        finally:
            conn.close()

    def _save_lead_from_agent(self, args):
        """Save a lead based on record_type from agent tool call arguments."""
        record_type = args.get("record_type")
        if record_type == "PERSON":
            org_lead_id = args.get("parent_org_id")
            email = args.get("email")
            domain = args.get("domain", "")
            person_full_name = args.get("person_full_name")
            role = args.get("role")
            linkedin_url = args.get("linkedin_url")
            result = self._save_person_lead(org_lead_id, email, domain, person_full_name, role, linkedin_url)
            if result:
                return f"Lead saved with ID {result}"
            else:
                return "Duplicate, lead already exists"
        elif record_type == "ORGANIZATION":
            city = args["city"]
            business_name = args.get("business_name", "")
            website = args.get("website", "")
            emails = [args["email"]] if args.get("email") else []
            phones = [args["phone"]] if args.get("phone") else []
            lead_score = args.get("lead_score", 70)
            role = args.get("role")
            linkedin_url = args.get("linkedin_url")
            lead_id = self._save_organization_lead(city, business_name, website, emails, phones, lead_score, role, linkedin_url)
            if lead_id:
                return f"Lead saved with ID {lead_id}"
            else:
                return "Duplicate, lead already exists"
        else:
            return "Invalid record_type"

    def _execute_tool_call(self, tool_call):
        """Execute a tool call returned by Groq and return the result as a string."""
        try:
            func_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            
            if func_name == "search_web":
                results = self.search_web(query=args["query"], max_results=args.get("max_results", 10))
                return json.dumps(results)
            elif func_name == "fetch_url":
                html = self.fetch_url(url=args["url"])
                if html is None:
                    return ""
                return html[:8000]
            elif func_name == "extract_contacts_from_page":
                result = self.extract_contacts_from_page(url=args["url"])
                return json.dumps(result)
            elif func_name == "query_db":
                result = self._execute_query(args["sql"])
                return result
            elif func_name == "save_lead":
                result = self._save_lead_from_agent(args)
                return result
            elif func_name == "google_places_search":
                results = self.search_google_places(city=args["city"], query=args.get("keyword", "pelletteria"))
                return json.dumps(results)
            elif func_name == "mark_city_done":
                self._mark_city_done(city_id=args["city_id"])
                return "City marked done"
            elif func_name == "discover_employees":
                self._discover_employees(domain=args["domain"], org_lead_id=args["org_lead_id"])
                return "Employee discovery complete"
            else:
                return f"Unknown tool: {func_name}"
        except Exception as e:
            self.status_updated.emit(f"Tool error: {str(e)}")
            return f"Error: {str(e)}"
