"""NCAA NET rankings with quadrant records, scraped from NCAA.com into net-YEAR.json.

Source: https://www.ncaa.com/rankings/basketball-men/d1/ncaa-mens-basketball-net-rankings
One static HTML table, every D1 team (~365 rows), current season only (NCAA.com keeps no
archive). It has no CORS header, so the browser can't read it; this module fetches it
at build time and the site will read the JSON file.

Columns: Rank, School, Record, Conf, Road, Neutral, Home, Non-Div I, Prev, Quad 1–4.
Quadrant records are official (NCAA cutoffs applied to opponent NET + game site) and
count D1 games only, so W-L here can differ from ESPN's overall record.

The season comes from the page's "Through Games <date>" line, not today's date: before
the first NET release of a season (usually early December) the page still shows the
previous season's final rankings.

Run through userpoll.py:
    python3 userpoll.py --net     # fetch → net-YEAR.json (YEAR = season shown on the page)

NCAA.com abbreviates names ("Iowa St.", "Fla. Atlantic"). to_key() maps them to our
canonical team keys (conferences.ESPN_IDS): exact match first, then "St." → "State" and
a trailing "(XX)" state tag dropped, then NCAA_NAME_OVERRIDES. Any name that still
doesn't map stops the run without writing; add it to NCAA_NAME_OVERRIDES.
"""

import datetime
import json
import os
import re
import urllib.request
from html import unescape

import conferences

NET_URL = "https://www.ncaa.com/rankings/basketball-men/d1/ncaa-mens-basketball-net-rankings"

COLUMNS = ["Rank", "School", "Record", "Conf", "Road", "Neutral", "Home", "Non-Div I",
           "Prev", "Quad 1", "Quad 2", "Quad 3", "Quad 4"]
# NCAA.com column → JSON field (School becomes the key, Conf is dropped: use conferences.py)
FIELDS = {"Rank": "rank", "Record": "record", "Road": "road", "Neutral": "neutral",
          "Home": "home", "Non-Div I": "nonD1", "Prev": "prev",
          "Quad 1": "q1", "Quad 2": "q2", "Quad 3": "q3", "Quad 4": "q4"}

# NCAA.com school name → our key, for names the generic rules don't cover.
NCAA_NAME_OVERRIDES = {
    "A&M-Corpus Christi": "TexasAMCorpusChristi", "Alcorn": "AlcornState",
    "App State": "AppalachianState", "Ark.-Pine Bluff": "ArkansasPineBluff",
    "Army West Point": "Army", "Boston U.": "BostonUniversity",
    "Cal St. Fullerton": "CalStateFullerton", "Central Ark.": "CentralArkansas",
    "Central Conn. St.": "CentralConnecticut", "Central Mich.": "CentralMichigan",
    "Charleston So.": "CharlestonSouthern", "Col. of Charleston": "Charleston",
    "ETSU": "EastTennesseeState", "Eastern Ill.": "EasternIllinois",
    "Eastern Ky.": "EasternKentucky", "Eastern Mich.": "EasternMichigan",
    "Eastern Wash.": "EasternWashington", "FDU": "FairleighDickinson",
    "FGCU": "FloridaGulfCoast", "Fla. Atlantic": "FloridaAtlantic",
    "Ga. Southern": "GeorgiaSouthern", "Grambling": "GramblingState",
    "LMU (CA)": "LoyolaMarymount", "Lamar University": "Lamar",
    "Loyola Maryland": "LoyolaMD", "Massachusetts": "UMass",
    "Middle Tenn.": "MiddleTennessee", "Mississippi Val.": "MississippiValleyState",
    "N.C. A&T": "NorthCarolinaAT", "N.C. Central": "NorthCarolinaCentral",
    "NIU": "NorthernIllinois", "North Ala.": "NorthAlabama",
    "Northern Ariz.": "NorthernArizona", "Northern Colo.": "NorthernColorado",
    "Northern Ky.": "NorthernKentucky", "Pittsburgh": "Pitt",
    "Prairie View": "PrairieViewAM", "SFA": "StephenFAustin",
    "Saint Francis": "SaintFrancisPA", "Seattle U": "Seattle",
    "South Fla.": "SouthFlorida", "Southeast Mo. St.": "SEMissouriState",
    "Southeastern La.": "SELouisiana", "Southern California": "USC",
    "Southern Ill.": "SouthernIllinois", "Southern Ind.": "SouthernIndiana",
    "Southern U.": "Southern", "UAlbany": "Albany", "UIW": "IncarnateWord",
    "ULM": "LouisianaMonroe", "UNCW": "UNCWilmington", "UNI": "NorthernIowa",
    "West Ga.": "WestGeorgia", "Western Caro.": "WesternCarolina",
    "Western Ill.": "WesternIllinois", "Western Ky.": "WesternKentucky",
    "Western Mich.": "WesternMichigan",
}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _lookup():
    """Normalized name → key, from our keys, aliases and display names."""
    table = {_norm(k): k for k in conferences.ESPN_IDS}
    table.update({_norm(a): conferences.canonical(a) for a in conferences.ALIASES})
    table.update({_norm(v): k for k, v in conferences.DISPLAY_NAMES.items()})
    return table


