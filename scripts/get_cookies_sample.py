import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from client import trackers
from client.api import Browser, ClientAPI
from client.config import BrowserConfig, CrawlConfig


def main():

    tracker_list = trackers.TrackerList()
    tracker_list.load(
        cache_dir=".tracker_cache",
        trackers={trackers.Detections.EasyPrivacy, trackers.Detections.OpenCookieDB},
    )

    try:
        asyncio.run(
            ClientAPI.process_batch(
                websites=[
                    "https://www.nytimes.com",
                    "https://www.bbc.com",
                    "https://www.reddit.com",
                    "https://www.theguardian.com",
                    "https://www.cnn.com",
                    "https://www.washingtonpost.com",
                ],
                browser_cfg=BrowserConfig(
                    tracker_list=tracker_list, browser_type=Browser.WEBKIT
                ),
                crawl_cfg=CrawlConfig(concurrency=4),
            )
        )

        asyncio.run(
            ClientAPI.process_batch(
                websites=[
                    "https://www.nytimes.com",
                    "https://www.bbc.com",
                    "https://www.reddit.com",
                    "https://www.theguardian.com",
                    "https://www.cnn.com",
                    "https://www.washingtonpost.com",
                ],
                browser_cfg=BrowserConfig(
                    tracker_list=tracker_list, browser_type=Browser.CHROMIUM
                ),
                crawl_cfg=CrawlConfig(concurrency=4),
            )
        )
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")


if __name__ == "__main__":
    main()
