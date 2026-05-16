import sqlite3
import os
import csv

DB_PATH = os.path.join(os.path.dirname(__file__), "leadfalcon.db")
CSV_PATH = "comuni.csv"


def import_comuni_from_csv(csv_path=None, progress_callback=None):
    """Import Italian municipalities from a local CSV file into the cities table.
    
    The CSV must use semicolons as delimiters and have the columns:
    'Denominazione in italiano' and 'Denominazione regione'.
    
    Args:
        csv_path: Path to the CSV file. Defaults to CSV_PATH.
        progress_callback: Optional function(current_row, total_rows) called every 100 rows.
        
    Returns:
        Number of new rows inserted, or -1 on error.
    """
    if csv_path is None:
        csv_path = CSV_PATH

    # Check that the file exists
    if not os.path.exists(csv_path):
        print(f"CSV file not found: {csv_path}. Please download it manually.")
        return -1

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        inserted_count = 0
        batch_size = 500
        batch = []

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')

            # Validate required columns
            if reader.fieldnames is None:
                raise ValueError("CSV file is empty or has no headers")

            required_cols = ['Denominazione in italiano', 'Denominazione regione']
            for col in required_cols:
                if col not in reader.fieldnames:
                    raise ValueError(f"Missing required column: {col}. Found: {reader.fieldnames}")

            rows_list = list(reader)
            total_rows = len(rows_list)

            for i, row in enumerate(rows_list):
                name = row['Denominazione in italiano'].strip()
                region = row['Denominazione regione'].strip()

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

                # Progress callback every 100 rows
                if progress_callback and (i + 1) % 100 == 0:
                    progress_callback(i + 1, total_rows)

            # Insert remaining rows
            if batch:
                cursor.executemany(
                    "INSERT OR IGNORE INTO cities (name, region) VALUES (?, ?)",
                    batch
                )
                inserted_count += cursor.rowcount
                conn.commit()

            if progress_callback:
                progress_callback(total_rows, total_rows)

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

    # Add plan column to cities table if it doesn't exist
    cursor.execute("PRAGMA table_info(cities)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'plan' not in columns:
        cursor.execute("ALTER TABLE cities ADD COLUMN plan TEXT")

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
