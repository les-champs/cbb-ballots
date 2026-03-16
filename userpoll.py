import os
import re
import json
import time
import html as html_mod
import argparse
import urllib.request
from io import BytesIO
from urllib.parse import unquote
from PIL import Image

# Output directory for logos
BASE_HTML_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_HTML_DIR, "cbb-logos")
HTML_PATH = os.path.join(BASE_HTML_DIR, "index.html")

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
    "Loyola-Chicago": "LoyolaChicago",
    "Loyola Chicago": "LoyolaChicago",
    "Miami (FL)": "MiamiFL",
    "Miami (OH)": "MiamiOH",
    "Chattanooga": "Chattanooga",
    "Texas A&M": "TexasAM",
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
    "William & Mary": "WilliamMary",
    "William and Mary": "WilliamMary",
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

    for week_key in weeks:
        week = int(week_key)
        week_data = data["weeks"][week_key]

        official = _cbbpoll_voters_to_tuples(week_data.get("official", []))
        provisional = _cbbpoll_voters_to_tuples(week_data.get("provisional", []))

        if not official and not provisional:
            print(f"  Week {week}: no voter data, skipping")
            continue

        week_block = build_week_block(week, year, official, provisional)
        save_html(week, year, week_block, HTML_PATH)
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

# ── HTML Building ────────────────────────────────────────────────────────────

def build_table_rows(voters_with_ballots):
    rows = ""
    for logo_filename, username, ballot_url, ballot_logos in voters_with_ballots:
        team_name = canonical_logo_name(logo_filename)
        ballot_attr = f' data-ballot-url="{ballot_url}"' if ballot_url else ''
        img_path = team_name
        inner = (
            f'<img class="logo" data-src="{img_path}" alt="{team_name}">'
            f'<span class="voter-name">{username}</span>'
        )
        voter_cell = f'<div class="voter-cell" {ballot_attr}>{inner}</div>'
        ballot_logo_cells = "".join(
            f'<td class="logo-cell"><img class="logo team-logo" data-team="{canonical_logo_name(bl)}" data-src="{canonical_logo_name(bl)}"></td>'
            for bl in ballot_logos
        )
        rows += f'<tr class="voter-row"><td>{voter_cell}</td>{ballot_logo_cells}</tr>\n'
    return rows

def build_aggregate_row(official):
    """Build a single aggregate row from official ballots using points system (rank 1=25pts ... rank 25=1pt)."""
    points = {}
    for _, _, _, ballot_logos in official:
        for i, logo in enumerate(ballot_logos[:25]):
            team = canonical_logo_name(logo)
            points[team] = points.get(team, 0) + (25 - i)
    ranked = sorted(points.items(), key=lambda x: -x[1])[:25]
    ballot_logo_cells = "".join(
        f'<td class="logo-cell"><img class="logo team-logo" data-team="{team}" data-src="{team}"></td>'
        for team, _ in ranked
    )
    voter_cell = (
        f'<div class="voter-cell" >'
        f'<span class="voter-name">Official Overall</span>'
        f'</div>'
    )
    return f'<tr class="voter-row"><td>{voter_cell}</td>{ballot_logo_cells}</tr>\n'

RANK_HEADERS = "".join(f"<th><span class='rank-header-num'>{i+1}</span></th>" for i in range(25))
THEAD_HTML = (
    f"<thead><tr>"
    f"<th><span class='voters-toggle' style='cursor:pointer; display:inline-block; transition:transform 0.1s ease;'>Alphabetic</span>"
    f"<span class='sort-picker'>"
    f"<span class='sort-option active' data-sort='alphabetic'>Alphabetic</span>"
    f"<span class='sort-option' data-sort='consensus'>Consensus</span>"
    f"<span class='sort-option' data-sort='ranking'>Précision <span class='sort-lock'>🔒</span></span>"
    f"<span class='sort-option' data-sort='tenure'>Tenure <span class='sort-lock'>🔒</span></span>"
    f"</span></th>"
    f"{RANK_HEADERS}</tr></thead>"
)

def build_table(tbody_html):
    return f"<table>\n{THEAD_HTML}\n<tbody>{tbody_html}</tbody>\n</table>"

def build_aggregate_table(official):
    row_overall = build_aggregate_row(official)
    return build_table(row_overall)

def build_table_html(voters_with_ballots):
    rows = build_table_rows(voters_with_ballots)
    return build_table(rows)

def build_week_block(week, year, official, provisional):
    """Build the full HTML block for one week, wrapped in a uniquely-id'd div."""
    week_id = f"week-{year}-{week}"
    official_table = build_table_html(official)
    provisional_table = build_table_html(provisional)
    aggregate_table = build_aggregate_table(official)
    return f"""
<div id="{week_id}" class="week-block" style="display:none;">
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

# ── HTML File Management ─────────────────────────────────────────────────────

CSS = """
body {
    font-family: sans-serif;
    margin: 20px;
    background-color: #f8f8f8;
    overflow-x: auto;
}

.header {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 8px;
    position: relative;
}

h1 {
    margin: 0;
    white-space: nowrap;
    line-height: 1.4em;
    overflow: visible;
}

h1 span {
    cursor: pointer;
    color: #333;
    display: inline-block;
    transition: transform 0.1s ease;
}


h1 span:hover {
    transform: scale(1.02);
}

.dropdown-wrapper {
    position: relative;
    display: inline-block;
}

#year-picker {
    display: none;
}

#year-picker.open {
    display: inline;
}


#week-picker {
    display: none;
    gap: 8px;
}

#week-picker.open {
    display: inline;
}

.picker-btn {
    cursor: pointer;
    color: #333;
    font-size: 1.5rem;
    font-weight: bold;
    background: none;
    border: none;
    padding: 0;
    margin-right: 0.4em;
    font-family: inherit;
    transition: transform 0.1s ease;
}

.picker-btn:hover {
    transform: scale(1.05);
}

.week-tabs {
    display: none;
}

.week-tab {
    padding: 4px 10px;
    border: 1px solid #aaa;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
    background: #fff;
    transition: background 0.15s;
}

.week-tab:hover {
    background: #e0e0e0;
}

.week-tab.active {
    background: #333;
    color: #fff;
    border-color: #333;
}

.table-scroll {
    width: 100%;
}

.table-container {
    width: 100%;
    position: relative;
}

.avg-rank-line {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    pointer-events: none;
    opacity: 0.45;
    transform: translateX(-50%);
    z-index: 1;
}

table {
    border-collapse: collapse;
    table-layout: fixed;
    min-width: 100%;
    width: max-content;
}

th, td {
    padding: 4px 5px;
    text-align: center;
    border: none;
    white-space: nowrap;
}

th:first-child, td:first-child {
    width: 180px;
    min-width: 180px;
    max-width: 180px;
    white-space: nowrap;
}

td:first-child {
    overflow: hidden;
}

th {
    border-bottom: 1px solid black;
}

tbody tr:nth-child(even) {
    background-color: #e8e8e8;
}

.logo {
    width: 22px;
    height: auto;
}

td.logo-cell {
    padding: 2px 5px;
    vertical-align: middle;
}

td.logo-cell .logo {
    vertical-align: middle;
}


.voter-cell {
    display: flex;
    flex-wrap: nowrap;
    align-items: center;
    gap: 2px;
    min-width: 0;
    overflow: hidden;
}

.voter-name {
    display: inline-block;
    cursor: pointer;
    transition: transform 0.1s ease;
    font-size: 13px;
    font-weight: bold;
    margin-left: 6px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
    flex: 0 1 auto;
}

.voter-cell:hover .voter-name {
    transform: scale(1.05);
}

.voter-row.row-highlight td {
    background-color: #fffde7 !important;
}

.pin-btn {
    display: none;
    cursor: pointer;
    font-size: 11px;
    flex-shrink: 0;
    opacity: 0.3;
    filter: grayscale(100%);
    user-select: none;
    transition: opacity 0.1s, filter 0.1s;
}

.pin-btn:hover {
    opacity: 0.6;
}

.pin-btn.pinned {
    opacity: 1;
    filter: grayscale(100%) brightness(0.2);
}

.highlight-btn {
    display: none;
    cursor: pointer;
    font-size: 11px;
    flex-shrink: 0;
    opacity: 0.3;
    filter: grayscale(100%);
    user-select: none;
    transition: opacity 0.1s, filter 0.1s;
}

.highlight-btn:hover {
    opacity: 0.6;
}

.highlight-btn.highlighted {
    opacity: 1;
    filter: grayscale(100%) brightness(0.2);
}

.voter-row.voter-cell-hover .pin-btn,
.voter-row.voter-cell-hover .highlight-btn {
    display: inline;
}

.voter-row.row-pinned .pin-btn {
    display: inline;
}

.voter-row.row-highlight .highlight-btn {
    display: inline;
}

.voter-row.row-pinned.row-highlight .pin-btn,
.voter-row.row-pinned.row-highlight .highlight-btn {
    display: inline;
}

.row-pinned-agg {
    border-top: 1px solid #ddd;
}

.history-btn {
    display: none;
    cursor: pointer;
    font-size: 11px;
    flex-shrink: 0;
    opacity: 0.3;
    filter: grayscale(100%);
    user-select: none;
    transition: opacity 0.1s, filter 0.1s;
}

.history-btn:hover {
    opacity: 0.6;
}

.voter-row.voter-cell-hover .history-btn {
    display: inline;
}


.voter-row.row-delta .delta-label,
.voter-row.row-delta .avg-label {
    display: block;
    text-align: center;
}

.delta-label {
    display: none;
    font-size: 11px;
    font-weight: bold;
    line-height: 1;
    margin-bottom: 1px;
    white-space: nowrap;
}



.delta-up { color: #2a9d2a; }
.delta-down { color: #cc0000; }
.delta-same { color: #888; }
.delta-new { color: #3388dd; }

.avg-label {
    display: none;
    font-size: 11px;
    line-height: 1;
    margin-top: 1px;
    color: #555;
    white-space: nowrap;
}

.rank-score-label {
    display: none;
    font-size: 11px;
    color: #888;
    margin-left: 4px;
    white-space: nowrap;
}

.voter-row.row-rank-sorted .rank-score-label {
    display: inline;
}




.voters-toggle:hover {
    transform: scale(1.05);
}

.sort-picker {
    display: none;
    white-space: nowrap;
    position: fixed;
    z-index: 1000;
}

.sort-picker.open {
    display: flex;
    gap: 6px;
    align-items: center;
}

.sort-option {
    cursor: pointer;
    white-space: nowrap;
    font-size: inherit;
    font-weight: inherit;
    color: inherit;
    background: transparent;
    border: none;
    padding: 0;
    text-decoration: none;
}

.sort-option:hover {
    opacity: 0.7;
}

.sort-option.active {
    text-decoration: underline;
    color: inherit;
    background: transparent;
    border: none;
}

.sort-lock {
    display: inline-block;
    vertical-align: middle;
    font-size: 0.75em;
    line-height: 1;
    margin-left: 2px;
    filter: grayscale(1) brightness(0);
}

.sort-option.locked {
    cursor: not-allowed;
    opacity: 0.5;
}

.sort-option.locked:hover {
    opacity: 0.5;
}

.team-logo {
    cursor: pointer;
}

.team-logo:hover {
    transform: scale(1.3);
    transition: transform 0.2s;
}

th:nth-child(5), td:nth-child(5),
th:nth-child(9), td:nth-child(9),
th:nth-child(13), td:nth-child(13),
th:nth-child(17), td:nth-child(17),
th:nth-child(21), td:nth-child(21) {
    border-right: 1px solid #0D0D0D;
}

thead th {
    position: sticky;
    top: 0;
    background: #f8f8f8;
    z-index: 2;
}

.rank-header-num {
    cursor: pointer;
}
thead th:first-child {
    z-index: 3;
    overflow: visible;
    white-space: nowrap;
}

.team-highlight-1 { outline: 2px solid #ffcc00; border-radius: 4px; box-shadow: 0 0 20px 6px #ffcc00; }
.team-highlight-2 { outline: 2px solid #0077cc; border-radius: 4px; box-shadow: 0 0 20px 6px #0077cc; }
.team-highlight-3 { outline: 2px solid #ff6666; border-radius: 4px; box-shadow: 0 0 20px 6px #ff6666; }
.team-highlight-4 { outline: 2px solid #33cc33; border-radius: 4px; box-shadow: 0 0 20px 6px #33cc33; }
.team-highlight-5 { outline: 2px solid #cc66ff; border-radius: 4px; box-shadow: 0 0 20px 6px #cc66ff; }

.row-delta .team-highlight-1,
.row-delta .team-highlight-2,
.row-delta .team-highlight-3,
.row-delta .team-highlight-4,
.row-delta .team-highlight-5 { box-shadow: none; }

#voter-history-modal, #keybind-legend-modal {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.55);
    z-index: 1000;
    justify-content: center;
    align-items: center;
}
#voter-history-modal.open, #keybind-legend-modal.open {
    display: flex;
}
#keybind-legend-box {
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.25);
    max-width: 520px;
    width: 95vw;
    max-height: 88vh;
    overflow: auto;
    padding: 20px 24px 20px;
}
#keybind-legend-box h2 {
    margin: 0 0 14px;
    font-size: 1.05rem;
    color: #333;
}
.keybind-section {
    margin-bottom: 12px;
}
.keybind-section-title {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #999;
    margin-bottom: 5px;
}
.keybind-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 3px 0;
    font-size: 13px;
    color: #444;
}
.keybind-keys {
    display: flex;
    gap: 4px;
    flex-shrink: 0;
    min-width: 130px;
    justify-content: flex-end;
}
kbd {
    display: inline-block;
    background: #f0f0f0;
    border: 1px solid #ccc;
    border-bottom: 2px solid #bbb;
    border-radius: 4px;
    padding: 1px 6px;
    font-family: inherit;
    font-size: 11px;
    color: #333;
    line-height: 1.5;
}
#voter-history-box {
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.25);
    max-width: 95vw;
    max-height: 88vh;
    overflow: auto;
    padding: 20px 24px 16px;
}
#voter-history-box h2 {
    margin: 0 0 12px;
    font-size: 1.1rem;
    color: #333;
}
#voter-history-table {
    border-collapse: collapse;
    white-space: nowrap;
    table-layout: auto;
    width: auto;
}
#voter-history-table th {
    font-size: 11px;
    color: #888;
    font-weight: normal;
    padding: 2px 4px;
    text-align: center;
    border-bottom: 1px solid #ddd;
}
#voter-history-table th.week-label {
    text-align: left;
    padding-right: 6px;
    color: #444;
    font-weight: bold;
    white-space: nowrap;
    width: 1px;
}
#voter-history-table td.week-label {
    font-size: 12px;
    color: #555;
    text-align: left;
    white-space: nowrap;
    min-width: 0;
    max-width: none;
    width: 1px;
}
#voter-history-table td {
    padding: 2px 5px;
    text-align: center;
    vertical-align: middle;
}
#voter-history-table .logo {
    width: 22px;
    height: 22px;
}
#voter-history-table td.no-ballot {
    color: #bbb;
    font-size: 11px;
    letter-spacing: 1px;
}

