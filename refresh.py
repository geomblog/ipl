#!/usr/bin/env python3
"""Fetch IPL 2026 fixtures and points table from cricbuzz and inject into ipl_scenarios.html.

Usage:  python3 refresh.py

Writes a fresh JSON blob into the <script id="ipl-data"> tag of the HTML file
that lives next to this script. Stdlib only.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

SERIES_ID = 9241
SERIES_NAME = "Indian Premier League 2026"
MATCHES_URL = f"https://www.cricbuzz.com/cricket-series/{SERIES_ID}/indian-premier-league-2026/matches"
POINTS_URL = f"https://www.cricbuzz.com/cricket-series/{SERIES_ID}/indian-premier-league-2026/points-table"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

HERE = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(HERE, "ipl_scenarios.html")

DATA_TAG_OPEN = '<script id="ipl-data" type="application/json">'
DATA_TAG_CLOSE = '</script>'


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def concat_next_payloads(html: str) -> str:
    """Extract and concatenate all self.__next_f.push([1,"..."]) string payloads."""
    pushes = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    out = []
    for p in pushes:
        try:
            out.append(bytes(p, "utf-8").decode("unicode_escape"))
        except UnicodeDecodeError:
            out.append(p)
    return "".join(out)


def find_balanced(text: str, key: str, opener: str = "{", closer: str = "}") -> list:
    """Return every balanced-brace substring following `"<key>":` in text."""
    results = []
    pat = f'"{key}":{opener}'
    idx = 0
    while True:
        i = text.find(pat, idx)
        if i < 0:
            break
        start = i + len(f'"{key}":')
        depth = 0
        j = start
        in_str = False
        esc = False
        while j < len(text):
            c = text[j]
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"' and not esc:
                in_str = not in_str
            elif not in_str:
                if c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        results.append(text[start:j + 1])
                        break
            j += 1
        idx = j + 1
    return results


def parse_matches(html: str) -> list:
    payload = concat_next_payloads(html)
    seen = {}
    for blob in find_balanced(payload, "matchInfo"):
        try:
            m = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if m.get("seriesId") != SERIES_ID:
            continue
        seen[m["matchId"]] = m
    return list(seen.values())


def parse_points(html: str) -> list:
    payload = concat_next_payloads(html)
    blobs = find_balanced(payload, "pointsTableInfo", "[", "]")
    if not blobs:
        return []
    try:
        return json.loads(blobs[0])
    except json.JSONDecodeError:
        return []


def winner_from_status(status: str, team_by_full_lc: dict) -> Optional[str]:
    if not status:
        return None
    low = status.strip().lower()
    if "no result" in low or "abandoned" in low or "match tied" in low:
        return None
    m = re.match(r"^(.+?)\s+won\b", status.strip(), re.IGNORECASE)
    if not m:
        return None
    return team_by_full_lc.get(m.group(1).strip().lower())


def build_data(raw_matches: list, raw_points: list) -> dict:
    short_by_full = {}
    short_by_full_lc = {}
    for m in raw_matches:
        for k in ("team1", "team2"):
            t = m.get(k, {}) or {}
            full, short = t.get("teamName"), t.get("teamSName")
            if full and short:
                short_by_full[full] = short
                short_by_full_lc[full.lower()] = short

    out_matches = []
    for m in raw_matches:
        t1, t2 = m.get("team1", {}) or {}, m.get("team2", {}) or {}
        state = m.get("state", "")
        status = m.get("status", "")
        winner = winner_from_status(status, short_by_full_lc) if state == "Complete" else None
        out_matches.append({
            "matchId": m["matchId"],
            "matchDesc": m.get("matchDesc", ""),
            "startDate": int(m.get("startDate", 0) or 0),
            "teamA": t1.get("teamSName") or t1.get("teamName", ""),
            "teamB": t2.get("teamSName") or t2.get("teamName", ""),
            "teamAFull": t1.get("teamName", ""),
            "teamBFull": t2.get("teamName", ""),
            "state": state,
            "status": status,
            "winner": winner,
        })

    def num_of(d):
        mo = re.match(r"^(\d+)", d.get("matchDesc", "") or "")
        return int(mo.group(1)) if mo else 9999
    out_matches.sort(key=lambda d: (num_of(d), d["matchId"]))

    standings = []
    for t in raw_points:
        full = t.get("teamFullName", "")
        short = short_by_full.get(full) or (full[:3].upper() if full else "?")
        standings.append({
            "team": short,
            "teamFull": full,
            "played": int(t.get("matchesPlayed", 0)),
            "wins": int(t.get("matchesWon", 0)),
            "losses": int(t.get("matchesLost", 0)),
            "tied": int(t.get("matchesTied", 0)),
            "noResults": int(t.get("noRes", 0)),
            "points": int(t.get("points", 0)),
            "nrr": float(t.get("nrr", 0) or 0),
        })

    return {
        "fetchedAt": int(time.time() * 1000),
        "seriesId": SERIES_ID,
        "seriesName": SERIES_NAME,
        "matches": out_matches,
        "standings": standings,
    }


def inject(data: dict) -> Tuple[int, int]:
    """Replace the contents of the <script id='ipl-data'> block. Returns (old_completed, new_completed)."""
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    start = html.find(DATA_TAG_OPEN)
    if start < 0:
        raise SystemExit(f"Could not find {DATA_TAG_OPEN!r} in {HTML_PATH}")
    body_start = start + len(DATA_TAG_OPEN)
    body_end = html.find(DATA_TAG_CLOSE, body_start)
    if body_end < 0:
        raise SystemExit("Could not find closing </script> for ipl-data block")

    old_json = html[body_start:body_end].strip()
    try:
        old = json.loads(old_json) if old_json else {"matches": []}
    except json.JSONDecodeError:
        old = {"matches": []}
    old_completed = sum(1 for m in old.get("matches", []) if m.get("state") == "Complete")
    new_completed = sum(1 for m in data["matches"] if m.get("state") == "Complete")

    compact = json.dumps(data, separators=(",", ":"))
    new_html = html[:body_start] + "\n" + compact + "\n" + html[body_end:]
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)
    return old_completed, new_completed


def main():
    print(f"Fetching {MATCHES_URL}")
    matches_html = fetch(MATCHES_URL)
    time.sleep(0.5)
    print(f"Fetching {POINTS_URL}")
    points_html = fetch(POINTS_URL)

    raw_matches = parse_matches(matches_html)
    raw_points = parse_points(points_html)
    if not raw_matches:
        raise SystemExit("Parsed zero matches — cricbuzz markup may have changed.")
    if not raw_points:
        raise SystemExit("Parsed zero points-table rows — cricbuzz markup may have changed.")

    data = build_data(raw_matches, raw_points)
    old_c, new_c = inject(data)

    total = len(data["matches"])
    delta = new_c - old_c
    delta_str = f"+{delta}" if delta > 0 else str(delta) if delta < 0 else "no change"
    print(f"Wrote {HTML_PATH}")
    print(f"  matches: {total}  completed: {new_c} ({delta_str})  teams: {len(data['standings'])}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        print(f"HTTP error {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Network error: {e.reason}", file=sys.stderr)
        sys.exit(1)
