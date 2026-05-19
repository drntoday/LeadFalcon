import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")


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
    """Return list of (id, name, region) for top 20 Italian cities."""
    cities = [
        (1, "Roma", "Lazio"),
        (2, "Milano", "Lombardia"),
        (3, "Napoli", "Campania"),
        (4, "Torino", "Piemonte"),
        (5, "Palermo", "Sicilia"),
        (6, "Genova", "Liguria"),
        (7, "Bologna", "Emilia-Romagna"),
        (8, "Firenze", "Toscana"),
        (9, "Catania", "Sicilia"),
        (10, "Bari", "Puglia"),
        (11, "Venezia", "Veneto"),
        (12, "Verona", "Veneto"),
        (13, "Messina", "Sicilia"),
        (14, "Padova", "Veneto"),
        (15, "Trieste", "Friuli-Venezia Giulia"),
        (16, "Brescia", "Lombardia"),
        (17, "Parma", "Emilia-Romagna"),
        (18, "Taranto", "Puglia"),
        (19, "Prato", "Toscana"),
        (20, "Modena", "Emilia-Romagna"),
    ]
    return cities