#avg-rank-modal {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.55);
    z-index: 1000;
    justify-content: center;
    align-items: center;
}
#avg-rank-modal.open {
    display: flex;
}
#avg-rank-box {
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.25);
    max-width: 420px;
    width: 95vw;
    max-height: 88vh;
    overflow: auto;
    padding: 20px 24px 16px;
}
#avg-rank-box h2 {
    margin: 0 0 12px;
    font-size: 1.05rem;
    color: #333;
}
#avg-rank-table {
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
}
#avg-rank-table th {
    font-size: 11px;
    color: #888;
    font-weight: normal;
    padding: 4px 8px;
    text-align: center;
    border-bottom: 1px solid #ddd;
    white-space: nowrap;
}
#avg-rank-table th.team-col { text-align: left; }
#avg-rank-table td {
    padding: 3px 6px;
    text-align: center;
    border-bottom: 1px solid #f4f4f4;
    vertical-align: middle;
    white-space: nowrap;
    overflow: hidden;
}
#avg-rank-table td:first-child { color: #aaa; font-size: 11px; }
#avg-rank-table td.team-col { text-align: left; font-size: 12px; color: #444; white-space: nowrap; }
#avg-rank-table .logo-sm { height: 20px; width: 20px; object-fit: contain; vertical-align: middle; }
#avg-rank-table tr.rv-divider td { padding: 6px 0 2px; color: #aaa; font-size: 11px; text-align: left; border-bottom: none; }

#season-stats-modal {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.55);
    z-index: 1000;
    justify-content: center;
    align-items: center;
}
#season-stats-modal.open {
    display: flex;
}
#season-stats-box {
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.25);
    max-width: 580px;
    width: 95vw;
    max-height: 88vh;
    overflow: auto;
    padding: 20px 24px 16px;
}
#season-stats-box h2 {
    margin: 0 0 12px;
    font-size: 1.05rem;
    color: #333;
}
#season-stats-table {
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
}
#season-stats-table th {
    font-size: 11px;
    color: #888;
    font-weight: normal;
    padding: 4px 8px;
    text-align: center;
    border-bottom: 1px solid #ddd;
    white-space: nowrap;
}
#season-stats-table th.team-col { text-align: left; }
#season-stats-table td {
    padding: 3px 6px;
    text-align: center;
    border-bottom: 1px solid #f4f4f4;
    white-space: nowrap;
    vertical-align: middle;
}
#season-stats-table td.team-col { text-align: left; font-size: 12px; color: #444; }
#season-stats-table td:first-child { color: #aaa; font-size: 11px; }
#season-stats-table .logo-sm { height: 20px; width: 20px; object-fit: contain; vertical-align: middle; }

body.year-loading::after {
    content: "Loading…";
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: rgba(0,0,0,0.7);
    color: #fff;
    padding: 12px 24px;
    border-radius: 6px;
    font-size: 14px;
    z-index: 9999;
    pointer-events: none;
}

@media (max-device-width: 768px) {
    .header {
        display: none !important;
    }
    .logo {
        width: 32px;
    }
    thead th {
        position: static;
    }
    body {
        margin: 8px;
    }
}
"""

JS = """
let _sortedTabsCache = null;
let _leaderboardDataCache = null;
let _deltaDataCache = null;
let _deltaDataCacheIsProvisional = null;

const _loadedYears = new Set();
const _loadingYears = {};

async function loadYear(year) {
    if (_loadedYears.has(year)) return;
    if (_loadingYears[year]) return _loadingYears[year];
    if (typeof FRAGMENT_YEARS === 'undefined' || !FRAGMENT_YEARS.includes(year)) {
        _loadedYears.add(year);
        return;
    }
    _loadingYears[year] = (async () => {
        try {
            document.body.classList.add('year-loading');
            const resp = await fetch(`data-${year}.html`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const html = await resp.text();
            const container = document.getElementById('year-data-container');
            container.insertAdjacentHTML('beforeend', html);
            _loadedYears.add(year);
            _sortedTabsCache = null;
            _leaderboardDataCache = null;
            _deltaDataCache = null;
        } catch (e) {
            console.error(`Failed to load year ${year}:`, e);
            throw e;
        } finally {
            delete _loadingYears[year];
            document.body.classList.remove('year-loading');
        }
    })();
    return _loadingYears[year];
}

const highlightClasses = [
    "team-highlight-1","team-highlight-2","team-highlight-3",
    "team-highlight-4","team-highlight-5"
];
const highlightColors = {
    "team-highlight-1": "#ffcc00",
    "team-highlight-2": "#0077cc",
    "team-highlight-3": "#ff6666",
    "team-highlight-4": "#33cc33",
    "team-highlight-5": "#cc66ff"
};

const highlightedTeams = {}; // "team-highlight-1" → team name, etc.

function applyHighlightStyles() {
    let el = document.getElementById("team-highlight-styles");
    if (!el) {
        el = document.createElement("style");
        el.id = "team-highlight-styles";
        document.head.appendChild(el);
    }
    const rules = [];
    highlightClasses.forEach(cls => {
        const team = highlightedTeams[cls];
        if (!team) return;
        const color = highlightColors[cls];
        rules.push(`.team-logo[data-team="${team}"] { outline: 2px solid ${color}; border-radius: 4px; box-shadow: 0 0 20px 6px ${color}; }`);
        rules.push(`.row-delta .team-logo[data-team="${team}"] { box-shadow: none; }`);
    });
    el.textContent = rules.join(" ");
}

function getOffsetLeftInContainer(el, container) {
    let x = 0;
    while (el && el !== container) {
        x += el.offsetLeft;
        el = el.offsetParent;
    }
    return x;
}

function updateAvgRankLines() {
    document.querySelectorAll(".avg-rank-line").forEach(el => el.remove());
    // Clear previous consensus header highlights
    document.querySelectorAll("th[data-consensus-highlight]").forEach(th => {
        th.style.color = "";
        delete th.dataset.consensusHighlight;
        delete th.dataset.consensusColor;
    });
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const block = document.getElementById(activeTab.dataset.week);
    if (!block) return;
    const officialSection = block.querySelectorAll(".ballot-section")[0];
    if (!officialSection || officialSection.style.display === "none") return;
    const container = officialSection.querySelector(".table-container");
    if (!container) return;
    const voterRows = Array.from(officialSection.querySelectorAll(".voter-row"))
        .filter(r => !r.classList.contains("row-pinned-agg") && !r.classList.contains("row-weighted-ranking"));
    if (voterRows.length === 0) return;
    const sampleCells = voterRows[0].querySelectorAll("td");

    // Get the aggregate row for consensus rank lookup
    const aggSection = block.querySelectorAll(".ballot-section")[2];
    const aggRow = aggSection ? aggSection.querySelector(".voter-row") : null;

    // Official table header ths: th[0]=voter, th[1..25]=ranks
    const headerThs = officialSection.querySelectorAll("thead th");

    highlightClasses.forEach(cls => {
        const team = highlightedTeams[cls];
        if (!team) return;
        const color = highlightColors[cls];
        const ranks = [];
        voterRows.forEach(row => {
            let found = false;
            row.querySelectorAll("td.logo-cell").forEach((cell, idx) => {
                if (cell.querySelector(`.team-logo[data-team="${team}"]`)) { ranks.push(idx + 1); found = true; }
            });
            if (!found) ranks.push(26);
        });
        const avg = ranks.reduce((a, b) => a + b, 0) / ranks.length;
        if (avg > 25) return;
        const floorR = Math.floor(avg);
        const ceilR = Math.ceil(avg);
        const frac = avg - floorR;
        const getX = r => {
            const cell = sampleCells[r];
            if (!cell) return 0;
            return getOffsetLeftInContainer(cell, container) + cell.offsetWidth / 2;
        };
        const x = floorR === ceilR ? getX(floorR) : getX(floorR) + (getX(ceilR) - getX(floorR)) * frac;
        const line = document.createElement("div");
        line.className = "avg-rank-line";
        line.style.left = x + "px";
        line.style.background = color;
        container.appendChild(line);

        // Color the consensus rank header number
        if (aggRow) {
            let consensusRank = -1;
            aggRow.querySelectorAll("td.logo-cell").forEach((cell, idx) => {
                if (cell.querySelector(`.team-logo[data-team="${team}"]`)) consensusRank = idx + 1;
            });
            if (consensusRank >= 1 && consensusRank <= 25 && headerThs[consensusRank]) {
                const th = headerThs[consensusRank];
                th.style.color = color;
                th.dataset.consensusHighlight = "1";
                th.dataset.consensusColor = color;
            }
        }
    });
}

function lazyLoadWeek(block) {
    if (!block) return;
    block.querySelectorAll("img[data-src]").forEach(img => {
        img.src = "cbb-logos/" + img.dataset.src + ".webp";
        img.removeAttribute("data-src");
    });
}

function getSortedTabs() {
    if (_sortedTabsCache) return _sortedTabsCache;
    _sortedTabsCache = Array.from(document.querySelectorAll(".week-tab"))
        .sort((a, b) => parseInt(b.dataset.year) - parseInt(a.dataset.year) || parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum));
    return _sortedTabsCache;
}

function getVoterName(row) {
    // Read from text nodes only to avoid label contamination
    const el = row?.querySelector(".voter-name");
    if (!el) return null;
    return Array.from(el.childNodes)
        .filter(n => n.nodeType === Node.TEXT_NODE)
        .map(n => n.textContent.trim())
        .join("") || el.textContent.trim();
}

function getRowsByUsername(username) {
    return Array.from(document.querySelectorAll(".voter-row"))
        .filter(r => getVoterName(r) === username);
}

function syncPinnedToAggregate(username, isPinning) {
    const tabs = Array.from(document.querySelectorAll(".week-tab"));

    function processChunk(startIdx) {
        const end = Math.min(startIdx + 5, tabs.length);
        for (let i = startIdx; i < end; i++) {
            const tab = tabs[i];
            const weekId = tab.dataset.week;
            const block = document.getElementById(weekId);
            if (!block) continue;
            const sections = block.querySelectorAll(".ballot-section");
            const officialSection = sections[0];
            const aggSection = sections[2];
            if (!officialSection || !aggSection) continue;
            const aggTbody = aggSection.querySelector("tbody");
            if (!aggTbody) continue;

            if (isPinning) {
                const officialRow = Array.from(officialSection.querySelectorAll(".voter-row"))
                    .find(r => getVoterName(r) === username);
                if (!officialRow) continue;
                const clone = officialRow.cloneNode(true);
                clone.dataset.pinnedUser = username;
                clone.classList.add("row-pinned-agg");
                clone.querySelectorAll(".pin-btn, .highlight-btn, .history-btn").forEach(el => el.remove());
                clone.querySelectorAll(".voter-cell").forEach(el => el.dataset.bound = "");
                clone.querySelectorAll(".team-logo").forEach(el => el.dataset.bound = "");
                aggTbody.appendChild(clone);
                bindVoterCells();
                bindTeamLogos();
                clone.querySelector(".pin-btn")?.classList.add("pinned");
                if (officialRow.classList.contains("row-delta")) {
                    clone.classList.add("row-delta");
                    const deltaData = buildDeltaData();
                    applyDeltaToRow(clone, weekId, deltaData, getSortedTabs());
                }
            } else {
                aggTbody.querySelectorAll(`[data-pinned-user="${username}"]`).forEach(r => r.remove());
            }
        }
        if (end < tabs.length) {
            requestAnimationFrame(() => processChunk(end));
        }
    }

    requestAnimationFrame(() => processChunk(0));
}

function pinRow(row, tbody) {
    const username = getVoterName(row);
    const allRows = getRowsByUsername(username);
    const isPinned = row.classList.contains("row-pinned");

    allRows.forEach(r => {
        const rTbody = r.closest("tbody");
        if (isPinned) {
            r.classList.remove("row-pinned");
            r.querySelector(".pin-btn")?.classList.remove("pinned");
            // Return to alphabetical position
            const siblings = Array.from(rTbody.querySelectorAll("tr"));
            const uname = username.toLowerCase();
            let insertBefore = null;
            for (const s of siblings) {
                if (s === r) continue;
                if (s.classList.contains("row-pinned")) continue;
                const sName = (getVoterName(s) || "").toLowerCase();
                if (sName > uname) { insertBefore = s; break; }
            }
            rTbody.insertBefore(r, insertBefore);
        } else {
            r.classList.add("row-pinned");
            r.querySelector(".pin-btn")?.classList.add("pinned");
            const siblings = Array.from(rTbody.querySelectorAll("tr"));
            const lastPinned = siblings.filter(s => s !== r && s.classList.contains("row-pinned")).pop();
            if (lastPinned) lastPinned.after(r);
            else rTbody.prepend(r);
        }
    });
    syncPinnedToAggregate(username, !isPinned);
    if (!isPinned) {
        allRows.forEach(r => r.classList.remove("voter-cell-hover"));
    }
}
function toggleAllDeltas() {
    const allRows = Array.from(document.querySelectorAll(".voter-row"));
    const allExpanded = allRows.every(r => r.classList.contains("row-delta"));
    const deltaData = buildDeltaData();
    const sortedTabs = getSortedTabs();
    if (allExpanded) {
        // Collapse all
        allRows.forEach(r => {
            r.classList.remove("row-delta");
            if (!r.classList.contains("row-weighted-ranking")) {
                r.querySelectorAll(".delta-label, .avg-label").forEach(el => el.remove());
            }
        });
    } else {
        // Expand all
        allRows.forEach(r => {
            if (!r.classList.contains("row-delta")) {
                r.classList.add("row-delta");
                if (r.classList.contains("row-weighted-ranking")) return;
                const weekId = r.closest(".week-block")?.id;
                if (weekId) applyDeltaToRow(r, weekId, deltaData, sortedTabs);
            }
        });
    }
}

function expandAllDeltas() {
    const allRows = Array.from(document.querySelectorAll(".voter-row"));
    const deltaData = buildDeltaData();
    const sortedTabs = getSortedTabs();
    allRows.forEach(r => {
        if (!r.classList.contains("row-delta")) {
            r.classList.add("row-delta");
            if (r.classList.contains("row-weighted-ranking")) return;
            const weekId = r.closest(".week-block")?.id;
            if (weekId) applyDeltaToRow(r, weekId, deltaData, sortedTabs);
        }
    });
}

