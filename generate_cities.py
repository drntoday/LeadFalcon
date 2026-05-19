#!/usr/bin/env python3
"""Download ISTAT cities CSV and extract all Italian communes."""

import csv
import io
import os
import requests

ISTAT_URL = "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv"
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "comuni.csv")


def main():
    # Download the CSV
    print(f"Downloading from {ISTAT_URL}...")
    response = requests.get(ISTAT_URL)
    response.raise_for_status()
    
    # The ISTAT CSV has a multiline header (3 lines), so we need to join them
    lines = response.text.splitlines()
    # Join first 3 lines to form complete header
    header_line = lines[0] + lines[1] + lines[2]
    # Data starts from line 3
    data_lines = [header_line] + lines[3:]
    
    # Parse with csv.DictReader (delimiter=';')
    reader = csv.DictReader(data_lines, delimiter=';')
    
    # Extract all cities with name and region
    filtered_cities = []
    for row in reader:
        name = row.get("Denominazione", "").strip()
        region = row.get("Denominazione Regione", "").strip()
        if name and region:
            filtered_cities.append((name, region))
    
    # Write result to comuni.csv with columns name and region
    with open(OUTPUT_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['name', 'region'])
        for name, region in filtered_cities:
            writer.writerow([name, region])
    
    print(f"Number of cities written: {len(filtered_cities)}")


if __name__ == "__main__":
    main()
