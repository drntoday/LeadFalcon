import csv
import os

SOURCE = "comuni.csv"
OUT_DIR = "comuni_parts"
CHUNK_SIZE = 200

os.makedirs(OUT_DIR, exist_ok=True)

with open(SOURCE, 'r', encoding='latin-1') as f:
    reader = csv.reader(f, delimiter=';')
    header = next(reader)
    part_num = 1
    rows = []
    for row in reader:
        rows.append(row)
        if len(rows) >= CHUNK_SIZE:
            filename = os.path.join(OUT_DIR, f"part_{part_num:04d}.csv")
            with open(filename, 'w', encoding='utf-8', newline='') as pf:
                writer = csv.writer(pf, delimiter=';')
                writer.writerow(header)
                writer.writerows(rows)
            rows = []
            part_num += 1
    # Last chunk
    if rows:
        filename = os.path.join(OUT_DIR, f"part_{part_num:04d}.csv")
        with open(filename, 'w', encoding='utf-8', newline='') as pf:
            writer = csv.writer(pf, delimiter=';')
            writer.writerow(header)
            writer.writerows(rows)

print(f"Done! Split into {part_num} parts in '{OUT_DIR}'.")