function hideRankHeaders(block) {
    if (!block) return;
    block.querySelectorAll("table thead th:not(:first-child)").forEach(th => { th.style.color = "transparent"; th.style.borderRight = "none"; });
}

function showRankHeaders(block) {
    if (!block) return;
    block.querySelectorAll("table thead th:not(:first-child)").forEach(th => { th.style.color = th.dataset.consensusColor || ""; th.style.borderRight = ""; });
}

function bindVotersToggle() {
    document.querySelectorAll(".voters-toggle").forEach(toggle => {
        if (toggle.dataset.bound) return;
        toggle.dataset.bound = "1";
        toggle.addEventListener("click", e => {
            e.stopPropagation();
            const picker = toggle._picker || toggle.nextElementSibling;
            if (!picker?.classList.contains("sort-picker")) return;
            toggle._picker = picker;
            const isOpen = picker.classList.contains("open");
            document.querySelectorAll(".sort-picker.open").forEach(p => {
                p.classList.remove("open");
                if (p._toggle) p._toggle.style.display = "";
                const b = p._sourceBlock || p.closest(".week-block");
                showRankHeaders(b);
            });
            const block = toggle.closest(".week-block");
            if (!isOpen) {
                picker._toggle = toggle;
                if (picker.parentElement !== document.body) {
                    picker._sourceBlock = block;
                    document.body.appendChild(picker);
                }
                const rect = toggle.getBoundingClientRect();
                picker.style.top = rect.top + "px";
                picker.style.left = rect.left + "px";
                // Match toggle font exactly
                const ts = getComputedStyle(toggle);
                picker.style.font = ts.font;
                toggle.style.display = "none";
                picker.classList.add("open");
                hideRankHeaders(block);
            } else {
                toggle.style.display = "";
                applyTableSort("alphabetic");
                showRankHeaders(block);
            }
        });
    });
}

// Sort option clicks via delegation — use mousedown so it fires before outside-click closes picker
document.addEventListener("mousedown", e => {
    const opt = e.target.closest(".sort-option");
    if (!opt) return;
    e.stopPropagation();
    const sort = opt.dataset.sort;
    // Check if locked and prevent interaction with locked tabs
    if (sortTabsLocked && (sort === "ranking" || sort === "tenure")) {
        return;
    }
    document.querySelectorAll(".consensus-dist").forEach(el => el.remove());
    document.querySelectorAll(".rank-score-label").forEach(el => el.remove());
    rankingSortActive = false;
    const picker = opt.closest(".sort-picker");
    // Show the toggle again
    if (picker._toggle) picker._toggle.style.display = "";
    picker.classList.remove("open");
    // Restore rank headers when picker closes
    const block = picker._sourceBlock || picker.closest(".week-block");
    showRankHeaders(block);
    applyTableSort(sort, opt.closest("table"));
}, true);

let currentSort = "alphabetic";

const SORT_LABELS = { alphabetic: "Alphabetic", consensus: "Consensus", ranking: "Précision", tenure: "Tenure" };

function setGlobalSort(sort) {
    currentSort = sort;
    const label = SORT_LABELS[sort] || (sort.charAt(0).toUpperCase() + sort.slice(1));
    document.querySelectorAll(".voters-toggle").forEach(t => {
        if (t.style.display !== "none") t.textContent = label;
    });
    document.querySelectorAll(".sort-option").forEach(o => {
        o.classList.toggle("active", o.dataset.sort === sort);
    });
}

function resetRankingSort() {
    setGlobalSort("alphabetic");
    document.querySelectorAll(".voters-toggle").forEach(t => { if (t.style.display === "none") t.style.display = ""; });
}

function applyTableSort(sort, clickedTable) {
    setGlobalSort(sort);
    // Close all sort pickers
    document.querySelectorAll(".sort-picker.open").forEach(p => p.classList.remove("open"));
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const block = document.getElementById(activeTab.dataset.week);
    if (!block) return;

    // Show/hide rank number headers based on sort
    document.querySelectorAll(".ballot-section").forEach(section => {
        if (section.style.display === "none") return;
        showRankHeaders(section.closest(".week-block"));
    });

    const sections = block.querySelectorAll(".ballot-section");
    const visibleSection = Array.from(sections).find(s => s.style.display !== "none") || sections[0];
    const tbody = visibleSection?.querySelector("tbody");
    if (!tbody) return;

    const rows = Array.from(tbody.querySelectorAll(".voter-row"));

    // Clear any existing consensus distance labels
    document.querySelectorAll(".consensus-dist").forEach(el => el.remove());

    const addVoterLabel = (row, text) => {
        const cell = row.querySelector(".voter-cell");
        if (!cell) return;
        const label = document.createElement("span");
        label.className = "consensus-dist";
        label.textContent = text;
        label.style.cssText = "font-size:11px; color:#999; font-weight:normal; margin-left:4px;";
        cell.appendChild(label);
    };

    if (sort === "alphabetic") {
        rows.sort((a, b) => getVoterName(a).localeCompare(getVoterName(b)));
        rows.forEach(r => tbody.appendChild(r));
        return;
    }

    if (sort === "ranking") {
        // Reuse existing Shift+J ranking sort
        sortByRanking();
        return;
    }

    if (sort === "consensus") {
        // Sort by deviation from official consensus (most conformist first)
        // Read consensus directly from the rendered aggregate row so it always
        // matches the Official Overall row exactly (avoids recompute divergence).
        const aggRow = sections[2]?.querySelector(".voter-row:not(.row-weighted-ranking)");
        const consensus = aggRow
            ? Array.from(aggRow.querySelectorAll(".team-logo")).map(img => img.dataset.team)
            : null;
        if (!consensus || !consensus.length) return;
        const scoreFn = teams => {
            if (!teams?.length) return Infinity;
            let dist = 0;
            for (let i = 0; i < 25; i++) {
                const vr = teams.indexOf(consensus[i]);
                dist += Math.abs(i - (vr === -1 ? 25 : vr));
            }
            return dist;
        };
        // Get voter teams directly from visible rows
        const voterTeams = {};
        rows.forEach(r => {
            const u = getVoterName(r);
            voterTeams[u] = Array.from(r.querySelectorAll(".team-logo")).map(img => img.dataset.team);
        });
        rows.sort((a, b) => scoreFn(voterTeams[getVoterName(a)]) - scoreFn(voterTeams[getVoterName(b)]));
        rows.forEach(r => {
            tbody.appendChild(r);
            const dist = scoreFn(voterTeams[getVoterName(r)]);
            if (dist !== Infinity) addVoterLabel(r, "+" + dist);
        });
        return;
    }

    if (sort === "tenure") {
        // Sort by total ballots submitted across all years (official + provisional), most first
        const lbData = buildLeaderboardData();
        const ballotCount = {};
        Object.values(lbData).forEach(weekData => {
            Object.entries(weekData).forEach(([u, entry]) => {
                if (u === "Official Overall" || !entry.teams?.length) return;
                ballotCount[u] = (ballotCount[u] || 0) + 1;
            });
        });
        rows.sort((a, b) => {
            const ua = getVoterName(a), ub = getVoterName(b);
            return (ballotCount[ub] ?? 0) - (ballotCount[ua] ?? 0);
        });
        rows.forEach(r => {
            tbody.appendChild(r);
            const count = ballotCount[getVoterName(r)] ?? 0;
            if (count) addVoterLabel(r, count);
        });
        return;
    }
}

function bindVoterCells() {
    document.querySelectorAll(".voter-cell").forEach(cell => {
        if (cell.dataset.bound) return;
        cell.dataset.bound = "1";

        // Add pin button if not already present
        if (!cell.querySelector(".pin-btn")) {
            const pin = document.createElement("span");
            pin.className = "pin-btn";
            pin.textContent = "📌";
            pin.addEventListener("click", e => {
                e.stopPropagation();
                const row = cell.closest("tr");
                const tbody = row.closest("tbody");
                if (row && tbody) pinRow(row, tbody);
            });
            cell.appendChild(pin);
        }

        // Add highlight button if not already present
        if (!cell.querySelector(".highlight-btn")) {
            const hl = document.createElement("span");
            hl.className = "highlight-btn";
            hl.textContent = "🖊️";
            hl.addEventListener("click", e => {
                e.stopPropagation();
                const row = cell.closest("tr");
                const username = getVoterName(row);
                const allRows = getRowsByUsername(username);
                const isHighlighted = row.classList.contains("row-highlight");
                allRows.forEach(r => {
                    r.classList.toggle("row-highlight", !isHighlighted);
                    r.querySelector(".highlight-btn")?.classList.toggle("highlighted", !isHighlighted);
                });
            });
            cell.appendChild(hl);
        }

        // Add history button if not already present
        if (!cell.querySelector(".history-btn")) {
            const cal = document.createElement("span");
            cal.className = "history-btn";
            cal.textContent = "📅";
            cal.addEventListener("click", e => {
                e.stopPropagation();
                const row = cell.closest("tr");
                const username = getVoterName(row);
                if (username) showVoterHistory(username);
            });
            cell.appendChild(cal);
        }


        cell.addEventListener("mouseenter", () => {
            cell.closest("tr")?.classList.add("voter-cell-hover");
        });
        cell.addEventListener("mouseleave", () => {
            cell.closest("tr")?.classList.remove("voter-cell-hover");
        });

        cell.addEventListener("click", e => {
            if (e.altKey) {
                const url = cell.dataset.ballotUrl;
                if (url) {
                    const a = document.createElement("a");
                    a.href = url;
                    a.target = "_blank";
                    a.rel = "noopener noreferrer";
                    a.click();
                }
                return;
            }
            const row = cell.closest("tr");

            // Special handling for the 5-Week Weighted aggregate row
            if (row.classList.contains("row-weighted-ranking")) {
                row.classList.toggle("row-delta");
                return;
            }

            const username = getVoterName(row);
            const isActive = row.classList.contains("row-delta");
            const allUserRows = getRowsByUsername(username);
            if (isActive) {
                allUserRows.forEach(r => {
                    r.classList.remove("row-delta");
                    r.querySelectorAll(".delta-label, .avg-label").forEach(el => el.remove());
                });
            } else {
                const deltaData = buildDeltaData();
                const sortedTabs = getSortedTabs();
                allUserRows.forEach(r => {
                    r.classList.add("row-delta");
                    const weekId = r.closest(".week-block")?.id;
                    if (weekId) applyDeltaToRow(r, weekId, deltaData, sortedTabs);
                });
            }
        });
    });
}

// Compute the 5-Week Weighted top-25 teams for a given week.
// Accepts pre-built deltaData and the year's tabs (sorted oldest-last, i.e. getSortedTabs() order).
function compute5WeekWeightedTeams(weekId, deltaData, yearTabs) {
    const currIdx = yearTabs.findIndex(t => t.dataset.week === weekId);
    if (currIdx === -1) return null;
    const last5WeekIds = [];
    for (let i = currIdx; i < yearTabs.length && last5WeekIds.length < 5; i++) {
        last5WeekIds.push(yearTabs[i].dataset.week);
    }
    if (last5WeekIds.length === 0) return null;
    const currentVoters = Object.keys(deltaData[weekId] || {}).filter(u => u !== "Official Overall");
    if (currentVoters.length === 0) return null;
    const allTeamsSeen = new Set();
    last5WeekIds.forEach(wid => {
        Object.entries(deltaData[wid] || {}).forEach(([u, ballot]) => {
            if (u !== "Official Overall" && ballot?.length) ballot.forEach(t => allTeamsSeen.add(t));
        });
    });
    const teamAvgRankSum = {};
    currentVoters.forEach(username => {
        const voterLast5 = last5WeekIds.map(wid => deltaData[wid]?.[username] || null);
        allTeamsSeen.forEach(team => {
            let weightedSum = 0, totalWeight = 0;
            voterLast5.forEach((ballot, wi) => {
                if (!ballot) return;
                const weight = last5WeekIds.length - wi;
                const pos = ballot.indexOf(team);
                weightedSum += (pos === -1 ? 26 : pos + 1) * weight;
                totalWeight += weight;
            });
            if (totalWeight > 0) teamAvgRankSum[team] = (teamAvgRankSum[team] || 0) + weightedSum / totalWeight;
        });
    });
    const ranked = Object.entries(teamAvgRankSum).sort((a, b) => a[1] - b[1]).slice(0, 25).map(([team]) => team);
    return ranked.length > 0 ? ranked : null;
}

// Build a map of { weekId -> teams[] | null } for the given username across all loaded weeks.
// Works for regular voters, "Official Overall" (aggregate row), and "5-Week Weighted" (computed).
function buildSeasonDataForUser(username) {
    const result = {};
    const allTabsSorted = getSortedTabs();
    if (username === "5-Week Weighted") {
        const deltaData = buildDeltaData();
        const yearGroups = {};
        allTabsSorted.forEach(tab => {
            if (!yearGroups[tab.dataset.year]) yearGroups[tab.dataset.year] = [];
            yearGroups[tab.dataset.year].push(tab);
        });
        allTabsSorted.forEach(tab => {
            result[tab.dataset.week] = compute5WeekWeightedTeams(tab.dataset.week, deltaData, yearGroups[tab.dataset.year]) || null;
        });
        return result;
    }
    // For all named rows (regular voters and "Official Overall"):
    allTabsSorted.forEach(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        result[weekId] = null;
        if (!block) return;
        outer: for (const section of block.querySelectorAll(".ballot-section")) {
            for (const row of section.querySelectorAll(".voter-row")) {
                if (getVoterName(row) !== username) continue;
                result[weekId] = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
                break outer;
            }
        }
    });
    return result;
}

