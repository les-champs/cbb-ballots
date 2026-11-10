"""Season-dependent conference and tier (Power / Mid-Major) mapping, 2025 onward.

Seasons use the project's convention: 2025 = the 2024-25 season (season_start is
July 1 of year-1). Keys are the logo names used in the data (data-src="Duke");
schools with no logo file yet use the same PascalCase style.

Power = ACC, Big Ten, Big 12, SEC, Big East, Pac-12. Every other D1 conference = Mid-Major.

Usage:
    from conferences import conference, tier
    conference("Gonzaga", 2026)  # "WCC"
    tier("Gonzaga", 2027)        # "Power" (Pac-12)

userpoll.py injects js_payload() into the pages as CONFERENCE_DATA, which feeds
the Shift+K conference table (showConferenceModal() in script.js).

Run `python3 conferences.py` to check that every team in the 2025+ data is mapped.
"""

import json

FIRST_SEASON = 2025

POWER_CONFERENCES = ["ACC", "Big Ten", "Big 12", "SEC", "Big East", "Pac-12"]

# Data names that refer to the same school as a canonical key.
ALIASES = {
    "CollegeofCharleston": "Charleston",
    "Citadel":             "TheCitadel",
    "NebraskaOmaha":       "Omaha",
    "MT":                  "MiddleTennessee",
    "USF":                 "SouthFlorida",
    "EastTexasAM":         "TexasAMCommerce",
    "IUIndy":              "IUPUI",
}

# Display names where splitting the PascalCase key isn't right.
DISPLAY_NAMES = {
    "TexasAM": "Texas A&M", "TexasAMCommerce": "East Texas A&M",
    "TexasAMCorpusChristi": "Texas A&M-CC", "FloridaAM": "Florida A&M",
    "AlabamaAM": "Alabama A&M", "PrairieViewAM": "Prairie View A&M",
    "NorthCarolinaAT": "North Carolina A&T", "IUPUI": "IU Indy",
    "StJohns": "St. John's", "SaintMarys": "Saint Mary's",
    "SaintJosephs": "Saint Joseph's", "SaintPeters": "Saint Peter's",
    "MountStMarys": "Mount St. Mary's", "StBonaventure": "St. Bonaventure",
    "StThomas": "St. Thomas", "SaintFrancisPA": "Saint Francis (PA)",
    "MiamiFL": "Miami (FL)", "MiamiOH": "Miami (OH)", "OleMiss": "Ole Miss",
    "NCState": "NC State", "Pitt": "Pitt", "TheCitadel": "The Citadel",
    "LoyolaMD": "Loyola (MD)", "LoyolaChicago": "Loyola Chicago",
    "WilliamandMary": "William & Mary", "StephenFAustin": "Stephen F. Austin",
    "SEMissouriState": "SE Missouri State", "SIUEdwardsville": "SIUE",
    "SCState": "South Carolina State", "UMES": "Maryland Eastern Shore",
    "UNCGreensboro": "UNC Greensboro", "UNCWilmington": "UNC Wilmington",
    "UNCAsheville": "UNC Asheville", "USCUpstate": "USC Upstate",
    "UTMartin": "UT Martin", "UTArlington": "UT Arlington", "UTRGV": "UTRGV",
    "ArkansasPineBluff": "Arkansas-Pine Bluff", "BethuneCookman": "Bethune-Cookman",
    "GardnerWebb": "Gardner-Webb", "LouisianaMonroe": "Louisiana-Monroe",
    "SELouisiana": "SE Louisiana", "NJIT": "NJIT", "UIC": "UIC",
    "CSUBakersfield": "CSU Bakersfield", "CSUN": "CSUN",
    "CalStateFullerton": "Cal State Fullerton", "LeMoyne": "Le Moyne",
    "FairleighDickinson": "Fairleigh Dickinson", "DetroitMercy": "Detroit Mercy",
    "EastTennesseeState": "East Tennessee State", "SouthFlorida": "South Florida",
    "NewOrleans": "New Orleans", "UMassLowell": "UMass Lowell",
    "DePaul": "DePaul", "UConn": "UConn", "UMass": "UMass", "McNeese": "McNeese",
}

