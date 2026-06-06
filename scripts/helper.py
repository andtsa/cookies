# import os
# # number of files in each category in cookies_data
# base_dir = "cookies_data"

# for category in os.listdir(base_dir):
#     category_path = os.path.join(base_dir, category)

#     if os.path.isdir(category_path):
#         file_count = sum(
#             1 for f in os.listdir(category_path)
#             if os.path.isfile(os.path.join(category_path, f))
#         )

#         print(f"{category}: {file_count} files")


import csv

INPUT_BIG = "list_websites_1M.csv"
INPUT_HEALTH = "health_websites.csv"
OUTPUT = "health_websites_sorted_with_positions.csv"  # overwrite in place

# Build a lookup: domain -> row number in the big file
print("Reading big list...")
domain_to_row = {}
with open(INPUT_BIG, newline="", encoding="utf-8") as f:
    reader = csv.reader(f)
    for line_number, row in enumerate(reader):
        if len(row) < 2:
            continue
        domain = row[1].strip()
        domain_to_row[domain] = line_number  # 0-indexed line number

print(f"Loaded {len(domain_to_row)} domains from big list.")

# Read health websites
with open(INPUT_HEALTH, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# Add position column
not_found = []
for row in rows:
    domain = row["domain"].strip()
    pos = domain_to_row.get(domain)
    if pos is not None:
        row["initial_list_row"] = pos
    else:
        row["initial_list_row"] = "NOT FOUND"
        not_found.append(domain)

# Sort by health_score descending and re-rank
rows.sort(key=lambda r: float(r["health_score"]), reverse=True)
for i, row in enumerate(rows, start=1):
    row["rank"] = i

# Write back with new column
fieldnames = ["rank", "domain", "health_score", "initial_list_row"]
with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)

print(f"Done. Written to {OUTPUT}")
if not_found:
    print(f"Could not find {len(not_found)} domains: {not_found}")