function renderVoterHistoryTable(mergedData, yearTabs, container) {
    container.innerHTML = "";
    container.style.cssText = "";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    const weekTh = document.createElement("th");
    weekTh.className = "week-label";
    weekTh.textContent = "Week";
    weekTh.style.cssText = "white-space:nowrap; padding-right:16px; width:1px; min-width:0;";
    headerRow.appendChild(weekTh);
    for (let i = 1; i <= 25; i++) {
        const th = document.createElement("th");
        th.textContent = i;
        headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    container.appendChild(thead);

    const tbody = document.createElement("tbody");
    yearTabs.forEach(tab => {
        const weekId = tab.dataset.week;
        const teams = mergedData[weekId];
        if (!teams || teams.length === 0) return;
        const tr = document.createElement("tr");

        const weekTd = document.createElement("td");
        weekTd.className = "week-label";
        weekTd.textContent = "Week " + tab.dataset.weeknum;
        weekTd.style.cssText = "white-space:nowrap; padding-right:16px; width:1px; min-width:0;";
        tr.appendChild(weekTd);

        teams.slice(0, 25).forEach(team => {
            const td = document.createElement("td");
            const img = document.createElement("img");
            img.className = "logo team-logo";
            img.src = "cbb-logos/" + team + ".webp";
            img.alt = team;
            img.dataset.team = team;
            td.appendChild(img);
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    container.appendChild(tbody);
}


function showVoterHistory(username) {
    const allTabsSorted = getSortedTabs();

    // Build ballot data for all weeks
    const mergedData = buildSeasonDataForUser(username);

    // Use the active week's year
    const activeTab = document.querySelector(".week-tab.active");
    const currentYear = activeTab?.dataset.year || allTabsSorted[0]?.dataset.year;
    const yearTabs = allTabsSorted
        .filter(t => t.dataset.year === currentYear)
        .reverse();

    const modal = document.getElementById("voter-history-modal");
    const title = document.getElementById("voter-history-title");
    const table = document.getElementById("voter-history-table");

    title.textContent = username + " \u2013 " + currentYear + " Ballots";

    renderVoterHistoryTable(mergedData, yearTabs, table);
    modal.classList.add("open");
    bindTeamLogos();
}

document.getElementById("voter-history-modal").addEventListener("click", e => {
    if (e.target === e.currentTarget) e.currentTarget.classList.remove("open");
});


function bindTeamLogos() {
    document.querySelectorAll(".team-logo").forEach(logo => {
        if (logo.dataset.bound) return;
        logo.dataset.bound = "1";
        logo.addEventListener("click", (e) => {
            if (e.shiftKey) {
                e.stopPropagation();
                const team = logo.dataset.team;
                const row = logo.closest(".voter-row");
                const username = row ? getVoterName(row) : null;
                showTeamRankChart(team, username);
                return;
            }
            const team = logo.dataset.team;
            const isHighlighted = highlightClasses.some(c => highlightedTeams[c] === team);
            if (isHighlighted) {
                highlightClasses.forEach(c => { if (highlightedTeams[c] === team) delete highlightedTeams[c]; });
            } else {
                const availableColor = highlightClasses.find(c => !highlightedTeams[c]);
                if (availableColor) highlightedTeams[availableColor] = team;
            }
            applyHighlightStyles();
            updateAvgRankLines();
        });
    });
}

function bindRankHeaders() {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const block = document.getElementById(activeTab.dataset.week);
    if (!block) return;
    const officialSection = block.querySelectorAll(".ballot-section")[0];
    if (!officialSection) return;
    officialSection.querySelectorAll("thead .rank-header-num").forEach((span, i) => {
        if (span.dataset.rankBound) return;
        span.dataset.rankBound = "1";
        const rank = i + 1;
        span.addEventListener("click", () => {
            const aggSection = block.querySelectorAll(".ballot-section")[2];
            if (!aggSection) return;
            const aggRow = aggSection.querySelector(".voter-row:not(.row-weighted-ranking)");
            if (!aggRow) return;
            const logo = aggRow.querySelectorAll("td.logo-cell")[rank - 1]?.querySelector(".team-logo");
            if (!logo) return;
            const team = logo.dataset.team;
            const isHighlighted = highlightClasses.some(c => highlightedTeams[c] === team);
            if (isHighlighted) {
                highlightClasses.forEach(c => { if (highlightedTeams[c] === team) delete highlightedTeams[c]; });
            } else {
                const availableColor = highlightClasses.find(c => !highlightedTeams[c]);
                if (availableColor) highlightedTeams[availableColor] = team;
            }
            applyHighlightStyles();
            updateAvgRankLines();
        });
    });
}

function showTeamRankChart(team, username) {
    const allTabsSorted = getSortedTabs();

    // Build ballot data for all weeks (works for all row types)
    const mergedData = username ? buildSeasonDataForUser(username) : {};

    // Current year's weeks in chronological order
    const activeTab = document.querySelector(".week-tab.active");
    const currentYear = activeTab?.dataset.year || allTabsSorted[0]?.dataset.year;
    const yearTabs = allTabsSorted.filter(t => t.dataset.year === currentYear).reverse();

    // Build data points: rank per week (null = not ranked, hasBallot = submitted a ballot that week)
    const dataPoints = yearTabs.map(tab => {
        const weekId = tab.dataset.week;
        const weekNum = parseInt(tab.dataset.weeknum);
        let rank = null;
        const teams = username ? mergedData[weekId] : null;
        const hasBallot = !!teams;
        if (teams) {
            const idx = teams.indexOf(team);
            if (idx !== -1) rank = idx + 1;
        }
        return { weekNum, rank, hasBallot };
    });

    const modal = document.getElementById("voter-history-modal");
    const title = document.getElementById("voter-history-title");
    const table = document.getElementById("voter-history-table");

    title.innerHTML = `<img class="logo" src="cbb-logos/${team}.webp" style="height:22px;vertical-align:middle;margin-right:6px;">${team} — ${username || "Unknown"}`;
    table.innerHTML = "";
    table.style.cssText = "display:block; white-space:normal; width:100%;";

    // SVG chart
    const svgNS = "http://www.w3.org/2000/svg";
    const W = 900, H = 500;
    const mL = 44, mR = 20, mT = 28, mB = 40;
    const cW = W - mL - mR, cH = H - mT - mB;

    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.style.cssText = "width:min(860px,90vw);display:block;margin:0 auto;";

    const weeks = dataPoints.map(d => d.weekNum);
    const minW = Math.min(...weeks), maxW = Math.max(...weeks);
    const wRange = Math.max(maxW - minW, 1);
    const xPos = w => mL + ((w - minW) / wRange) * cW;
    const yPos = r => mT + ((r - 1) / 24) * cH;  // rank 1 at top

    const axisColor = "#999", gridColor = "#e8e8e8";

    // Rank gridlines + y-axis labels
    [1, 5, 10, 15, 20, 25].forEach(r => {
        const y = yPos(r);
        const line = document.createElementNS(svgNS, "line");
        line.setAttribute("x1", mL); line.setAttribute("x2", mL + cW);
        line.setAttribute("y1", y); line.setAttribute("y2", y);
        line.setAttribute("stroke", gridColor); line.setAttribute("stroke-width", "1");
        svg.appendChild(line);
        const txt = document.createElementNS(svgNS, "text");
        txt.setAttribute("x", mL - 6); txt.setAttribute("y", y + 4);
        txt.setAttribute("text-anchor", "end"); txt.setAttribute("font-size", "11");
        txt.setAttribute("fill", axisColor);
        txt.textContent = r;
        svg.appendChild(txt);
    });

    // Chart border
    const border = document.createElementNS(svgNS, "rect");
    border.setAttribute("x", mL); border.setAttribute("y", mT);
    border.setAttribute("width", cW); border.setAttribute("height", cH);
    border.setAttribute("fill", "none"); border.setAttribute("stroke", "#ddd");
    border.setAttribute("stroke-width", "1");
    svg.appendChild(border);

    // Y-axis label
    const yLbl = document.createElementNS(svgNS, "text");
    yLbl.setAttribute("x", 10); yLbl.setAttribute("y", mT + cH / 2);
    yLbl.setAttribute("text-anchor", "middle"); yLbl.setAttribute("font-size", "11");
    yLbl.setAttribute("fill", axisColor);
    yLbl.setAttribute("transform", `rotate(-90,10,${mT + cH / 2})`);
    yLbl.textContent = "Rank";
    svg.appendChild(yLbl);

    // X-axis ticks + week labels
    dataPoints.forEach(d => {
        const x = xPos(d.weekNum);
        const tick = document.createElementNS(svgNS, "line");
        tick.setAttribute("x1", x); tick.setAttribute("x2", x);
        tick.setAttribute("y1", mT + cH); tick.setAttribute("y2", mT + cH + 4);
        tick.setAttribute("stroke", axisColor);
        svg.appendChild(tick);
        const txt = document.createElementNS(svgNS, "text");
        txt.setAttribute("x", x); txt.setAttribute("y", mT + cH + 15);
        txt.setAttribute("text-anchor", "middle"); txt.setAttribute("font-size", "11");
        txt.setAttribute("fill", axisColor);
        txt.textContent = d.weekNum;
        svg.appendChild(txt);
    });

    // X-axis label
    const xLbl = document.createElementNS(svgNS, "text");
    xLbl.setAttribute("x", mL + cW / 2); xLbl.setAttribute("y", H - 4);
    xLbl.setAttribute("text-anchor", "middle"); xLbl.setAttribute("font-size", "11");
    xLbl.setAttribute("fill", axisColor);
    xLbl.textContent = "Week";
    svg.appendChild(xLbl);

    // Dashed vertical line for NR weeks (only when ballot was submitted but team not ranked)
    dataPoints.filter(d => d.rank === null && d.hasBallot).forEach(d => {
        const x = xPos(d.weekNum);
        const nrLine = document.createElementNS(svgNS, "line");
        nrLine.setAttribute("x1", x); nrLine.setAttribute("x2", x);
        nrLine.setAttribute("y1", mT); nrLine.setAttribute("y2", mT + cH);
        nrLine.setAttribute("stroke", "#eee"); nrLine.setAttribute("stroke-width", "1");
        nrLine.setAttribute("stroke-dasharray", "3,3");
        svg.appendChild(nrLine);
        const nrTxt = document.createElementNS(svgNS, "text");
        nrTxt.setAttribute("x", x); nrTxt.setAttribute("y", mT + cH - 5);
        nrTxt.setAttribute("text-anchor", "middle"); nrTxt.setAttribute("font-size", "9");
        nrTxt.setAttribute("fill", "#ccc");
        nrTxt.textContent = "NR";
        svg.appendChild(nrTxt);
    });

    // Line connecting ranked weeks
    const ranked = dataPoints.filter(d => d.rank !== null);
    if (ranked.length >= 2) {
        const poly = document.createElementNS(svgNS, "polyline");
        poly.setAttribute("points", ranked.map(d => `${xPos(d.weekNum)},${yPos(d.rank)}`).join(" "));
        poly.setAttribute("fill", "none"); poly.setAttribute("stroke", "#2277cc");
        poly.setAttribute("stroke-width", "2.5"); poly.setAttribute("stroke-linejoin", "round");
        poly.setAttribute("stroke-linecap", "round");
        svg.appendChild(poly);
    }

    // Data point circles + rank labels
    ranked.forEach(d => {
        const x = xPos(d.weekNum), y = yPos(d.rank);
        const circle = document.createElementNS(svgNS, "circle");
        circle.setAttribute("cx", x); circle.setAttribute("cy", y);
        circle.setAttribute("r", "5"); circle.setAttribute("fill", "#2277cc");
        circle.setAttribute("stroke", "#fff"); circle.setAttribute("stroke-width", "2");
        svg.appendChild(circle);
        const lbl = document.createElementNS(svgNS, "text");
        lbl.setAttribute("x", x); lbl.setAttribute("y", y - 9);
        lbl.setAttribute("text-anchor", "middle"); lbl.setAttribute("font-size", "11");
        lbl.setAttribute("fill", "#2277cc"); lbl.setAttribute("font-weight", "bold");
        lbl.textContent = d.rank;
        svg.appendChild(lbl);
    });

    // Message if never ranked
    if (ranked.length === 0) {
        const msg = document.createElementNS(svgNS, "text");
        msg.setAttribute("x", mL + cW / 2); msg.setAttribute("y", mT + cH / 2);
        msg.setAttribute("text-anchor", "middle"); msg.setAttribute("font-size", "14");
        msg.setAttribute("fill", "#999");
        msg.textContent = `${team} not ranked by ${username || "this voter"} this season`;
        svg.appendChild(msg);
    }

    table.appendChild(svg);
    modal.classList.add("open");
}

let weekPickerPinned = false;
const isMobile = () => screen.width <= 768;

let _lastFaviconWeek = null;
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (_lastFaviconWeek !== null) updateFavicon(_lastFaviconWeek);
});

function updateFavicon(n) {
    _lastFaviconWeek = n;
    const size = 64;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');

    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    const label = String(n);
    let fontSize = size;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    do {
        ctx.font = `bold ${fontSize}px sans-serif`;
        fontSize--;
    } while (ctx.measureText(label).width > size * 0.88 && fontSize > 4);

    ctx.fillStyle = dark ? '#ffffff' : '#222222';
    ctx.fillText(label, size / 2, size / 2);

    const url = canvas.toDataURL('image/png');
    const old = document.getElementById('favicon');
    if (old) old.parentNode.removeChild(old);
    const link = document.createElement('link');
    link.id = 'favicon';
    link.rel = 'icon';
    link.type = 'image/png';
    link.href = url;
    document.head.appendChild(link);
}

function closeAllPickers(forceCloseYear = false) {
    if (weekPickerPinned && !forceCloseYear) return;
    if (!weekPickerPinned) {
        document.getElementById("week-picker").classList.remove("open");
        if (!isMobile()) document.getElementById("week-text").style.display = "";
    }
    document.getElementById("year-picker").classList.remove("open");
    if (!isMobile()) document.getElementById("year-text").style.display = "";
}

function rebuildYearPicker() {
    const tabs = Array.from(document.querySelectorAll(".week-tab"));
    const byYear = {};
    tabs.forEach(t => {
        const y = t.dataset.year;
        if (!byYear[y]) byYear[y] = [];
        byYear[y].push(t);
    });
    const years = Object.keys(byYear).sort();

    const yearPicker = document.getElementById("year-picker");
    yearPicker.innerHTML = "";
    const activeTab = document.querySelector(".week-tab.active");
    const activeYear = activeTab ? activeTab.dataset.year : null;
    years.forEach(y => {
        const btn = document.createElement("button");
        btn.className = "picker-btn";
        btn.textContent = y;
        btn.dataset.year = y;
        if (y === activeYear) {
            btn.style.textDecoration = "underline";
        }
        btn.addEventListener("click", async e => {
            e.stopPropagation();
            try { await loadYear(y); } catch { return; }
            const activeTab = document.querySelector(".week-tab.active");
            const currentWeekNum = activeTab ? parseInt(activeTab.dataset.weeknum) : null;
            const sameWeek = currentWeekNum
                ? byYear[y].find(t => parseInt(t.dataset.weeknum) === currentWeekNum)
                : null;
            const target = sameWeek || byYear[y][byYear[y].length - 1];
            showWeek(target.dataset.week);
            const weekWasPinned = weekPickerPinned;
            // Always close year picker explicitly
            const yearPicker = document.getElementById("year-picker");
            const yearText = document.getElementById("year-text");
            yearPicker.classList.remove("open");
            yearText.style.display = "";
            // Restore week picker if pinned, otherwise close everything
            if (weekWasPinned) {
                weekPickerPinned = true;
                const weekPicker = document.getElementById("week-picker");
                const weekText = document.getElementById("week-text");
                rebuildWeekPicker();
                weekPicker.classList.add("open");
                weekText.style.display = "none";
            } else {
                closeAllPickers();
            }
        });
        yearPicker.appendChild(btn);
    });
}

function rebuildWeekPicker() {
    const currentYear = document.getElementById("year-text").innerText;
    const activeTab = document.querySelector(".week-tab.active");
    const tabs = Array.from(document.querySelectorAll(`.week-tab[data-year="${currentYear}"]`))
        .sort((a, b) => parseInt(a.dataset.weeknum) - parseInt(b.dataset.weeknum));
    const weekPicker = document.getElementById("week-picker");
    weekPicker.innerHTML = "";
    tabs.forEach(t => {
        const btn = document.createElement("button");
        btn.className = "picker-btn";
        const wnum = parseInt(t.dataset.weeknum);
        btn.textContent = wnum < 10 ? "0" + wnum : String(wnum);
        btn.dataset.week = t.dataset.week;
        if (activeTab && t.dataset.week === activeTab.dataset.week) {
            btn.style.textDecoration = "underline";
        }
        btn.addEventListener("click", e => {
            e.stopPropagation();
            if (weekPickerPinned) {
                const activeTab = document.querySelector(".week-tab.active");
                if (activeTab && activeTab.dataset.week === t.dataset.week) {
                    // Clicking the current week while pinned: unpin and close
                    weekPickerPinned = false;
                    closeAllPickers();
                } else {
                    showWeek(t.dataset.week);
                    rebuildWeekPicker();
                }
            } else {
                showWeek(t.dataset.week);
                closeAllPickers();
            }
        });
        weekPicker.appendChild(btn);
    });
}

function showWeek(weekId) {
    document.querySelectorAll(".week-block").forEach(b => b.style.display = "none");
    document.querySelectorAll(".week-tab").forEach(t => t.classList.remove("active"));
    const block = document.getElementById(weekId);
    if (block) block.style.display = "block";
    const tab = document.querySelector(`.week-tab[data-week="${weekId}"]`);
    if (tab) tab.classList.add("active");

    if (tab) {
        const wn = parseInt(tab.dataset.weeknum);
        if (!isMobile()) {
            document.getElementById("week-text").innerText = "#" + (wn < 10 ? "0" + wn : wn);
            document.getElementById("year-text").innerText = tab.dataset.year;
            rebuildWeekPicker();
        }
        updateFavicon(wn);
    }

    const toggleText = document.getElementById("toggle-text").innerText;
    const isProvisional = !isMobile() && toggleText === "Provisional Ballots";
    const isAggregate = !isMobile() && toggleText === "Data Ballots";
    if (block) {
        block.querySelectorAll(".ballot-section").forEach(s => s.style.display = "none");
        const sections = block.querySelectorAll(".ballot-section");
        let targetSection;
        if (isAggregate && sections[2]) targetSection = sections[2];
        else if (isProvisional) targetSection = sections[1];
        else targetSection = sections[0];
        if (targetSection) targetSection.style.display = "block";
        else if (sections[0]) sections[0].style.display = "block";
        lazyLoadWeek(block);
        if (isAggregate) {
            const newActiveTab = document.querySelector(".week-tab.active");
            if (newActiveTab) injectWeightedRankingRow(newActiveTab, block);
        }
    }

    bindTeamLogos();
    bindRankHeaders();
    bindVoterCells();
    bindVotersToggle();
    updateRankingOptionVisibility();
    if (currentSort && currentSort !== "ranking") {
        applyTableSort(currentSort);
    }
    updateAvgRankLines();
    if (rankingSortActive) {
        const activeTab2 = document.querySelector(".week-tab.active");
        if (activeTab2) {
            // Remove labels from all other blocks
            document.querySelectorAll(".week-block").forEach(b => {
                if (b.id !== weekId) {
                    b.querySelectorAll(".rank-score-label").forEach(l => l.remove());
                }
            });
            const yearTabs2 = getSortedTabs().filter(t => t.dataset.year === activeTab2.dataset.year).reverse();
            const lbData2 = buildLeaderboardData();
            const voterAvg2 = computeVoterAvg(yearTabs2, lbData2);
            if (voterAvg2) applyRankingSortToBlock(document.getElementById(weekId), voterAvg2, true);
        }
    }
}

// Toggle Official / Provisional within current week
document.getElementById("toggle-text").addEventListener("click", () => {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const activeBlock = document.getElementById(activeTab.dataset.week);
    if (!activeBlock) return;
    const sections = activeBlock.querySelectorAll(".ballot-section");
    const current = document.getElementById("toggle-text").innerText;
    sections.forEach(s => s.style.display = "none");
    if (current === "Official Ballots") {
        if (sections[1]) sections[1].style.display = "block";
        document.getElementById("toggle-text").innerText = "Provisional Ballots";
    } else {
        if (sections[0]) sections[0].style.display = "block";
        document.getElementById("toggle-text").innerText = "Official Ballots";
    }
    _deltaDataCache = null;
    updateRankingOptionVisibility();
    if (currentSort === "ranking") resetRankingSort();
    applyTableSort(currentSort);
    updateAvgRankLines();
});

function updateRankingOptionVisibility() {
    const toggleText = document.getElementById("toggle-text")?.innerText;
    const isOfficial = !toggleText || toggleText === "Official Ballots";
    document.querySelectorAll(".sort-option[data-sort='ranking']").forEach(opt => {
        opt.style.display = isOfficial ? "" : "none";
    });
}

function injectWeightedRankingRow(activeTab, activeBlock) {
    // Build a "5-Week Weighted" ranking row in the aggregate table.
    // For each voter in the current week, compute the same per-team weighted avg rank
    // that applyDeltaToRow shows as the avg-label (last 5 weeks, weight 5→1).
    // Sum those avg ranks across all voters per team, then rank by lowest total.
    const sections = activeBlock.querySelectorAll(".ballot-section");
    const aggTbody = sections[2]?.querySelector("tbody");
    if (!aggTbody) return;

    // Remove any previously injected weighted row, remembering if it was expanded
    const existingRow = aggTbody.querySelector(".row-weighted-ranking");
    const wasExpanded = existingRow?.classList.contains("row-delta") ?? false;
    existingRow?.remove();

    const activeYear = activeTab.dataset.year;
    const weekId = activeTab.dataset.week;
    const allTabsSorted = getSortedTabs().filter(t => t.dataset.year === activeYear);

    const currIdx = allTabsSorted.findIndex(t => t.dataset.week === weekId);
    if (currIdx === -1) return;

    // Gather the last 5 week IDs (same year, most recent first)
    const last5WeekIds = [];
    for (let i = currIdx; i < allTabsSorted.length && last5WeekIds.length < 5; i++) {
        last5WeekIds.push(allTabsSorted[i].dataset.week);
    }
    if (last5WeekIds.length === 0) return;

    const deltaData = buildDeltaData();

    // Get the list of voters in the current week's official section
    const currentVoters = Object.keys(deltaData[weekId] || {})
        .filter(u => u !== "Official Overall");
    if (currentVoters.length === 0) return;

    // For each voter, replicate the avg-label calculation: weighted avg rank per team
    // over their last 5 ballots. Then accumulate per team across all voters.
    // Collect all teams seen across the 5 weeks so we can apply rank-26 for non-rankers
    const allTeamsSeen = new Set();
    last5WeekIds.forEach(wid => {
        const weekVoters = deltaData[wid];
        if (!weekVoters) return;
        Object.entries(weekVoters).forEach(([username, ballot]) => {
            if (username === "Official Overall" || !ballot?.length) return;
            ballot.forEach(t => allTeamsSeen.add(t));
        });
    });

    const totalVoters = currentVoters.length;

    // For each voter, compute weighted avg rank for every team seen (unranked = 26)
    const teamAvgRankSum = {};
    const teamRankedByCount = {};

    currentVoters.forEach(username => {
        // voterLast5: this week's ballot always exists (currentVoters is from this week).
        // Prior weeks use null if voter missed, rank-26 per team if week submitted but team unranked.
        const voterLast5 = last5WeekIds.map(wid => deltaData[wid]?.[username] || null);

        allTeamsSeen.forEach(team => {
            let weightedSum = 0, totalWeight = 0, everRanked = false;
            voterLast5.forEach((ballot, wi) => {
                if (!ballot) return;
                const weight = last5WeekIds.length - wi;
                const pos = ballot.indexOf(team);
                const rank = pos === -1 ? 26 : pos + 1;
                if (pos !== -1) everRanked = true;
                weightedSum += rank * weight;
                totalWeight += weight;
            });
            if (totalWeight > 0) {
                const avgRank = weightedSum / totalWeight;
                teamAvgRankSum[team] = (teamAvgRankSum[team] || 0) + avgRank;
                if (everRanked) teamRankedByCount[team] = (teamRankedByCount[team] || 0) + 1;
            }
        });
    });

    // Rank by lowest sum of avg ranks across all voters (unranked voters penalize via rank 26)
    const ranked = Object.entries(teamAvgRankSum)
        .sort((a, b) => a[1] - b[1])
        .slice(0, 25)
        .map(([team]) => team);

    if (ranked.length === 0) return;

    // Display avg = sum / totalVoters (includes rank-26 penalty for non-rankers)
    const teamDisplayAvg = {};
    const teamVoterCount = {};
    ranked.forEach(team => {
        teamDisplayAvg[team] = teamAvgRankSum[team] / totalVoters;
        teamVoterCount[team] = teamRankedByCount[team] || 0;
    });

    // Compute previous week's weighted ranking for delta comparison.
    // Shift the 5-week window back by 1 (drop current week, add one older week).
    const prevWeekIds = [];
    for (let i = currIdx + 1; i < allTabsSorted.length && prevWeekIds.length < 5; i++) {
        prevWeekIds.push(allTabsSorted[i].dataset.week);
    }
    const prevRanked = prevWeekIds.length > 0 ? (() => {
        const prevVoters = Object.keys(deltaData[prevWeekIds[0]] || {})
            .filter(u => u !== "Official Overall");
        const prevTeamsSeen = new Set();
        prevWeekIds.forEach(wid => {
            Object.entries(deltaData[wid] || {}).forEach(([u, b]) => {
                if (u !== "Official Overall" && b?.length) b.forEach(t => prevTeamsSeen.add(t));
            });
        });
        const prevSum = {};
        prevVoters.forEach(username => {
            const voterPrev5 = prevWeekIds.map(wid => deltaData[wid]?.[username] || null);
            prevTeamsSeen.forEach(team => {
                let ws = 0, tw = 0;
                voterPrev5.forEach((ballot, wi) => {
                    if (!ballot) return;
                    const w = prevWeekIds.length - wi;
                    const pos = ballot.indexOf(team);
                    ws += (pos === -1 ? 26 : pos + 1) * w;
                    tw += w;
                });
                if (tw > 0) prevSum[team] = (prevSum[team] || 0) + ws / tw;
            });
        });
        const pv = prevVoters.length || 1;
        return Object.entries(prevSum)
            .sort((a, b) => a[1] - b[1])
            .slice(0, 25)
            .map(([team]) => team);
    })() : [];
    // Build lookup: team -> rank in previous weighted ranking (1-based, 0 if not present)
    const prevRankOf = {};
    prevRanked.forEach((team, i) => { prevRankOf[team] = i + 1; });

    // Build the row
    const tr = document.createElement("tr");
    tr.className = "voter-row row-weighted-ranking";

    const voterTd = document.createElement("td");
    voterTd.innerHTML = `<div class="voter-cell"><span class="voter-name" style="color:#555;">5-Week Weighted</span></div>`;
    tr.appendChild(voterTd);

    ranked.forEach((team, idx) => {
        const currRank = idx + 1;
        const td = document.createElement("td");
        td.className = "logo-cell";
        const wrapper = document.createElement("div");
        wrapper.className = "cell-logo-wrapper";

        // Delta label above logo
        const deltaLabel = document.createElement("span");
        deltaLabel.className = "delta-label";
        const prev = prevRankOf[team];
        if (!prev) {
            deltaLabel.textContent = "NEW"; deltaLabel.classList.add("delta-new");
        } else {
            const diff = prev - currRank;
            if (diff > 0) {
                deltaLabel.textContent = diff <= 2 ? String(diff) : "▲" + diff;
                deltaLabel.classList.add("delta-up");
            } else if (diff < 0) {
                deltaLabel.textContent = Math.abs(diff) <= 2 ? String(Math.abs(diff)) : "▼" + Math.abs(diff);
                deltaLabel.classList.add("delta-down");
            } else {
                deltaLabel.textContent = "—"; deltaLabel.classList.add("delta-same");
            }
        }
        wrapper.appendChild(deltaLabel);

        const img = document.createElement("img");
        img.className = "logo team-logo";
        img.dataset.team = team;
        img.src = "cbb-logos/" + team + ".webp";
        wrapper.appendChild(img);

        const avgLabel = document.createElement("span");
        avgLabel.className = "avg-label";
        avgLabel.textContent = teamDisplayAvg[team].toFixed(1);
        wrapper.appendChild(avgLabel);

        td.appendChild(wrapper);
        tr.appendChild(td);
    });

    // Insert after the Official Overall row, restoring expanded state if it was active
    const overallRow = aggTbody.querySelector(".voter-row:not(.row-weighted-ranking)");
    if (overallRow) {
        overallRow.after(tr);
    } else {
        aggTbody.appendChild(tr);
    }
    if (wasExpanded) tr.classList.add("row-delta");

    bindTeamLogos();
}

function showAvgRankModal(weekId) {
    const block = document.getElementById(weekId);
    if (!block) return;
    const sections = block.querySelectorAll(".ballot-section");
    const officialSection = sections[0];
    if (!officialSection) return;

    // Collect all voter rows (exclude Official Overall)
    const voterRows = Array.from(officialSection.querySelectorAll(".voter-row"))
        .filter(r => getVoterName(r) !== "Official Overall");
    const totalVoters = voterRows.length;
    if (totalVoters === 0) return;

    // Compute rank sums, voter counts, points, and rank lists per team
    const teamRankSum = {};
    const teamVoterCount = {};
    const teamPoints = {};
    const teamRanks = {};
    voterRows.forEach(row => {
        const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
        teams.slice(0, 25).forEach((team, i) => {
            const rank = i + 1;
            teamRankSum[team] = (teamRankSum[team] || 0) + rank;
            teamVoterCount[team] = (teamVoterCount[team] || 0) + 1;
            teamPoints[team] = (teamPoints[team] || 0) + (26 - rank);
            if (!teamRanks[team]) teamRanks[team] = [];
            teamRanks[team].push(rank);
        });
    });

    const computeMedian = ranks => {
        const sorted = [...ranks].sort((a, b) => a - b);
        const mid = Math.floor(sorted.length / 2);
        return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
    };

    // Sort by points descending (same order as Official Overall)
    const allTeams = Object.entries(teamPoints).sort((a, b) => b[1] - a[1]).map(([t]) => t);
    const top25 = allTeams.slice(0, 25);
    const receivingVotes = allTeams.slice(25);

    const activeTab = document.querySelector(".week-tab.active");
    const weekNum = activeTab?.dataset.weeknum || "";
    const year = activeTab?.dataset.year || "";

    const modal = document.getElementById("avg-rank-modal");
    const title = document.getElementById("avg-rank-title");
    const table = document.getElementById("avg-rank-table");

    const weekPad = String(weekNum).padStart(2, "0");
    title.textContent = `${year} #${weekPad} Statistics`;

    const buildRow = (team, rank) => {
        const avg = teamRankSum[team] / teamVoterCount[team];
        const median = computeMedian(teamRanks[team]);
        const count = teamVoterCount[team];
        const pts = teamPoints[team];
        return `<tr>
            <td>${rank}</td>
            <td style="padding:2px 4px;"><img class="logo-sm" src="cbb-logos/${team}.webp"></td>
            <td class="team-col">${team}</td>
            <td>${avg.toFixed(2)}</td>
            <td>${Number.isInteger(median) ? median : median.toFixed(1)}</td>
            <td>${count}/${totalVoters}</td>
            <td>${pts}</td>
        </tr>`;
    };

    let html = `<colgroup>
        <col style="width:28px">
        <col style="width:28px">
        <col>
        <col style="width:64px">
        <col style="width:56px">
        <col style="width:56px">
        <col style="width:36px">
    </colgroup><thead><tr>
        <th>#</th><th></th>
        <th class="team-col">Team</th>
        <th>Avg Rank</th>
        <th>Median</th>
        <th>Voters</th>
        <th>Pts</th>
    </tr></thead><tbody>`;
    top25.forEach((team, i) => { html += buildRow(team, i + 1); });
    if (receivingVotes.length > 0) {
        html += `<tr class="rv-divider"><td colspan="7">Receiving Votes</td></tr>`;
        receivingVotes.forEach((team, i) => { html += buildRow(team, 26 + i); });
    }
    html += "</tbody>";
    table.innerHTML = html;
    modal.classList.add("open");
}

function showAggregateSection() {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const activeBlock = document.getElementById(activeTab.dataset.week);
    if (!activeBlock) return;
    const sections = activeBlock.querySelectorAll(".ballot-section");
    if (!sections[2]) return;
    sections.forEach(s => s.style.display = "none");
    sections[2].style.display = "block";
    document.getElementById("toggle-text").innerText = "Data Ballots";
    _deltaDataCache = null;
    injectWeightedRankingRow(activeTab, activeBlock);
    bindVoterCells();
    bindTeamLogos();
    updateRankingOptionVisibility();
    if (currentSort === "ranking") resetRankingSort();
}

// Year picker toggle — hide year text, show all years inline
document.getElementById("year-text").addEventListener("click", e => {
    e.stopPropagation();
    const picker = document.getElementById("year-picker");
    const yearText = document.getElementById("year-text");
    const isOpen = picker.classList.contains("open");
    const weekPicker = document.getElementById("week-picker");
    const weekText = document.getElementById("week-text");
    closeAllPickers();
    if (!isOpen) {
        rebuildYearPicker();
        picker.classList.add("open");
        yearText.style.display = "none";
        // Temporarily hide week picker while year picker is open (pin state preserved)
        weekPicker.classList.remove("open");
        weekText.style.display = "";
    }
});

// Week picker toggle — hide week number, show all weeks inline
document.getElementById("week-text").addEventListener("click", e => {
    e.stopPropagation();
    rebuildWeekPicker();
    const picker = document.getElementById("week-picker");
    const weekText = document.getElementById("week-text");
    const isOpen = picker.classList.contains("open");
    if (e.altKey) {
        weekPickerPinned = true;
        picker.classList.add("open");
        weekText.style.display = "none";
    } else {
        weekPickerPinned = false;
        closeAllPickers();
        if (!isOpen) {
            picker.classList.add("open");
            weekText.style.display = "none";
        }
    }
});

// Close sort pickers on scroll
document.addEventListener("scroll", () => {
    document.querySelectorAll(".sort-picker.open").forEach(p => {
        p.classList.remove("open");
        if (p._toggle) p._toggle.style.display = "";
        showRankHeaders(p._sourceBlock || p.closest(".week-block"));
    });
}, { passive: true });

// Close pickers when clicking elsewhere (respects pinned state)
document.addEventListener("click", e => {
    const yearPickerOpen = document.getElementById("year-picker").classList.contains("open");
    closeAllPickers(true); // always close year picker on outside click
    // If year picker was open and week picker is pinned, restore week picker
    if (yearPickerOpen && weekPickerPinned) {
        const weekPicker = document.getElementById("week-picker");
        const weekText = document.getElementById("week-text");
        rebuildWeekPicker();
        weekPicker.classList.add("open");
        weekText.style.display = "none";
    }
    // Close any open sort pickers
    if (!e.target.closest(".sort-picker") && !e.target.classList.contains("voters-toggle")) {
        document.querySelectorAll(".sort-picker.open").forEach(p => {
            p.classList.remove("open");
            if (p._toggle) p._toggle.style.display = "";
            showRankHeaders(p._sourceBlock || p.closest(".week-block"));
        });
    }
});

function getBackgroundImageQueue() {
    const allTabs = Array.from(document.querySelectorAll(".week-tab"));
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return [];

    const currentYear = activeTab.dataset.year;

    const sameYear = allTabs
        .filter(t => t.dataset.year === currentYear && t !== activeTab)
        .sort((a, b) => parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum));

    const otherYears = allTabs
        .filter(t => t.dataset.year !== currentYear)
        .sort((a, b) => parseInt(b.dataset.year) - parseInt(a.dataset.year) || parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum));

    // Build a flat queue of individual img elements across all weeks
    const imgs = [];
    for (const tab of [...sameYear, ...otherYears]) {
        const block = document.getElementById(tab.dataset.week);
        if (block) {
            block.querySelectorAll("img[data-src]").forEach(img => imgs.push(img));
        }
    }
    return imgs;
}

function loadImageQueue(queue) {
    if (queue.length === 0) return Promise.resolve();
    return new Promise(resolve => {
        let index = 0;
        const CONCURRENCY = 16;
        let active = 0;
        let resolved = false;
        function loadNext() {
            while (active < CONCURRENCY && index < queue.length) {
                while (index < queue.length && !queue[index].dataset.src) index++;
                if (index >= queue.length) break;
                const img = queue[index++];
                active++;
                img.src = "cbb-logos/" + img.dataset.src + ".webp";
                img.removeAttribute("data-src");
                const onDone = () => {
                    active--;
                    loadNext();
                };
                img.addEventListener("load", onDone, { once: true });
                img.addEventListener("error", onDone, { once: true });
            }
            if (active === 0 && !resolved) { resolved = true; resolve(); }
        }
        loadNext();
    });
}

function backgroundLoad() {
    // Load images for the current year (already in DOM)
    const queue = getBackgroundImageQueue();
    const loadCurrentImages = queue.length > 0
        ? new Promise(resolve => setTimeout(() => loadImageQueue(queue).then(resolve), 1000))
        : Promise.resolve();

    // After current year images settle, fetch all year fragments in parallel
    if (typeof FRAGMENT_YEARS !== 'undefined' && FRAGMENT_YEARS.length > 0) {
        loadCurrentImages.then(() => {
            setTimeout(() => {
                Promise.all(FRAGMENT_YEARS.map(year =>
                    loadYear(year).catch(() => {})
                )).then(() => {
                    const yearQueue = getBackgroundImageQueue();
                    loadImageQueue(yearQueue);
                });
            }, 3000);
        });
    }
}

// Save table as PNG (Shift+P)
function saveTableAsPng() {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const block = document.getElementById(activeTab.dataset.week);
    const section = block.querySelector(".ballot-section[style*='block'], .ballot-section:not([style])");
    const table = section ? section.querySelector("table") : null;
    if (!table) return;
    html2canvas(table, { useCORS: true, scale: 2 }).then(canvas => {
        const link = document.createElement("a");
        const week = activeTab.dataset.weeknum;
        const year = activeTab.dataset.year;
        const label = document.getElementById("toggle-text").innerText.includes("Provisional") ? "provisional" : "official";
        link.download = `cbb-poll-${year}-week${week}-${label}.png`;
        link.href = canvas.toDataURL("image/png");
        link.click();
    });
}

// Delta feature

function buildLeaderboardData() {
    if (_leaderboardDataCache) return _leaderboardDataCache;
    // Build a map: { weekId -> { username -> { teams: [...], isOfficial: bool } } }
    // Reads both official (sections[0]) and provisional (sections[1]) independently.
    const data = {};
    document.querySelectorAll(".week-tab").forEach(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        if (!block) return;
        data[weekId] = {};
        const sections = block.querySelectorAll(".ballot-section");

        const readSection = (section, isOfficial) => {
            if (!section) return;
            section.querySelectorAll(".voter-row").forEach(row => {
                const username = getVoterName(row);
                if (!username || username === "Official Overall") return;
                if (data[weekId][username]) {
                    // Appears in both sections — data error, prefer official
                    console.warn("Voter " + username + " in both sections for " + weekId);
                    if (isOfficial) data[weekId][username].isOfficial = true;
                    return;
                }
                const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
                data[weekId][username] = { teams, isOfficial };
            });
        };

        readSection(sections[0], true);
        readSection(sections[1], false);

        // Index Official Overall by computing points from official section rows
        if (sections[0]) {
            const points = {};
            sections[0].querySelectorAll(".voter-row").forEach(row => {
                const logos = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
                logos.slice(0, 25).forEach((team, i) => {
                    points[team] = (points[team] || 0) + (25 - i);
                });
            });
            const ranked = Object.entries(points)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 25)
                .map(([team]) => team);
            if (ranked.length > 0) {
                data[weekId]["Official Overall"] = { teams: ranked, isOfficial: true };
            }
        }
    });
    _leaderboardDataCache = data;
    return data;
}

