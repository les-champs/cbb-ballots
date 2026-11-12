import os
import sys
import re
import json
import time
import html as html_mod
import argparse
import urllib.request
import datetime
from io import BytesIO
from urllib.parse import unquote
from PIL import Image

import conferences
import nond1_logos
import net_rankings
import quads

# Output directory for logos
BASE_HTML_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_HTML_DIR, "cbb-logos")
HTML_PATH = os.path.join(BASE_HTML_DIR, "index.html")
AP_HTML_PATH = os.path.join(BASE_HTML_DIR, "ap-ballots.html")
CSS_PATH = os.path.join(BASE_HTML_DIR, "style.css")
JS_PATH = os.path.join(BASE_HTML_DIR, "script.js")

BASE_URL = "https://www.cbbpoll.net"
LOGO_PATH_PREFIX = "/static/D1/"

# Maps cbbpoll.net PNG filenames (without extension) to our canonical local logo names
LOGO_NAME_MAP = {
    "Miami(Florida)":            "MiamiFL",
    "MassachusettsAmherst":      "UMass",
    "Missouri\u2013KansasCity":  "KansasCity",
    "WisconsinGreenBay":         "GreenBay",
    "WisconsinMilwaukee":        "Milwaukee",
    "Boston":                                    "BostonCollege",
    "NorthCarolinaatCharlotte":                  "Charlotte",
    "MiamiUniversity(OH)":                       "MiamiOH",
    "TexasatAustin":                             "Texas",
    "Pennsylvania":                              "Penn",
    "MiamiUniversity(Ohio)":                     "MiamiOH",
    "SouthernIllinoisUniversityCarbondale":      "SouthernIllinois",
    "AlabamaA&M":                                "AlabamaAM",
    "UnitedStatesAirForceAcademy":               "AirForce",
    "PrairieViewA&M":                            "PrairieViewAM",
    "CollegeofWilliamandMary":                   "WilliamandMary",
    "NorthCarolinaatGreensboro":                 "UNCGreensboro",
    "NorthCarolinaatWilmington":                 "UNCWilmington",
    "TexasA&MUniversityCorpusChristi":                      "TexasAMCorpusChristi",
    "MiddleTennesseeState":                                 "MiddleTennessee",
    "HoustonBaptist":                                       "HoustonChristian",
    "FloridaAgriculturalandMechanical":                     "FloridaAM",
    "William&Mary":                                         "WilliamandMary",
    "IndianaUniversityPurdueUniversityIndianapolis":        "Purdue",
    "SavannahStateUniversity":                              "GeorgiaSouthern",
}

def canonical_logo_name(png_name):
    """Strip .png and apply LOGO_NAME_MAP to get the canonical local logo filename stem."""
    stem = png_name[:-4] if png_name.lower().endswith(".png") else png_name
    return LOGO_NAME_MAP.get(stem, stem)

# --- DEBUG SETTING ---
# Set to an integer to limit how many voter ballots are fetched (e.g. 5).
# Set to None to fetch all ballots.
DEBUG_LIMIT = None

# ── Fetching ────────────────────────────────────────────────────────────────

def fetch_page_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response:
        return response.read().decode("utf-8")

def extract_voters_from_section(section_html):
    voters, seen = [], set()

    # Format 1: homepage (w=64) or archive (w=32) — ballot link present
    linked_pattern = r'%2Fstatic%2FD1%2F([^&"]+\.png)&amp;w=(?:64|32)[^"]*"[^<]*(?:<[^>]+>)*</noscript></span><a href="(/ballots/[^"]*?)">([^<]+)</a>'
    linked_matches = re.findall(linked_pattern, section_html, re.DOTALL)
    if linked_matches:
        for logo_filename, ballot_path, username in linked_matches:
            logo_filename = unquote(logo_filename)
            username = username.strip()
            ballot_url = BASE_URL + ballot_path
            if username not in seen:
                seen.add(username)
                voters.append((logo_filename, username, ballot_url))
        return voters

    # Format 2: seasons archive — no ballot links available, username follows logo
    archive_pattern = r'srcSet="[^"]*%2Fstatic%2FD1%2F([^&"]+\.png)&amp;w=32[^"]*"[^<]*(?:<[^>]+>\s*)*</noscript></span>\s*(?:<!-- -->)?\s*([A-Za-z0-9_\-]+)'
    archive_matches = re.findall(archive_pattern, section_html, re.DOTALL)
    for logo_filename, username in archive_matches:
        logo_filename = unquote(logo_filename)
        username = username.strip()
        if username not in seen:
            seen.add(username)
            voters.append((logo_filename, username, None))  # None = no ballot URL on this page
    return voters

def split_voter_sections(html):
    # Homepage format: "Official Ballots" / "Provisional Ballots"
    official_match = re.search(r'Official Ballots', html)
    provisional_match = re.search(r'Provisional Ballots', html)
    if official_match and provisional_match:
        official_section = html[official_match.end():provisional_match.start()]
        provisional_section = html[provisional_match.end():]
        return official_section, provisional_section

    # Seasons archive format: "Poll Voters" / "Provisional Voters"
    poll_match = re.search(r'Poll Voters', html)
    prov_match = re.search(r'Provisional Voters', html)
    if poll_match and prov_match:
        official_section = html[poll_match.end():prov_match.start()]
        provisional_section = html[prov_match.end():]
        return official_section, provisional_section
    if poll_match:
        return html[poll_match.end():], ""

    print("WARNING: Could not find section headings — treating all voters as official.")
    return html, ""

def fetch_ballot_logos(ballot_url):
    try:
        html = fetch_page_html(ballot_url)
        encoded = re.findall(r'%2Fstatic%2FD1%2F([^&"]+\.png)&amp;w=64', html)
        return list(dict.fromkeys(unquote(e) for e in encoded))
    except Exception as e:
        print(f"  ✗ Could not fetch ballot {ballot_url}: {e}")
        return []

def fetch_ballot_url_for_week(username, week):
    """Fallback: fetch ballot URL from user profile page. Less reliable across years."""
    try:
        user_url = f"{BASE_URL}/users/{username}"
        html = fetch_page_html(user_url)
        pattern = rf'/ballots/{week}/([a-f0-9]+)'
        match = re.search(pattern, html)
        if match:
            return f"{BASE_URL}/ballots/{week}/{match.group(1)}"
        return None
    except Exception as e:
        print(f"  ✗ Could not fetch ballot for {username} week {week}: {e}")
        return None

def extract_next_data(html):
    """Extract the __NEXT_DATA__ JSON embedded in the page, if present."""
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except Exception:
        return None

def extract_ballot_urls_from_next_data(next_data, week):
    """Extract a {username: ballot_url} map from __NEXT_DATA__ pollVoters/provisionalVoters."""
    ballot_map = {}
    try:
        page_props = next_data.get("props", {}).get("pageProps", {})
        for key in ("pollVoters", "provisionalVoters"):
            entries = page_props.get(key, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                username = entry.get("username")
                ballot_id = entry.get("ballotId")
                if username and ballot_id:
                    ballot_map[username] = f"{BASE_URL}/ballots/{week}/{ballot_id}"
    except Exception as e:
        print(f"  [debug] Error parsing __NEXT_DATA__ for ballot URLs: {e}")
    return ballot_map

def fetch_unique_logos(html):
    encoded = re.findall(r'%2Fstatic%2FD1%2F([^&"]+\.png)', html)
    return sorted(set(unquote(e) for e in encoded))

# ESPN location name → our canonical logo filename stem (for cases where stripping spaces fails)
ESPN_NAME_OVERRIDES = {
    "Connecticut":              "UConn",
    "Louisiana State":          "LSU",
    "Southern California":      "USC",
    "Texas Christian":          "TCU",
    "Brigham Young":            "BYU",
    "Nevada Las Vegas":         "UNLV",
    "Miami":                    "MiamiFL",
    "Miami (OH)":               "MiamiOH",
    "Pittsburgh":               "Pitt",
    "Massachusetts":            "UMass",
    "Central Florida":          "UCF",
    "Alabama Birmingham":       "UAB",
    "California":               "Cal",
    "Texas El Paso":            "UTEP",
    "Texas San Antonio":        "UTSA",
    "Virginia Commonwealth":    "VCU",
    "Southern Methodist":       "SMU",
    "Alabama A&M":              "AlabamaAM",
    "Florida A&M":              "FloridaAM",
    "Prairie View A&M":         "PrairieViewAM",
    "Texas A&M Corpus Christi": "TexasAMCorpusChristi",
    "Wisconsin Green Bay":      "GreenBay",
    "Wisconsin Milwaukee":      "Milwaukee",
    "Missouri Kansas City":     "KansasCity",
    "North Carolina Charlotte": "Charlotte",
    "North Carolina Greensboro":"UNCGreensboro",
    "North Carolina Wilmington":"UNCWilmington",
    "McNeese State":            "McNeese",
    "St. John's (NY)":          "StJohns",
    "William & Mary":           "WilliamandMary",
    "Stephen F. Austin":        "StephenFAustin",
    "Arkansas Pine Bluff":      "ArkansasPineBluff",
    "Texas Rio Grande Valley":  "TexasRGV",
    "Texas Arlington":          "TexasArlington",
}

def get_dark_logo_teams():
    """Return sorted list of team name stems that have -dark.webp variants."""
    teams = []
    for fname in os.listdir(OUTPUT_DIR):
        m = re.match(r'^(.+)-dark\.webp$', fname)
        if m:
            teams.append(m.group(1))
    return sorted(teams)

def download_dark_logos():
    """Download ESPN dark-mode logos for all teams we have regular logos for."""
    api_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams?limit=1000"
    print("Fetching ESPN teams list...")
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    # Build ESPN location → ESPN ID map
    espn_map = {}
    for sport in data.get("sports", []):
        for league in sport.get("leagues", []):
            for entry in league.get("teams", []):
                t = entry.get("team", {})
                location = t.get("location", "")
                espn_id = t.get("id", "")
                if location and espn_id:
                    espn_map[location] = espn_id
    print(f"  ESPN has {len(espn_map)} teams")

    # Build our_name → ESPN ID by iterating all ESPN teams
    our_logos = set(
        fname[:-5]  # strip .webp
        for fname in os.listdir(OUTPUT_DIR)
        if fname.endswith(".webp") and not fname.endswith("-dark.webp")
    )
    espn_id_for = {}
    for location, espn_id in espn_map.items():
        if location in ESPN_NAME_OVERRIDES:
            our_name = ESPN_NAME_OVERRIDES[location]
        else:
            our_name = location.replace(' ', '')
        if our_name in our_logos:
            espn_id_for[our_name] = espn_id

    unmatched = our_logos - set(espn_id_for.keys())
    print(f"  Matched {len(espn_id_for)} teams, {len(unmatched)} unmatched")
    if unmatched:
        sample = sorted(unmatched)[:20]
        print(f"  Unmatched: {', '.join(sample)}" + (" ..." if len(unmatched) > 20 else ""))

    # Download dark logos
    downloaded = skipped = failed = no_dark = 0
    for team, espn_id in sorted(espn_id_for.items()):
        dest = os.path.join(OUTPUT_DIR, f"{team}-dark.webp")
        if os.path.exists(dest):
            skipped += 1
            continue
        url = f"https://a.espncdn.com/i/teamlogos/ncaa/500-dark/{espn_id}.png"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
            img = Image.open(BytesIO(raw))
            img.save(dest, format="WEBP", lossless=True)
            downloaded += 1
            print(f"  ✓ {team} (ESPN id={espn_id})")
            time.sleep(0.15)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                no_dark += 1
            else:
                print(f"  ✗ {team}: HTTP {e.code}")
                failed += 1
        except Exception as e:
            print(f"  ✗ {team}: {e}")
            failed += 1

    print(f"\n✓ Done. Downloaded {downloaded}, skipped {skipped} existing, "
          f"{no_dark} had no dark variant on ESPN, {failed} errors.")

# ESPN team IDs for schools whose conferences.py key doesn't match ESPN's
# location name (used by --missing-logos).
ESPN_ID_OVERRIDES = {
    "CSUBakersfield":  "2934",  # Cal State Bakersfield
    "CSUN":            "2463",  # Cal State Northridge
    "LouisianaMonroe": "2433",  # UL Monroe
    "LoyolaMD":        "2352",  # Loyola Maryland
    "NewOrleans":      "2443",  # LSU New Orleans
    "Queens":          "2511",  # Queens University
    "SaintFrancisPA":  "2598",  # left D1 in 2026, not in ESPN's current list
    "Seattle":         "2547",  # Seattle U
    "UTRGV":           "292",   # UT Rio Grande Valley
}

def download_missing_logos():
    """Download ESPN logos (regular + dark) for conferences.py schools with no logo file."""
    def norm(x):
        return re.sub(r"[^a-z]", "", x.lower())

    all_keys = {t for season in conferences.SEASONS.values() for t in season}
    missing = sorted(t for t in all_keys
                     if not os.path.exists(os.path.join(OUTPUT_DIR, f"{t}.webp")))
    if not missing:
        print("✓ Every school in conferences.py already has a logo.")
        return
    print(f"{len(missing)} schools have no logo file.")

    api_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams?limit=1000"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    by_location = {}
    for sport in data.get("sports", []):
        for league in sport.get("leagues", []):
            for entry in league.get("teams", []):
                t = entry.get("team", {})
                if t.get("location") and t.get("id"):
                    by_location[norm(t["location"])] = t["id"]

    def fetch(url, dest):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            Image.open(BytesIO(resp.read())).save(dest, format="WEBP", lossless=True)

    got = dark = 0
    failed = []
    for team in missing:
        display = conferences.DISPLAY_NAMES.get(team, re.sub(r"([a-z])([A-Z])", r"\1 \2", team))
        espn_id = (ESPN_ID_OVERRIDES.get(team)
                   or by_location.get(norm(team))
                   or by_location.get(norm(display)))
        if not espn_id:
            failed.append(f"{team} (no ESPN match)")
            continue
        try:
            fetch(f"https://a.espncdn.com/i/teamlogos/ncaa/500/{espn_id}.png",
                  os.path.join(OUTPUT_DIR, f"{team}.webp"))
            got += 1
        except Exception as e:
            failed.append(f"{team} (id={espn_id}: {e})")
            continue
        try:
            fetch(f"https://a.espncdn.com/i/teamlogos/ncaa/500-dark/{espn_id}.png",
                  os.path.join(OUTPUT_DIR, f"{team}-dark.webp"))
            dark += 1
        except Exception:
            pass  # no dark variant; the regular logo is used in dark mode
        print(f"  ✓ {team} (ESPN id={espn_id})")
        time.sleep(0.15)

    print(f"\n✓ Done. Downloaded {got} logos ({dark} with dark variants).")
    if failed:
        print("  ✗ Failed: " + ", ".join(failed))

def convert_all_to_webp():
    """One-time batch conversion of all existing PNGs to WebP."""
    logos = [f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".png")]
    print(f"Converting {len(logos)} PNGs to WebP...")
    before = sum(os.path.getsize(os.path.join(OUTPUT_DIR, f)) for f in logos)
    for i, logo in enumerate(logos):
        png_path = os.path.join(OUTPUT_DIR, logo)
        webp_path = os.path.join(OUTPUT_DIR, logo[:-4] + ".webp")
        try:
            img = Image.open(png_path)
            img.save(webp_path, format="WEBP", lossless=True)
            os.remove(png_path)
            print(f"  [{i+1}/{len(logos)}] {logo} → {os.path.basename(webp_path)}")
        except Exception as e:
            print(f"  ✗ Could not convert {logo}: {e}")
    after = sum(os.path.getsize(os.path.join(OUTPUT_DIR, f)) for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".webp"))
    saved = before - after
    print(f"\n✓ Done. Saved {saved/1024:.1f} KB ({100*saved/before:.1f}% reduction)")

