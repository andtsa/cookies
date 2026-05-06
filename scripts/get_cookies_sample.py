import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from client.client_utils import ClientUtils, Browser


asyncio.run(ClientUtils.process_batch(
    websites=[
        'https://www.nytimes.com',
        'https://www.bbc.com',
        'https://www.reddit.com',
        'https://www.theguardian.com',
        'https://www.cnn.com',
        'https://www.washingtonpost.com',
    ],
    concurrency=4
))