function buildDeltaData() {
    const isProvisional = document.getElementById("toggle-text")?.innerText === "Provisional Ballots";
    if (_deltaDataCache !== null && _deltaDataCacheIsProvisional === isProvisional) return _deltaDataCache;
    const data = {};
    document.querySelectorAll(".week-tab").forEach(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        if (!block) return;
        data[weekId] = {};
        const sections = block.querySelectorAll(".ballot-section");
        const section = isProvisional && sections[1] ? sections[1] : sections[0];
        if (!section) return;
        section.querySelectorAll(".voter-row").forEach(row => {
            const username = getVoterName(row);
            if (!username) return;
            const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
            data[weekId][username] = teams;
        });
        // Also index Official Overall from the aggregate section
        if (sections[2]) {
            const aggRow = sections[2].querySelector(".voter-row");
            if (aggRow) {
                const teams = Array.from(aggRow.querySelectorAll(".team-logo")).map(img => img.dataset.team);
                data[weekId]["Official Overall"] = teams;
            }
        }
    });
    _deltaDataCache = data;
    _deltaDataCacheIsProvisional = isProvisional;
    return data;
}

let deltaWeeksBack = 1;

function applyDeltaToRow(row, weekId, deltaData, allTabsSorted) {
    const username = getVoterName(row);
    if (!username) return;
    const currIdx = allTabsSorted.findIndex(t => t.dataset.week === weekId);
    const currYear = allTabsSorted[currIdx]?.dataset.year;

    // Walk exactly deltaWeeksBack week-slots back to find the comparison point.
    // If the voter has no ballot at that exact slot, use the most recent ballot
    // found within those slots. If still none, keep searching further back for
    // their most recent available ballot (same year only).
    let prevTeams = null;
    const targetIdx = currIdx + deltaWeeksBack;
    for (let i = currIdx + 1; i <= targetIdx && i < allTabsSorted.length; i++) {
        if (allTabsSorted[i].dataset.year !== currYear) break;
        const wid = allTabsSorted[i].dataset.week;
        if (deltaData[wid]?.[username]) prevTeams = deltaData[wid][username];
    }
    // If no ballot found in the window, keep searching further back
    if (!prevTeams) {
        for (let i = targetIdx + 1; i < allTabsSorted.length; i++) {
            if (allTabsSorted[i].dataset.year !== currYear) break;
            const wid = allTabsSorted[i].dataset.week;
            if (deltaData[wid]?.[username]) { prevTeams = deltaData[wid][username]; break; }
        }
    }
    if (!prevTeams) return;

    // Build last 5 calendar weeks (same year only)
    const last5 = [];
    for (let i = currIdx; i < allTabsSorted.length && i < currIdx + 5; i++) {
        if (allTabsSorted[i].dataset.year !== currYear) break;
        const wid = allTabsSorted[i].dataset.week;
        last5.push(deltaData[wid]?.[username] || null);
    }

    // Build set of all teams this voter has ranked previously this year
    const priorTeams = new Set();
    for (let i = currIdx + 1; i < allTabsSorted.length; i++) {
        if (allTabsSorted[i].dataset.year !== currYear) break;
        const wid = allTabsSorted[i].dataset.week;
        if (deltaData[wid]?.[username]) deltaData[wid][username].forEach(t => priorTeams.add(t));
    }

    const logos = row.querySelectorAll(".team-logo");
    logos.forEach((logo, idx) => {
        const team = logo.dataset.team;
        const wrapper = logo.closest(".cell-logo-wrapper") || logo.closest("td");
        if (!wrapper) return;

        wrapper.querySelector(".delta-label")?.remove();
        wrapper.querySelector(".avg-label")?.remove();

        // Delta label above
        const prevIdx2 = prevTeams.indexOf(team);
        const label = document.createElement("span");
        label.className = "delta-label";
        if (prevIdx2 === -1 && !priorTeams.has(team)) {
            // Truly first time ranked this year
            label.textContent = "NEW"; label.classList.add("delta-new");
        } else {
            // Was unranked last period but ranked before — treat as coming from #26
            const effectivePrev = prevIdx2 === -1 ? 25 : prevIdx2; // 0-indexed, so 25 = rank 26
            const diff = effectivePrev - idx;
            if (diff > 0) {
                if (diff <= 2) { label.textContent = String(diff); label.classList.add("delta-up"); }
                else { label.textContent = "▲" + diff; label.classList.add("delta-up"); }
            } else if (diff < 0) {
                if (Math.abs(diff) <= 2) { label.textContent = String(Math.abs(diff)); label.classList.add("delta-down"); }
                else { label.textContent = "▼" + Math.abs(diff); label.classList.add("delta-down"); }
            }
        }
        if (label.textContent) {
            wrapper.insertBefore(label, logo);
        } else {
            label.textContent = "—"; label.classList.add("delta-same");
            wrapper.insertBefore(label, logo);
        }

        // Weighted avg label below (linear weights: most recent=5, oldest=1, missing weeks skipped)
        let weightedSum = 0, totalWeight = 0;
        last5.forEach((ballot, wi) => {
            if (!ballot) return;
            const weight = 5 - wi;
            const pos = ballot.indexOf(team);
            const rank = pos === -1 ? 26 : pos + 1;
            weightedSum += rank * weight;
            totalWeight += weight;
        });
        if (totalWeight > 0) {
            const avg = weightedSum / totalWeight;
            const avgLabel = document.createElement("span");
            avgLabel.className = "avg-label";
            avgLabel.textContent = avg.toFixed(1);
            wrapper.appendChild(avgLabel);
        }
    });
}