def download_logos(logos):
    for logo in logos:
        # Store as WebP using canonical name (applies LOGO_NAME_MAP)
        webp_name = canonical_logo_name(logo) + ".webp"
        dest = os.path.join(OUTPUT_DIR, webp_name)
        if os.path.exists(dest):
            continue
        url = BASE_URL + LOGO_PATH_PREFIX + logo
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as response:
                raw = response.read()
            img = Image.open(BytesIO(raw))
            img.save(dest, format="WEBP", lossless=True)
        except Exception as e:
            print(f"✗ Failed to download {logo}: {e}")

def ballot_created_at(ballot_url):
    """cbbpoll.net ballot IDs are MongoDB ObjectIds; the first 8 hex chars are the creation time."""
    m = re.search(r'/([0-9a-f]{24})/?$', ballot_url or "")
    if not m:
        return None
    return datetime.datetime.fromtimestamp(int(m.group(1)[:8], 16), datetime.timezone.utc)

def season_start(year):
    """Earliest valid ballot date for season YEAR (the YEAR-1 to YEAR season starts in the fall of YEAR-1)."""
    return datetime.datetime(year - 1, 7, 1, tzinfo=datetime.timezone.utc)

def is_stale_ballot(ballot_url, year):
    created = ballot_created_at(ballot_url)
    return created is not None and year is not None and created < season_start(year)

def drop_stale_ballots(voters, year, label):
    """Drop voters whose listed ballot was created before season YEAR began (leftovers from past seasons)."""
    kept, dropped = [], []
    for v in voters:
        (dropped if is_stale_ballot(v[2], year) else kept).append(v)
    if dropped:
        names = ", ".join(f"{v[1]} ({ballot_created_at(v[2]).date()})" for v in dropped)
        print(f"Dropped {len(dropped)} {label} ballot(s) created before {season_start(year).date()}: {names}")
    return kept

def process_voters(voters, label, week=None, year=None, ballot_map=None):
    if DEBUG_LIMIT is not None:
        voters = voters[:DEBUG_LIMIT]
        print(f"  DEBUG MODE: limiting to {DEBUG_LIMIT} {label} voters.")
    results = []
    for i, (logo_filename, username, ballot_url) in enumerate(voters):
        print(f"  [{i+1}/{len(voters)}] {label}: {username}")
        # If no ballot URL, first try __NEXT_DATA__ map (year-scoped), then fall back to profile
        if ballot_url is None and week is not None:
            if ballot_map and username in ballot_map:
                ballot_url = ballot_map[username]
                print(f"    → found ballot via page JSON (year-scoped)")
            else:
                ballot_url = fetch_ballot_url_for_week(username, week)
                if ballot_url:
                    print(f"    → found ballot via archive")
                else:
                    print(f"    → no ballot found for week {week}")
            time.sleep(0.3)
            if ballot_url and is_stale_ballot(ballot_url, year):
                print(f"    → ballot is from {ballot_created_at(ballot_url).date()}, before this season; skipping")
                ballot_url = None
        if ballot_url:
            ballot_logos = fetch_ballot_logos(ballot_url)
            new_logos = [l for l in ballot_logos if not os.path.exists(os.path.join(OUTPUT_DIR, l))]
            if new_logos:
                download_logos(new_logos)
            results.append((logo_filename, username, ballot_url, ballot_logos[:25]))
            time.sleep(0.3)
        else:
            results.append((logo_filename, username, None, []))
    return sorted(results, key=lambda x: x[1].lower())

# ── cbbpoll.com Legacy Scraper ──────────────────────────────────────────────

CBBPOLL_BASE = "https://cbbpoll.com"

# Seasons available on cbbpoll.com: year param → valid weeks
CBBPOLL_SEASONS = {
    2016: list(range(2, 20)),          # 2015-16 (no preseason)
    2017: [0] + list(range(3, 20)),   # 2016-17
    2018: [0] + list(range(2, 21)),   # 2017-18
    2019: [0] + list(range(2, 22)),   # 2018-19
    2020: [0] + list(range(2, 21)),   # 2019-20
    2021: [0] + list(range(2, 19)),   # 2020-21
    2022: [0] + list(range(2, 21)),   # 2021-22
}

# Map cbbpoll.com display names → our logo filenames (without extension).
# Auto-normalization handles most cases; these are manual overrides.
CBBPOLL_NAME_OVERRIDES = {
    # Directional / regional qualifiers
    "NC State": "NCState",
    "Ole Miss": "OleMiss",
    "Miami (FL)": "MiamiFL",
    "Miami (OH)": "MiamiOH",
    "USC Upstate": "USCUpstate",
    "Saint Mary's": "SaintMarys",
    "Saint Mary's (CA)": "SaintMarys",
    "St. Mary's": "SaintMarys",
    "St. Mary's (CA)": "SaintMarys",
    "Saint Joseph's": "SaintJosephs",
    "St. Joseph's": "SaintJosephs",
    "Saint Louis": "SaintLouis",
    "St. Louis": "SaintLouis",
    "St. John's": "StJohns",
    "Saint John's": "StJohns",
    "St. Bonaventure": "StBonaventure",
    "Saint Bonaventure": "StBonaventure",
    "Mt. St. Mary's": "MountStMarys",
    "Mount St. Mary's": "MountStMarys",
    "Stephen F. Austin": "StephenFAustin",
    "UNC Greensboro": "UNCGreensboro",
    "UNC Wilmington": "UNCWilmington",
    "UT Martin": "UTMartin",
    "North Carolina": "NorthCarolina",
    "North Carolina at Chapel Hill": "NorthCarolina",
    "Wisconsin-Madison": "Wisconsin",
    "South Carolina": "SouthCarolina",
    "North Dakota": "NorthDakota",
    "South Dakota": "SouthDakota",
    "South Dakota State": "SouthDakotaState",
    "North Dakota State": "NorthDakotaState",
    "West Virginia": "WestVirginia",
    "San Diego State": "SanDiegoState",
    "San Jose State": "SanJoseState",
    "San Francisco": "SanFrancisco",
    "Santa Clara": "SantaClara",
    "Boise State": "BoiseState",
    "Colorado State": "ColoradoState",
    "Utah State": "UtahState",
    "Iowa State": "IowaState",
    "Ohio State": "OhioState",
    "Penn State": "PennState",
    "Michigan State": "MichiganState",
    "Kansas State": "KansasState",
    "Oklahoma State": "OklahomaState",
    "Oregon State": "OregonState",
    "Washington State": "WashingtonState",
    "Arizona State": "ArizonaState",
    "Mississippi State": "MississippiState",
    "Florida State": "FloridaState",
    "Florida Atlantic": "FloridaAtlantic",
    "Central Michigan": "CentralMichigan",
    "Eastern Michigan": "EasternMichigan",
    "Western Michigan": "WesternMichigan",
    "Northern Iowa": "NorthernIowa",
    "Northern Arizona": "NorthernArizona",
    "Northern Colorado": "NorthernColorado",
    "North Texas": "NorthTexas",
    "North Florida": "NorthFlorida",
    "South Florida": "SouthFlorida",
    "South Alabama": "SouthAlabama",
    "Southern Miss": "SouthernMiss",
    "Southern Mississippi": "SouthernMiss",
    "Appalachian State": "AppalachianState",
    "Arkansas State": "ArkansasState",
    "Indiana State": "IndianaState",
    "Missouri State": "MissouriState",
    "Murray State": "MurrayState",
    "Wichita State": "WichitaState",
    "Kent State": "KentState",
    "Bowling Green": "BowlingGreen",
    "George Mason": "GeorgeMason",
    "George Washington": "GeorgeWashington",
    "Georgia Tech": "GeorgiaTech",
    "Georgia State": "GeorgiaState",
    "Virginia Tech": "VirginiaTech",
    "Wake Forest": "WakeForest",
    "Boston University": "BostonUniversity",
    "Boston College": "BostonCollege",
    "Central Connecticut": "CentralConnecticut",
    "Youngstown State": "YoungstownState",
    "Weber State": "WeberState",
    "Morehead State": "MoreheadState",
    "Western Carolina": "WesternCarolina",
    "James Madison": "JamesMadison",
    "West Georgia": "WestGeorgia",
    "Grand Canyon": "GrandCanyon",
    "High Point": "HighPoint",
    "Purdue Fort Wayne": "PurdueFortWayne",
    "UC Irvine": "UCIrvine",
    "UC Davis": "UCDavis",
    "UC Riverside": "UCRiverside",
    "UC San Diego": "UCSanDiego",
    "UC Santa Barbara": "UCSantaBarbara",
    "UMass Lowell": "UMassLowell",
    "Louisiana Tech": "LouisianaTech",
    "Texas A&M": "TexasAM",
    "Texas Tech": "TexasTech",
    "New Mexico": "NewMexico",
    "New Mexico State": "NewMexicoState",
    "Loyola Chicago": "LoyolaChicago",
    "Loyola-Chicago": "LoyolaChicago",
    "Loyola Marymount": "LoyolaMarymount",
    "Rhode Island": "RhodeIsland",
    "Seton Hall": "SetonHall",
    "De Paul": "DePaul",
    "DePaul": "DePaul",
    "California Baptist": "CaliforniaBaptist",
    "Notre Dame": "NotreDame",
    "La Salle": "LaSalle",
    "Long Island": "LIU",
    "Long Island University": "LIU",
    "Delaware State": "DelawareState",
    "Stony Brook": "StonyBrook",
    "St. Peter's": "SaintPeters",
    "Saint Peter's": "SaintPeters",
    "Chattanooga": "Chattanooga",
    "URI": "RhodeIsland",
    "UAB": "UAB",
    "UNCG": "UNCGreensboro",
    "UNCW": "UNCWilmington",
    "UNI": "NorthernIowa",
    "SDSU": "SanDiegoState",
    "SJSU": "SanJoseState",
    "UCSB": "UCSantaBarbara",
    "UIC": "UIC",
    "SIUE": "SIUEdwardsville",
    "SIU Edwardsville": "SIUEdwardsville",
    "SIU": "SIU",
    "ETSU": "EastTennesseeState",
    "MTSU": "MiddleTennesseeState",
    "MT": "MT",  # Middle Tennessee — logo saved as MT.webp
    "UTSA": "UTSA",
    "BC": "BostonCollege",
    "ECU": "EastCarolina",
    "Cal Baptist": "CaliforniaBaptist",
    "Central Connecticut State": "CentralConnecticut",
    "University of Central Arkansas": "CentralArkansas",
    "Texas A&M-Corpus Christi": "TexasAMCorpusChristi",
    "The Citadel": "Citadel",
    "Alabama A&M": "AlabamaAM",
    "Prairie View A&M": "PrairieViewAM",
    "SE Missouri State": "SEMissouriState",
    "Nebraska-Omaha": "NebraskaOmaha",
    "Kansas City": "KansasCity",
    "College of Charleston": "CollegeofCharleston",
    "Tarleton State": "TarletonState",
    "Savannah State University": "SavannahState",
    "Savannah State": "SavannahState",
    "GW": "GeorgeWashington",
    "William & Mary": "WilliamandMary",
    "William and Mary": "WilliamandMary",
    "USF": "USF",
    "SC State": "SCState",
    "UMES": "UMES",
}

