# Cookie Tracking Analysis on Sensitive Websites

## Overview

This project investigates cookie usage on websites that may process or expose sensitive user information, with a focus on privacy implications, storage duration, and consent.

The goal is to examine:

- **What cookies are placed on websites?**
- **How long these cookies persist?**
- **Whether cookie collection occurs before or after user consent?**
- **How tracking behavior differs across websites?**

This project was developed as part of a research study.

---

## Features

### Cookie Collection
- Automated browser instrumentation using **Playwright + Chromium**
- Cookie capture through the **Chrome DevTools Protocol (CDP)**

---

### Batch Crawling

Supports automated crawling of large website lists, such as:

- Tranco Top 500 / Top 1M lists

Each website is visited automatically and cookies are saved as structured JSON.

---

## Setup

**1. Create and activate a new conda environment**
```bash
conda create -n cookies38 python=3.8 -y
conda activate cookies38
```

**2. Install Python dependencies**
```bash
pip install -r requirements.txt
```

**3. Install Playwright browsers**
```bash
python -m playwright install chromium firefox webkit
```
---

## Usage

### Run a single site

```bash
python get_all_cookies.py
```

---

### Run batch collection

Example using Tranco list:

```bash
python scripts/get_cookies.py list_websites_1M.csv --headless --tracker-lists
```

This processes websites from:

```bash
list_websites_1M.csv
```

and saves results into:

```bash
cookies_data/
```

## Ethical Considerations

This project collects only publicly observable browser cookie metadata.

It does **not**:
- bypass authentication
- access user accounts
- scrape personal user data
- circumvent security protections

The project is intended solely for privacy research and educational purposes.

### Note on stored request URLs

For Chromium-family crawls, the full URLs of outgoing requests (including query
strings) are retained in each site's JSON under a `requests` field. This is
required to detect **cookie syncing** — identifiers passed between trackers via
request parameters (`scripts/find_cookie_syncing.py`). These URLs are observed
from automated, un-authenticated visits and may contain identifier-like
parameter values; they are stored raw so syncing can be detected accurately. If
you share a collected dataset, treat these URLs as you would any observational
web-measurement data.

---

## Authors



---

## References

- Chrome DevTools Protocol  
  https://chromedevtools.github.io/devtools-protocol/

- Playwright  
  https://playwright.dev/

- Tranco List  
  https://tranco-list.eu/

- EasyPrivacy  
  https://easylist.to/