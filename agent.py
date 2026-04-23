import os
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================
# CONFIG
# =========================

URLS_TO_CHECK = [
    "https://www.bipspatiala.net",
    "https://www.spakora.in",
    "https://www.bodyzonegym.in",
    "https://www.abcmontessori.co.in/",
    "https://www.thegcsgroup.in/",
]

PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

MAX_PAGES_PER_SITE = 100
REQUEST_TIMEOUT = (5, 10)   # connect timeout, read timeout
MAX_WORKERS = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WebsiteHealthBot/1.0)"
}

SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip",
    ".mp4", ".mp3", ".avi", ".mov", ".css", ".js", ".xml"
)

# =========================
# FETCH DATA FROM PAGESPEED
# =========================

def get_pagespeed_data(url, api_key):
    params = [
        ("url", url),
        ("key", api_key),
        ("category", "performance"),
        ("category", "accessibility"),
        ("category", "seo"),
        ("category", "best-practices"),
    ]

    try:
        response = requests.get(PAGESPEED_ENDPOINT, params=params, timeout=60, headers=HEADERS)
    except Exception as e:
        return None, f"Request failed: {str(e)}"

    if response.status_code != 200:
        return None, f"API Error {response.status_code}: {response.text}"

    data = response.json()
    lighthouse = data.get("lighthouseResult", {})
    categories = lighthouse.get("categories", {})
    audits = lighthouse.get("audits", {})

    scores = {}
    for key in ["performance", "accessibility", "seo", "best-practices"]:
        score = categories.get(key, {}).get("score")
        if score is not None:
            scores[key] = int(score * 100)

    suggestions = []
    for audit in audits.values():
        if audit.get("scoreDisplayMode") == "numeric" and audit.get("score", 1) < 0.9:
            title = audit.get("title")
            if title:
                suggestions.append(title)

    return {
        "scores": scores,
        "suggestions": suggestions[:5]
    }, None

# =========================
# URL HELPERS
# =========================

def normalize_url(base_url, href):
    full_url = urljoin(base_url, href)
    full_url, _ = urldefrag(full_url)
    return full_url.rstrip("/")

def is_same_domain(url, root_netloc):
    return urlparse(url).netloc == root_netloc

def is_http_url(url):
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https")

def should_skip_url(url):
    lower = url.lower()
    return lower.endswith(SKIP_EXTENSIONS)

# =========================
# LINK CHECKING
# =========================

def check_url(session, source_page, url):
    try:
        response = session.get(
            url,
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
            headers=HEADERS,
            stream=True
        )
        status_code = response.status_code
        response.close()

        if status_code >= 400:
            return {
                "source_page": source_page,
                "broken_url": url,
                "status": status_code,
                "error": None
            }
        return None

    except Exception as e:
        return {
            "source_page": source_page,
            "broken_url": url,
            "status": "REQUEST_FAILED",
            "error": str(e)
        }

# =========================
# FULL WEBSITE CRAWLER
# =========================

def crawl_site_for_broken_links(start_url, max_pages=25):
    parsed_start = urlparse(start_url)
    root_netloc = parsed_start.netloc

    queue = deque([start_url.rstrip("/")])
    visited_pages = set()
    checked_links = set()
    broken_links = []
    tasks = []
    crawled_count = 0

    session = requests.Session()
    session.headers.update(HEADERS)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        while queue and crawled_count < max_pages:
            current_page = queue.popleft()

            if current_page in visited_pages:
                continue

            visited_pages.add(current_page)
            crawled_count += 1

            try:
                page_response = session.get(current_page, timeout=REQUEST_TIMEOUT)
            except Exception as e:
                broken_links.append({
                    "source_page": current_page,
                    "broken_url": current_page,
                    "status": "REQUEST_FAILED",
                    "error": str(e)
                })
                continue

            if page_response.status_code >= 400:
                broken_links.append({
                    "source_page": current_page,
                    "broken_url": current_page,
                    "status": page_response.status_code,
                    "error": None
                })
                continue

            content_type = page_response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                continue

            soup = BeautifulSoup(page_response.text, "html.parser")

            for tag in soup.find_all("a", href=True):
                href = tag["href"].strip()

                if not href:
                    continue
                if href.startswith("#"):
                    continue
                if href.startswith(("mailto:", "tel:", "javascript:")):
                    continue

                full_url = normalize_url(current_page, href)

                if not is_http_url(full_url):
                    continue
                if not is_same_domain(full_url, root_netloc):
                    continue
                if should_skip_url(full_url):
                    continue

                if full_url not in checked_links:
                    checked_links.add(full_url)
                    tasks.append(executor.submit(check_url, session, current_page, full_url))

                if full_url not in visited_pages:
                    queue.append(full_url)

        for future in as_completed(tasks):
            result = future.result()
            if result:
                broken_links.append(result)

    return {
        "broken_links": broken_links,
        "pages_crawled": crawled_count,
        "unique_links_checked": len(checked_links)
    }

