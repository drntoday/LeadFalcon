import sqlite3
import os
import csv
import traceback

DB_PATH = os.path.join(os.path.dirname(__file__), "leadfalcon.db")
CSV_PATH = "comuni.csv"              # kept for reference only, not used
PARTS_DIR = "comuni_parts"


def import_comuni_from_parts(parts_dir=None, progress_callback=None):
    """Import municipalities from pre-split CSV parts (200 rows each)."""
    if parts_dir is None:
        parts_dir = PARTS_DIR

    if not os.path.isdir(parts_dir):
        print(f"Directory '{parts_dir}' not found. Please run split_csv.py first.")
        return -1

    # Get all part files sorted
    part_files = sorted([
        f for f in os.listdir(parts_dir)
        if f.startswith("part_") and f.endswith(".csv")
    ])
    if not part_files:
        print(f"No part files found in '{parts_dir}'.")
        return -1

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Ensure csv_import_status table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS csv_import_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                part_file TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'pending',
                inserted_count INTEGER DEFAULT 0,
                processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Mark any newly discovered parts as pending if not already recorded
        for fname in part_files:
            cursor.execute(
                "INSERT OR IGNORE INTO csv_import_status (part_file, status) VALUES (?, 'pending')",
                (fname,)
            )
        conn.commit()

        # Get list of pending parts in sorted order
        cursor.execute(
            "SELECT part_file FROM csv_import_status WHERE status = 'pending' ORDER BY part_file"
        )
        pending = [row[0] for row in cursor.fetchall()]

        total_parts = len(pending)
        total_inserted = 0

        for idx, fname in enumerate(pending, 1):
            filepath = os.path.join(parts_dir, fname)
            if not os.path.exists(filepath):
                # Mark as failed and skip
                cursor.execute(
                    "UPDATE csv_import_status SET status = 'error' WHERE part_file = ?",
                    (fname,)
                )
                conn.commit()
                continue

            inserted_count = 0
            batch_size = 100
            batch = []

            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                # Validate required columns
                required = ['Denominazione in italiano', 'Denominazione Regione']
                if not all(col in (reader.fieldnames or []) for col in required):
                    raise ValueError(f"Missing columns in {fname}")

                rows_list = list(reader)
                for row in rows_list:
                    name = row['Denominazione in italiano'].strip()
                    region = row['Denominazione Regione'].strip()
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
                # Remainder
                if batch:
                    cursor.executemany(
                        "INSERT OR IGNORE INTO cities (name, region) VALUES (?, ?)",
                        batch
                    )
                    inserted_count += cursor.rowcount
                    conn.commit()

            # Update part status
            cursor.execute(
                "UPDATE csv_import_status SET status = 'done', inserted_count = ?, processed_at = CURRENT_TIMESTAMP WHERE part_file = ?",
                (inserted_count, fname)
            )
            conn.commit()
            total_inserted += inserted_count

            if progress_callback:
                progress_callback(idx, total_parts, total_inserted, f"Part {idx}/{total_parts}")

        conn.close()
        return total_inserted

    except Exception as e:
        print(f"Error importing from parts: {e}")
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
