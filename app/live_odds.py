"""
Fetch and parse Kentucky Derby live odds from kentuckyderby.com /wager/live-odds/.

The page embeds a TwinSpires race widget: we select the widget titled Kentucky Derby
(not Kentucky Oaks) and read .race-horse-entry rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

LIVE_ODDS_URL = "https://www.kentuckyderby.com/wager/live-odds/"

_FRACTIONAL_ODDS = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_horse_name(name: str) -> str:
    """Uppercase and collapse whitespace for matching to prediction CSV names."""
    s = " ".join(name.strip().split())
    return s.upper()


def parse_fractional_odds(s: str) -> tuple[int, int] | None:
    """Parse '5/1' or ' 9/2 ' -> (5, 1), (9, 2). Returns None if invalid."""
    m = _FRACTIONAL_ODDS.match(s.strip())
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a < 0 or b <= 0:
        return None
    return a, b


def implied_win_probability(frac: tuple[int, int]) -> float:
    """UK fractional a/b: implied win probability = b / (a + b)."""
    a, b = frac
    return b / (a + b)


def find_kentucky_derby_widget(soup: BeautifulSoup):
    """Return the BeautifulSoup node for the Derby race widget, or None."""
    for widget in soup.select("div.race-entry-widget"):
        h2 = widget.select_one("h2.race-widget-title")
        if not h2:
            continue
        title = h2.get_text()
        if "Kentucky Derby" in title and "Oaks" not in title:
            return widget
    return None


def add_market_strength(rows: list[dict[str, Any]]) -> None:
    """
    In-place: set market_strength in [0, 1] — higher = stronger market (shorter odds).

    Ranks by implied_probability descending (favorite gets rank 1, ties averaged),
    then maps to strength so the favorite gets 1.0 and the longest price ~0.0.
    """
    n = len(rows)
    if n == 0:
        return
    if n == 1:
        rows[0]["market_strength"] = 1.0
        return

    probs = [r["implied_probability"] for r in rows]
    # Sort indices by probability descending
    order = sorted(range(n), key=lambda i: probs[i], reverse=True)
    ranks = [0.0] * n
    pos = 0
    while pos < n:
        end = pos
        v = probs[order[pos]]
        while end + 1 < n and probs[order[end + 1]] == v:
            end += 1
        # 1-based ranks (pos+1) .. (end+1), average for ties
        r_avg = (pos + 1 + end + 1) / 2.0
        for k in range(pos, end + 1):
            ranks[order[k]] = r_avg
        pos = end + 1

    for idx in range(n):
        rows[idx]["market_strength"] = (n - ranks[idx]) / (n - 1)


def parse_derby_entries_from_html(html: str) -> list[dict[str, Any]]:
    """
    Parse Derby horse rows from full page HTML.

    Each row dict: program_number, horse_name, odds_str, implied_probability, market_strength.
    """
    soup = BeautifulSoup(html, "html.parser")
    widget = find_kentucky_derby_widget(soup)
    if not widget:
        raise ValueError("Kentucky Derby race widget not found in HTML")

    rows: list[dict[str, Any]] = []
    for entry in widget.select(".race-horse-entry"):
        num_el = entry.select_one(".horse-number")
        name_el = entry.select_one(".race-horse-column.horse")
        odds_el = entry.select_one(".odds")
        if not num_el or not name_el or not odds_el:
            continue
        raw_name = name_el.get_text(" ", strip=True)
        odds_str = odds_el.get_text(" ", strip=True)
        frac = parse_fractional_odds(odds_str)
        if not frac:
            continue
        try:
            program_number = int(num_el.get_text(strip=True))
        except ValueError:
            program_number = -1

        p = implied_win_probability(frac)
        rows.append(
            {
                "program_number": program_number,
                "horse_name": raw_name,
                "horse_name_normalized": normalize_horse_name(raw_name),
                "odds_str": odds_str.strip(),
                "implied_probability": round(p, 6),
            }
        )

    if not rows:
        raise ValueError("No race-horse-entry rows found in Kentucky Derby widget")

    add_market_strength(rows)
    return rows


async def fetch_live_odds_html(*, timeout_s: float = 25.0) -> str:
    async with httpx.AsyncClient(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(timeout_s),
    ) as client:
        r = await client.get(LIVE_ODDS_URL)
        r.raise_for_status()
        return r.text


def fetch_live_odds_html_sync(*, timeout_s: float = 25.0) -> str:
    with httpx.Client(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=timeout_s,
    ) as client:
        r = client.get(LIVE_ODDS_URL)
        r.raise_for_status()
        return r.text


@dataclass
class LiveOddsResult:
    fetched_at_iso: str
    source_url: str
    horses: list[dict[str, Any]]


async def fetch_and_parse_derby_odds(*, timeout_s: float = 25.0) -> LiveOddsResult:
    from datetime import datetime, timezone

    html = await fetch_live_odds_html(timeout_s=timeout_s)
    horses = parse_derby_entries_from_html(html)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return LiveOddsResult(fetched_at_iso=ts, source_url=LIVE_ODDS_URL, horses=horses)


def fetch_and_parse_derby_odds_sync(*, timeout_s: float = 25.0) -> LiveOddsResult:
    from datetime import datetime, timezone

    html = fetch_live_odds_html_sync(timeout_s=timeout_s)
    horses = parse_derby_entries_from_html(html)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return LiveOddsResult(fetched_at_iso=ts, source_url=LIVE_ODDS_URL, horses=horses)