function showSeasonStatsModal() {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const currentYear = activeTab.dataset.year;

    const allTabs = getSortedTabs();
    const yearTabs = allTabs.filter(t => t.dataset.year === currentYear).reverse();
    if (yearTabs.length === 0) return;

    const totalWeeks = yearTabs.length;

    // Accumulate per-team stats from official ballot sections only
    const teamTotalPts = {};
    const teamRankSum = {};
    const teamVoterWeeks = {};  // total voter-ballot appearances (for avg rank)
    const teamWeeksRanked = {}; // distinct weeks the team appeared in any ballot
    const teamFirstPlaceVotes = {};
    const teamBestRank = {};

    yearTabs.forEach(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        if (!block) return;
        const officialSection = block.querySelectorAll(".ballot-section")[0];
        if (!officialSection) return;

        const seenThisWeek = new Set();
        officialSection.querySelectorAll(".voter-row").forEach(row => {
            if (getVoterName(row) === "Official Overall") return;
            const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
            teams.slice(0, 25).forEach((team, i) => {
                const rank = i + 1;
                teamTotalPts[team] = (teamTotalPts[team] || 0) + (25 - i);
                teamRankSum[team] = (teamRankSum[team] || 0) + rank;
                teamVoterWeeks[team] = (teamVoterWeeks[team] || 0) + 1;
                seenThisWeek.add(team);
                if (rank === 1) teamFirstPlaceVotes[team] = (teamFirstPlaceVotes[team] || 0) + 1;
                if (!teamBestRank[team] || rank < teamBestRank[team]) teamBestRank[team] = rank;
            });
        });
        seenThisWeek.forEach(team => {
            teamWeeksRanked[team] = (teamWeeksRanked[team] || 0) + 1;
        });
    });

    // Sort by total season points descending
    const allTeams = Object.keys(teamTotalPts).sort((a, b) => teamTotalPts[b] - teamTotalPts[a]);

    const modal = document.getElementById("season-stats-modal");
    const title = document.getElementById("season-stats-title");
    const table = document.getElementById("season-stats-table");

    title.textContent = `${currentYear} Season Statistics`;

    let html = `<colgroup>
        <col style="width:24px">
        <col style="width:26px">
        <col>
        <col style="width:52px">
        <col style="width:44px">
        <col style="width:60px">
        <col style="width:52px">
        <col style="width:36px">
    </colgroup><thead><tr>
        <th>#</th><th></th>
        <th class="team-col">Team</th>
        <th>Weeks</th>
        <th>Pts</th>
        <th>Avg Rank</th>
        <th>#1 Votes</th>
        <th>Best</th>
    </tr></thead><tbody>`;

    allTeams.forEach((team, i) => {
        const avgRank = (teamRankSum[team] / teamVoterWeeks[team]).toFixed(2);
        const firstPlace = teamFirstPlaceVotes[team] || 0;
        html += `<tr>
            <td>${i + 1}</td>
            <td><img class="logo-sm" src="cbb-logos/${team}.webp"></td>
            <td class="team-col">${team}</td>
            <td>${teamWeeksRanked[team]}/${totalWeeks}</td>
            <td>${teamTotalPts[team]}</td>
            <td>${avgRank}</td>
            <td>${firstPlace || "—"}</td>
            <td>${teamBestRank[team]}</td>
        </tr>`;
    });

    html += `</tbody>`;
    table.innerHTML = html;
    modal.classList.add("open");
}

