import asyncio
import csv
import os
import sys

# Get project root directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add project root to Python path
sys.path.append(BASE_DIR)

from client.client_utils import Browser, ClientUtils

# Absolute paths
CSV_PATH = os.path.join(BASE_DIR, "list_websites_1M.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "cookies_data")
FAILED_FILE = os.path.join(BASE_DIR, "failed_sites.txt")

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)


async def process_sites(csv_path: str, limit: int = 500):

    with open(csv_path, newline="", encoding="utf-8") as f:

        reader = csv.reader(f)

        for i, row in enumerate(reader):

            if i >= limit:
                break

            rank = row[0]
            domain = row[1]

            url = f"https://{domain}"

            output_name = f"{domain}.json"
            output_path = os.path.join(OUTPUT_DIR, output_name)

            # Skip if already collected
            if os.path.exists(output_path):
                print(f"Skipping {domain}, already collected.")
                continue

            params = {
                "target_url": url,
                "rank": rank,
                "wait_time_seconds": 10
            }

            print(f"\n[{i+1}/{limit}] Processing {url}")
            print(f"Saving to: {output_path}")

            try:

                await ClientUtils.run_for_page(
                    url=url,
                    wait_time_ms=10000,
                    output_dir=OUTPUT_DIR,
                    output_name=output_name,
                    browser=Browser.CHROMIUM,
                    params=params,
                    headless=False
                )

                print(f"Finished {domain}")

            except Exception as e:

                print(f"Failed for {url}: {e}")

                with open(FAILED_FILE, "a", encoding="utf-8") as fail_file:
                    fail_file.write(f"{domain}\n")

            await asyncio.sleep(2)


async def main():
    await process_sites(CSV_PATH, limit=500)


if __name__ == "__main__":
    asyncio.run(main())