# Full D1 membership for the 2024-25 season (2025), basketball affiliation.
_BASE_2025 = {
    "ACC": [
        "BostonCollege", "California", "Clemson", "Duke", "FloridaState",
        "GeorgiaTech", "Louisville", "MiamiFL", "NorthCarolina", "NCState",
        "NotreDame", "Pitt", "SMU", "Stanford", "Syracuse", "Virginia",
        "VirginiaTech", "WakeForest",
    ],
    "Big Ten": [
        "Illinois", "Indiana", "Iowa", "Maryland", "Michigan", "MichiganState",
        "Minnesota", "Nebraska", "Northwestern", "OhioState", "Oregon",
        "PennState", "Purdue", "Rutgers", "UCLA", "USC", "Washington",
        "Wisconsin",
    ],
    "Big 12": [
        "Arizona", "ArizonaState", "Baylor", "BYU", "Cincinnati", "Colorado",
        "Houston", "IowaState", "Kansas", "KansasState", "OklahomaState",
        "TCU", "TexasTech", "UCF", "Utah", "WestVirginia",
    ],
    "SEC": [
        "Alabama", "Arkansas", "Auburn", "Florida", "Georgia", "Kentucky",
        "LSU", "OleMiss", "MississippiState", "Missouri", "Oklahoma",
        "SouthCarolina", "Tennessee", "Texas", "TexasAM", "Vanderbilt",
    ],
    "Big East": [
        "Butler", "UConn", "Creighton", "DePaul", "Georgetown", "Marquette",
        "Providence", "StJohns", "SetonHall", "Villanova", "Xavier",
    ],
    "America East": [
        "Albany", "Binghamton", "Bryant", "Maine", "NewHampshire", "NJIT",
        "UMassLowell", "UMBC", "Vermont",
    ],
    "American": [
        "Charlotte", "EastCarolina", "FloridaAtlantic", "Memphis", "NorthTexas",
        "Rice", "SouthFlorida", "Temple", "Tulane", "Tulsa", "UAB", "UTSA",
        "WichitaState",
    ],
    "Atlantic 10": [
        "Davidson", "Dayton", "Duquesne", "Fordham", "GeorgeMason",
        "GeorgeWashington", "LaSalle", "LoyolaChicago", "UMass", "RhodeIsland",
        "Richmond", "StBonaventure", "SaintJosephs", "SaintLouis", "VCU",
    ],
    "ASUN": [
        "AustinPeay", "Bellarmine", "CentralArkansas", "EasternKentucky",
        "FloridaGulfCoast", "Jacksonville", "Lipscomb", "NorthAlabama",
        "NorthFlorida", "Queens", "Stetson", "WestGeorgia",
    ],
    "Big Sky": [
        "EasternWashington", "Idaho", "IdahoState", "Montana", "MontanaState",
        "NorthernArizona", "NorthernColorado", "PortlandState",
        "SacramentoState", "WeberState",
    ],
    "Big South": [
        "CharlestonSouthern", "GardnerWebb", "HighPoint", "Longwood",
        "Presbyterian", "Radford", "UNCAsheville", "USCUpstate", "Winthrop",
    ],
    "Big West": [
        "CalPoly", "CSUBakersfield", "CalStateFullerton", "CSUN", "Hawaii",
        "LongBeachState", "UCDavis", "UCIrvine", "UCRiverside", "UCSanDiego",
        "UCSantaBarbara",
    ],
    "CAA": [
        "Campbell", "Charleston", "Delaware", "Drexel", "Elon", "Hampton",
        "Hofstra", "Monmouth", "NorthCarolinaAT", "Northeastern", "StonyBrook",
        "Towson", "UNCWilmington", "WilliamandMary",
    ],
    "Conference USA": [
        "FIU", "JacksonvilleState", "KennesawState", "Liberty", "LouisianaTech",
        "MiddleTennessee", "NewMexicoState", "SamHouston", "UTEP",
        "WesternKentucky",
    ],
    "Horizon": [
        "ClevelandState", "DetroitMercy", "GreenBay", "IUPUI", "Milwaukee",
        "NorthernKentucky", "Oakland", "PurdueFortWayne", "RobertMorris",
        "WrightState", "YoungstownState",
    ],
    "Ivy": [
        "Brown", "Columbia", "Cornell", "Dartmouth", "Harvard", "Penn",
        "Princeton", "Yale",
    ],
    "MAAC": [
        "Canisius", "Fairfield", "Iona", "Manhattan", "Marist", "Merrimack",
        "MountStMarys", "Niagara", "Quinnipiac", "Rider", "SacredHeart",
        "SaintPeters", "Siena",
    ],
    "MAC": [
        "Akron", "BallState", "BowlingGreen", "Buffalo", "CentralMichigan",
        "EasternMichigan", "KentState", "MiamiOH", "NorthernIllinois", "Ohio",
        "Toledo", "WesternMichigan",
    ],
    "MEAC": [
        "CoppinState", "DelawareState", "Howard", "UMES", "MorganState",
        "NorfolkState", "NorthCarolinaCentral", "SCState",
    ],
    "Missouri Valley": [
        "Belmont", "Bradley", "Drake", "Evansville", "IllinoisState",
        "IndianaState", "MissouriState", "MurrayState", "NorthernIowa",
        "SouthernIllinois", "UIC", "Valparaiso",
    ],
    "Mountain West": [
        "AirForce", "BoiseState", "ColoradoState", "FresnoState", "Nevada",
        "NewMexico", "SanDiegoState", "SanJoseState", "UNLV", "UtahState",
        "Wyoming",
    ],
    "NEC": [
        "CentralConnecticut", "ChicagoState", "FairleighDickinson", "LeMoyne",
        "LIU", "Mercyhurst", "SaintFrancisPA", "Stonehill", "Wagner",
    ],
    "OVC": [
        "EasternIllinois", "Lindenwood", "LittleRock", "MoreheadState",
        "SEMissouriState", "SIUEdwardsville", "SouthernIndiana",
        "TennesseeState", "TennesseeTech", "UTMartin", "WesternIllinois",
    ],
    "Patriot": [
        "American", "Army", "BostonUniversity", "Bucknell", "Colgate",
        "HolyCross", "Lafayette", "Lehigh", "LoyolaMD", "Navy",
    ],
    "SoCon": [
        "Chattanooga", "EastTennesseeState", "Furman", "Mercer", "Samford",
        "TheCitadel", "UNCGreensboro", "VMI", "WesternCarolina", "Wofford",
    ],
    "Southland": [
        "TexasAMCommerce", "HoustonChristian", "IncarnateWord", "Lamar",
        "McNeese", "NewOrleans", "Nicholls", "NorthwesternState",
        "SELouisiana", "StephenFAustin", "TexasAMCorpusChristi", "UTRGV",
    ],
    "Summit": [
        "Denver", "KansasCity", "NorthDakota", "NorthDakotaState", "Omaha",
        "OralRoberts", "SouthDakota", "SouthDakotaState", "StThomas",
    ],
    "Sun Belt": [
        "AppalachianState", "ArkansasState", "CoastalCarolina",
        "GeorgiaSouthern", "GeorgiaState", "JamesMadison", "Louisiana",
        "LouisianaMonroe", "Marshall", "OldDominion", "SouthAlabama",
        "SouthernMiss", "TexasState", "Troy",
    ],
    "SWAC": [
        "AlabamaAM", "AlabamaState", "AlcornState", "ArkansasPineBluff",
        "BethuneCookman", "FloridaAM", "GramblingState", "JacksonState",
        "MississippiValleyState", "PrairieViewAM", "Southern", "TexasSouthern",
    ],
    "WAC": [
        "AbileneChristian", "CaliforniaBaptist", "GrandCanyon", "Seattle",
        "SouthernUtah", "TarletonState", "UTArlington", "UtahTech",
        "UtahValley",
    ],
    # Oregon State and Washington State were WCC affiliate members for
    # basketball in 2024-25 and 2025-26 (the Pac-12 had only those two schools).
    "WCC": [
        "Gonzaga", "LoyolaMarymount", "OregonState", "Pacific", "Pepperdine",
        "Portland", "SaintMarys", "SanDiego", "SanFrancisco", "SantaClara",
        "WashingtonState",
    ],
}

