import asyncio
import csv
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.client_utils import Browser, ClientUtils
from client.trackers import Detections, TrackerList


async def process_sites(
    csv_path: str, limit: int = 500, tracker_list: TrackerList | None = None
):
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

            params = {"target_url": url, "rank": rank, "wait_time_seconds": 5}

            print(f"[{i + 1}/{limit}] Processing {url}")

            try:
                await ClientUtils.run_for_page(
                    url=url,
                    wait_time_ms=5000,
                    output_dir="../cookies_data",
                    output_name=output_name,
                    browser=Browser.CHROMIUM,
                    params=params,
                    headless=True,
                    tracker_list=tracker_list,
                )

            except Exception as e:
                print(f"Failed for {url}: {e}")

                with open("failed_sites.txt", "a", encoding="utf-8") as fail_file:
                    fail_file.write(f"{domain}\n")

            await asyncio.sleep(2)


async def main():
    tracker_list = TrackerList()
    tracker_list.load(
        cache_dir=".tracker_cache",
        trackers={Detections.OpenCookieDB, Detections.EasyPrivacy},
    )

    await process_sites("list_websites_1M.csv", limit=500, tracker_list=tracker_list)


if __name__ == "__main__":
    asyncio.run(main())