def to_key(name, table=None):
    """NCAA.com school name → our canonical key, or None."""
    if name in NCAA_NAME_OVERRIDES:
        return NCAA_NAME_OVERRIDES[name]
    table = table or _lookup()
    for cand in (name, re.sub(r"\bSt\.$", "State", re.sub(r"\s*\([A-Z]{2}\)$", "", name))):
        if _norm(cand) in table:
            return table[_norm(cand)]
    return None


def fetch_html():
    req = urllib.request.Request(NET_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _cells(fragment, tag):
    return [unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", fragment, re.S)]


def parse(html):
    """→ (through date, rows as dicts keyed by COLUMNS). Raises ValueError if the page changed."""
    m = re.search(r"Through Games\s+([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", html)
    if not m or m.group(1)[:3].lower() not in _MONTHS:
        raise ValueError("no 'Through Games <date>' line on the NET page")
    through = datetime.date(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2)))

    table = re.search(r"<table[^>]*>(.*?)</table>", html, re.S)
    if not table:
        raise ValueError("no table on the NET page")
    head = _cells(table.group(1), "th")
    if head != COLUMNS:
        raise ValueError(f"NET table columns changed: {head}")
    body = re.search(r"<tbody>(.*?)</tbody>", table.group(1), re.S)
    rows = [dict(zip(COLUMNS, _cells(tr, "td")))
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1) if body else "", re.S)]
    rows = [r for r in rows if len(r) == len(COLUMNS)]
    if len(rows) < 300:
        raise ValueError(f"NET table has only {len(rows)} rows")
    return through, rows


def season_of(day):
    """Project convention: 2027 = 2026-27 (season starts July 1)."""
    return day.year + (1 if day.month >= 7 else 0)


def build(html):
    """→ (payload dict, list of problems). Payload is only valid if problems is empty."""
    through, rows = parse(html)
    season = season_of(through)
    lookup = _lookup()
    teams, problems = {}, []
    for r in rows:
        key = to_key(r["School"], lookup)
        if not key:
            problems.append(f"unmapped NCAA name {r['School']!r} (add to NCAA_NAME_OVERRIDES)")
            continue
        if key in teams:
            problems.append(f"{r['School']!r} and another school both map to {key}")
            continue
        entry = {}
        for col, field in FIELDS.items():
            v = r[col]
            entry[field] = int(v) if field in ("rank", "prev") and v.isdigit() else v
        teams[key] = entry
    d1 = conferences.SEASONS.get(season)
    if d1:
        missing = sorted(set(d1) - set(teams))
        if missing:
            # Not fatal: a school can be D1 in conferences.py but absent from NET.
            print(f"  Note: {len(missing)} conferences.py schools not in NET: {missing}")
        extra = sorted(set(teams) - set(d1))
        if extra:
            print(f"  Note: in NET but not D1 in conferences.py for {season}: {extra}")
    payload = {
        "season": season,
        "through": through.isoformat(),
        "fetched": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "source": NET_URL,
        "teams": dict(sorted(teams.items(), key=lambda kv: kv[1]["rank"])),
    }
    return payload, problems


def run(base_dir):
    """Fetch NCAA.com and write net-SEASON.json. Returns True on success."""
    print("Fetching NCAA NET rankings...")
    try:
        payload, problems = build(fetch_html())
    except (OSError, ValueError) as e:
        print(f"  ✗ {e}")
        return False
    if problems:
        print("  ✗ Not writing:")
        for p in problems:
            print(f"    {p}")
        return False
    path = os.path.join(base_dir, f"net-{payload['season']}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=1)
        f.write("\n")
    top = next(iter(payload["teams"].items()))
    print(f"  ✓ {len(payload['teams'])} teams, season {payload['season']}, "
          f"through {payload['through']} → {os.path.basename(path)} "
          f"(#1 {top[0]}, Q1 {top[1]['q1']})")
    return True
