import sqlite3
import os
import csv
import traceback

DB_PATH = os.path.join(os.path.dirname(__file__), "leadfalcon.db")


def import_comuni_from_csv(csv_path):
    """Import Italian municipalities from a CSV file into the cities table.
    
    Args:
        csv_path: Path to the CSV file with columns 'name' and 'region'.
        
    Returns:
        Number of new rows inserted, or -1 if an error occurred.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        inserted_count = 0
        batch_size = 100
        batch = []
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Support both column naming conventions
                name = row.get('nome', row.get('name', '')).strip()
                region = row.get('regione', row.get('region', '')).strip()
                
                if name and region:
                    batch.append((name, region))
                    
                    if len(batch) >= batch_size:
                        cursor.executemany(
                            "INSERT OR IGNORE INTO cities (name, region) VALUES (?, ?)",
                            batch
                        )
                        inserted_count += cursor.rowcount
                        conn.commit()
                        batch = []
        
        # Insert remaining rows
        if batch:
            cursor.executemany(
                "INSERT OR IGNORE INTO cities (name, region) VALUES (?, ?)",
                batch
            )
            inserted_count += cursor.rowcount
            conn.commit()
        
        conn.close()
        return inserted_count
        
    except Exception as e:
        print(f"Error importing comuni: {e}")
        traceback.print_exc()
        return -1


def initialize_db():
    """Initialize the database and create tables if they do not exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create cities table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            region TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)

    # Create keywords table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city_id INTEGER REFERENCES cities(id),
            keyword_hash TEXT UNIQUE NOT NULL,
            keyword_text TEXT NOT NULL
        )
    """)

    # Create search_queries table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city_id INTEGER REFERENCES cities(id),
            keyword_id INTEGER REFERENCES keywords(id),
            source TEXT,
            executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create search_results table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id INTEGER REFERENCES search_queries(id),
            url TEXT UNIQUE NOT NULL,
            title TEXT,
            snippet TEXT,
            extracted INTEGER DEFAULT 0
        )
    """)

    # Create leads table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL CHECK(record_type IN ('ORGANIZATION','PERSON')),
            parent_org_id INTEGER,
            business_name TEXT,
            person_full_name TEXT,
            role TEXT,
            email TEXT,
            phone TEXT,
            website TEXT,
            linkedin_url TEXT,
            source_urls TEXT,
            city TEXT,
            lead_score INTEGER,
            date_added DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create unique indexes on leads table
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email ON leads(email) WHERE email IS NOT NULL
    """)

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone) WHERE phone IS NOT NULL
    """)

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_business ON leads(business_name, city, website) 
        WHERE record_type='ORGANIZATION' AND business_name IS NOT NULL
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    initialize_db()
