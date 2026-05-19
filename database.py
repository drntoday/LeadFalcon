import os
import sqlite3

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
    """Return list of (id, name, region) for Italian cities.
    
    First tries to read from comuni.csv (semicolon delimiter, columns: name, region).
    If file doesn't exist, falls back to hardcoded list of 100 largest Italian cities.
    """
    # Try to read from CSV file
    if os.path.exists(CSV_PATH):
        cities = []
        try:
            with open(CSV_PATH, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for idx, line in enumerate(lines):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(';')
                    if len(parts) >= 2:
                        name = parts[0].strip()
                        region = parts[1].strip()
                        cities.append((idx, name, region))
            if cities:
                return cities
        except Exception as e:
            print(f"Error reading {CSV_PATH}: {e}")
    
    # Fallback to hardcoded list of 100 largest Italian cities
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
        (21, "Reggio Calabria", "Calabria"),
        (22, "Reggio Emilia", "Emilia-Romagna"),
        (23, "Perugia", "Umbria"),
        (24, "Livorno", "Toscana"),
        (25, "Ravenna", "Emilia-Romagna"),
        (26, "Cagliari", "Sardegna"),
        (27, "Foggia", "Puglia"),
        (28, "Rimini", "Emilia-Romagna"),
        (29, "Salerno", "Campania"),
        (30, "Ferrara", "Emilia-Romagna"),
        (31, "Sassari", "Sardegna"),
        (32, "Latina", "Lazio"),
        (33, "Giugliano in Campania", "Campania"),
        (34, "Monza", "Lombardia"),
        (35, "Siracusa", "Sicilia"),
        (36, "Pescara", "Abruzzo"),
        (37, "Bergamo", "Lombardia"),
        (38, "Forlì", "Emilia-Romagna"),
        (39, "Trento", "Trentino-Alto Adige"),
        (40, "Vicenza", "Veneto"),
        (41, "Terni", "Umbria"),
        (42, "Bolzano", "Trentino-Alto Adige"),
        (43, "Novara", "Piemonte"),
        (44, "Piacenza", "Emilia-Romagna"),
        (45, "Ancona", "Marche"),
        (46, "Andria", "Puglia"),
        (47, "Arezzo", "Toscana"),
        (48, "Udine", "Friuli-Venezia Giulia"),
        (49, "Cesena", "Emilia-Romagna"),
        (50, "Lecce", "Puglia"),
        (51, "Pesaro", "Marche"),
        (52, "Barletta", "Puglia"),
        (53, "Alessandria", "Piemonte"),
        (54, "La Spezia", "Liguria"),
        (55, "Pistoia", "Toscana"),
        (56, "Catanzaro", "Calabria"),
        (57, "Lucca", "Toscana"),
        (58, "Torre del Greco", "Campania"),
        (59, "Pisa", "Toscana"),
        (60, "Como", "Lombardia"),
        (61, "Varese", "Lombardia"),
        (62, "Treviso", "Veneto"),
        (63, "Pozzuoli", "Campania"),
        (64, "Asti", "Piemonte"),
        (65, "Caserta", "Campania"),
        (66, "Ragusa", "Sicilia"),
        (67, "Cremona", "Lombardia"),
        (68, "Trapani", "Sicilia"),
        (69, "Gela", "Sicilia"),
        (70, "Imola", "Emilia-Romagna"),
        (71, "Carrara", "Toscana"),
        (72, "Marsala", "Sicilia"),
        (73, "Viterbo", "Lazio"),
        (74, "Cosenza", "Calabria"),
        (75, "Altamura", "Puglia"),
        (76, "Carpi", "Emilia-Romagna"),
        (77, "Massa", "Toscana"),
        (78, "Potenza", "Basilicata"),
        (79, "Vigevano", "Lombardia"),
        (80, "Collegno", "Piemonte"),
        (81, "Ciampino", "Lazio"),
        (82, "Savona", "Liguria"),
        (83, "Faenza", "Emilia-Romagna"),
        (84, "Viareggio", "Toscana"),
        (85, "Acerra", "Campania"),
        (86, "Molfetta", "Puglia"),
        (87, "Nardò", "Puglia"),
        (88, "Crotone", "Calabria"),
        (89, "Siena", "Toscana"),
        (90, "Afragola", "Campania"),
        (91, "Vittoria", "Sicilia"),
        (92, "Manfredonia", "Puglia"),
        (93, "Campobasso", "Molise"),
        (94, "Avellino", "Campania"),
        (95, "Grosseto", "Toscana"),
    ]
    return cities