# Map cbbpoll.com full university alt text → our logo filenames.
# e.g., "University of Virginia Logo" → "Virginia"
CBBPOLL_ALT_OVERRIDES = {
    "University of California, Los Angeles Logo": "UCLA",
    "University of Southern California Logo": "USC",
    "University of Connecticut Logo": "UConn",
    "University of Central Florida Logo": "UCF",
    "University of Texas at El Paso Logo": "UTEP",
    "University of Nevada, Las Vegas Logo": "UNLV",
    "Brigham Young University Logo": "BYU",
    "Virginia Commonwealth University Logo": "VCU",
    "Southern Methodist University Logo": "SMU",
    "Texas Christian University Logo": "TCU",
    "Louisiana State University Logo": "LSU",
    "University of Pittsburgh Logo": "Pitt",
    "University of Massachusetts Logo": "UMass",
    "University of Massachusetts Lowell Logo": "UMassLowell",
    "North Carolina State University Logo": "NCState",
    "Virginia Polytechnic Institute and State University Logo": "VirginiaTech",
    "University of Mississippi Logo": "OleMiss",
    "University of Illinois at Urbana-Champaign Logo": "Illinois",
    "Georgia Institute of Technology Logo": "GeorgiaTech",
    "Pennsylvania State University Logo": "PennState",
    "Indiana University Bloomington Logo": "Indiana",
    "Arizona State University Logo": "ArizonaState",
    "Mississippi State University Logo": "MississippiState",
    "University of California, Irvine Logo": "UCIrvine",
    "University of California, Davis Logo": "UCDavis",
    "University of California, Riverside Logo": "UCRiverside",
    "University of California, San Diego Logo": "UCSanDiego",
    "University of California, Santa Barbara Logo": "UCSantaBarbara",
    "University of California, Berkeley Logo": "California",
    "University of Miami Logo": "MiamiFL",
    "Miami University Logo": "MiamiOH",
    "Purdue University Fort Wayne Logo": "PurdueFortWayne",
    "Stephen F. Austin State University Logo": "StephenFAustin",
    "Texas A&M University Logo": "TexasAM",
    "St. Bonaventure University Logo": "StBonaventure",
    "College of the Holy Cross Logo": "HolyCross",
    "Saint Mary's College of California Logo": "SaintMarys",
    "Loyola University Chicago Logo": "LoyolaChicago",
    "Loyola Marymount University Logo": "LoyolaMarymount",
    "Seton Hall University Logo": "SetonHall",
    "Long Island University Logo": "LIU",
    "Florida International University Logo": "FIU",
    "University of Hawai'i at Manoa Logo": "Hawaii",
    "University of Hawaii at Manoa Logo": "Hawaii",
    "University of Nebraska Omaha Logo": "Omaha",
    "University of Nebraska-Lincoln Logo": "Nebraska",
}

def _normalize_team_name(display_name):
    """Auto-normalize a cbbpoll.com display name to our logo filename format."""
    # Check manual overrides first
    if display_name in CBBPOLL_NAME_OVERRIDES:
        return CBBPOLL_NAME_OVERRIDES[display_name]
    # Strip periods, apostrophes, hyphens, spaces → PascalCase already matches most
    normalized = display_name.replace(".", "").replace("'", "").replace("'", "").replace("-", "").replace(" ", "")
    return normalized

def _normalize_alt_text(alt_text):
    """Map a cbbpoll.com alt text (e.g. 'University of Virginia Logo') to our logo filename."""
    if alt_text in CBBPOLL_ALT_OVERRIDES:
        return CBBPOLL_ALT_OVERRIDES[alt_text]
    # Try stripping " Logo" and common prefixes
    name = alt_text
    if name.endswith(" Logo"):
        name = name[:-5]
    # "University of X" → "X"
    if name.startswith("University of "):
        name = name[14:]
        # "University of X at Y" → just "X" for simple cases
        if ", " in name:
            name = name.split(", ")[0]
    elif name.endswith(" University"):
        name = name[:-11]
    elif name.endswith(" College"):
        name = name[:-8]
    # Now normalize like a display name
    return _normalize_team_name(name.strip())

def cbbpoll_fetch_poll_page(year, week):
    """Fetch a cbbpoll.com poll page and extract voters + ballot URLs."""
    url = f"{CBBPOLL_BASE}/poll/{year}/{week}"
    html = fetch_page_html(url)

    official = []
    provisional = []

    # Split into sections
    off_start = html.find("Official Ballots")
    prov_start = html.find("Provisional Ballots")
    nonsub_start = html.find("Voters who failed to submit")

    if off_start == -1:
        print(f"  WARNING: No 'Official Ballots' section found on {url}")
        return official, provisional

    # Determine section boundaries
    off_end = prov_start if prov_start != -1 else (nonsub_start if nonsub_start != -1 else len(html))
    prov_end = nonsub_start if nonsub_start != -1 else len(html)

    off_section = html[off_start:off_end]
    prov_section = html[prov_start:prov_end] if prov_start != -1 else ""

    # Extract ballot-list-items: <a href="/ballot/ID"><span class=logo23>...<alt="..."></span>USERNAME</a>
    pattern = r"<a href=\"/ballot/(\d+)\"><span class=logo23><img[^>]*alt=\"([^\"]*)\"></span>([^<]+)</a>"

    for match in re.finditer(pattern, off_section):
        ballot_id, flair_alt, username = match.groups()
        official.append({
            "username": html_mod.unescape(username.strip()),
            "flair_alt": html_mod.unescape(flair_alt),
            "ballot_id": int(ballot_id),
        })

    for match in re.finditer(pattern, prov_section):
        ballot_id, flair_alt, username = match.groups()
        provisional.append({
            "username": html_mod.unescape(username.strip()),
            "flair_alt": html_mod.unescape(flair_alt),
            "ballot_id": int(ballot_id),
        })

    return official, provisional

def cbbpoll_fetch_ballot(ballot_id):
    """Fetch a cbbpoll.com ballot page and extract the ordered team list."""
    url = f"{CBBPOLL_BASE}/ballot/{ballot_id}"
    html = fetch_page_html(url)

    # Extract team display names from: <span class="team-name">...</span> TEAMNAME</span>
    pattern = r'class="team-name"><span class=logo30><img[^>]*></span>\s*([^<]+)</span>'
    teams = [html_mod.unescape(m.strip()) for m in re.findall(pattern, html)]
    return teams[:25]

def cbbpoll_scrape_season(year):
    """Scrape an entire season from cbbpoll.com, saving to JSON with resume support."""
    if year not in CBBPOLL_SEASONS:
        print(f"✗ Year {year} not available on cbbpoll.com. Valid: {sorted(CBBPOLL_SEASONS.keys())}")
        return

    json_path = os.path.join(BASE_HTML_DIR, f"cbbpoll-{year}.json")

    # Load existing cache for resume
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            data = json.load(f)
        print(f"Loaded existing cache: {json_path}")
    else:
        data = {"year": year, "weeks": {}}

    weeks = CBBPOLL_SEASONS[year]
    unmapped_names = set()

    for week in weeks:
        week_key = str(week)
        # Check if week already fully scraped (all voters have teams)
        if week_key in data["weeks"]:
            existing = data["weeks"][week_key]
            all_have_teams = all(
                v.get("teams") for section in ("official", "provisional")
                for v in existing.get(section, [])
            )
            if all_have_teams:
                n_off = len(existing.get("official", []))
                n_prov = len(existing.get("provisional", []))
                print(f"Week {week}: already cached ({n_off} official, {n_prov} provisional)")
                continue

        print(f"\nWeek {week}: fetching poll page...")
        try:
            official, provisional = cbbpoll_fetch_poll_page(year, week)
        except Exception as e:
            print(f"  ✗ Failed to fetch poll page: {e}")
            continue
        print(f"  Found {len(official)} official, {len(provisional)} provisional voters")
        time.sleep(0.5)

        # Build lookup of already-fetched ballots for this week
        existing_week = data["weeks"].get(week_key, {})
        existing_ballots = {}
        for section in ("official", "provisional"):
            for v in existing_week.get(section, []):
                if v.get("teams"):
                    existing_ballots[v["ballot_id"]] = v["teams"]

        # Fetch each ballot
        for label, voters in [("Official", official), ("Provisional", provisional)]:
            if DEBUG_LIMIT is not None:
                voters_to_fetch = voters[:DEBUG_LIMIT]
                print(f"  DEBUG MODE: limiting to {DEBUG_LIMIT} {label} voters.")
            else:
                voters_to_fetch = voters
            for i, voter in enumerate(voters_to_fetch):
                bid = voter["ballot_id"]
                if bid in existing_ballots:
                    voter["teams"] = existing_ballots[bid]
                    continue
                print(f"  [{i+1}/{len(voters_to_fetch)}] {label}: {voter['username']}")
                try:
                    teams = cbbpoll_fetch_ballot(bid)
                    voter["teams"] = teams
                except Exception as e:
                    print(f"    ✗ Failed: {e}")
                    voter["teams"] = []
                time.sleep(0.3)

        # Track unmapped names
        for section in (official, provisional):
            for v in section:
                for team_name in v.get("teams", []):
                    logo = _normalize_team_name(team_name)
                    if not os.path.exists(os.path.join(OUTPUT_DIR, f"{logo}.webp")):
                        unmapped_names.add(team_name)

        data["weeks"][week_key] = {
            "official": official,
            "provisional": provisional,
        }

        # Save after each week for resume support
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  ✓ Saved week {week} to {json_path}")

    if unmapped_names:
        print(f"\n⚠️  Unmapped team names (no matching logo file):")
        for name in sorted(unmapped_names):
            print(f"    {name!r} → {_normalize_team_name(name)!r}")

    print(f"\n✓ Done scraping {year}. Data saved to {json_path}")

