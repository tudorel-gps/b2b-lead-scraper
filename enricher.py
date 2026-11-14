"""Website health checks, email extraction and lead scoring."""

from __future__ import annotations

import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

import httpx

from database import Lead
from scraper import USER_AGENTS

HOT, WARM, COLD = "HOT_LEAD", "WARM_LEAD", "COLD_LEAD"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_BAD_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
_BAD_EMAIL_DOMAINS = ("example.com", "domain.com", "sentry.io", "wixpress.com", "sentry-next.wixpress.com")


def extract_emails(html: str) -> list[str]:
    emails: list[str] = []
    for raw in EMAIL_RE.findall(html):
        e = raw.strip(".").lower()
        if e.endswith(_BAD_EMAIL_SUFFIXES) or any(e.endswith("@" + d) or e.endswith("." + d) for d in _BAD_EMAIL_DOMAINS):
            continue
        if e not in emails:
            emails.append(e)
    return emails[:5]


def check_website(lead: Lead, timeout: float = 5.0) -> Lead:
    """Populate site_status / https / emails on the lead. Never raises."""
    if not lead.has_website:
        return lead
    url = lead.website if lead.website.startswith("http") else f"http://{lead.website}"
    headers = {"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8"}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers, verify=True) as client:
            resp = client.get(url)
        lead.site_status = resp.status_code
        lead.https = resp.url.scheme == "https"
        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", "text/html"):
            lead.emails = extract_emails(resp.text)
    except httpx.ConnectError as exc:
        # An SSL failure on an https URL means the site has a broken certificate.
        lead.site_status = 0
        lead.https = False if "SSL" in str(exc) or "CERTIFICATE" in str(exc).upper() else url.startswith("https")
    except (httpx.HTTPError, ValueError):
        lead.site_status = 0
        lead.https = url.startswith("https")
    return lead


def score_lead(lead: Lead, review_threshold: int = 20) -> Lead:
    if not lead.has_website:
        lead.tag, lead.tag_reason = HOT, "Fara website"
    elif lead.site_status != 200:
        status = "nu raspunde" if not lead.site_status else f"HTTP {lead.site_status}"
        lead.tag, lead.tag_reason = HOT, f"Website picat ({status})"
    elif not lead.https:
        lead.tag, lead.tag_reason = HOT, "Website fara HTTPS"
    elif (lead.reviews or 0) < review_threshold:
        lead.tag, lead.tag_reason = WARM, f"Putine recenzii ({lead.reviews or 0} < {review_threshold})"
    else:
        lead.tag, lead.tag_reason = COLD, "Website OK, prezenta online solida"
    return lead


def enrich_leads(
    leads: Iterable[Lead],
    review_threshold: int = 20,
    timeout: float = 5.0,
    workers: int = 8,
    on_done: Callable[[Lead], None] | None = None,
) -> list[Lead]:
    leads = list(leads)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check_website, lead, timeout): lead for lead in leads}
        for fut in as_completed(futures):
            lead = futures[fut]
            try:
                fut.result()
            except Exception:  # defensive: check_website already swallows network errors
                lead.site_status = 0
            score_lead(lead, review_threshold)
            if on_done:
                on_done(lead)
    return leads
