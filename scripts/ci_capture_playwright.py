#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT / "data" / "ci_watchlists.json"
DEFAULT_OUT = ROOT / "data" / "ci_manual_urls.txt"

GOOGLE_NEWS_SEARCH = "https://news.google.com/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def load_watchlist_domains() -> List[str]:
    if not WATCHLIST_PATH.exists():
        return []
    data = json.loads(WATCHLIST_PATH.read_text())
    domains = data.get("media_domains", [])
    return [d for d in domains if isinstance(d, str) and d.strip()]


def load_direct_sources(limit: int) -> List[Tuple[str, str]]:
    if not WATCHLIST_PATH.exists():
        return []
    data = json.loads(WATCHLIST_PATH.read_text())
    rows = data.get("press_rooms", [])
    if not isinstance(rows, list):
        return []
    sorted_rows = sorted(rows, key=lambda r: int(r.get("priority", 3)))
    out: List[Tuple[str, str]] = []
    for row in sorted_rows:
        name = (row.get("name") or "").strip()
        url = (row.get("url") or "").strip()
        if name and url.startswith("http"):
            out.append((name, url))
        if len(out) >= limit:
            break
    return out


def build_queries(days: int, domains: List[str], max_queries: int) -> List[Tuple[str, str]]:
    seeds = [
        '("atrial fibrillation" OR AFib) (drug OR device OR trial OR pivotal OR ablation OR LAAO) when:{days}d',
        '(AFib OR "atrial fibrillation") ("late-breaking" OR conference OR symposium OR ACC OR HRS OR ESC OR EHRA) when:{days}d',
        '(AFib OR "atrial fibrillation") (PFA OR "pulsed field" OR catheter OR WATCHMAN OR Amulet) when:{days}d',
    ]
    queries: List[Tuple[str, str]] = []
    for idx, pattern in enumerate(seeds, start=1):
        q = pattern.format(days=days)
        queries.append((f"Core {idx}", GOOGLE_NEWS_SEARCH.format(query=quote(q, safe=""))))
    for domain in domains:
        q = f"site:{domain} (AFib OR \"atrial fibrillation\") (drug OR device OR trial OR ablation OR LAAO OR PFA) when:{days}d"
        queries.append((f"Media {domain}", GOOGLE_NEWS_SEARCH.format(query=quote(q, safe=""))))
    return queries[:max_queries]


def dedupe_rows(rows: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    seen = set()
    out = []
    for title, url in rows:
        key = (title.strip().lower(), url.strip())
        if key in seen:
            continue
        seen.add(key)
        out.append((title.strip(), url.strip()))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture AFib links in a real browser via Playwright")
    parser.add_argument("--days", type=int, default=10, help="Lookback days for query text")
    parser.add_argument("--max-queries", type=int, default=8, help="Max Google News queries to open")
    parser.add_argument("--direct-sources", type=int, default=6, help="Number of direct source pages to scan")
    parser.add_argument("--output", default=str(DEFAULT_OUT), help="Output file (title<TAB>url)")
    parser.add_argument("--profile-dir", default=str(ROOT / ".playwright-profile"), help="Persistent browser profile")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Pause for consent/login confirmation after opening first page",
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("Playwright is not installed in this Python environment.")
        print("Run: bash scripts/setup_playwright.sh")
        return 1

    domains = load_watchlist_domains()
    queries = build_queries(args.days, domains, args.max_queries)
    direct_sources = load_direct_sources(args.direct_sources)
    if not queries:
        print("No queries configured.")
        return 1

    all_rows: List[Tuple[str, str]] = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=args.profile_dir,
            headless=args.headless,
            viewport={"width": 1440, "height": 960},
        )
        page = context.new_page()
        print("Browser opened.")
        label0, url0 = queries[0]
        page.goto(url0, wait_until="domcontentloaded")
        if args.interactive:
            print("Complete consent/login if prompted.")
            print("After the first page loads, return to terminal and press Enter to continue.")
            input()

        for label, url in queries:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(1200)
            current_url = page.url
            page_title = page.title()
            print(f"Query page: {label} | title: {page_title} | url: {current_url}")
            rows: List[Dict[str, str]] = page.evaluate(
                """
                () => {
                  const links = Array.from(document.querySelectorAll('a'));
                  const out = [];
                  for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    const rawText = (a.textContent || '').trim().replace(/\\s+/g, ' ');
                    const aria = (a.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
                    const text = rawText || aria;
                    if (!text || text.length < 12) continue;

                    // Google News commonly uses /read/ and /articles/ relative links.
                    const isNewsLink =
                      href.includes('/articles/') ||
                      href.includes('/read/') ||
                      href.startsWith('./articles/') ||
                      href.startsWith('./read/') ||
                      href.startsWith('https://news.google.com/');
                    if (!isNewsLink) continue;

                    const full = href.startsWith('http')
                      ? href
                      : new URL(href, 'https://news.google.com').toString();
                    out.push({ title: text, url: full });
                  }
                  return out;
                }
                """
            )
            for row in rows:
                title = row.get("title", "").strip()
                link = row.get("url", "").strip()
                if title and link.startswith("http"):
                    all_rows.append((title, link))
            print(f"Captured from {label}: {len(rows)} candidate links")

        # Direct source pass: capture headline links from priority sources in a real browser.
        for label, url in direct_sources:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2200)
            rows: List[Dict[str, str]] = page.evaluate(
                """
                () => {
                  const include = ['atrial fibrillation','afib','ablation','pfa','laao','watchman','amulet','trial','phase','pivotal','approval','fda','ema','device','catheter','stroke'];
                  const links = Array.from(document.querySelectorAll('a'));
                  const out = [];
                  for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    const text = ((a.textContent || '').trim().replace(/\\s+/g, ' ')) || ((a.getAttribute('aria-label') || '').trim());
                    if (!text || text.length < 18) continue;
                    const hay = (text + ' ' + href).toLowerCase();
                    if (!include.some(k => hay.includes(k))) continue;
                    const full = href.startsWith('http') ? href : new URL(href, window.location.href).toString();
                    out.push({ title: text, url: full });
                  }
                  return out;
                }
                """
            )
            for row in rows:
                title = row.get("title", "").strip()
                link = row.get("url", "").strip()
                if title and link.startswith("http"):
                    all_rows.append((title, link))
            print(f"Captured from source {label}: {len(rows)} candidate links")

        context.close()

    unique_rows = dedupe_rows(all_rows)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# title<TAB>url",
        "# Generated by scripts/ci_capture_playwright.py",
    ]
    for title, url in unique_rows:
        lines.append(f"{title}\t{url}")
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(unique_rows)} unique links to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