def cbbpoll_build_season(year):
    """Build HTML week blocks from cached cbbpoll.com JSON data."""
    json_path = os.path.join(BASE_HTML_DIR, f"cbbpoll-{year}.json")
    if not os.path.exists(json_path):
        print(f"✗ No cached data found at {json_path}. Run --cbbpoll --year {year} first.")
        return

    with open(json_path, "r") as f:
        data = json.load(f)

    weeks = sorted(data["weeks"].keys(), key=lambda w: int(w))
    print(f"Building HTML for {year}: {len(weeks)} weeks")

    # Build set of official voter usernames from weeks 2 and 3 to reclassify week 0
    official_panel = set()
    for ref_week in ("2", "3"):
        for v in data["weeks"].get(ref_week, {}).get("official", []):
            official_panel.add(v["username"])

    for week_key in weeks:
        week = int(week_key)
        week_data = data["weeks"][week_key]

        if week == 0 and official_panel:
            # Reclassify week 0 voters based on their status in weeks 2/3
            all_week0 = week_data.get("official", []) + week_data.get("provisional", [])
            reclassified_official = [v for v in all_week0 if v["username"] in official_panel]
            reclassified_provisional = [v for v in all_week0 if v["username"] not in official_panel]
            official = _cbbpoll_voters_to_tuples(reclassified_official)
            provisional = _cbbpoll_voters_to_tuples(reclassified_provisional)
            print(f"  Week 0: reclassified {len(reclassified_official)} official + {len(reclassified_provisional)} provisional (from weeks 2/3 panel)")
        else:
            official = _cbbpoll_voters_to_tuples(week_data.get("official", []))
            provisional = _cbbpoll_voters_to_tuples(week_data.get("provisional", []))

        if not official and not provisional:
            print(f"  Week {week}: no voter data, skipping")
            continue

        week_label = "Pre-Season" if week == 0 else None
        week_block = build_week_block(week, year, official, provisional)
        save_html(week, year, week_block, HTML_PATH, week_label=week_label)
        print(f"  ✓ Week {week}: {len(official)} official + {len(provisional)} provisional")

    print(f"\n✓ Built HTML for {year}.")

def _cbbpoll_voters_to_tuples(voters):
    """Convert cbbpoll.com JSON voter dicts to the (logo_filename, username, ballot_url, ballot_logos) tuples
    expected by build_week_block."""
    results = []
    for v in voters:
        username = v["username"]
        ballot_id = v.get("ballot_id")
        ballot_url = f"{CBBPOLL_BASE}/ballot/{ballot_id}" if ballot_id else None

        # Voter flair logo
        flair_alt = v.get("flair_alt", "")
        flair_logo = _normalize_alt_text(flair_alt) + ".png" if flair_alt else "unknown.png"

        # Ballot team logos
        teams = v.get("teams", [])
        ballot_logos = [_normalize_team_name(t) + ".png" for t in teams]

        results.append((flair_logo, username, ballot_url, ballot_logos))
    return sorted(results, key=lambda x: x[1].lower())

# ── AP 25 Scraper (collegepolltracker.com) ─────────────────────────────────

AP25_BASE = "https://collegepolltracker.com/basketball/grid"

# Site year → our year: site's 2025 = 2025-26 season = our 2026
# Available site years: 2021-2026 → our 2022-2027
AP25_SITE_YEARS = {2021: 2022, 2022: 2023, 2023: 2024, 2024: 2025, 2025: 2026, 2026: 2027}

# Site years whose in-season slugs start at week-1 instead of week-2 (the first
# poll after pre-season is "week-1"). Our stored week = site week number + 1.
AP25_WEEK1_SITE_YEARS = {2026}

# AP-specific name overrides (title attributes from collegepolltracker.com)
# Most names match cbbpoll overrides already; add AP-specific ones here.
AP25_NAME_OVERRIDES = {
    "McNeese State": "McNeese",
    "East Texas A&M": "TexasAMCommerce",
    "Pittsburgh": "Pitt",
}

def _normalize_ap_team_name(display_name):
    """Normalize an AP team display name to our logo filename."""
    # Check AP-specific overrides first, then fall back to cbbpoll overrides
    if display_name in AP25_NAME_OVERRIDES:
        return AP25_NAME_OVERRIDES[display_name]
    return _normalize_team_name(display_name)

def ap25_fetch_grid(site_year, week_slug):
    """Fetch an AP grid page and extract voter ballots.

    Returns (voters, actual_week_slug) where voters is a list of
    {"username": str, "affiliation": str, "teams": [str]} dicts.
    actual_week_slug is what the page actually shows (to detect redirects).
    """
    url = f"{AP25_BASE}/{site_year}/{week_slug}"
    page_html = fetch_page_html(url)

    # Detect which week the page is actually showing (redirect detection)
    selected_match = re.search(
        r'<option value="([^"]*)" selected="selected">[^<]*</option>(?=.*</select>.*<select)',
        page_html, re.DOTALL
    )
    # Simpler: find the week dropdown's selected value
    # The week select comes second; find all selected options
    selected_options = re.findall(r'<option value="([^"]*)" selected="selected">', page_html)
    actual_week = selected_options[1] if len(selected_options) >= 2 else week_slug

    # Parse grid rows
    parts = page_html.split('<div class="gridRow">')
    voters = []
    for part in parts[1:]:  # skip preamble before first row
        # Voter name
        voter_match = re.search(r'<a href="[^"]*">([^<]+)</a>', part)
        if not voter_match:
            continue
        username = html_mod.unescape(voter_match.group(1).strip())

        # Affiliation
        aff_match = re.search(r'gridPollsterAffiliation">([^<]+)', part)
        affiliation = html_mod.unescape(aff_match.group(1).strip()) if aff_match else ""

        # Teams from title attributes (only on team icons — the last row's chunk
        # runs to end of page, where ad-rail close buttons also carry titles)
        teams_raw = [
            m.group(1)
            for img in re.findall(r'<img[^>]*class="gridTeamIcon"[^>]*>', part)
            if (m := re.search(r'title="([^"]+)"', img))
        ]
        teams = [html_mod.unescape(t) for t in teams_raw[:25]]

        voters.append({
            "username": username,
            "affiliation": affiliation,
            "teams": teams,
        })

    return voters, actual_week

def ap25_scrape_season(our_year):
    """Scrape an entire AP season from collegepolltracker.com to JSON."""
    site_year = our_year - 1
    if site_year not in AP25_SITE_YEARS:
        print(f"✗ Year {our_year} not available. Valid our-years: {sorted(AP25_SITE_YEARS.values())}")
        return

    json_path = os.path.join(BASE_HTML_DIR, f"ap25-{our_year}.json")

    # Load existing cache
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            data = json.load(f)
        print(f"Loaded existing cache: {json_path}")
    else:
        data = {"year": our_year, "site_year": site_year, "weeks": {}}

    # Week slugs to try: pre-season, then week-2 through week-19, then final-rankings
    shift = 1 if site_year in AP25_WEEK1_SITE_YEARS else 0
    week_slugs = ["pre-season"] + [f"week-{w - shift}" for w in range(2, 20)] + ["final-rankings"]
    unmapped_names = set()

    for week_slug in week_slugs:
        # Map week slug to our week number
        if week_slug == "pre-season":
            week_num = 0
        elif week_slug == "final-rankings":
            week_num = 20
        else:
            week_num = int(week_slug.split("-")[1]) + shift
        week_key = str(week_num)

        # Skip already-cached weeks
        if week_key in data["weeks"] and data["weeks"][week_key].get("voters"):
            n = len(data["weeks"][week_key]["voters"])
            print(f"Week {week_num}: already cached ({n} voters)")
            continue

        print(f"\nWeek {week_num} ({week_slug}): fetching grid...")
        try:
            voters, actual_week = ap25_fetch_grid(site_year, week_slug)
        except Exception as e:
            print(f"  ✗ Failed to fetch: {e}")
            continue

        # Detect redirect to different week (invalid week)
        if actual_week != week_slug:
            print(f"  → Redirected to {actual_week}, skipping (week doesn't exist)")
            continue

        if not voters:
            print(f"  → No voter data found, skipping")
            continue

        print(f"  Found {len(voters)} voters")

        # Track unmapped names
        for v in voters:
            for team_name in v["teams"]:
                logo = _normalize_ap_team_name(team_name)
                if not os.path.exists(os.path.join(OUTPUT_DIR, f"{logo}.webp")):
                    unmapped_names.add(team_name)

        data["weeks"][week_key] = {"voters": voters}

        # Save after each week for resume support
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  ✓ Saved week {week_num} to {json_path}")
        time.sleep(0.3)

    if unmapped_names:
        print(f"\n⚠️  Unmapped AP team names (no matching logo file):")
        for name in sorted(unmapped_names):
            print(f"    {name!r} → {_normalize_ap_team_name(name)!r}")

    print(f"\n✓ Done scraping AP {our_year} (site {site_year}). Data saved to {json_path}")

def ap25_build_season(our_year):
    """Build HTML week blocks from cached AP JSON data (batch — one fragment write per year)."""
    json_path = os.path.join(BASE_HTML_DIR, f"ap25-{our_year}.json")
    if not os.path.exists(json_path):
        print(f"✗ No cached data at {json_path}. Run --ap25 --year {our_year} first.")
        return

    with open(json_path, "r") as f:
        data = json.load(f)

    weeks = sorted(data["weeks"].keys(), key=lambda w: int(w))
    print(f"Building AP HTML for {our_year}: {len(weeks)} weeks")

    # Build all week blocks and tabs for this year in memory
    new_tabs = []
    new_blocks = []
    appage_blocks = []
    for week_key in weeks:
        week = int(week_key)
        week_data = data["weeks"][week_key]
        if not week_data.get("voters"):
            print(f"  Week {week}: no voter data, skipping")
            continue
        voter_tuples = _ap_voter_tuples(week_data)
        new_blocks.append(build_ap_week_block(week, our_year, voter_tuples))
        appage_blocks.append(build_ap_week_block(week, our_year, voter_tuples, for_ap_page=True))
        new_tabs.append(make_tab(our_year, week, ap_week_label(week), poll="ap"))
        print(f"  ✓ Week {week}: {len(voter_tuples)} voters")

    # Write fragment files for this year (single write each): index.html AP fragments
    # and ap-ballots.html fragments with clean IDs (no 'ap-' prefix)
    base_dir = os.path.dirname(HTML_PATH) or "."
    for prefix, blocks in (("data-ap-", new_blocks), ("data-appage-", appage_blocks)):
        with open(os.path.join(base_dir, f"{prefix}{our_year}.html"), "w", encoding="utf-8") as f:
            f.write("\n".join(b.strip() for b in blocks))

    # Update index.html: read existing AP tabs, remove this year's tabs, add new ones
    _update_ap_tabs_for_year(HTML_PATH, our_year, new_tabs)

    # Regenerate ap-ballots.html
    rebuild_ap_html()

    print(f"\n✓ Built AP HTML for {our_year}.")

def _compute_aggregate_points(voters):
    """Return top-25 list of (team, pts) from voter tuples using rank 1=25pts … rank 25=1pt."""
    points = {}
    for _, _, _, ballot_logos in voters:
        for i, logo in enumerate(ballot_logos[:25]):
            team = canonical_logo_name(logo)
            points[team] = points.get(team, 0) + (25 - i)
    return sorted(points.items(), key=lambda x: -x[1])[:25]

def ap_week_label(week):
    """Display label for an AP week: 0 is Pre-Season, 20 is Final, others are numbered."""
    return "Pre-Season" if week == 0 else ("Final" if week == 20 else None)

