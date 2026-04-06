import os
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

# =========================
# CONFIG
# =========================

URLS_TO_CHECK = [
    "https://thegcsgroup.in", # TO CHANGE
]

PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


# =========================
# FETCH DATA FROM PAGESPEED
# =========================

def get_pagespeed_data(url, api_key):
    params = {
        "url": url,
        "key": api_key,
        "category": ["performance", "accessibility", "seo", "best-practices"]
    }

    try:
        response = requests.get(PAGESPEED_ENDPOINT, params=params, timeout=60)
    except Exception as e:
        return None, f"Request failed: {str(e)}"

    if response.status_code != 200:
        return None, f"API Error {response.status_code}: {response.text}"

    data = response.json()

    lighthouse = data.get("lighthouseResult", {})
    categories = lighthouse.get("categories", {})

    scores = {}
    for key in ["performance", "accessibility", "seo", "best-practices"]:
        if key in categories:
            scores[key] = int(categories[key]["score"] * 100)

    audits = lighthouse.get("audits", {})

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
# GENERATE REPORT
# =========================

def generate_report(results, timezone_label):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    report = f"""
Website Health Report
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

        report += "\nTop Issues:\n"

        if result["suggestions"]:
            for issue in result["suggestions"]:
                report += f"- {issue}\n"
        else:
            report += "No major issues detected\n"

        report += "----------------------------------------\n"

    return report


# =========================
# SEND EMAIL
# =========================

def send_email(subject, body):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT"))
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

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(mail_from, recipients.split(","), msg.as_string())
    except Exception as e:
        raise Exception(f"SMTP Error: {str(e)}")


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

        if error:
            results[url] = {"error": error}
        else:
            results[url] = data

    report = generate_report(results, timezone_label)

    send_email(
        subject="Website Health Report",
        body=report
    )

    print("Report sent successfully.")


if __name__ == "__main__":
    main()
