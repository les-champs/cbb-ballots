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
# Available site years: 2021-2025 → our 2022-2026
AP25_SITE_YEARS = {2021: 2022, 2022: 2023, 2023: 2024, 2024: 2025, 2025: 2026}

# AP-specific name overrides (title attributes from collegepolltracker.com)
# Most names match cbbpoll overrides already; add AP-specific ones here.
AP25_NAME_OVERRIDES = {
    "McNeese State": "McNeese",
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

        # Teams from title attributes
        teams_raw = re.findall(r'title="([^"]+)"', part)
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
    week_slugs = ["pre-season"] + [f"week-{w}" for w in range(2, 20)] + ["final-rankings"]
    unmapped_names = set()

    for week_slug in week_slugs:
        # Map week slug to our week number
        if week_slug == "pre-season":
            week_num = 0
        elif week_slug == "final-rankings":
            week_num = 20
        else:
            week_num = int(week_slug.split("-")[1])
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
    for week_key in weeks:
        week = int(week_key)
        week_data = data["weeks"][week_key]
        voters = week_data.get("voters", [])
        if not voters:
            print(f"  Week {week}: no voter data, skipping")
            continue

        voter_tuples = []
        for v in voters:
            if not v["teams"]:
                continue
            ballot_logos = [_normalize_ap_team_name(t) + ".png" for t in v["teams"]]
            voter_tuples.append(("", v["username"], None, ballot_logos))
        voter_tuples.sort(key=lambda x: x[1].lower())

        week_label = "Pre-Season" if week == 0 else ("Final" if week == 20 else None)
        week_block = build_ap_week_block(week, our_year, voter_tuples)
        new_blocks.append(week_block)

        week_id = f"week-ap-{our_year}-{week}"
        label_attr = f' data-weeklabel="{week_label}"' if week_label else ""
        tab_text = f"{our_year} {week_label}" if week_label else f"{our_year} #{week}"
        new_tab = f'<button class="week-tab" data-week="{week_id}" data-weeknum="{week}" data-year="{our_year}" data-poll="ap"{label_attr}>{tab_text}</button>'
        new_tabs.append(new_tab)
        print(f"  ✓ Week {week}: {len(voter_tuples)} voters")

    # Write fragment file for this year (single write)
    base_dir = os.path.dirname(HTML_PATH) or "."
    frag_path = os.path.join(base_dir, f"data-ap-{our_year}.html")
    with open(frag_path, "w", encoding="utf-8") as f:
        f.write("\n".join(b.strip() for b in new_blocks))

    # Also write appage fragment file with clean IDs (no 'ap-' prefix) for ap-ballots.html
    appage_blocks = []
    for week_key in weeks:
        week = int(week_key)
        week_data = data["weeks"][week_key]
        voters = week_data.get("voters", [])
        if not voters:
            continue
        voter_tuples = []
        for v in voters:
            if not v["teams"]:
                continue
            ballot_logos = [_normalize_ap_team_name(t) + ".png" for t in v["teams"]]
            voter_tuples.append(("", v["username"], None, ballot_logos))
        voter_tuples.sort(key=lambda x: x[1].lower())
        appage_blocks.append(build_appage_week_block(week, our_year, voter_tuples))
    appage_frag_path = os.path.join(base_dir, f"data-appage-{our_year}.html")
    with open(appage_frag_path, "w", encoding="utf-8") as f:
        f.write("\n".join(b.strip() for b in appage_blocks))

    # Update index.html: read existing AP tabs, remove this year's tabs, add new ones
    _update_ap_tabs_for_year(HTML_PATH, our_year, new_tabs)

    # Regenerate ap-ballots.html
    rebuild_ap_html()

    print(f"\n✓ Built AP HTML for {our_year}.")

def build_ap_week_block(week, year, voters):
    """Build the full HTML block for one AP week."""
    week_id = f"week-ap-{year}-{week}"
    official_table = build_table_html(voters)

    # Build aggregate row labeled "AP Overall"
    points = {}
    for _, _, _, ballot_logos in voters:
        for i, logo in enumerate(ballot_logos[:25]):
            team = canonical_logo_name(logo)
            points[team] = points.get(team, 0) + (25 - i)
    ranked = sorted(points.items(), key=lambda x: -x[1])[:25]
    ballot_logo_cells = "".join(
        f'<td class="logo-cell"><img class="logo team-logo" data-team="{team}" data-src="{team}"></td>'
        for team, _ in ranked
    )
    agg_voter_cell = '<div class="voter-cell" ><span class="voter-name">AP Overall</span></div>'
    agg_row = f'<tr class="voter-row"><td>{agg_voter_cell}</td>{ballot_logo_cells}</tr>\n'
    aggregate_table = build_table(agg_row)

    return f"""
<div id="{week_id}" class="week-block" data-poll="ap" style="display:none;">
  <div id="{week_id}-official" class="ballot-section">
    <div class="table-scroll"><div class="table-container">{official_table}</div></div>
  </div>
  <div id="{week_id}-provisional" class="ballot-section" style="display:none;">
    <div class="table-scroll"><div class="table-container">{build_table("")}</div></div>
  </div>
  <div id="{week_id}-aggregate" class="ballot-section" style="display:none;">
    <div class="table-scroll"><div class="table-container">{aggregate_table}</div></div>
  </div>
</div><!-- /week-block:{week_id} -->"""

def build_appage_week_block(week, year, voters):
    """Build an AP week block with clean IDs (no 'ap-' prefix, no data-poll) for ap-ballots.html."""
    week_id = f"week-{year}-{week}"
    official_table = build_table_html(voters)

    # Build aggregate row labeled "AP Overall"
    points = {}
    for _, _, _, ballot_logos in voters:
        for i, logo in enumerate(ballot_logos[:25]):
            team = canonical_logo_name(logo)
            points[team] = points.get(team, 0) + (25 - i)
    ranked = sorted(points.items(), key=lambda x: -x[1])[:25]
    ballot_logo_cells = "".join(
        f'<td class="logo-cell"><img class="logo team-logo" data-team="{team}" data-src="{team}"></td>'
        for team, _ in ranked
    )
    agg_voter_cell = '<div class="voter-cell" ><span class="voter-name">AP Overall</span></div>'
    agg_row = f'<tr class="voter-row"><td>{agg_voter_cell}</td>{ballot_logo_cells}</tr>\n'
    aggregate_table = build_table(agg_row)

    return f"""
<div id="{week_id}" class="week-block" style="display:none;">
  <div id="{week_id}-official" class="ballot-section">
    <div class="table-scroll"><div class="table-container">{official_table}</div></div>
  </div>
  <div id="{week_id}-provisional" class="ballot-section" style="display:none;">
    <div class="table-scroll"><div class="table-container">{build_table("")}</div></div>
  </div>
  <div id="{week_id}-aggregate" class="ballot-section" style="display:none;">
    <div class="table-scroll"><div class="table-container">{aggregate_table}</div></div>
  </div>
</div><!-- /week-block:{week_id} -->"""

def _update_ap_tabs_for_year(html_path, year, new_tabs):
    """Update AP tabs in index.html: remove this year's old tabs, add new ones, update AP_FRAGMENT_YEARS."""
    if not os.path.exists(html_path):
        return
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract existing AP tabs
    tabs_match = re.search(r'<!-- AP-TABS -->\n(.*?)(?=\n<!-- /AP-TABS -->)', content, re.DOTALL)
    existing_tabs = tabs_match.group(1).strip() if tabs_match else ""

    # Remove tabs for this year
    year_str = str(year)
    kept_lines = [line for line in existing_tabs.split("\n")
                  if line.strip() and f'data-year="{year_str}" data-poll="ap"' not in line]
    # Add new tabs
    all_tabs = kept_lines + new_tabs
    ap_tabs_html = "\n".join(all_tabs).strip()

    # Discover AP fragment years from filesystem
    base_dir = os.path.dirname(html_path) or "."
    ap_fragment_years = sorted([
        re.match(r'data-ap-(\d+)\.html$', f).group(1)
        for f in os.listdir(base_dir)
        if re.match(r'data-ap-\d+\.html$', f)
    ])

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
    f"<th><span class='voters-toggle' style='cursor:pointer; display:inline-block; transition:transform 0.1s ease;'>Functions</span>"
    f"<span class='sort-picker'>"
    f"<span class='picker-category'>Sort</span>"
    f"<span class='sort-option active' data-sort='alphabetic'>Alphabetic</span>"
    f"<span class='sort-option' data-sort='zetabetique' style='display:none'>Zétabétique</span>"
    f"<span class='sort-option' data-sort='consensus'>Consensus</span>"
    f"<span class='picker-category'>Tables</span>"
    f"<span class='sort-option' data-action='weeklyStats'>Week</span>"
    f"<span class='sort-option' data-action='yearlyStats'>Year</span>"
    f"<span class='picker-category'>Graphs</span>"
    f"<span class='sort-option' data-action='dotPlot'>Spread</span>"
    f"<span class='sort-option' data-action='heatmap'>Heatmap</span>"
    f"<span class='picker-category'>Actions</span>"
    f"<span class='sort-option' data-action='expandDeltas'>Deltas</span>"
    f"<span class='sort-option dark-mode-toggle' data-action='darkMode'>Dark Mode</span>"
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
        return f.read()

WEEK_TABS_MARKER = "<!-- WEEK-TABS -->"
WEEK_DATA_MARKER = "<!-- WEEK-DATA -->"

def get_ap_info(html_path):
    """Return (ap_tabs_html, ap_fragment_years) from existing index.html + fragment files."""
    ap_tabs_html = ""
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        tabs_match = re.search(r'<!-- AP-TABS -->\n(.*?)(?=\n<!-- /AP-TABS -->)', content, re.DOTALL)
        ap_tabs_html = tabs_match.group(1).strip() if tabs_match else ""
    base_dir = os.path.dirname(html_path) or "."
    ap_fragment_years = sorted([
        re.match(r'data-ap-(\d+)\.html$', f).group(1)
        for f in os.listdir(base_dir)
        if re.match(r'data-ap-\d+\.html$', f)
    ])
    return ap_tabs_html, ap_fragment_years

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

def compute_tenure_counts(data_html):
    """Count total ballots per voter across all week/year data (all loaded HTML).
    Adds 36 to voters present in both 2022 and 2025 to account for missing 2023/2024 seasons."""
    SKIP_NAMES = {"Official Overall", "5-Week Weighted"}
    name_re = re.compile(r'<span class="voter-name"[^>]*>([^<]+)<')
    counts = {}
    for m in name_re.finditer(data_html):
        username = m.group(1).strip()
        if username in SKIP_NAMES:
            continue
        counts[username] = counts.get(username, 0) + 1

    # Voters active in both 2022 and 2025 likely also voted in missing 2023/2024 seasons
    by_year = split_data_by_year(data_html)
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

def build_full_html(week_tabs_html, week_data_html, fragment_years=None, tenure_counts=None, ap_tabs_html="", ap_fragment_years=None, ap_tenure_counts=None):
    CSS = load_css()
    JS = load_js()
    fragment_years_js = json.dumps(fragment_years or [])
    tenure_counts_js = json.dumps(tenure_counts or {})
    ap_tenure_counts_js = json.dumps(ap_tenure_counts or {})
    ap_fragment_years_js = json.dumps(ap_fragment_years or [])
    dark_logo_teams_js = "new Set(" + json.dumps(get_dark_logo_teams()) + ")"
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
    <h2>Keyboard Shortcuts</h2>
    <div class="keybind-section">
      <div class="keybind-section-title">Navigation</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>→</kbd> / <kbd>←</kbd></span><span>Next / Previous Week</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>↑</kbd> / <kbd>↓</kbd></span><span>Next / Previous Year</span></div>
<div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>D</kbd></span><span>Jump to Data Ballots</span></div>
    </div>
    <div class="keybind-section">
      <div class="keybind-section-title">Views</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>E</kbd></span><span>Expand / Collapse All Deltas</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>J</kbd></span><span>Toggle Delta Sub-label (Consensus Diff / Recency)</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>1</kbd> – <kbd>9</kbd></span><span>Adjust Delta Lookback Window</span></div>
    </div>
    <div class="keybind-section">
      <div class="keybind-section-title">Sorting</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>A</kbd></span><span>Sort Alphabetically</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>C</kbd></span><span>Sort by Consensus</span></div>
    </div>
    <div class="keybind-section">
      <div class="keybind-section-title">Other</div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>R</kbd></span><span>Précision leaderboard</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>T</kbd></span><span>Tenure leaderboard</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>Y</kbd></span><span>Week avg rank table</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>G</kbd></span><span>Week rank spread chart</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>U</kbd></span><span>Season statistics</span></div>
      <div class="keybind-row"><span class="keybind-keys"><kbd>Shift</kbd><kbd>H</kbd></span><span>Season rank heatmap</span></div>
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

def save_html(week, year, new_week_block, html_path, week_label=None):
    """Load existing HTML, append the new week, and save."""
    week_id = f"week-{year}-{week}"
    tabs_html, data_html, existing_ids = load_existing_weeks(html_path)

    if week_id in existing_ids:
        print(f"⚠️  Week {week} {year} already exists in HTML. Overwriting its block.")
        tabs_html = remove_week_tab(tabs_html, week_id)
        data_html = remove_week_block(data_html, week_id)

    # Add new tab
    label_attr = f' data-weeklabel="{week_label}"' if week_label else ""
    tab_text = f"{year} {week_label}" if week_label else f"{year} #{week}"
    new_tab = f'<button class="week-tab" data-week="{week_id}" data-weeknum="{week}" data-year="{year}"{label_attr}>{tab_text}</button>'
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
    tenure_counts = compute_tenure_counts(data_html)

    ap_tabs_html, ap_fragment_years = get_ap_info(html_path)
    ap_tenure_counts = compute_ap_tenure_counts()
    full_html = build_full_html(tabs_html, inline_data, fragment_years, tenure_counts, ap_tabs_html, ap_fragment_years, ap_tenure_counts)
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
    tenure_counts = compute_tenure_counts(data_html)

    ap_tabs_html, ap_fragment_years = get_ap_info(HTML_PATH)
    ap_tenure_counts = compute_ap_tenure_counts()
    full_html = build_full_html(tabs_html, inline_data, fragment_years, tenure_counts, ap_tabs_html, ap_fragment_years, ap_tenure_counts)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(full_html)
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
    full_html = full_html.replace("<title>Userpoll Landscape</title>", "<title>AP Ballots Landscape</title>")
    full_html = full_html.replace('content="Userpoll Landscape"', 'content="AP Ballots Landscape"')
    full_html = full_html.replace(
        'content="Landscape view of r/collegebasketball userpoll ballots."',
        'content="Landscape view of AP Top 25 individual voter ballots."'
    )
    # Set toggle-text to "AP Ballots" (click will be a no-op; exitApBallots returns early when _apCurrentYear is null)
    full_html = full_html.replace(
        '<span id="toggle-text">Official Ballots</span>',
        '<span id="toggle-text" style="cursor:default;">AP Ballots</span>'
    )
    # Replace the userpoll forward link with a back link to index.html
    full_html = full_html.replace(
        '<a href="ap-ballots.html" class="ap-forward-link">AP Ballots →</a>',
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

    # Discover available appage years from fragment files
    appage_years = sorted([
        re.match(r'data-appage-(\d+)\.html$', fname).group(1)
        for fname in os.listdir(base_dir)
        if re.match(r'data-appage-\d+\.html$', fname)
    ])
    if not appage_years:
        print("No data-appage-YEAR.html files found; skipping ap-ballots.html rebuild.")
        return

    current_year = max(appage_years)
    fragment_years = [y for y in appage_years if y != current_year]

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
            voters = week_data.get("voters", [])
            if not voters:
                continue
            voter_tuples = []
            for v in voters:
                if not v["teams"]:
                    continue
                ballot_logos = [_normalize_ap_team_name(t) + ".png" for t in v["teams"]]
                voter_tuples.append(("", v["username"], None, ballot_logos))
            voter_tuples.sort(key=lambda x: x[1].lower())
            block = build_appage_week_block(week, current_year, voter_tuples)
            inline_data = (inline_data + "\n" + block).strip()
            week_label = "Pre-Season" if week == 0 else ("Final" if week == 20 else None)
            label_attr = f' data-weeklabel="{week_label}"' if week_label else ""
            tab_text = f"{current_year} {week_label}" if week_label else f"{current_year} #{week}"
            week_id = f"week-{current_year}-{week}"
            tabs_html_lines.append(
                f'<button class="week-tab" data-week="{week_id}" data-weeknum="{week}"'
                f' data-year="{current_year}"{label_attr}>{tab_text}</button>'
            )

    # Patch all data-appage-YEAR.html fragment files to current THEAD_HTML
    for year in appage_years:
        if year == current_year:
            continue
        frag_path = os.path.join(base_dir, f"data-appage-{year}.html")
        if not os.path.exists(frag_path):
            continue
        with open(frag_path, "r", encoding="utf-8") as f:
            frag_content = f.read()
        patched = re.sub(r'<thead>.*?</thead>', THEAD_HTML, frag_content, flags=re.DOTALL)
        if patched != frag_content:
            with open(frag_path, "w", encoding="utf-8") as f:
                f.write(patched)
            print(f"  ✓ Patched thead in data-appage-{year}.html")

    # Build tabs for prior fragment years by reading their week IDs from the fragment files
    for year in sorted(appage_years):
        if year == current_year:
            continue
        frag_path = os.path.join(base_dir, f"data-appage-{year}.html")
        if not os.path.exists(frag_path):
            continue
        with open(frag_path, "r", encoding="utf-8") as f:
            frag = f.read()
        for wid_match in re.finditer(r'<div id="(week-(\d+)-(\d+))"', frag):
            wid, yr, wn_str = wid_match.group(1), wid_match.group(2), wid_match.group(3)
            wn = int(wn_str)
            week_label = "Pre-Season" if wn == 0 else ("Final" if wn == 20 else None)
            label_attr = f' data-weeklabel="{week_label}"' if week_label else ""
            tab_text = f"{yr} {week_label}" if week_label else f"{yr} #{wn}"
            tabs_html_lines.append(
                f'<button class="week-tab" data-week="{wid}" data-weeknum="{wn}"'
                f' data-year="{yr}"{label_attr}>{tab_text}</button>'
            )

    tabs_html = "\n".join(tabs_html_lines)
    ap_tenure_counts = compute_ap_tenure_counts()
    full_html = build_ap_html(tabs_html, inline_data, fragment_years, ap_tenure_counts)
    with open(AP_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"✓ Rebuilt ap-ballots.html ({current_year} inline, {len(fragment_years)} year fragments).")


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
    tenure_counts = compute_tenure_counts(data_html)

    # Patch data-ap-YEAR.html fragment files to current THEAD_HTML
    for fname in os.listdir(base_dir):
        if re.match(r'data-ap-\d+\.html$', fname):
            frag_path = os.path.join(base_dir, fname)
            with open(frag_path, "r", encoding="utf-8") as f:
                frag_content = f.read()
            patched = re.sub(r'<thead>.*?</thead>', THEAD_HTML, frag_content, flags=re.DOTALL)
            if patched != frag_content:
                with open(frag_path, "w", encoding="utf-8") as f:
                    f.write(patched)
                print(f"  ✓ Patched thead in {fname}")

    ap_tabs_html, ap_fragment_years = get_ap_info(HTML_PATH)
    ap_tenure_counts = compute_ap_tenure_counts()
    full_html = build_full_html(tabs_html, inline_data, fragment_years, tenure_counts, ap_tabs_html, ap_fragment_years, ap_tenure_counts)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"✓ Rebuilt HTML with {len(week_ids)} weeks ({current_year} inline, {len(fragment_years)} year fragments).")
    rebuild_ap_html()

def parse_voter_tuples_from_section_html(section_html):
    """
    Parse voter tuples from an HTML official/provisional section for aggregate recomputation.
    Returns list of (flair, username, ballot_url, teams) tuples.
    Skips synthetic rows (Official Overall, 5-Week Weighted).
    """
    SKIP_NAMES = {"Official Overall", "5-Week Weighted"}
    tuples = []
    row_re      = re.compile(r'<tr class="voter-row">.*?</tr>', re.DOTALL)
    name_re     = re.compile(r'voter-name[^>]*>([^<]+)<')
    ballot_re   = re.compile(r'data-ballot-url="([^"]+)"')
    flair_re    = re.compile(r'<img class="logo" data-team="([^"]+)"')
    team_re     = re.compile(r'<td[^>]*><img[^>]*data-team="([^"]+)"')
    for row_m in row_re.finditer(section_html):
        row_html = row_m.group(0)
        name_m = name_re.search(row_html)
        if not name_m:
            continue
        username = name_m.group(1).strip()
        if username in SKIP_NAMES:
            continue
        flair_m    = flair_re.search(row_html)
        ballot_m   = ballot_re.search(row_html)
        flair      = flair_m.group(1) if flair_m else "Unknown"
        ballot_url = ballot_m.group(1) if ballot_m else None
        teams      = team_re.findall(row_html)
        tuples.append((flair, username, ballot_url, teams))
    return tuples


def apply_recovery(year=2024):
    """
    Apply recovered ballot data from cbbpoll-YEAR-recovery.json into data-YEAR.html.

    For each week that has recovered voters, inserts their rows into the official section
    and recomputes the aggregate row to include them.
    """
    recovery_path = os.path.join(BASE_HTML_DIR, f"cbbpoll-{year}-recovery.json")
    if not os.path.exists(recovery_path):
        print(f"ERROR: {recovery_path} not found. Run recover_{year}.py --recover first.")
        return

    with open(recovery_path) as f:
        recovery_data = json.load(f)

    # Build flair map from the next year's fragment (voters' flair is stable year-to-year)
    flair_map = {}
    for ref_year in [year + 1, year + 2, year - 1]:
        ref_path = os.path.join(BASE_HTML_DIR, f"data-{ref_year}.html")
        if not os.path.exists(ref_path):
            continue
        with open(ref_path) as f:
            ref_html = f.read()
        voter_re = re.compile(
            r'class="voter-cell"[^>]*data-ballot-url="[^"]*">.*?'
            r'<img class="logo" data-team="([^"]+)".*?voter-name[^>]*>([^<]+)<',
            re.DOTALL
        )
        for m in voter_re.finditer(ref_html):
            flair_map[m.group(2).strip()] = m.group(1)
        if flair_map:
            print(f"  Flair map built from data-{ref_year}.html ({len(flair_map)} voters)")
            break

    # Group recovery data by week, keeping only entries with ballot content
    by_week = {}
    for key, val in recovery_data.items():
        if not val.get("teams"):
            continue
        week_str, username = key.split(":", 1)
        week = int(week_str)
        by_week.setdefault(week, {})[username] = val

    if not by_week:
        print("No recovered ballot content found in recovery JSON.")
        return

    # Determine target HTML file
    fragment_path = os.path.join(BASE_HTML_DIR, f"data-{year}.html")
    if not os.path.exists(fragment_path):
        print(f"ERROR: {fragment_path} not found.")
        return

    with open(fragment_path, encoding="utf-8") as f:
        html = f.read()

    print(f"Applying recovery to {fragment_path}")
    print(f"Weeks with recovered data: {sorted(by_week.keys())}\n")

    for week in sorted(by_week.keys()):
        voters = by_week[week]
        print(f"Week {week}: adding {len(voters)} recovered voters")

        # Build voter tuples sorted alphabetically (matching existing sort order)
        recovered_tuples = sorted(
            [
                (flair_map.get(u, "Unknown"), u, v["ballot_url"], v["teams"])
                for u, v in voters.items()
            ],
            key=lambda x: x[1].lower(),
        )

        new_rows = build_table_rows(recovered_tuples)

        # --- Locate the official section and append rows before </tbody> ---
        off_id    = f'id="week-{year}-{week}-official"'
        pro_id    = f'id="week-{year}-{week}-provisional"'
        agg_id    = f'id="week-{year}-{week}-aggregate"'

        off_start = html.find(off_id)
        if off_start == -1:
            print(f"  WARNING: official section not found for week {week}, skipping")
            continue

        # Official block ends at provisional (or aggregate if no provisional)
        off_end = html.find(pro_id, off_start)
        if off_end == -1:
            off_end = html.find(agg_id, off_start)

        official_block = html[off_start:off_end]
        tbody_end_rel  = official_block.rfind("</tbody>")
        if tbody_end_rel == -1:
            print(f"  WARNING: </tbody> not found in official section for week {week}, skipping")
            continue

        insert_pos = off_start + tbody_end_rel
        html = html[:insert_pos] + new_rows + html[insert_pos:]
        print(f"  ✓ Inserted {len(recovered_tuples)} rows into official section")

        # --- Recompute aggregate row using all official voters (old + new) ---
        # Re-locate official block after insertion
        off_start2 = html.find(off_id)
        off_end2   = html.find(pro_id, off_start2)
        if off_end2 == -1:
            off_end2 = html.find(agg_id, off_start2)
        official_block2 = html[off_start2:off_end2]

        all_official = parse_voter_tuples_from_section_html(official_block2)
        new_agg_row  = build_aggregate_row(all_official)

        # Replace the aggregate tbody
        agg_start      = html.find(agg_id, off_end2)
        agg_tbody_s    = html.find("<tbody>", agg_start)
        agg_tbody_e    = html.find("</tbody>", agg_tbody_s) + len("</tbody>")
        html = html[:agg_tbody_s] + f"<tbody>{new_agg_row}</tbody>" + html[agg_tbody_e:]
        print(f"  ✓ Aggregate row recomputed ({len(all_official)} official voters total)")

    with open(fragment_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDone! Updated {fragment_path}")
    print("Run: python3 userpoll.py --rebuild  to regenerate index.html")


def fix_season_contamination(year):
    """
    Remove voter rows from data-YEAR.html that contain ballot IDs from a different season.

    When a season is scraped and some voters' ballot links are missing from the poll page,
    the scraper's profile-page fallback may retrieve a ballot ID from a prior season
    (same week number, earlier ObjectID timestamp). This function identifies and removes
    those contaminated rows, then recomputes the affected aggregate rows.

    Contamination detection: ballot IDs whose first 3 hex chars (ObjectID timestamp prefix)
    fall outside the expected season window.

    Season ObjectID prefix ranges (approximate):
      2024 season (2023-24): 655–65f  (Nov 2023 – Mar 2024)
      2025 season (2024-25): 672–67f  (Nov 2024 – Mar 2025)
      2026 season (2025-26): 690–69e  (Nov 2025 – Mar 2026)
    """
    SEASON_PREFIXES = {
        2024: set(f"{x:03x}" for x in range(0x654, 0x660)),
        2025: set(f"{x:03x}" for x in range(0x672, 0x680)),
        2026: set(f"{x:03x}" for x in range(0x690, 0x6a0)),
    }
    expected = SEASON_PREFIXES.get(year)
    if not expected:
        print(f"ERROR: No known season prefix range for year {year}.")
        return

    fragment_path = os.path.join(BASE_HTML_DIR, f"data-{year}.html")
    if not os.path.exists(fragment_path):
        print(f"ERROR: {fragment_path} not found.")
        return

    with open(fragment_path, encoding="utf-8") as f:
        html = f.read()

    # Find all voter rows with a ballot URL whose ObjectID prefix is outside the expected range
    row_re     = re.compile(r'<tr class="voter-row">.*?</tr>', re.DOTALL)
    ballot_re  = re.compile(r'data-ballot-url="https://www\.cbbpoll\.net/ballots/\d+/([a-f0-9]{24})"')
    name_re    = re.compile(r'voter-name[^>]*>([^<]+)<')

    contaminated_rows = []
    for m in row_re.finditer(html):
        row_html  = m.group(0)
        ballot_m  = ballot_re.search(row_html)
        if not ballot_m:
            continue
        bid = ballot_m.group(1)
        if bid[:3].lower() not in expected:
            name_m = name_re.search(row_html)
            username = name_m.group(1).strip() if name_m else "?"
            contaminated_rows.append((m.group(0), username, bid))

    if not contaminated_rows:
        print(f"No contaminated rows found in data-{year}.html.")
        return

    print(f"Found {len(contaminated_rows)} contaminated voter rows in data-{year}.html")
    by_voter = {}
    for _, username, bid in contaminated_rows:
        by_voter.setdefault(username, []).append(bid[:6])
    for u, prefixes in sorted(by_voter.items()):
        print(f"  {u}: {len(prefixes)} rows (prefix examples: {prefixes[:3]})")

    # Remove contaminated rows from HTML
    for row_html, _, _ in contaminated_rows:
        html = html.replace(row_html, "", 1)

    print(f"\nRemoved {len(contaminated_rows)} contaminated rows.")

    # Recompute aggregate rows for ALL weeks (contaminated rows may affect any week)
    week_re = re.compile(rf'id="week-{year}-(\d+)-official"')
    weeks_to_fix = sorted(set(int(m.group(1)) for m in week_re.finditer(html)))
    print(f"Recomputing aggregates for {len(weeks_to_fix)} weeks...")

    for week in weeks_to_fix:
        off_id = f'id="week-{year}-{week}-official"'
        pro_id = f'id="week-{year}-{week}-provisional"'
        agg_id = f'id="week-{year}-{week}-aggregate"'

        off_start = html.find(off_id)
        if off_start == -1:
            continue
        off_end = html.find(pro_id, off_start)
        if off_end == -1:
            off_end = html.find(agg_id, off_start)

        official_block = html[off_start:off_end]
        all_official   = parse_voter_tuples_from_section_html(official_block)
        new_agg_row    = build_aggregate_row(all_official)

        agg_start   = html.find(agg_id, off_end)
        agg_tbody_s = html.find("<tbody>", agg_start)
        agg_tbody_e = html.find("</tbody>", agg_tbody_s) + len("</tbody>")
        html = html[:agg_tbody_s] + f"<tbody>{new_agg_row}</tbody>" + html[agg_tbody_e:]

    with open(fragment_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDone! Updated {fragment_path}")
    print("Run: python3 userpoll.py --rebuild  to regenerate index.html")


def remove_overwritten_ballots(year, reference_year):
    """
    Remove rows from data-YEAR.html whose ballot IDs also appear in data-REFERENCE_YEAR.html.

    cbbpoll.net reuses ballot IDs across seasons: when a voter submits a ballot for the
    same week in a new season, the old ballot ID record is overwritten with new content.
    If recovery added rows using those now-overwritten ballot IDs, the rows in data-YEAR.html
    will contain content from the newer season. This function detects and removes them.

    Example: data-2024.html has ballot IDs that also appear in data-2025.html. Those IDs
    were fetched during recovery but already had 2024-25 content → remove from 2024.
    """
    target_path = os.path.join(BASE_HTML_DIR, f"data-{year}.html")
    ref_path    = os.path.join(BASE_HTML_DIR, f"data-{reference_year}.html")

    for p in (target_path, ref_path):
        if not os.path.exists(p):
            print(f"ERROR: {p} not found.")
            return

    with open(target_path, encoding="utf-8") as f:
        html = f.read()
    with open(ref_path, encoding="utf-8") as f:
        ref_html = f.read()

    ref_ids = set(re.findall(r'data-ballot-url="[^"]*ballots/\d+/([a-f0-9]{24})"', ref_html))
    print(f"Reference ballot IDs loaded from data-{reference_year}.html: {len(ref_ids)}")

    row_re    = re.compile(r'<tr class="voter-row">.*?</tr>', re.DOTALL)
    ballot_re = re.compile(r'data-ballot-url="[^"]*ballots/\d+/([a-f0-9]{24})"')
    name_re   = re.compile(r'voter-name[^>]*>([^<]+)<')

    to_remove = []
    for m in row_re.finditer(html):
        row_html = m.group(0)
        bid_m    = ballot_re.search(row_html)
        if not bid_m:
            continue
        if bid_m.group(1) in ref_ids:
            name_m   = name_re.search(row_html)
            username = name_m.group(1).strip() if name_m else "?"
            to_remove.append((m.group(0), username, bid_m.group(1)))

    if not to_remove:
        print(f"No overwritten ballot rows found in data-{year}.html.")
        return

    print(f"Found {len(to_remove)} rows in data-{year}.html with ballot IDs also in data-{reference_year}.html")
    by_voter = {}
    for _, username, bid in to_remove:
        by_voter.setdefault(username, []).append(bid[:8])
    for u, bids in sorted(by_voter.items()):
        print(f"  {u}: {len(bids)} rows")

    for row_html, _, _ in to_remove:
        html = html.replace(row_html, "", 1)
    print(f"\nRemoved {len(to_remove)} rows.")

    week_re = re.compile(rf'id="week-{year}-(\d+)-official"')
    weeks_to_fix = sorted(set(int(m.group(1)) for m in week_re.finditer(html)))
    print(f"Recomputing aggregates for {len(weeks_to_fix)} weeks...")

    for week in weeks_to_fix:
        off_id = f'id="week-{year}-{week}-official"'
        pro_id = f'id="week-{year}-{week}-provisional"'
        agg_id = f'id="week-{year}-{week}-aggregate"'

        off_start = html.find(off_id)
        if off_start == -1:
            continue
        off_end = html.find(pro_id, off_start)
        if off_end == -1:
            off_end = html.find(agg_id, off_start)

        official_block = html[off_start:off_end]
        all_official   = parse_voter_tuples_from_section_html(official_block)
        new_agg_row    = build_aggregate_row(all_official)

        agg_start   = html.find(agg_id, off_end)
        agg_tbody_s = html.find("<tbody>", agg_start)
        agg_tbody_e = html.find("</tbody>", agg_tbody_s) + len("</tbody>")
        html = html[:agg_tbody_s] + f"<tbody>{new_agg_row}</tbody>" + html[agg_tbody_e:]

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDone! Updated {target_path}")
    print("Run: python3 userpoll.py --rebuild  to regenerate index.html")


def main():
    parser = argparse.ArgumentParser(description="Scrape CBB Poll ballots and generate HTML.")
    parser.add_argument("--week", type=str, help="Poll week slug to fetch from cbbpoll.net (e.g. 18 or Pre-Season)")
    parser.add_argument("--store-week", type=int, dest="store_week",
                        help="Override the week number used for HTML storage/label (e.g. 0 for pre-season)")
    parser.add_argument("--label", type=str, help="Custom display label for the week tab (e.g. 'Pre-Season')")
    parser.add_argument("--year", type=int, help="Poll year (e.g. 2026)")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild HTML from existing data without scraping")
    parser.add_argument("--to-webp", action="store_true", help="Convert all existing PNG logos to WebP and exit")
    parser.add_argument("--dark-logos", action="store_true", help="Download ESPN dark-mode logos for all teams")
    parser.add_argument("--delete", action="store_true", help="Delete a specific week from the HTML")
    parser.add_argument("--apply-recovery", action="store_true", help="Apply recovered ballot data from cbbpoll-YEAR-recovery.json")
    parser.add_argument("--fix-contamination", action="store_true", help="Remove wrong-season ballot rows from data-YEAR.html")
    parser.add_argument("--remove-overwritten", type=int, metavar="REF_YEAR",
                        help="Remove rows from data-YEAR.html whose ballot IDs appear in data-REF_YEAR.html (detects reused/overwritten ballot IDs)")
    parser.add_argument("--cbbpoll", action="store_true", help="Scrape from cbbpoll.com (legacy site)")
    parser.add_argument("--cbbpoll-build", action="store_true", help="Build HTML from cached cbbpoll.com data")
    parser.add_argument("--ap25", action="store_true", help="Scrape AP 25 data from collegepolltracker.com")
    parser.add_argument("--ap25-build", action="store_true", help="Build HTML from cached AP 25 data")
    args = parser.parse_args()

    if args.to_webp:
        convert_all_to_webp()
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

    if args.apply_recovery:
        if not args.year:
            parser.error("--year is required with --apply-recovery (e.g. --year 2024)")
        apply_recovery(args.year)
        return

    if args.fix_contamination:
        if not args.year:
            parser.error("--year is required with --fix-contamination (e.g. --year 2025)")
        fix_season_contamination(args.year)
        return

    if args.remove_overwritten:
        if not args.year:
            parser.error("--year is required with --remove-overwritten (e.g. --year 2024 --remove-overwritten 2025)")
        remove_overwritten_ballots(args.year, args.remove_overwritten)
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

    # For pre-season (week 0): reclassify voters based on their status in weeks 2/3
    if store_week == 0:
        official_panel = get_official_voters_from_html(year, [2, 3], HTML_PATH)
        if official_panel:
            all_voters = official_with_ballots + provisional_with_ballots
            official_with_ballots = [v for v in all_voters if v[1] in official_panel]
            provisional_with_ballots = [v for v in all_voters if v[1] not in official_panel]
            print(f"\nReclassified week 0 using weeks 2/3 panel: {len(official_with_ballots)} official + {len(provisional_with_ballots)} provisional")
        else:
            print("\nNo weeks 2/3 data found — keeping pre-season voters as provisional")

    week_block = build_week_block(store_week, year, official_with_ballots, provisional_with_ballots)
    save_html(store_week, year, week_block, HTML_PATH, week_label=args.label)
    week_display = args.label or f"Week {store_week}"
    print(f"\nDone! {week_display} {year}: {len(official_with_ballots)} official + {len(provisional_with_ballots)} provisional voters.")

if __name__ == "__main__":
    main()