def _ap_voter_tuples(week_data):
    """Convert one week of cached AP JSON into sorted (flair, username, ballot_url, logos) tuples."""
    tuples = [
        ("", v["username"], None, [_normalize_ap_team_name(t) + ".png" for t in v["teams"]])
        for v in week_data.get("voters", []) if v["teams"]
    ]
    tuples.sort(key=lambda x: x[1].lower())
    return tuples

def build_ap_week_block(week, year, voters, for_ap_page=False):
    """Build the HTML block for one AP week.

    index.html blocks use IDs week-ap-YEAR-N with data-poll="ap"; ap-ballots.html
    (for_ap_page=True) uses plain week-YEAR-N IDs and no data-poll.
    """
    if for_ap_page:
        week_id, attrs = f"week-{year}-{week}", ""
    else:
        week_id, attrs = f"week-ap-{year}-{week}", ' data-poll="ap"'
    return _week_block_html(
        week_id,
        build_table_html(voters),
        build_table(""),
        build_table(build_overall_row(voters, "AP Overall")),
        attrs,
    )

def _update_ap_tabs_for_year(html_path, year, new_tabs):
    """Update AP tabs in index.html: remove this year's old tabs, add new ones, update AP_FRAGMENT_YEARS."""
    if not os.path.exists(html_path):
        return
    existing_tabs, ap_fragment_years = get_ap_info(html_path)
    kept_lines = [line for line in existing_tabs.split("\n")
                  if line.strip() and f'data-year="{year}" data-poll="ap"' not in line]
    ap_tabs_html = "\n".join(kept_lines + new_tabs).strip()
    _update_ap_in_index(html_path, ap_tabs_html, ap_fragment_years)

def _update_ap_in_index(html_path, ap_tabs_html, ap_fragment_years):
    """Update the AP tabs section and AP_FRAGMENT_YEARS constant in index.html."""
    if not os.path.exists(html_path):
        return
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Update AP tabs section
    ap_tabs_block = f"<!-- AP-TABS -->\n{ap_tabs_html}\n<!-- /AP-TABS -->"
    if "<!-- AP-TABS -->" in content:
        # Replace existing AP-TABS block in-place
        content = re.sub(
            r'<!-- AP-TABS -->\n.*?\n<!-- /AP-TABS -->',
            ap_tabs_block,
            content, flags=re.DOTALL
        )
    else:
        # Insert before the closing </div> of week-tabs (which precedes voter-history-modal)
        content = content.replace(
            "</div>\n\n<div id=\"voter-history-modal\">",
            f"\n{ap_tabs_block}\n</div>\n\n<div id=\"voter-history-modal\">",
            1,
        )

    # Update AP_FRAGMENT_YEARS
    ap_years_js = json.dumps(ap_fragment_years)
    if "const AP_FRAGMENT_YEARS" in content:
        content = re.sub(
            r'const AP_FRAGMENT_YEARS = \[.*?\];',
            f'const AP_FRAGMENT_YEARS = {ap_years_js};',
            content
        )
    else:
        content = content.replace(
            "const FRAGMENT_YEARS",
            f"const AP_FRAGMENT_YEARS = {ap_years_js};\nconst FRAGMENT_YEARS",
        )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)


# ── HTML Building ────────────────────────────────────────────────────────────

def build_table_rows(voters_with_ballots):
    rows = ""
    for logo_filename, username, ballot_url, ballot_logos in voters_with_ballots:
        team_name = canonical_logo_name(logo_filename)
        ballot_attr = f' data-ballot-url="{ballot_url}"' if ballot_url else ''
        if team_name:
            flair_html = f'<img class="logo" data-team="{team_name}" data-src="{team_name}">'
        else:
            flair_html = ''
        inner = flair_html + f'<span class="voter-name">{username}</span>'
        voter_cell = f'<div class="voter-cell" {ballot_attr}>{inner}</div>'
        ballot_logo_cells = "".join(
            f'<td class="logo-cell"><img class="logo team-logo" data-team="{canonical_logo_name(bl)}" data-src="{canonical_logo_name(bl)}"></td>'
            for bl in ballot_logos
        )
        rows += f'<tr class="voter-row"><td>{voter_cell}</td>{ballot_logo_cells}</tr>\n'
    return rows

def build_overall_row(voters, label):
    """Build a single aggregate row using points (rank 1=25pts ... rank 25=1pt)."""
    ballot_logo_cells = "".join(
        f'<td class="logo-cell"><img class="logo team-logo" data-team="{team}" data-src="{team}"></td>'
        for team, _ in _compute_aggregate_points(voters)
    )
    voter_cell = f'<div class="voter-cell" ><span class="voter-name">{label}</span></div>'
    return f'<tr class="voter-row"><td>{voter_cell}</td>{ballot_logo_cells}</tr>\n'

# One Functions menu per page, in a <template>: script.js clones it next to a
# table's Functions toggle the first time that toggle is clicked, so the ~60
# tables in each fragment carry only the toggle instead of a full menu copy.
PICKER_HTML = (
    f"<span class='sort-picker'>"
    f"<span class='picker-category'>Sort</span>"
    f"<span class='sort-option active' data-sort='alphabetic'>Alphabetic</span>"
    f"<span class='sort-option' data-sort='zetabetique' style='display:none'>Zétabétique</span>"
    f"<span class='sort-option' data-sort='consensus'>Consensus</span>"
    f"<span class='picker-category'>Show</span>"
    f"<span class='sort-option' data-action='toggleOverall'>Overall</span>"
    f"<span class='sort-option' data-action='expandDeltas'>Deltas</span>"
    f"<span class='sort-option' data-action='toggleOutliers'>Outliers</span>"
    f"<span class='picker-category'>Stats</span>"
    f"<span class='sort-option' data-action='dotPlot'>Week</span>"
    f"<span class='sort-option' data-action='yearlyStats'>Records</span>"
    f"<span class='sort-option' data-action='results'>Results</span>"
    f"<span class='picker-category'>&bull;</span>"
    f"<span class='sort-option' data-action='settings'>Settings</span>"
    f"<span class='sort-option' data-action='credits'>Credits</span>"
    f"<span class='picker-category settings-only'>Settings</span>"
    f"<span class='sort-option settings-only' data-action='darkMode'>Dark Mode</span>"
    f"<span class='sort-option settings-only' data-action='weekArrows'>Nav Arrows ON</span>"
    f"<span class='picker-category settings-only'>Other</span>"
    f"<span class='sort-option settings-only' data-action='savePng'>Save as PNG</span>"
    f"<span class='sort-option settings-only' data-action='legend'>Keybinds</span>"
    f"<span class='sort-option settings-only' data-action='devPin'>Dev</span>"
    f"<span class='credits-only credits-text'>Site displays &amp; analyzes the results of ballot votes from <a href='https://www.cbbpoll.net' target='_blank' rel='noopener'>cbbpoll.net</a>. Thank you to the mods and voters of the r/CollegeBasketball Userpoll.</span>"
    f"</span>"
)

RANK_HEADERS = "".join(f"<th><span class='rank-header-num'>{i+1}</span></th>" for i in range(25))
THEAD_HTML = (
    f"<thead><tr>"
    f"<th><span class='voters-toggle'>Functions</span></th>"
    f"{RANK_HEADERS}</tr></thead>"
)

def build_table(tbody_html):
    return f"<table>\n{THEAD_HTML}\n<tbody>{tbody_html}</tbody>\n</table>"

def build_table_html(voters_with_ballots):
    return build_table(build_table_rows(voters_with_ballots))

def _week_block_html(week_id, official_table, provisional_table, aggregate_table, attrs=""):
    """Wrap the three ballot-section tables in a uniquely-id'd week-block div."""
    return f"""
<div id="{week_id}" class="week-block"{attrs} style="display:none;">
  <div id="{week_id}-official" class="ballot-section">
    <div class="table-scroll"><div class="table-container">{official_table}</div></div>
  </div>
  <div id="{week_id}-provisional" class="ballot-section" style="display:none;">
    <div class="table-scroll"><div class="table-container">{provisional_table}</div></div>
  </div>
  <div id="{week_id}-aggregate" class="ballot-section" style="display:none;">
    <div class="table-scroll"><div class="table-container">{aggregate_table}</div></div>
  </div>
</div><!-- /week-block:{week_id} -->"""

def build_week_block(week, year, official, provisional):
    """Build the full HTML block for one userpoll week."""
    return _week_block_html(
        f"week-{year}-{week}",
        build_table_html(official),
        build_table_html(provisional),
        build_table(build_overall_row(official, "Official Overall")),
    )

def get_official_voters_from_html(year, weeks, html_path):
    """Return a set of official voter usernames from already-saved week blocks.

    Reads the official ballot section (first .ballot-section div) of each
    requested week and extracts voter names from <span class="voter-name">.
    """
    _, data_html, _ = load_existing_weeks(html_path)
    official_panel = set()
    for week in weeks:
        week_id = f"week-{year}-{week}"
        # Find the week block
        block_match = re.search(
            rf'<div id="{re.escape(week_id)}".*?</div><!-- /week-block:{re.escape(week_id)} -->',
            data_html, re.DOTALL
        )
        if not block_match:
            continue
        block = block_match.group(0)
        # Extract everything between the official and provisional section divs
        official_match = re.search(
            rf'<div id="{re.escape(week_id)}-official"(.*?)<div id="{re.escape(week_id)}-provisional"',
            block, re.DOTALL
        )
        if not official_match:
            continue
        official_html = official_match.group(1)
        for name in re.findall(r'<span class="voter-name"[^>]*>([^<]+)</span>', official_html):
            if name != "Official Overall":
                official_panel.add(name)
    return official_panel

# ── HTML File Management ─────────────────────────────────────────────────────

def load_css():
    with open(CSS_PATH, "r", encoding="utf-8") as f:
        return f.read()

def load_js():
    with open(JS_PATH, "r", encoding="utf-8") as f:
        return minify_js(f.read())

# ── JS minifier (stdlib only) ────────────────────────────────────────────────
# Conservative: drops comments and indentation/blank lines and removes spaces
# next to punctuation. It never renames identifiers or joins lines (so automatic
# semicolon insertion behaves exactly as in the source). Strings, template
# literals (incl. nested ${...}) and regex literals are copied verbatim.
# minify_js() re-tokenizes its output and falls back to the source if the token
# stream changed.

_JS_PUNCT_NO_SPACE = set("{}()[];,:=<>?!&|*%^~.")
# After these tokens a "/" starts a regex literal rather than a division.
_JS_REGEX_PREV_WORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete",
                        "void", "throw", "case", "do", "else", "yield", "await"}

def _js_tokens(src):
    """Yield (kind, text) with kind in ws, nl, comment, str, regex, word, punct."""
    i, n = 0, len(src)
    prev = None          # last significant token, for regex-vs-division
    brace_stack = []     # for template literals: "tpl" marks a ${ opened inside one

    def read_template(i):
        # src[i] is "`" or the "}" closing a ${...}; return index just past the
        # closing "`" or past the next "${" (pushing a marker).
        j = i + 1
        while j < n:
            c = src[j]
            if c == "\\":
                j += 2
                continue
            if c == "`":
                return j + 1, False
            if c == "$" and j + 1 < n and src[j + 1] == "{":
                return j + 2, True
            j += 1
        raise ValueError("unterminated template literal")

    while i < n:
        c = src[i]
        if c == "\n":
            j = i
            while j < n and src[j] in " \t\r\n":
                j += 1
            yield ("nl", src[i:j]); i = j; continue
        if c in " \t\r":
            j = i
            while j < n and src[j] in " \t\r":
                j += 1
            yield ("ws", src[i:j]); i = j; continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            yield ("comment", src[i:j]); i = j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j == -1:
                raise ValueError("unterminated block comment")
            yield ("comment", src[i:j + 2]); i = j + 2; continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n":
                    raise ValueError("newline in string literal")
                j += 1
            tok = ("str", src[i:j + 1]); i = j + 1
            yield tok; prev = tok; continue
        if c == "`" or (c == "}" and brace_stack and brace_stack[-1] == "tpl"):
            if c == "}":
                brace_stack.pop()
            j, opened = read_template(i)
            if opened:
                brace_stack.append("tpl")
            tok = ("str", src[i:j]); i = j
            yield tok; prev = tok; continue
        if c == "/":
            regex_ok = (prev is None or (prev[0] == "punct" and prev[1] not in (")", "]", "}"))
                        or (prev[0] == "word" and prev[1] in _JS_REGEX_PREV_WORDS))
            if regex_ok:
                j, in_class = i + 1, False
                while j < n:
                    ch = src[j]
                    if ch == "\\":
                        j += 2; continue
                    if ch == "\n":
                        raise ValueError("newline in regex literal")
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        break
                    j += 1
                j += 1
                while j < n and (src[j].isalnum() or src[j] == "_"):
                    j += 1   # flags
                tok = ("regex", src[i:j]); i = j
                yield tok; prev = tok; continue
        if c.isalnum() or c in "_$" or ord(c) > 127:
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$." and (src[j] != "." or src[i].isdigit())
                             or ord(src[j]) > 127):
                j += 1
            tok = ("word", src[i:j]); i = j
            yield tok; prev = tok; continue
        if c == "{":
            brace_stack.append("{")
        elif c == "}" and brace_stack:
            brace_stack.pop()
        tok = ("punct", c); i += 1
        yield tok; prev = tok