// Keyboard shortcuts
let rankingSortActive = false;
let sortTabsLocked = true;
let lastKeyWasU = false;

function computeVoterAvg(yearTabs, lbData) {
    // Per-week consensus ranking (Official Overall computed from that week's official ballots)
    const weekConsensus = {};
    yearTabs.forEach(tab => {
        const overall = lbData[tab.dataset.week]?.["Official Overall"]?.teams;
        weekConsensus[tab.dataset.week] = overall && overall.length > 0 ? overall : null;
    });

    // Build finalRanking as weighted 5-week average of the last 5 consensus rankings
    // Mirrors the avg-label logic in applyDeltaToRow (weight 5=most recent, 1=oldest)
    let finalRanking = null;
    {
        const last5 = [];
        for (let i = yearTabs.length - 1; i >= 0 && last5.length < 5; i--) {
            const c = weekConsensus[yearTabs[i].dataset.week];
            if (c) last5.push(c);
        }
        if (last5.length === 0) return null;
        const points = {};
        last5.forEach((ranking, wi) => {
            const weight = last5.length - wi; // most recent = 5 (or last5.length), oldest = 1
            ranking.forEach((team, i) => {
                points[team] = (points[team] || 0) + (25 - i) * weight;
            });
        });
        finalRanking = Object.entries(points)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 25)
            .map(([team]) => team);
    }
    if (!finalRanking) return null;

    function posWeight(rank) {
        // Weight scales from 1.0 at #1 to 0.5 at #25
        return 1.0 - (rank - 1) * (0.5 / 24);
    }

    function ballotDistance(teams, reference) {
        let dist = 0;
        for (let i = 0; i < 25; i++) {
            const team = reference[i];
            const rank = i + 1;
            const vr = teams.indexOf(team);
            dist += Math.abs(rank - (vr === -1 ? 26 : vr + 1)) * posWeight(rank);
        }
        teams.forEach((team, vi) => {
            if (!reference.includes(team)) dist += Math.abs((vi + 1) - 26) * posWeight(vi + 1);
        });
        return dist;
    }

    const weekFieldAvg = {};
    yearTabs.forEach(tab => {
        const weekId = tab.dataset.week;
        const weekData = lbData[weekId];
        if (!weekData) { weekFieldAvg[weekId] = 0; return; }
        const dists = [];
        Object.entries(weekData).forEach(([u, entry]) => {
            if (u === "Official Overall" || !entry.isOfficial || !entry.teams?.length) return;
            dists.push(ballotDistance(entry.teams, finalRanking));
        });
        weekFieldAvg[weekId] = dists.length
            ? dists.reduce((a, b) => a + b, 0) / dists.length : 0;
    });

    const MISS_PENALTY = 1, MAX_MISSES = 5, MAX_CONSEC_MISSES = 3;
    const voterAvg = {};
    const allUsernames = new Set();
    yearTabs.forEach(tab => {
        const weekData = lbData[tab.dataset.week];
        if (!weekData) return;
        Object.keys(weekData).forEach(u => { if (u !== "Official Overall") allUsernames.add(u); });
    });
    const totalWeeks = yearTabs.length;

    allUsernames.forEach(username => {
        let lastBallot = null, total = 0, totalWW = 0, missed = 0, boldAdj = 0, consecMisses = 0;
        yearTabs.forEach((tab, weekIdx) => {
            const weekId = tab.dataset.week;
            // Week weight: 0.5 for first week, 1.0 for last week, linear taper
            const ww = totalWeeks > 1 ? 0.5 + (weekIdx / (totalWeeks - 1)) * 0.5 : 1.0;
            const entry = lbData[weekId]?.[username];
            const teams = entry?.teams;
            const consensus = weekConsensus[weekId];
            if (teams && teams.length > 0) {
                total += ballotDistance(teams, finalRanking) * ww;
                totalWW += ww;
                lastBallot = teams;
                consecMisses = 0;
                // Boldness adjustment: compare voter vs consensus against final overall
                if (consensus) {
                    let weekBoldAdj = 0, totalWeight = 0;
                    for (let i = 0; i < 25; i++) {
                        const team = finalRanking[i];
                        const finalRank = i + 1;
                        const vi = teams.indexOf(team), ci = consensus.indexOf(team);
                        const voterRank = vi === -1 ? 26 : vi + 1;
                        const consensusRank = ci === -1 ? 26 : ci + 1;
                        const deviation = Math.abs(voterRank - consensusRank);
                        if (deviation > 0) {
                            const scalar = 0.05; // flat boldness multiplier
                            const weight = deviation;
                            const consensusDist = Math.abs(consensusRank - finalRank);
                            const voterDist = Math.abs(voterRank - finalRank);
                            const gain = consensusDist - voterDist;
                            if (gain > 0) {
                                weekBoldAdj += gain * weight * scalar * posWeight(finalRank);
                                totalWeight += weight;
                            }
                        }
                    }
                    if (totalWeight > 0) {
                        boldAdj += (weekBoldAdj / totalWeight) * ww;
                    }
                }
            } else {
                const missDist = (lastBallot ? ballotDistance(lastBallot, finalRanking) : weekFieldAvg[weekId]);
                total += missDist * ww;
                totalWW += ww;
                missed++;
                consecMisses++;
            }
        });
        if (missed >= MAX_MISSES || consecMisses >= MAX_CONSEC_MISSES) {
            voterAvg[username] = { avg: Infinity, combined: Infinity };
            return;
        }
        const avg = totalWW > 0 ? total / totalWW : 0;
        // Miss penalty applied post-hoc: +1 per missed week on final combined score
        const combined = avg - boldAdj + missed * MISS_PENALTY;
        voterAvg[username] = { avg, boldAdj, combined };
    });
    return voterAvg;
}

function applyRankingSortToBlock(block, voterAvg, showLabels = false) {
    if (!block) return;
    const tbody = block.querySelectorAll(".ballot-section")[0]?.querySelector("tbody");
    if (!tbody || !tbody.querySelector(".voter-row")) return;

    const sortFn = (a, b) => {
        const ua = getVoterName(a);
        const ub = getVoterName(b);
        const sa = voterAvg[ua]?.combined ?? Infinity;
        const sb = voterAvg[ub]?.combined ?? Infinity;
        if (sa === Infinity && sb === Infinity) return ua.localeCompare(ub);
        return sa - sb;
    };
    const rows = Array.from(tbody.querySelectorAll(".voter-row"));
    rows.forEach((r, i) => {
        if (!r.dataset.origIdx) r.dataset.origIdx = i;
        const nameSpan = r.querySelector(".voter-name");
        if (nameSpan && showLabels) {
            nameSpan.querySelector(".rank-score-label")?.remove();
            const username = getVoterName(r);
            const scores = voterAvg[username];
            const label = document.createElement("span");
            label.className = "rank-score-label";
            if (!scores || scores.combined === Infinity) {
                label.textContent = "—";
            } else {
                const adj = scores.boldAdj || 0;
                label.textContent = scores.combined.toFixed(1);
                if (adj > 0.05) {
                    const adjSpan = document.createElement("span");
                    adjSpan.style.marginLeft = "2px";
                    adjSpan.style.color = "#2a9d2a";
                    adjSpan.textContent = `↑${adj.toFixed(1)}`;
                    label.appendChild(adjSpan);
                }
            }
            nameSpan.parentElement.appendChild(label);
        }
        r.classList.add("row-rank-sorted");
    });
    rows.sort(sortFn);
    rows.forEach(r => tbody.appendChild(r));
}

function restoreOriginalSortToBlock(block) {
    if (!block) return;
    const tbody = block.querySelectorAll(".ballot-section")[0]?.querySelector("tbody");
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll(".voter-row"));
    rows.forEach(r => {
        r.classList.remove("row-rank-sorted");
        r.querySelector(".rank-score-label")?.remove();
    });
    rows.sort((a, b) => parseInt(a.dataset.origIdx || 0) - parseInt(b.dataset.origIdx || 0));
    rows.forEach(r => tbody.appendChild(r));
}

function sortByRanking() {
    document.querySelectorAll(".consensus-dist").forEach(el => el.remove());
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const activeBlock = document.getElementById(activeTab.dataset.week);
    if (!activeBlock) return;

    if (rankingSortActive) {
        // Restore all week blocks
        document.querySelectorAll(".week-block").forEach(block => restoreOriginalSortToBlock(block));
        rankingSortActive = false;
        return;
    }

    const currentYear = activeTab.dataset.year;
    const yearTabs = getSortedTabs().filter(t => t.dataset.year === currentYear).reverse();
    const lbData = buildLeaderboardData();
    const voterAvg = computeVoterAvg(yearTabs, lbData);
    if (!voterAvg) return;

    // Apply sort+labels to all loaded week blocks, labels only show on visible week
    yearTabs.forEach(tab => {
        const block = document.getElementById(tab.dataset.week);
        applyRankingSortToBlock(block, voterAvg, block === activeBlock);
    });
    rankingSortActive = true;
}

document.getElementById("keybind-legend-modal").addEventListener("click", e => {
    if (e.target === document.getElementById("keybind-legend-modal"))
        document.getElementById("keybind-legend-modal").classList.remove("open");
});

document.getElementById("avg-rank-modal").addEventListener("click", e => {
    if (e.target === document.getElementById("avg-rank-modal"))
        document.getElementById("avg-rank-modal").classList.remove("open");
});

document.getElementById("season-stats-modal").addEventListener("click", e => {
    if (e.target === document.getElementById("season-stats-modal"))
        document.getElementById("season-stats-modal").classList.remove("open");
});

