import csv

TRACKING_CATEGORIES = {"Advertising", "Analytics", "Social Media"}


def parse_ocdb_list(text: str) -> dict:
    db = {}
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        name = row["Cookie / Data Key name"].strip()
        db[name] = {
            "category": row["Category"].strip(),
            "platform": row["Platform"].strip(),
            "description": row["Description"].strip(),
            "retention": row["Retention period"].strip(),
        }
    return db


def is_ocdb_tracker(cookie: dict, db: dict) -> bool:
    cookie_name = cookie["name"]
    entry = db.get(cookie_name)
    if entry is None:
        return False
    return entry["category"] in TRACKING_CATEGORIES