def _js_significant(src):
    return [t for t in _js_tokens(src) if t[0] not in ("ws", "nl", "comment")]

def minify_js(src):
    try:
        toks = list(_js_tokens(src))
        out, pending = [], None   # pending: "ws" or "nl" separator before the next token
        last = None
        for kind, text in toks:
            if kind == "comment":
                if text.startswith("/*") and "\n" in text and pending != "nl":
                    pending = "nl"   # a multi-line block comment counts as a line break for ASI
                elif pending is None:
                    pending = "ws"
                continue
            if kind in ("ws", "nl"):
                if kind == "nl" or pending != "nl":
                    pending = kind
                continue
            if last is not None and pending:
                if pending == "nl":
                    out.append("\n")
                else:
                    a, b = last[-1], text[0]
                    if not (a in _JS_PUNCT_NO_SPACE or b in _JS_PUNCT_NO_SPACE):
                        out.append(" ")
            out.append(text)
            last, pending = text, None
        result = "".join(out) + "\n"
        if _js_significant(result) != _js_significant(src):
            raise ValueError("token stream changed")
        return result
    except ValueError as e:
        print(f"⚠ JS minify skipped ({e}); inlining script.js unminified")
        return src

WEEK_TABS_MARKER = "<!-- WEEK-TABS -->"
WEEK_DATA_MARKER = "<!-- WEEK-DATA -->"

def list_fragment_years(prefix, base_dir=BASE_HTML_DIR):
    """Sorted year strings for fragment files named PREFIX<year>.html (e.g. 'data-ap-')."""
    pat = re.compile(rf'{re.escape(prefix)}(\d+)\.html$')
    return sorted(m.group(1) for m in map(pat.match, os.listdir(base_dir)) if m)

def patch_fragment_theads(prefix, skip_year=None):
    """Rewrite every <thead> in PREFIX<year>.html fragment files to the current THEAD_HTML."""
    for year in list_fragment_years(prefix):
        if year == skip_year:
            continue
        frag_path = os.path.join(BASE_HTML_DIR, f"{prefix}{year}.html")
        with open(frag_path, "r", encoding="utf-8") as f:
            frag_content = f.read()
        patched = re.sub(r'<thead>.*?</thead>', THEAD_HTML, frag_content, flags=re.DOTALL)
        if patched != frag_content:
            with open(frag_path, "w", encoding="utf-8") as f:
                f.write(patched)
            print(f"  ✓ Patched thead in {prefix}{year}.html")

def make_tab(year, week, label=None, poll=None):
    """Week tab button. poll="ap" gives an index.html AP tab (week-ap-YEAR-N, data-poll="ap")."""
    week_id = f"week-ap-{year}-{week}" if poll == "ap" else f"week-{year}-{week}"
    poll_attr = f' data-poll="{poll}"' if poll else ""
    label_attr = f' data-weeklabel="{label}"' if label else ""
    tab_text = f"{year} {label}" if label else f"{year} #{week}"
    return (f'<button class="week-tab" data-week="{week_id}" data-weeknum="{week}"'
            f' data-year="{year}"{poll_attr}{label_attr}>{tab_text}</button>')

def get_ap_info(html_path):
    """Return (ap_tabs_html, ap_fragment_years) from existing index.html + fragment files."""
    ap_tabs_html = ""
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        tabs_match = re.search(r'<!-- AP-TABS -->\n(.*?)(?=\n<!-- /AP-TABS -->)', content, re.DOTALL)
        ap_tabs_html = tabs_match.group(1).strip() if tabs_match else ""
    return ap_tabs_html, list_fragment_years("data-ap-", os.path.dirname(html_path) or ".")

def split_data_by_year(data_html):
    """Split data_html into a dict of { year_str: year_data_html }."""
    parts = re.split(r'(?=<div [^>]*id="week-\d+-\d+")', data_html)
    by_year = {}
    for part in parts:
        m = re.match(r'<div [^>]*id="week-(\d+)-\d+"', part)
        if m:
            year = m.group(1)
            by_year.setdefault(year, []).append(part)
    return {y: "".join(blocks).strip() for y, blocks in by_year.items()}

def get_current_year(tabs_html):
    """Extract the most recent year from tab buttons."""
    years = re.findall(r'data-year="(\d+)"', tabs_html)
    return max(years) if years else None

def write_year_fragments(data_by_year, current_year, base_dir):
    """Write data-YEAR.html fragment files for all years except the current year."""
    for year, year_html in data_by_year.items():
        if year == current_year:
            continue
        frag_path = os.path.join(base_dir, f"data-{year}.html")
        with open(frag_path, "w", encoding="utf-8") as f:
            f.write(year_html)

# Userpoll seasons kept in the data but left out of all analysis (2024 is an incomplete Wayback recovery).
# Keep in sync with HIDDEN_YEARS in script.js.
EXCLUDED_YEARS = {"2023", "2024"}

def compute_tenure_counts(data_html):
    """Count total ballots per voter across all week/year data (all loaded HTML).
    Adds 36 to voters present in both 2022 and 2025 to account for missing 2023/2024 seasons."""
    SKIP_NAMES = {"Official Overall", "Recency"}
    name_re = re.compile(r'<span class="voter-name"[^>]*>([^<]+)<')
    counts = {}
    by_year = split_data_by_year(data_html)
    for year_str, year_html in by_year.items():
        # Incomplete seasons are kept on disk but never counted; the +36 bonus below covers them
        if year_str in EXCLUDED_YEARS:
            continue
        for m in name_re.finditer(year_html):
            username = m.group(1).strip()
            if username in SKIP_NAMES:
                continue
            counts[username] = counts.get(username, 0) + 1

    # Voters active in both 2022 and 2025 likely also voted in missing 2023/2024 seasons
    def voters_in_year(year_str):
        html = by_year.get(year_str, "")
        return {m.group(1).strip() for m in name_re.finditer(html) if m.group(1).strip() not in SKIP_NAMES}

    # Additional voters confirmed to have voted in 2023/2024 but not present in legacy 2022 data
    EXTRA_BONUS = {"DCProf", "Nacos2001", "Travbowman", "bbbredy", "corndogshuffle",
                   "danielshap2", "maddydotcom", "oddcharisma"}

    bonus_voters = (voters_in_year("2022") & voters_in_year("2025")) | EXTRA_BONUS
    for voter in bonus_voters:
        if voter in counts:
            counts[voter] += 36
    return counts

def compute_ap_tenure_counts():
    """Count total AP ballots per voter across all ap25-YEAR.json files."""
    counts = {}
    base_dir = BASE_HTML_DIR
    for fname in os.listdir(base_dir):
        m = re.match(r'ap25-(\d+)\.json$', fname)
        if not m:
            continue
        json_path = os.path.join(base_dir, fname)
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
        except Exception:
            continue
        for week_data in data.get('weeks', {}).values():
            for v in week_data.get('voters', []):
                username = v.get('username', '')
                if username and v.get('teams'):
                    counts[username] = counts.get(username, 0) + 1
    return counts

def get_quad_files():
    """{season: {"net": bool, "quads": bool}} for the net-YEAR.json / quads-YEAR.json files on disk.

    The Records tab fetches them at view time (net_rankings.py = official NCAA quads,
    quads.py = computed per-game quads); pages.yml deploys them."""
    found = {}
    for name in os.listdir(BASE_HTML_DIR):
        m = re.fullmatch(r"(net|quads)-(\d{4})\.json", name)
        if m and m.group(2) not in EXCLUDED_YEARS:
            found.setdefault(m.group(2), {"net": False, "quads": False})[m.group(1)] = True
    return dict(sorted(found.items()))


def build_full_html(week_tabs_html, week_data_html, fragment_years=None, tenure_counts=None, ap_tabs_html="", ap_fragment_years=None, ap_tenure_counts=None):
    CSS = load_css()
    JS = load_js()
    fragment_years_js = json.dumps(fragment_years or [])
    tenure_counts_js = json.dumps(tenure_counts or {})
    ap_tenure_counts_js = json.dumps(ap_tenure_counts or {})
    ap_fragment_years_js = json.dumps(ap_fragment_years or [])
    dark_logo_teams_js = "new Set(" + json.dumps(get_dark_logo_teams()) + ")"
    ncaa_light, ncaa_dark = nond1_logos.logo_ids(OUTPUT_DIR)
    ncaa_logo_ids_js = "new Set(" + json.dumps(ncaa_light) + ")"
    ncaa_dark_logo_ids_js = "new Set(" + json.dumps(ncaa_dark) + ")"
    conference_data_js = conferences.js_payload()
    quad_files_js = json.dumps(get_quad_files())
    return f"""<!DOCTYPE html>
<html>
<head>
<title>Userpoll Landscape</title>
<meta charset="UTF-8">
<meta name="viewport" content="width=1200, user-scalable=yes">
<link id="favicon" rel="icon" type="image/png" href="data:,">
<!-- Open Graph / link preview -->
<meta property="og:type" content="website">
<meta property="og:title" content="Userpoll Landscape">
<meta property="og:description" content="Landscape view of r/collegebasketball userpoll ballots.">
<meta property="og:image" content="https://les-champs.github.io/cbb-ballots/thumbnail.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<!-- Twitter/X card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Userpoll Landscape">
<meta name="twitter:description" content="Landscape view of r/collegebasketball userpoll ballots.">
<meta name="twitter:image" content="https://les-champs.github.io/cbb-ballots/thumbnail.png">
<style>
{CSS}
</style>
</head>
<body>

<div class="header">
  <h1>
    <span id="toggle-text">Official Ballots</span>
    <span id="year-picker"></span><span id="year-text"></span>
    <span id="week-text"></span><span id="week-picker"></span>
  </h1>
  <div id="week-arrows">
    <button type="button" id="week-arrow-prev" class="week-arrow" aria-label="Previous week" title="Previous week"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg></button>
    <button type="button" id="week-arrow-next" class="week-arrow" aria-label="Next week" title="Next week"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7"/></svg></button>
  </div>
</div>

<div class="week-tabs" style="display:none;">
{WEEK_TABS_MARKER}
{week_tabs_html}
<!-- AP-TABS -->
{ap_tabs_html}
<!-- /AP-TABS -->
</div>

<div id="voter-history-modal">
  <div id="voter-history-box">
    <h2 id="voter-history-title"></h2>
    <table id="voter-history-table"></table>
  </div>
</div>

<div id="keybind-legend-modal">
  <div id="keybind-legend-box">
    <h2>Keybinds</h2>
    <div class="keybind-section">
      <div class="keybind-section-title">Navigation</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>→</kbd> / <kbd>←</kbd></span><span>Next / Previous Week</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>↑</kbd> / <kbd>↓</kbd></span><span>Next / Previous Year</span></div>
    </div>
    <div class="keybind-section">
      <div class="keybind-section-title">Views</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>O</kbd></span><span>Toggle Outlier Highlighting</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>L</kbd></span><span>Toggle Overall Row</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>E</kbd></span><span>Toggle Deltas</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>J</kbd></span><span>Toggle Delta Sub-label (Consensus Diff / Recency)</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>1</kbd> – <kbd>9</kbd></span><span>Adjust Delta Lookback Window</span></div>
    </div>
    <div class="keybind-section">
      <div class="keybind-section-title">Sorting</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>A</kbd></span><span>Sort Alphabetically</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>C</kbd></span><span>Sort by Consensus</span></div>
    </div>
    <div class="keybind-section">
      <div class="keybind-section-title">Locked</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>D</kbd></span><span>Jump to Data Ballots</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>X</kbd></span><span>Toggle AP Ballots</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>R</kbd></span><span>Précision leaderboard</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>T</kbd></span><span>Tenure leaderboard</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>Y</kbd></span><span>Week stats table</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>G</kbd></span><span>Week stats with chart</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>U</kbd></span><span>Season statistics</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>W</kbd></span><span>Season voters</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>H</kbd></span><span>Season rank heatmap</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>K</kbd></span><span>Conference table</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>P</kbd></span><span>Save as PNG</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>?</kbd></span><span>Show legend</span></div>
    </div>
  </div>
</div>

<template id="picker-template">{PICKER_HTML}</template>

<div id="pin-modal">
  <div id="pin-box">
    <h2>Enter PIN</h2>
    <input id="pin-input" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="9" autocomplete="off" aria-label="9-digit PIN">
  </div>
</div>

<div id="season-stats-modal">
  <div id="season-stats-box">
    <h2 id="season-stats-title"></h2>
    <table id="season-stats-table"></table>
  </div>
</div>

<div id="heatmap-modal">
  <div id="heatmap-box">
    <h2 id="heatmap-title"></h2>
    <div id="heatmap-container"></div>
  </div>
</div>

<div id="precision-modal">
  <div id="precision-box">
    <h2 id="precision-title"></h2>
    <table id="precision-table"></table>
  </div>
</div>

<div id="conference-modal">
  <div id="conference-box">
    <div id="conference-header">
      <h2 id="conference-title"></h2>
      <div id="conference-years"></div>
    </div>
    <div id="conference-body"></div>
  </div>
</div>

<div id="tenure-modal">
  <div id="tenure-box">
    <h2 id="tenure-title"></h2>
    <table id="tenure-table"></table>
  </div>
</div>


<div id="year-data-container">
{WEEK_DATA_MARKER}
{week_data_html}
</div>
<script>
const AP_FRAGMENT_YEARS = {ap_fragment_years_js};
const FRAGMENT_YEARS = {fragment_years_js};
const TENURE_COUNTS = {tenure_counts_js};
const AP_TENURE_COUNTS = {ap_tenure_counts_js};
const DARK_LOGO_TEAMS = {dark_logo_teams_js};
const NCAA_LOGO_IDS = {ncaa_logo_ids_js};
const NCAA_DARK_LOGO_IDS = {ncaa_dark_logo_ids_js};
const CONFERENCE_DATA = {conference_data_js};
const QUAD_FILES = {quad_files_js};
{JS}
</script>

</body>
</html>"""

