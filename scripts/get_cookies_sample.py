import asyncio
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from client import trackers
from client.client_utils import Browser, ClientUtils


def signal_handler(signum, frame):
    print("\nReceived Ctrl-C, shutting down...")
    sys.exit(0)


# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)

tracker_list = trackers.TrackerList()
tracker_list.load(
    cache_dir=".tracker_cache",
    trackers={trackers.Detections.EasyPrivacy, trackers.Detections.OpenCookieDB},
)

try:
    asyncio.run(
        ClientUtils.process_batch(
            websites=[
                "https://www.nytimes.com",
                "https://www.bbc.com",
                "https://www.reddit.com",
                "https://www.theguardian.com",
                "https://www.cnn.com",
                "https://www.washingtonpost.com",
            ],
            concurrency=4,
            tracker_list=tracker_list,
            browser=Browser.WEBKIT,
        )
    )
except KeyboardInterrupt:
    print("\nProcess interrupted by user.")
