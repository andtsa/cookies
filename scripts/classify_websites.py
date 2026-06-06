# import sys
# import os

# sys.path.insert(
#     0,
#     os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# )

# import asyncio
# import csv
# from pathlib import Path

# from playwright.async_api import async_playwright

# from classifier.sensitive_classifier import SensitiveClassifier


# INPUT_CSV = "list_websites_1M.csv"

# OUTPUT_CSV = "health_websites.csv"

# MAX_HEALTH = 120

# CONCURRENCY = 20

# TIMEOUT_MS = 30000


# classifier = SensitiveClassifier()

# health_count = 0

# counter_lock = asyncio.Lock()


# async def classify_website(browser, idx, domain):

#     global health_count

#     async with counter_lock:
#         if health_count >= MAX_HEALTH:
#             return

#     url = f"https://{domain}"

#     context = await browser.new_context()

#     # BLOCK HEAVY RESOURCES
#     await context.route(
#         "**/*",
#         lambda route: route.abort()
#         if route.request.resource_type in ["image", "media", "font"]
#         else route.continue_()
#     )

#     page = await context.new_page()

#     try:

#         await page.goto(
#             url,
#             timeout=TIMEOUT_MS,
#             wait_until="load"
#         )

#         # IMPORTANT:
#         # allow dynamic content to render
#         # await asyncio.sleep(2)

#         html = await page.content()

#         result = classifier.classify_html(html)

#         health_score = result["scores"].get("Health", 0)
#         predicted_category = result["predicted_category"]

#         print(
#             f"{domain} -> "
#             f"{result['predicted_category']} "
#             f"({health_score:.3f})"
#         )

#         if predicted_category == "Health" and health_score > 0.85:

#             async with counter_lock:

#                 if health_count >= MAX_HEALTH:
#                     return

#                 health_count += 1

#                 print(
#                     f"[{health_count}] HEALTH "
#                     f"({health_score:.3f}) -> {domain}"
#                 )

#                 with open(OUTPUT_CSV, "a", encoding="utf-8") as f:
#                     f.write(f"{health_count},{domain},{health_score:.3f}\n")

#     except Exception as e:
#         print(f"ERROR {domain}: {e}")

#     finally:
#         await context.close()


# async def worker(queue, browser):

#     while True:

#         item = await queue.get()

#         if item is None:
#             break

#         idx, domain = item

#         await classify_website(browser, idx, domain)

#         async with counter_lock:
#             if health_count >= MAX_HEALTH:
#                 queue.task_done()
#                 break

#         queue.task_done()


# async def main():

#     # clear previous output
#     Path(OUTPUT_CSV).write_text("rank,domain,health_score\n")
#     queue = asyncio.Queue()

#     with open(INPUT_CSV, newline="", encoding="utf-8") as f:

#         reader = csv.reader(f)

#         for row in reader:

#             if len(row) < 2:
#                 continue

#             idx = row[0]
#             domain = row[1]

#             await queue.put((idx, domain))

#     async with async_playwright() as p:

#         browser = await p.chromium.launch(
#             headless=True
#         )

#         tasks = [
#             asyncio.create_task(worker(queue, browser))
#             for _ in range(CONCURRENCY)
#         ]

#         await queue.join()

#         for _ in tasks:
#             await queue.put(None)

#         await asyncio.gather(*tasks)

#         await browser.close()

#     print("DONE")


# if __name__ == "__main__":
#     asyncio.run(main())
import sys
import os

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
)

import asyncio
import csv
from pathlib import Path

from playwright.async_api import async_playwright

from classifier.sensitive_classifier import SensitiveClassifier


INPUT_CSV = "list_websites_1M.csv"

OUTPUT_CSV = "health_websites.csv"

MAX_HEALTH = 1000

CONCURRENCY = 10

TIMEOUT_MS = 30000

# resume position
START_FROM_LINE = 89797

classifier = SensitiveClassifier()

# already found 32
health_count = 701

counter_lock = asyncio.Lock()


async def classify_website(browser, idx, domain):

    global health_count

    async with counter_lock:
        if health_count >= MAX_HEALTH:
            return

    url = f"https://{domain}"

    context = await browser.new_context()

    await context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ["image", "media", "font"]
        else route.continue_()
    )

    page = await context.new_page()

    try:

        await page.goto(
            url,
            timeout=TIMEOUT_MS,
            wait_until="load"
        )

        html = await page.content()

        result = classifier.classify_html(html)

        health_score = result["scores"].get("Health", 0)
        predicted_category = result["predicted_category"]

        print(
            f"{domain} -> "
            f"{result['predicted_category']} "
            f"({health_score:.3f})"
        )

        if predicted_category == "Health" and health_score > 0.85:

            async with counter_lock:

                if health_count >= MAX_HEALTH:
                    return

                health_count += 1

                print(
                    f"[{health_count}] HEALTH "
                    f"({health_score:.3f}) -> {domain}"
                )

                with open(OUTPUT_CSV, "a", encoding="utf-8") as f:
                    f.write(
                        f"{health_count},"
                        f"{domain},"
                        f"{health_score:.3f}\n"
                    )

    except Exception as e:
        print(f"ERROR {domain}: {e}")

    finally:
        await context.close()


async def worker(queue, browser):

    while True:

        item = await queue.get()

        if item is None:
            break

        idx, domain = item

        await classify_website(browser, idx, domain)

        async with counter_lock:
            if health_count >= MAX_HEALTH:
                queue.task_done()
                break

        queue.task_done()


async def main():

    queue = asyncio.Queue()

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:

        reader = csv.reader(f)

        for line_number, row in enumerate(reader):

            # skip already processed lines
            if line_number < START_FROM_LINE:
                continue

            if len(row) < 2:
                continue

            idx = row[0]
            domain = row[1]

            await queue.put((idx, domain))

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        tasks = [
            asyncio.create_task(worker(queue, browser))
            for _ in range(CONCURRENCY)
        ]

        await queue.join()

        for _ in tasks:
            await queue.put(None)

        await asyncio.gather(*tasks)

        await browser.close()

    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())