# Changes that take effect in a season: {season: {team: new_conference}}.
# None = left Division I. A {"rename": {old: new}} entry renames a conference.
_MOVES = {
    2026: {  # 2025-26
        "UMass":         "MAC",
        "GrandCanyon":   "Mountain West",
        "Seattle":       "WCC",
        "MissouriState": "Conference USA",
        "Delaware":      "Conference USA",
        "NewHaven":      "NEC",
    },
    2027: {  # 2026-27: Pac-12 rebuilt, WAC -> UAC, MAAC -> Metro
        "rename": {"WAC": "UAC", "MAAC": "Metro"},
        "BoiseState":       "Pac-12",
        "ColoradoState":    "Pac-12",
        "FresnoState":      "Pac-12",
        "Gonzaga":          "Pac-12",
        "OregonState":      "Pac-12",
        "SanDiegoState":    "Pac-12",
        "TexasState":       "Pac-12",
        "UtahState":        "Pac-12",
        "WashingtonState":  "Pac-12",
        "UTEP":             "Mountain West",
        "Hawaii":           "Mountain West",
        "UCDavis":          "Mountain West",
        "LouisianaTech":    "Sun Belt",
        "NorthernIllinois": "Horizon",  # MW for football only
        "Denver":           "WCC",
        "CaliforniaBaptist": "Big West",
        "UtahValley":       "Big West",
        "SacramentoState":  "Big West",
        "SouthernUtah":     "Big Sky",
        "UtahTech":         "Big Sky",
        "AustinPeay":       "UAC",
        "CentralArkansas":  "UAC",
        "EasternKentucky":  "UAC",
        "NorthAlabama":     "UAC",
        "WestGeorgia":      "UAC",
        "LittleRock":       "UAC",
        "TennesseeTech":    "SoCon",
        "WestFlorida":      "ASUN",  # new to D1
        "SaintFrancisPA":   None,    # left for D3
    },
}


