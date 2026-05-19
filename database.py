import os
import sqlite3
import csv

DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")
CSV_PATH = "comuni.csv"


def initialize_db():
    """Create the leads table and unique indexes if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            name TEXT,
            phone TEXT,
            email TEXT,
            website TEXT,
            city TEXT,
            source TEXT,
            date_added DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Add score column if it doesn't exist
    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN score INTEGER DEFAULT 50")
    except sqlite3.OperationalError:
        # Column already exists
        pass
    
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email ON leads(email) WHERE email IS NOT NULL
    """)
    
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone) WHERE phone IS NOT NULL
    """)
    
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_name_city ON leads(name, city) WHERE name IS NOT NULL AND city IS NOT NULL
    """)
    
    conn.commit()
    conn.close()


def get_cities():
    """Return list of (row_index, name, region) for Italian cities.
    
    Reads from comuni.csv (semicolon delimiter, columns: name, region).
    If file doesn't exist, prints a message and returns an empty list.
    """
    if not os.path.exists(CSV_PATH):
        print("comuni.csv not found – please run generate_cities.py first")
        return []
    
    cities = []
    try:
        with open(CSV_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for idx, row in enumerate(reader):
                name = row.get('name', '').strip()
                region = row.get('region', '').strip()
                if name and region:
                    cities.append((idx, name, region))
    except Exception as e:
        print(f"Error reading {CSV_PATH}: {e}")
        return []
    
    return cities