def load_existing_weeks(html_path):
    """Parse existing HTML file and return (tabs_html, data_html, list of week_ids)."""
    if not os.path.exists(html_path):
        return "", "", []
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract existing tab entries
    tabs_match = re.search(
        r'<!-- WEEK-TABS -->\n(.*?)(?=\n</div>)',
        content, re.DOTALL
    )
    tabs_html = tabs_match.group(1).strip() if tabs_match else ""
    # Strip any AP-TABS block captured inside tabs_html — handled separately by get_ap_info
    tabs_html = re.sub(r'\n?<!-- AP-TABS -->.*?<!-- /AP-TABS -->', '', tabs_html, flags=re.DOTALL).strip()

    # Extract existing week data blocks (handle both old format and new year-data-container format)
    data_match = re.search(
        r'<!-- WEEK-DATA -->\n(.*?)(?=\n</div>\n<script>|\n\n?<script>)',
        content, re.DOTALL
    )
    data_html = data_match.group(1).strip() if data_match else ""

    # Also load any year fragment files to get the full dataset
    base_dir = os.path.dirname(html_path) or "."
    for frag_file in sorted(os.listdir(base_dir)):
        if re.match(r'data-\d+\.html$', frag_file):
            frag_path = os.path.join(base_dir, frag_file)
            with open(frag_path, "r", encoding="utf-8") as frag_f:
                frag_html = frag_f.read().strip()
            if frag_html:
                data_html = (data_html + "\n" + frag_html).strip()

    # Extract existing week IDs
    week_ids = re.findall(r'data-week="(week-\d+-\d+)"', tabs_html)

    return tabs_html, data_html, week_ids

def write_index(tabs_html, data_html, html_path):
    """Write index.html (current year inline) plus data-YEAR.html fragments for prior years.

    Returns (data_by_year, current_year, fragment_years).
    """
    current_year = get_current_year(tabs_html)
    data_by_year = split_data_by_year(data_html)
    inline_data = data_by_year.get(current_year, "")
    fragment_years = sorted([y for y in data_by_year if y != current_year])
    write_year_fragments(data_by_year, current_year, os.path.dirname(html_path) or ".")
    tenure_counts = compute_tenure_counts(data_html)
    ap_tabs_html, ap_fragment_years = get_ap_info(html_path)
    full_html = build_full_html(tabs_html, inline_data, fragment_years, tenure_counts,
                                ap_tabs_html, ap_fragment_years, compute_ap_tenure_counts())
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(full_html)
    return data_by_year, current_year, fragment_years

def save_html(week, year, new_week_block, html_path, week_label=None):
    """Load existing HTML, append the new week, and save."""
    week_id = f"week-{year}-{week}"
    tabs_html, data_html, existing_ids = load_existing_weeks(html_path)

    if week_id in existing_ids:
        print(f"⚠️  Week {week} {year} already exists in HTML. Overwriting its block.")
        tabs_html = remove_week_tab(tabs_html, week_id)
        data_html = remove_week_block(data_html, week_id)

    # Add new tab
    tabs_html = (tabs_html + "\n" + make_tab(year, week, week_label)).strip()

    # Append new week block
    data_html = (data_html + "\n" + new_week_block).strip()

    write_index(tabs_html, data_html, html_path)
    print(f"✓ Saved to: {html_path}")

# ── Main ─────────────────────────────────────────────────────────────────────

def remove_week_block(data_html, week_id):
    """Remove a week's data block from data_html by walking div depth."""
    start_tag = f'<div id="{week_id}"'
    start_idx = data_html.find(start_tag)
    if start_idx == -1:
        return data_html
    depth, i = 0, start_idx
    while i < len(data_html):
        if data_html[i:i+4] == '<div':
            depth += 1; i += 4
        elif data_html[i:i+6] == '</div>':
            depth -= 1
            if depth == 0:
                return data_html[:start_idx] + data_html[i+6:]
            i += 6
        else:
            i += 1
    return data_html

def remove_week_tab(tabs_html, week_id):
    """Remove a week's tab button from tabs_html."""
    tabs_html = re.sub(rf'<button[^>]+data-week="{week_id}"[^>]*/>\s*', '', tabs_html)
    tabs_html = re.sub(rf'<button[^>]+data-week="{week_id}"[^>]*>[^<]*</button>\s*', '', tabs_html)
    return tabs_html

def delete_week(week, year):
    """Remove a specific week's tab and data block from index.html."""
    week_id = f"week-{year}-{week}"
    tabs_html, data_html, existing_ids = load_existing_weeks(HTML_PATH)
    if week_id not in existing_ids:
        print(f"✗ Week {week} {year} not found in HTML.")
        return
    tabs_html = remove_week_tab(tabs_html, week_id).strip()
    data_html = remove_week_block(data_html, week_id).strip()

    data_by_year, _, _ = write_index(tabs_html, data_html, HTML_PATH)
    # Remove fragment file for year if it has no more data
    if not data_by_year.get(str(year), "").strip():
        frag_path = os.path.join(BASE_HTML_DIR, f"data-{year}.html")
        if os.path.exists(frag_path):
            os.remove(frag_path)
    print(f"✓ Deleted week {week} {year} from HTML.")

def build_ap_html(week_tabs_html, week_data_html, fragment_years=None, ap_tenure_counts=None):
    """Build the full ap-ballots.html from the template, with AP weeks as primary content."""
    full_html = build_full_html(
        week_tabs_html=week_tabs_html,
        week_data_html=week_data_html,
        fragment_years=fragment_years or [],
        tenure_counts={},
        ap_tabs_html="",
        ap_fragment_years=[],
        ap_tenure_counts=ap_tenure_counts or {},
    )
    # Update title and meta
    full_html = full_html.replace("<title>Userpoll Landscape</title>", "<title>Associated Press Landscape</title>")
    full_html = full_html.replace('content="Userpoll Landscape"', 'content="Associated Press Landscape"')
    full_html = full_html.replace(
        'content="Landscape view of r/collegebasketball userpoll ballots."',
        'content="Landscape view of AP Top 25 individual voter ballots."'
    )
    # Set toggle-text to "Associated Press" (clicking cycles Associated Press ↔ Data Ballots)
    full_html = full_html.replace(
        '<span id="toggle-text">Official Ballots</span>',
        '<span id="toggle-text">Associated Press</span>'
    )
    # Replace the userpoll forward link with a back link to index.html
    full_html = full_html.replace(
        '<a href="ap-ballots.html" class="ap-forward-link">Associated Press →</a>',
        '<a href="index.html" class="ap-back-link">← Userpoll</a>'
    )
    # Inject IS_AP_PAGE and FRAG_PATH_PREFIX constants before the inlined JS
    fragment_years_js = json.dumps(fragment_years or [])
    full_html = full_html.replace(
        f"const FRAGMENT_YEARS = {fragment_years_js};",
        f"const IS_AP_PAGE = true;\nconst FRAG_PATH_PREFIX = 'data-appage-';\nconst FRAGMENT_YEARS = {fragment_years_js};"
    )
    return full_html


def rebuild_ap_html():
    """Rebuild ap-ballots.html from cached ap25-YEAR.json and data-appage-YEAR.html fragment files."""
    base_dir = BASE_HTML_DIR

    appage_years = list_fragment_years("data-appage-", base_dir)
    if not appage_years:
        print("No data-appage-YEAR.html files found; skipping ap-ballots.html rebuild.")
        return

    current_year = max(appage_years)
    prior_years = [y for y in appage_years if y != current_year]

    # Build inline data and tabs for the current year from ap25-YEAR.json
    json_path = os.path.join(base_dir, f"ap25-{current_year}.json")
    inline_data = ""
    tabs_html_lines = []

    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            data = json.load(f)
        for week_key in sorted(data["weeks"].keys(), key=lambda w: int(w)):
            week = int(week_key)
            week_data = data["weeks"][week_key]
            if not week_data.get("voters"):
                continue
            block = build_ap_week_block(week, current_year, _ap_voter_tuples(week_data), for_ap_page=True)
            inline_data = (inline_data + "\n" + block).strip()
            tabs_html_lines.append(make_tab(current_year, week, ap_week_label(week)))

    patch_fragment_theads("data-appage-", skip_year=current_year)

    # Build tabs for prior fragment years by reading their week IDs from the fragment files
    for year in prior_years:
        with open(os.path.join(base_dir, f"data-appage-{year}.html"), "r", encoding="utf-8") as f:
            frag = f.read()
        for wid_match in re.finditer(r'<div id="week-(\d+)-(\d+)"', frag):
            wn = int(wid_match.group(2))
            tabs_html_lines.append(make_tab(wid_match.group(1), wn, ap_week_label(wn)))

    tabs_html = "\n".join(tabs_html_lines)
    ap_tenure_counts = compute_ap_tenure_counts()
    full_html = build_ap_html(tabs_html, inline_data, prior_years, ap_tenure_counts)
    with open(AP_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"✓ Rebuilt ap-ballots.html ({current_year} inline, {len(prior_years)} year fragments).")