def _build():
    seasons = {}
    current = {t: c for c, teams in _BASE_2025.items() for t in teams}
    seasons[FIRST_SEASON] = dict(current)
    for year in range(FIRST_SEASON + 1, max(_MOVES) + 1):
        moves = dict(_MOVES.get(year, {}))
        renames = moves.pop("rename", {})
        current = {t: renames.get(c, c) for t, c in current.items()}
        for team, conf in moves.items():
            if conf is None:
                current.pop(team, None)
            else:
                current[team] = conf
        seasons[year] = dict(current)
    return seasons


SEASONS = _build()
LAST_DEFINED_SEASON = max(SEASONS)


def canonical(team):
    return ALIASES.get(team, team)


def conference(team, year):
    """Conference for a team in a season (2025+). None if unmapped or pre-2025."""
    if year < FIRST_SEASON:
        return None
    return SEASONS[min(year, LAST_DEFINED_SEASON)].get(canonical(team))


def tier(team, year):
    """'Power', 'Mid-Major', or None if unmapped or pre-2025."""
    conf = conference(team, year)
    if conf is None:
        return None
    return "Power" if conf in POWER_CONFERENCES else "Mid-Major"


def js_payload():
    """JSON for the page: {seasons: {year: {conf: [teams]}}, power, aliases, names}."""
    seasons = {}
    for year, table in SEASONS.items():
        by_conf = {}
        for team, conf in table.items():
            by_conf.setdefault(conf, []).append(team)
        seasons[year] = {c: sorted(ts) for c, ts in sorted(by_conf.items())}
    return json.dumps({
        "seasons": seasons,
        "power": POWER_CONFERENCES,
        "aliases": ALIASES,
        "names": DISPLAY_NAMES,
    }, separators=(",", ":"))


def _teams_in_data(year):
    """Team names that appear on ballots in a season's userpoll + AP files."""
    import os
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    files = [f"data-{year}.html", f"data-ap-{year}.html"]
    if not os.path.exists(os.path.join(here, files[0])):
        files[0] = "index.html"  # current season lives inline
    teams = set()
    for name in files:
        path = os.path.join(here, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if name == "index.html":
            # Only count ballots from this season's week blocks.
            text = "".join(re.findall(
                rf'id="week-{year}-.*?(?=id="week-\d{{4}}-|\Z)', text, re.S))
        teams.update(re.findall(r'data-src="([^"]+)"', text))
    return teams


if __name__ == "__main__":
    ok = True
    for year in sorted(SEASONS):
        sizes = {}
        for conf in SEASONS[year].values():
            sizes[conf] = sizes.get(conf, 0) + 1
        teams = _teams_in_data(year)
        missing = sorted(t for t in teams if conference(t, year) is None)
        print(f"{year}: {len(SEASONS[year])} D1 schools in {len(sizes)} conferences; "
              f"{len(teams)} on ballots"
              + (f", UNMAPPED: {missing}" if missing else ", all mapped"))
        print("   " + ", ".join(f"{c} {n}" for c, n in sorted(sizes.items())))
        ok &= not missing
    raise SystemExit(0 if ok else 1)
