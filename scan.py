#!/usr/bin/env python3
"""
JobTrackerCZ — Daily RSS scan
Fetches IT leadership jobs from Czech job board RSS feeds.
No API key required. 100% free.
"""

import json
import os
import re
import time
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ==================== CONFIG ====================

KEYWORDS_MATCH = [
    'IT manager', 'IT manažer', 'IT director', 'IT ředitel',
    'head of IT', 'vedoucí IT', 'head of infrastructure',
    'vedoucí infrastruktury', 'infrastructure lead', 'infrastructure manager',
    'platform lead', 'cloud lead', 'technický ředitel', 'CTO',
    'VP IT', 'VP infrastructure', 'IT architect', 'IT architekt',
    'technology director', 'engineering manager',
]

KEYWORDS_BOOST = [
    'linux', 'vmware', 'ansible', 'azure', 'kubernetes', 'open source',
    'cloud', 'infrastructure', 'devops', 'automation', 'team lead',
    'people management', 'finops', 'cost', 'hybrid',
]

KEYWORDS_EXCLUDE = [
    'sales', 'account manager', 'marketing', 'recruiter', 'HR',
    'java developer', 'frontend', 'backend developer', '.net developer',
    'tester', 'QA', 'graphic', 'design', 'accountant', 'finance',
]

# RSS feeds — pre-filtered for IT management roles
RSS_FEEDS = [
    {
        'name': 'jobs.cz — IT Manager',
        'source': 'jobs.cz',
        'url': 'https://www.jobs.cz/rss/prace/?q%5B%5D=IT+manager&locality%5Bradius%5D=0',
    },
    {
        'name': 'jobs.cz — IT Director',
        'source': 'jobs.cz',
        'url': 'https://www.jobs.cz/rss/prace/?q%5B%5D=IT+director',
    },
    {
        'name': 'jobs.cz — Head of IT',
        'source': 'jobs.cz',
        'url': 'https://www.jobs.cz/rss/prace/?q%5B%5D=head+of+IT',
    },
    {
        'name': 'jobs.cz — IT Ředitel',
        'source': 'jobs.cz',
        'url': 'https://www.jobs.cz/rss/prace/?q%5B%5D=IT+%C5%99editel',
    },
    {
        'name': 'jobs.cz — vedoucí IT',
        'source': 'jobs.cz',
        'url': 'https://www.jobs.cz/rss/prace/?q%5B%5D=vedouc%C3%AD+IT',
    },
    {
        'name': 'jobs.cz — Infrastructure Manager',
        'source': 'jobs.cz',
        'url': 'https://www.jobs.cz/rss/prace/?q%5B%5D=infrastructure+manager',
    },
    {
        'name': 'jobs.cz — CTO',
        'source': 'jobs.cz',
        'url': 'https://www.jobs.cz/rss/prace/?q%5B%5D=CTO',
    },
    {
        'name': 'jobs.cz — Cloud Lead',
        'source': 'jobs.cz',
        'url': 'https://www.jobs.cz/rss/prace/?q%5B%5D=cloud+lead',
    },
    {
        'name': 'indeed.cz — IT Manager',
        'source': 'indeed.cz',
        'url': 'https://cz.indeed.com/rss?q=IT+Manager&l=Czech+Republic&sort=date',
    },
    {
        'name': 'indeed.cz — IT Director',
        'source': 'indeed.cz',
        'url': 'https://cz.indeed.com/rss?q=IT+Director&l=Czech+Republic&sort=date',
    },
    {
        'name': 'indeed.cz — Head of Infrastructure',
        'source': 'indeed.cz',
        'url': 'https://cz.indeed.com/rss?q=Head+of+Infrastructure&l=Czech+Republic&sort=date',
    },
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; JobTrackerCZ/1.0; RSS reader)',
    'Accept': 'application/rss+xml, application/xml, text/xml, */*',
}

# ==================== RSS FETCH ====================