document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
        document.getElementById("voter-history-modal").classList.remove("open");
        document.getElementById("keybind-legend-modal").classList.remove("open");
        document.getElementById("avg-rank-modal").classList.remove("open");
        document.getElementById("season-stats-modal").classList.remove("open");
    }
    // Check for unlock combo: Shift+U then !
    if (e.shiftKey && (e.key === "!" || e.key === "Shift")) {
        if (e.key === "!" && lastKeyWasU) {
            e.preventDefault();
            sortTabsLocked = false;
            lastKeyWasU = false;
            // Update UI to remove locked class from tabs
            document.querySelectorAll(".sort-option[data-sort='ranking'], .sort-option[data-sort='tenure']").forEach(opt => {
                opt.classList.remove("locked");
            });
            return;
        }
    }
    if (!e.shiftKey) {
        lastKeyWasU = false;
        return;
    }
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;

    const currentWeekNum = parseInt(activeTab.dataset.weeknum);
    const currentYear = activeTab.dataset.year;

    if (e.key === "A" || e.key === "a") {
        e.preventDefault();
        applyTableSort("alphabetic");
        return;
    }

    if (e.key === "D" || e.key === "d") {
        e.preventDefault();
        showAggregateSection();
        return;
    }

    if (e.key === "E" || e.key === "e") {
        e.preventDefault();
        expandAllDeltas();
        return;
    }

    if (e.key === "J" || e.key === "j") {
        e.preventDefault();
        if (!sortTabsLocked) {
            applyTableSort("ranking");
        }
        return;
    }

    if (e.key === "C" || e.key === "c") {
        e.preventDefault();
        applyTableSort("consensus");
        return;
    }

    if (e.key === "R" || e.key === "r") {
        e.preventDefault();
        if (!sortTabsLocked) {
            applyTableSort("ranking");
        }
        return;
    }

    if (e.key === "T" || e.key === "t") {
        e.preventDefault();
        if (!sortTabsLocked) {
            applyTableSort("tenure");
        }
        return;
    }

    if (e.key === "Y" || e.key === "y") {
        e.preventDefault();
        const activeTab = document.querySelector(".week-tab.active");
        if (activeTab) showAvgRankModal(activeTab.dataset.week);
        return;
    }

    if (e.key === "U" || e.key === "u") {
        e.preventDefault();
        lastKeyWasU = true;
        // Reset flag after 1 second if no ! is pressed
        setTimeout(() => { lastKeyWasU = false; }, 1000);
        showSeasonStatsModal();
        return;
    }

    if (e.code >= "Digit1" && e.code <= "Digit9") {
        e.preventDefault();
        deltaWeeksBack = parseInt(e.code.replace("Digit", ""));
        // Re-apply deltas to all currently active delta rows
        const deltaData = buildDeltaData();
        const sortedTabs = getSortedTabs();
        document.querySelectorAll(".voter-row.row-delta").forEach(r => {
            r.querySelectorAll(".delta-label, .avg-label").forEach(el => el.remove());
            const wid = r.closest(".week-block")?.id;
            if (wid) applyDeltaToRow(r, wid, deltaData, sortedTabs);
        });
        return;
    }

    if (e.key === "P" || e.key === "p") {
        e.preventDefault();
        saveTableAsPng();
        return;
    }

    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const sortedAll = getSortedTabs().slice().reverse();
        const idx = sortedAll.findIndex(t => t.dataset.week === activeTab.dataset.week);
        const target = e.key === "ArrowRight"
            ? sortedAll[idx + 1]
            : sortedAll[idx - 1];
        if (target) {
            loadYear(target.dataset.year).then(() => {
                showWeek(target.dataset.week);
                if (weekPickerPinned) rebuildWeekPicker();
            }).catch(() => {});
        }
    }

    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        const tabs = getSortedTabs();
        const years = [...new Set(tabs.map(t => t.dataset.year))].sort();
        const yearIdx = years.indexOf(currentYear);
        const targetYear = e.key === "ArrowUp"
            ? years[yearIdx + 1]
            : years[yearIdx - 1];
        if (!targetYear) return;
        loadYear(targetYear).then(() => {
            const yearTabs = getSortedTabs().filter(t => t.dataset.year === targetYear);
            const sameWeek = yearTabs.find(t => parseInt(t.dataset.weeknum) === currentWeekNum);
            const target = sameWeek || yearTabs.sort((a, b) => parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum))[0];
            if (target) {
                showWeek(target.dataset.week);
                if (weekPickerPinned) rebuildWeekPicker();
            }
        }).catch(() => {});
    }

    if (e.key === "?") {
        e.preventDefault();
        document.getElementById("keybind-legend-modal").classList.toggle("open");
    }
});

// Update locked state UI
function updateLockedUI() {
    document.querySelectorAll(".sort-option[data-sort='ranking'], .sort-option[data-sort='tenure']").forEach(opt => {
        if (sortTabsLocked) {
            opt.classList.add("locked");
        } else {
            opt.classList.remove("locked");
        }
    });
}

// Init
updateLockedUI();
rebuildYearPicker();
rebuildWeekPicker();
const allTabs = getSortedTabs();
if (allTabs.length > 0) {
    const inlineYear = allTabs[0]?.dataset.year;
    if (inlineYear) _loadedYears.add(inlineYear);
    showWeek(allTabs[0].dataset.week);
    setTimeout(() => backgroundLoad(), 1000);
}
"""

WEEK_TABS_MARKER = "<!-- WEEK-TABS -->"
WEEK_DATA_MARKER = "<!-- WEEK-DATA -->"

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

def build_full_html(week_tabs_html, week_data_html, fragment_years=None):
    fragment_years_js = json.dumps(fragment_years or [])
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
<meta property="og:description" content="College basketball poll voter visualizer">
<meta property="og:image" content="https://les-champs.github.io/cbb-ballots/thumbnail.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<!-- Twitter/X card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Userpoll Landscape">
<meta name="twitter:description" content="College basketball poll voter visualizer">
<meta name="twitter:image" content="https://les-champs.github.io/cbb-ballots/thumbnail.png">
<style>
{CSS}
</style>
</head>
<body>

<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
<div class="header">
  <h1>
    <span id="toggle-text">Official Ballots</span>
    <span id="year-picker"></span><span id="year-text"></span>
    <span id="week-text"></span><span id="week-picker"></span>
  </h1>
</div>

<div class="week-tabs" style="display:none;">
{WEEK_TABS_MARKER}
{week_tabs_html}
</div>

<div id="voter-history-modal">
  <div id="voter-history-box">
    <h2 id="voter-history-title"></h2>
    <table id="voter-history-table"></table>
  </div>
</div>

<div id="keybind-legend-modal">
  <div id="keybind-legend-box">
    <h2>Keyboard Shortcuts</h2>
    <div class="keybind-section">
      <div class="keybind-section-title">Navigation</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>→</kbd> / <kbd>←</kbd></span><span>Next / Previous Week</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>↑</kbd> / <kbd>↓</kbd></span><span>Next / Previous Year</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>D</kbd></span><span>Jump to Data Ballots</span></div>
    </div>
    <div class="keybind-section">
      <div class="keybind-section-title">Views</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>E</kbd></span><span>Expand Deltas</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>1</kbd> – <kbd>9</kbd></span><span>Adjust Delta Lookback Window</span></div>
    </div>
    <div class="keybind-section">
      <div class="keybind-section-title">Sorting</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>A</kbd></span><span>Sort Alphabetically</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>C</kbd></span><span>Sort by Consensus</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>R</kbd></span><span>Sort by Précision</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>T</kbd></span><span>Sort by Tenure</span></div>
    </div>
    <div class="keybind-section">
      <div class="keybind-section-title">Other</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>Y</kbd></span><span>Week avg rank table</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>U</kbd></span><span>Season statistics</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>P</kbd></span><span>Save table as PNG</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>?</kbd></span><span>Show legend</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Esc</kbd></span><span>Close</span></div>
    </div>
  </div>
</div>

<div id="avg-rank-modal">
  <div id="avg-rank-box">
    <h2 id="avg-rank-title"></h2>
    <table id="avg-rank-table"></table>
  </div>
</div>

<div id="season-stats-modal">
  <div id="season-stats-box">
    <h2 id="season-stats-title"></h2>
    <table id="season-stats-table"></table>
  </div>
</div>

<div id="year-data-container">
{WEEK_DATA_MARKER}
{week_data_html}
</div>
<script>
const FRAGMENT_YEARS = {fragment_years_js};
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

def save_html(week, year, new_week_block, html_path):
    """Load existing HTML, append the new week, and save."""
    week_id = f"week-{year}-{week}"
    tabs_html, data_html, existing_ids = load_existing_weeks(html_path)

    if week_id in existing_ids:
        print(f"⚠️  Week {week} {year} already exists in HTML. Overwriting its block.")
        tabs_html = remove_week_tab(tabs_html, week_id)
        data_html = remove_week_block(data_html, week_id)

    # Add new tab
    new_tab = f'<button class="week-tab" data-week="{week_id}" data-weeknum="{week}" data-year="{year}">{year} #{week}</button>'
    tabs_html = (tabs_html + "\n" + new_tab).strip()

    # Append new week block
    data_html = (data_html + "\n" + new_week_block).strip()

    # Split by year: only embed the current year inline, write fragments for the rest
    current_year = get_current_year(tabs_html)
    data_by_year = split_data_by_year(data_html)
    inline_data = data_by_year.get(current_year, "")
    fragment_years = sorted([y for y in data_by_year if y != current_year])
    base_dir = os.path.dirname(html_path) or "."
    write_year_fragments(data_by_year, current_year, base_dir)

    full_html = build_full_html(tabs_html, inline_data, fragment_years)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(full_html)
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

    current_year = get_current_year(tabs_html)
    data_by_year = split_data_by_year(data_html)
    inline_data = data_by_year.get(current_year, "")
    fragment_years = sorted([y for y in data_by_year if y != current_year])
    base_dir = os.path.dirname(HTML_PATH) or "."
    write_year_fragments(data_by_year, current_year, base_dir)
    # Remove fragment file for year if it has no more data
    del_year_str = str(year)
    if del_year_str not in data_by_year or not data_by_year[del_year_str].strip():
        frag_path = os.path.join(base_dir, f"data-{del_year_str}.html")
        if os.path.exists(frag_path):
            os.remove(frag_path)

    full_html = build_full_html(tabs_html, inline_data, fragment_years)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"✓ Deleted week {week} {year} from HTML.")

def rebuild_html():
    """Rewrite index.html using existing tab/data content but updated CSS/JS/structure."""
    if not os.path.exists(HTML_PATH):
        print("No existing HTML found.")
        return

    tabs_html, data_html, week_ids = load_existing_weeks(HTML_PATH)
    if not week_ids:
        print("No existing weeks found in HTML. Nothing to rebuild.")
        return

    # Remove any stray lone } lines between week blocks (leftover from old JS bug)
    data_html = re.sub(r'\n\}\n(<div [^>]*id="week-)', r'\n\1', data_html)

    # Patch all old thead variants to current format
    data_html = re.sub(r'<thead>.*?</thead>', THEAD_HTML, data_html, flags=re.DOTALL)

    # Migrate old cell-logo-wrapper divs to bare td.logo-cell
    data_html = re.sub(
        r'<td><div class="cell-logo-wrapper">(.*?)</div></td>',
        r'<td class="logo-cell">\1</td>',
        data_html, flags=re.DOTALL
    )

    # Migrate old full data-src paths to shortened team-name-only form
    data_html = re.sub(
        r'data-src="cbb-logos/([^.]+)\.webp"',
        r'data-src="\1"',
        data_html
    )

    # Remove redundant src= attribute (same as data-src, set by JS on load)
    data_html = re.sub(r' src="cbb-logos/[^"]+\.webp"', '', data_html)

    # Remove alt= attributes from team logos (redundant with data-team)
    data_html = re.sub(r'(<img\b[^>]*\bdata-team="[^"]*"[^>]*?) alt="[^"]*"', r'\1', data_html)

    # Apply logo name corrections (fix wrong cbbpoll.net filenames to canonical local names)
    for wrong, right in LOGO_NAME_MAP.items():
        data_html = data_html.replace(f'data-src="{wrong}"', f'data-src="{right}"')
        data_html = data_html.replace(f'data-team="{wrong}"', f'data-team="{right}"')
        data_html = data_html.replace(f'alt="{wrong}"', f'alt="{right}"')

    # Remove inline styles from voter-cell divs
    data_html = re.sub(
        r'(<div class="voter-cell") style="[^"]*"',
        r'\1',
        data_html
    )

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
            teams = re.findall(r'data-team="([^"]+)"', row)
            if teams:
                official.append(("", "", None, [t + ".png" for t in teams]))
        if not official:
            return block_html

        agg_table = build_aggregate_table(official)
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

    # Split by year: embed only the current year, write fragments for the rest
    current_year = get_current_year(tabs_html)
    data_by_year = split_data_by_year(data_html)
    inline_data = data_by_year.get(current_year, "")
    fragment_years = sorted([y for y in data_by_year if y != current_year])
    base_dir = os.path.dirname(HTML_PATH) or "."
    write_year_fragments(data_by_year, current_year, base_dir)

    full_html = build_full_html(tabs_html, inline_data, fragment_years)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"✓ Rebuilt HTML with {len(week_ids)} weeks ({current_year} inline, {len(fragment_years)} year fragments).")

def main():
    parser = argparse.ArgumentParser(description="Scrape CBB Poll ballots and generate HTML.")
    parser.add_argument("--week", type=int, help="Poll week number (e.g. 18)")
    parser.add_argument("--year", type=int, help="Poll year (e.g. 2026)")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild HTML from existing data without scraping")
    parser.add_argument("--to-webp", action="store_true", help="Convert all existing PNG logos to WebP and exit")
    parser.add_argument("--delete", action="store_true", help="Delete a specific week from the HTML")
    parser.add_argument("--cbbpoll", action="store_true", help="Scrape from cbbpoll.com (legacy site)")
    parser.add_argument("--cbbpoll-build", action="store_true", help="Build HTML from cached cbbpoll.com data")
    args = parser.parse_args()

    if args.to_webp:
        convert_all_to_webp()
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

    if not args.week or not args.year:
        parser.error("--week and --year are required unless using --rebuild")

    week, year = args.week, args.year

    # Try homepage first (most up-to-date for current week), then seasons archive for past weeks
    candidate_urls = [
        f"{BASE_URL}/",
        f"{BASE_URL}/seasons/{year}/{week}",
    ]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html = None
    for poll_url in candidate_urls:
        try:
            print(f"Trying {poll_url}...")
            html = fetch_page_html(poll_url)
            # Verify the page contains voter data for this week
            # Homepage has ballot links; seasons archive has "Poll Voters" heading
            if f"/ballots/{week}/" in html or "Poll Voters" in html:
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
    print(f"Found {len(official_voters)} official and {len(provisional_voters)} provisional voters.\n")

    print("Fetching official ballots...")
    official_with_ballots = process_voters(official_voters, "Official", week=week, year=year, ballot_map=ballot_map)

    print("\nFetching provisional ballots...")
    provisional_with_ballots = process_voters(provisional_voters, "Provisional", week=week, year=year, ballot_map=ballot_map)

    week_block = build_week_block(week, year, official_with_ballots, provisional_with_ballots)
    save_html(week, year, week_block, HTML_PATH)
    print(f"\nDone! Week {week} {year}: {len(official_with_ballots)} official + {len(provisional_with_ballots)} provisional voters.")

if __name__ == "__main__":
    main()