# =========================
# GENERATE REPORT
# =========================

def generate_report(results, timezone_label):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    report = f"""Website Health Report
Generated: {timestamp}
Timezone: {timezone_label}

========================================
"""

    for url, result in results.items():
        report += f"\nURL: {url}\n"

        if "error" in result:
            report += f"ERROR: {result['error']}\n"
            report += "----------------------------------------\n"
            continue

        for metric, score in result["scores"].items():
            report += f"{metric.capitalize()}: {score}\n"

        report += f"\nPages Crawled: {result.get('pages_crawled', 0)}\n"
        report += f"Unique Internal Links Checked: {result.get('unique_links_checked', 0)}\n"

        report += "\nTop Issues:\n"
        if result["suggestions"]:
            for issue in result["suggestions"]:
                report += f"- {issue}\n"
        else:
            report += "- No major issues detected\n"

        report += "\nBroken Links:\n"
        if result.get("broken_links"):
            for item in result["broken_links"][:20]:
                report += (
                    f"- Broken URL: {item['broken_url']}\n"
                    f"  Found on: {item['source_page']}\n"
                    f"  Status: {item['status']}\n"
                )
                if item.get("error"):
                    report += f"  Error: {item['error']}\n"
        else:
            report += "- No broken internal links detected\n"

        report += "----------------------------------------\n"

    return report

# =========================
# SEND EMAIL
# =========================

def send_email(subject, body):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    mail_from = os.environ.get("MAIL_FROM")
    recipients = os.environ.get("REPORT_RECIPIENTS")

    if not all([smtp_host, smtp_port, smtp_user, smtp_password, mail_from, recipients]):
        raise Exception("Missing one or more SMTP environment variables")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = recipients

    with smtplib.SMTP(smtp_host, int(smtp_port), timeout=20) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(mail_from, [r.strip() for r in recipients.split(",")], msg.as_string())

# =========================
# MAIN EXECUTION
# =========================

def main():
    api_key = os.environ.get("PAGESPEED_API_KEY")
    timezone_label = os.environ.get("TIMEZONE_LABEL", "UTC")

    if not api_key:
        raise Exception("Missing PAGESPEED_API_KEY")

    results = {}

    for url in URLS_TO_CHECK:
        data, error = get_pagespeed_data(url, api_key)
        crawl_result = crawl_site_for_broken_links(url, max_pages=MAX_PAGES_PER_SITE)

        if error:
            results[url] = {
                "error": error,
                "broken_links": crawl_result["broken_links"],
                "pages_crawled": crawl_result["pages_crawled"],
                "unique_links_checked": crawl_result["unique_links_checked"]
            }
        else:
            data["broken_links"] = crawl_result["broken_links"]
            data["pages_crawled"] = crawl_result["pages_crawled"]
            data["unique_links_checked"] = crawl_result["unique_links_checked"]
            results[url] = data

    report = generate_report(results, timezone_label)
    send_email("Website Health Report", report)
    print("Report sent successfully.")

if __name__ == "__main__":
    main()