def fetch_rss(feed):
    """Fetch and parse a single RSS feed."""
    print(f"  Fetching: {feed['name']}")
    try:
        req = urllib.request.Request(feed['url'], headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()

        root = ET.fromstring(raw)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        items = []

        # Standard RSS
        for item in root.findall('.//item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            desc = (item.findtext('description') or '').strip()
            pub_date = (item.findtext('pubDate') or '').strip()

            if title and link:
                items.append({
                    'title': title,
                    'url': link,
                    'description': desc,
                    'posted': pub_date[:16] if pub_date else 'Recent',
                    'source': feed['source'],
                })

        print(f"    → {len(items)} items")
        return items

    except Exception as e:
        print(f"    → ERROR: {e}")
        return []

# ==================== SCORING ====================

def score_job(title, description):
    """Score a job based on keyword matching."""
    text = (title + ' ' + description).lower()

    # Exclude irrelevant roles
    for kw in KEYWORDS_EXCLUDE:
        if kw.lower() in text and kw.lower() not in title.lower():
            return 0, "Excluded by keyword filter"

    score = 50
    reasons = []

    # Title match (high weight)
    title_lower = title.lower()
    for kw in KEYWORDS_MATCH:
        if kw.lower() in title_lower:
            score += 20
            reasons.append(f"Title matches '{kw}'")
            break

    # Description match
    for kw in KEYWORDS_MATCH:
        if kw.lower() in text and kw.lower() not in title_lower:
            score += 5

    # Boost keywords
    boost_found = []
    for kw in KEYWORDS_BOOST:
        if kw.lower() in text:
            score += 3
            boost_found.append(kw)

    if boost_found:
        reasons.append(f"Skills match: {', '.join(boost_found[:4])}")

    # Location bonus
    for loc in ['brno', 'praha', 'prague', 'remote', 'hybrid']:
        if loc in text:
            score += 5
            reasons.append(f"Location: {loc}")
            break

    score = min(score, 98)
    reason = '. '.join(reasons) if reasons else 'General IT leadership role matching your seniority level.'
    return score, reason

# ==================== PARSE JOBS ====================

def parse_location(text):
    """Extract location from job text."""
    text_lower = text.lower()
    if 'brno' in text_lower: return 'Brno, CZ'
    if 'praha' in text_lower or 'prague' in text_lower: return 'Praha, CZ'
    if 'ostrava' in text_lower: return 'Ostrava, CZ'
    if 'plzeň' in text_lower or 'pilsen' in text_lower: return 'Plzeň, CZ'
    if 'remote' in text_lower: return 'Remote'
    return 'Czech Republic'

def parse_work_mode(text):
    """Detect work mode from text."""
    text_lower = text.lower()
    if 'remote' in text_lower and 'hybrid' in text_lower: return 'hybrid'
    if 'remote' in text_lower: return 'remote'
    if 'hybrid' in text_lower: return 'hybrid'
    if 'home' in text_lower: return 'hybrid'
    return 'on-site'

def clean_html(text):
    """Strip HTML tags from text."""
    return re.sub(r'<[^>]+>', ' ', text).strip()

def make_id(title, company, url):
    """Generate stable unique ID."""
    raw = f"{title}-{url}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def process_items(items):
    """Convert RSS items to job objects."""
    jobs = []
    for item in items:
        title = clean_html(item['title'])
        desc = clean_html(item.get('description', ''))
        url = item['url']
        source = item['source']
        posted = item.get('posted', 'Recent')

        # Score
        score, reason = score_job(title, desc)
        if score < 40:
            continue  # Skip low relevance

        # Extract company from title if possible (common format: "Title - Company")
        company = 'See posting'
        if ' - ' in title:
            parts = title.split(' - ')
            if len(parts) >= 2:
                title = parts[0].strip()
                company = parts[-1].strip()
        elif ' | ' in title:
            parts = title.split(' | ')
            title = parts[0].strip()
            company = parts[-1].strip() if len(parts) > 1 else company

        job = {
            'id': make_id(title, company, url),
            'title': title,
            'company': company,
            'location': parse_location(title + ' ' + desc),
            'workMode': parse_work_mode(title + ' ' + desc),
            'salary': 'Not disclosed',
            'url': url,
            'source': source,
            'posted': posted[:10] if len(posted) > 10 else posted,
            'matchScore': score,
            'matchReason': reason,
            'language': 'cs' if any(c in title for c in 'řžýáéíóůúěšč') else 'en',
            'status': 'new',
            'notes': '',
            'addedAt': datetime.now(timezone.utc).isoformat(),
        }
        jobs.append(job)

    return jobs

# ==================== MERGE ====================

def load_existing():
    try:
        with open('jobs.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('jobs', [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def merge(existing, new_jobs):
    existing_ids = {j['id'] for j in existing}
    existing_urls = {j.get('url', '').lower() for j in existing}
    added = 0

    for job in new_jobs:
        if job['id'] in existing_ids:
            continue
        if job.get('url', '').lower() in existing_urls:
            continue
        existing.insert(0, job)
        existing_ids.add(job['id'])
        existing_urls.add(job.get('url', '').lower())
        added += 1

    print(f"Added {added} new jobs ({len(existing)} total)")
    return existing, added

def write(jobs, added):
    output = {
        'lastScan': datetime.now(timezone.utc).isoformat(),
        'totalJobs': len(jobs),
        'newThisScan': added,
        'jobs': jobs,
    }
    with open('jobs.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Written jobs.json ({len(jobs)} jobs)")

# ==================== MAIN ====================

def main():
    print('=' * 50)
    print('JobTrackerCZ Daily RSS Scan')
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print('=' * 50)

    existing = load_existing()
    print(f"Existing jobs: {len(existing)}")

    all_items = []
    for feed in RSS_FEEDS:
        items = fetch_rss(feed)
        all_items.extend(items)
        time.sleep(1)  # Be polite to servers

    print(f"\nTotal RSS items fetched: {len(all_items)}")

    new_jobs = process_items(all_items)
    print(f"Jobs passing filter: {len(new_jobs)}")

    merged, added = merge(existing, new_jobs)
    write(merged, added)

    print('=' * 50)
    print(f"Scan complete! {added} new leads added.")

if __name__ == '__main__':
    main()