def rebuild_html():
    """Rewrite index.html using existing tab/data content but updated CSS/JS/structure."""
    if not os.path.exists(HTML_PATH):
        print("No existing HTML found.")
        return

    tabs_html, data_html, week_ids = load_existing_weeks(HTML_PATH)
    if not week_ids:
        print("No existing weeks found in HTML. Nothing to rebuild.")
        return

    # Patch all old thead variants to current format
    data_html = re.sub(r'<thead>.*?</thead>', THEAD_HTML, data_html, flags=re.DOTALL)

    # Regenerate aggregate sections
    def rebuild_aggregate(week_id, block_html):
        end_marker = f'</div><!-- /week-block:{week_id} -->'

        # Remove any existing aggregate section
        agg_marker = f'id="{week_id}-aggregate"'
        if agg_marker in block_html:
            agg_pos = block_html.index(agg_marker)
            div_start = block_html.rindex('<div', 0, agg_pos)
            block_html = block_html[:div_start].rstrip() + '\n'
            # Restore end marker if missing
            if end_marker not in block_html:
                block_html = block_html.rstrip() + f'\n{end_marker}'

        # Slice out only the official section
        official_marker = f'id="{week_id}-official"'
        provisional_marker = f'id="{week_id}-provisional"'
        if official_marker not in block_html:
            return block_html
        start = block_html.index(official_marker)
        end = block_html.index(provisional_marker) if provisional_marker in block_html else len(block_html)
        official_html = block_html[start:end]
        rows = re.findall(r'<tr class="voter-row">.*?</tr>', official_html, re.DOTALL)
        official = []
        for row in rows:
            teams = re.findall(r'<td class="logo-cell">.*?data-team="([^"]+)"', row)
            if teams:
                official.append(("", "", None, [t + ".png" for t in teams]))
        if not official:
            return block_html

        agg_table = build_table(build_overall_row(official, "Official Overall"))
        agg_section = (
            f'  <div id="{week_id}-aggregate" class="ballot-section" style="display:none;">\n'
            f'    <div class="table-scroll"><div class="table-container">{agg_table}</div></div>\n'
            f'  </div>\n'
        )

        # Insert before end marker
        if end_marker in block_html:
            block_html = block_html.replace(end_marker, agg_section + end_marker)
        else:
            # Fallback: append before final \n</div>
            block_html = block_html.rstrip()
            block_html = block_html[:-6].rstrip() + '\n' + agg_section + '</div>'
        return block_html

    parts = re.split(r'(?=<div [^>]*id="week-\d+-\d+")', data_html)
    new_parts = []
    for part in parts:
        wid_match = re.match(r'<div [^>]*id="(week-\d+-\d+)"', part)
        if wid_match:
            part = rebuild_aggregate(wid_match.group(1), part)
        new_parts.append(part)
    data_html = "".join(new_parts)

    patch_fragment_theads("data-ap-")
    _, current_year, fragment_years = write_index(tabs_html, data_html, HTML_PATH)
    print(f"✓ Rebuilt HTML with {len(week_ids)} weeks ({current_year} inline, {len(fragment_years)} year fragments).")
    rebuild_ap_html()

def main():
    parser = argparse.ArgumentParser(description="Scrape CBB Poll ballots and generate HTML.")
    parser.add_argument("--week", type=str, help="Poll week slug to fetch from cbbpoll.net (e.g. 18 or Pre-Season)")
    parser.add_argument("--store-week", type=int, dest="store_week",
                        help="Override the week number used for HTML storage/label (e.g. 0 for pre-season)")
    parser.add_argument("--label", type=str, help="Custom display label for the week tab (e.g. 'Pre-Season')")
    parser.add_argument("--year", type=int, help="Poll year (e.g. 2026)")
    parser.add_argument("--official-only", action="store_true", dest="official_only",
                        help="Scrape only the Official section; store no provisional ballots for this week")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild HTML from existing data without scraping")
    parser.add_argument("--missing-logos", action="store_true", help="Download ESPN logos for conferences.py schools with no logo file and exit")
    parser.add_argument("--ncaa-logos", action="store_true", help="Download NCAA.com logos for non-D1 opponents ESPN has none for (nond1_logos.NCAA_SLUGS), list unmapped ones, and exit. --year 0 = every shown season (default: current)")
    parser.add_argument("--net", action="store_true", help="Fetch NCAA NET rankings + quadrant records from NCAA.com into net-YEAR.json and exit")
    parser.add_argument("--quads", action="store_true", help="Compute Q1–Q4 records from ESPN schedules + BPI (or NET) ranks into quads-YEAR.json and exit (--year, default current)")
    parser.add_argument("--rank-source", choices=["auto", "bpi", "net"], default="auto", dest="rank_source", help="With --quads: opponent ranking (auto = NET if net-YEAR.json exists, else BPI)")
    parser.add_argument("--check", action="store_true", help="With --quads: compare computed quads with official ones in net-YEAR.json")
    parser.add_argument("--force", action="store_true", help="With --ncaa-logos: re-download files that already exist")
    parser.add_argument("--to-webp", action="store_true", help="Convert all existing PNG logos to WebP and exit")
    parser.add_argument("--dark-logos", action="store_true", help="Download ESPN dark-mode logos for all teams")
    parser.add_argument("--delete", action="store_true", help="Delete a specific week from the HTML")
    parser.add_argument("--cbbpoll", action="store_true", help="Scrape from cbbpoll.com (legacy site)")
    parser.add_argument("--cbbpoll-build", action="store_true", help="Build HTML from cached cbbpoll.com data")
    parser.add_argument("--ap25", action="store_true", help="Scrape AP 25 data from collegepolltracker.com")
    parser.add_argument("--ap25-build", action="store_true", help="Build HTML from cached AP 25 data")
    args = parser.parse_args()

    if args.to_webp:
        convert_all_to_webp()
        return

    if args.missing_logos:
        download_missing_logos()
        return
    if args.net:
        if not net_rankings.run(BASE_HTML_DIR):
            sys.exit(1)
        return
    if args.quads:
        today = datetime.date.today()
        season = args.year or today.year + (1 if today.month >= 7 else 0)
        if not quads.run(BASE_HTML_DIR, season, args.rank_source, args.check):
            sys.exit(1)
        return
    if args.ncaa_logos:
        today = datetime.date.today()
        current = today.year + (1 if today.month >= 7 else 0)
        if args.year == 0:
            seasons = [y for y in range(2016, current + 1) if str(y) not in EXCLUDED_YEARS]
        else:
            seasons = [args.year or current]
        nond1_logos.run(OUTPUT_DIR, seasons, force=args.force)
        return
    if args.dark_logos:
        download_dark_logos()
        return

    if args.delete:
        if not args.week or not args.year:
            parser.error("--week and --year are required with --delete")
        delete_week(args.week, args.year)
        return

    if args.rebuild:
        rebuild_html()
        return

    if args.cbbpoll:
        if not args.year:
            parser.error("--year is required with --cbbpoll (e.g. --year 2022 or --year 0 for all)")
        if args.year == 0:
            for y in sorted(CBBPOLL_SEASONS.keys()):
                cbbpoll_scrape_season(y)
        else:
            cbbpoll_scrape_season(args.year)
        return

    if args.cbbpoll_build:
        if not args.year:
            parser.error("--year is required with --cbbpoll-build")
        if args.year == 0:
            for y in sorted(CBBPOLL_SEASONS.keys()):
                cbbpoll_build_season(y)
        else:
            cbbpoll_build_season(args.year)
        return

    if args.ap25:
        if args.year is None:
            parser.error("--year is required with --ap25 (our year, e.g. 2026, or 0 for all)")
        if args.year == 0:
            for our_y in sorted(AP25_SITE_YEARS.values()):
                ap25_scrape_season(our_y)
        else:
            ap25_scrape_season(args.year)
        return

    if args.ap25_build:
        if args.year is None:
            parser.error("--year is required with --ap25-build (our year, e.g. 2026, or 0 for all)")
        if args.year == 0:
            for our_y in sorted(AP25_SITE_YEARS.values()):
                ap25_build_season(our_y)
        else:
            ap25_build_season(args.year)
        return

    if not args.week or not args.year:
        parser.error("--week and --year are required unless using --rebuild")

    week, year = args.week, args.year
    if args.store_week is not None:
        store_week = args.store_week
    elif week.lstrip("-").isdigit():
        store_week = int(week)
    else:
        parser.error(f"--store-week is required when --week is a non-numeric slug like '{week}'")

    # Seasons page first: it is year-scoped. The homepage links each voter's ballot for this week
    # *number* from any season (2027 Week 2 listed 90 of 129 ballots from prior seasons), so it is
    # only a fallback for when the seasons page has no voters yet.
    candidate_urls = [
        f"{BASE_URL}/seasons/{year}/{week}",
        f"{BASE_URL}/",
    ]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html = None
    for poll_url in candidate_urls:
        try:
            print(f"Trying {poll_url}...")
            html = fetch_page_html(poll_url)
            # Verify the page contains voter data for this week
            # Seasons page: ballot IDs in __NEXT_DATA__; homepage: direct ballot links
            nd = extract_next_data(html) if "Poll Voters" in html else None
            if (nd and extract_ballot_urls_from_next_data(nd, week)) or f"/ballots/{week}/" in html:
                print(f"✓ Found Week {week} data at {poll_url}\n")
                break
            else:
                print(f"  (no Week {week} ballots found here, trying next...)")
                html = None
        except Exception as e:
            print(f"  ({poll_url} failed: {e})")
            html = None

    if html is None:
        print(f"\n✗ Could not find Week {week} data at any URL. Exiting.")
        return

    logos = fetch_unique_logos(html)
    print(f"Found {len(logos)} unique logos. Downloading...\n")
    download_logos(logos)

    # Try to extract ballot URLs from embedded JSON (year-scoped, avoids cross-year contamination)
    next_data = extract_next_data(html)
    ballot_map = {}
    if next_data:
        ballot_map = extract_ballot_urls_from_next_data(next_data, week)
        if ballot_map:
            print(f"  ✓ Found {len(ballot_map)} ballot URLs from page JSON (year-scoped)\n")

    official_section, provisional_section = split_voter_sections(html)
    official_voters = extract_voters_from_section(official_section)
    provisional_voters = extract_voters_from_section(provisional_section)
    # cbbpoll.net sometimes lists a voter under both headings; the official listing wins.
    official_names = {v[1].lower() for v in official_voters}
    dupes = [v[1] for v in provisional_voters if v[1].lower() in official_names]
    if dupes:
        provisional_voters = [v for v in provisional_voters if v[1].lower() not in official_names]
        print(f"Dropped {len(dupes)} provisional duplicate(s) also listed as official: {', '.join(dupes)}")
    official_voters = drop_stale_ballots(official_voters, year, "official")
    provisional_voters = drop_stale_ballots(provisional_voters, year, "provisional")
    if args.official_only:
        print(f"--official-only: ignoring {len(provisional_voters)} provisional voter(s).")
        provisional_voters = []
    print(f"Found {len(official_voters)} official and {len(provisional_voters)} provisional voters.\n")

    print("Fetching official ballots...")
    official_with_ballots = process_voters(official_voters, "Official", week=week, year=year, ballot_map=ballot_map)

    print("\nFetching provisional ballots...")
    provisional_with_ballots = process_voters(provisional_voters, "Provisional", week=week, year=year, ballot_map=ballot_map)

    # For pre-season (week 0): reclassify voters based on their status in weeks 2/3
    if store_week == 0:
        official_panel = get_official_voters_from_html(year, [2, 3], HTML_PATH)
        if official_panel:
            all_voters = official_with_ballots + provisional_with_ballots
            official_with_ballots = [v for v in all_voters if v[1] in official_panel]
            provisional_with_ballots = [v for v in all_voters if v[1] not in official_panel]
            print(f"\nReclassified week 0 using weeks 2/3 panel: {len(official_with_ballots)} official + {len(provisional_with_ballots)} provisional")
        else:
            print("\nNo weeks 2/3 data found — keeping pre-season sections as scraped")

    week_block = build_week_block(store_week, year, official_with_ballots, provisional_with_ballots)
    save_html(store_week, year, week_block, HTML_PATH, week_label=args.label)
    week_display = args.label or f"Week {store_week}"
    print(f"\nDone! {week_display} {year}: {len(official_with_ballots)} official + {len(provisional_with_ballots)} provisional voters.")

if __name__ == "__main__":
    main()
