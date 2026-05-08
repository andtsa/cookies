import asyncio
import csv
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.client_utils import Browser, ClientUtils


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
            output_path = os.path.join("../cookies_data", output_name)

            if os.path.exists(output_path):
                print(f"Skipping {domain}, already collected.")
                continue

            params = {
                "target_url": url,
                "rank": rank,
                "wait_time_seconds": 5
            }

            print(f"[{i+1}/{limit}] Processing {url}")

            try:
                await ClientUtils.run_for_page(
                    url=url,
                    wait_time_ms=5000,
                    output_dir="../cookies_data",
                    output_name=output_name,
                    browser=Browser.CHROMIUM,
                    params=params,
                    headless = True
                )

            except Exception as e:
                print(f"Failed for {url}: {e}")

                with open("failed_sites.txt", "a", encoding="utf-8") as fail_file:
                    fail_file.write(f"{domain}\n")

            await asyncio.sleep(2)


async def main():
    await process_sites("list_websites_1M.csv", limit=500)

if __name__ == "__main__":
    asyncio.run(main())
