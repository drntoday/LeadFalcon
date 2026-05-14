import sqlite3
import os
import csv
import traceback
import curl_cffi.requests

DB_PATH = os.path.join(os.path.dirname(__file__), "leadfalcon.db")
CSV_URL = "https://raw.githubusercontent.com/MatteoRagni/Italian-Comuni-List/master/comuni.csv"


def import_comuni_from_csv(csv_path, progress_callback=None):
    """Import Italian municipalities from a CSV file into the cities table.
    
    Args:
        csv_path: Path to the CSV file with columns 'nome' and 'regione'.
        progress_callback: Optional callback function(current_row, total_rows) called every 100 rows.
        
    Returns:
        Number of new rows inserted.
        
    Raises:
        FileNotFoundError: If the CSV file does not exist and cannot be downloaded.
        ValueError: If the CSV file is invalid or missing required columns.
    """
    # Check if file exists, if not download it
    if not os.path.exists(csv_path):
        try:
            response = curl_cffi.requests.get(CSV_URL)
            if response.status_code != 200:
                raise FileNotFoundError(f"Failed to download CSV: HTTP {response.status_code}")
            with open(csv_path, 'w', encoding='utf-8') as f:
                f.write(response.text)
        except Exception as e:
            raise FileNotFoundError(f"Could not download or access CSV file: {e}")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        inserted_count = 0
        batch_size = 100
        batch = []
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Validate that required columns exist
            if reader.fieldnames is None:
                raise ValueError("CSV file is empty or has no headers")
            
            # Check for required columns (support both Italian and English naming)
            valid_name_cols = {'nome', 'name'}
            valid_region_cols = {'regione', 'region'}
            
            has_name = any(col in reader.fieldnames for col in valid_name_cols)
            has_region = any(col in reader.fieldnames for col in valid_region_cols)
            
            if not has_name or not has_region:
                raise ValueError(f"CSV must contain 'nome' (or 'name') and 'regione' (or 'region') columns. Found: {reader.fieldnames}")
            
            # Count total rows for progress reporting
            rows_list = list(reader)
            total_rows = len(rows_list)
            
            for i, row in enumerate(rows_list):
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
                
                # Call progress callback every 100 rows
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
        
        # Final progress callback
        if progress_callback:
            progress_callback(total_rows, total_rows)
        
        conn.close()
        return inserted_count
        
    except Exception as e:
        print(f"Error importing comuni: {e}")
        traceback.print_exc()
        raise


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
