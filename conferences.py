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


# ESPN team ID for every school above (all seasons). Feeds the Year window's Records
# tab, which reads live W-L records from ESPN's standings API. IDs never change for a
# school; a school added to _BASE_2025/_MOVES needs an entry here too (the check at the
# bottom of this file reports any that are missing).
ESPN_IDS = {
    "AbileneChristian":"2000", "AirForce":"2005", "Akron":"2006", "Alabama":"333",
    "AlabamaAM":"2010", "AlabamaState":"2011", "Albany":"399", "AlcornState":"2016",
    "American":"44", "AppalachianState":"2026", "Arizona":"12", "ArizonaState":"9",
    "Arkansas":"8", "ArkansasPineBluff":"2029", "ArkansasState":"2032", "Army":"349",
    "Auburn":"2", "AustinPeay":"2046", "BYU":"252", "BallState":"2050", "Baylor":"239",
    "Bellarmine":"91", "Belmont":"2057", "BethuneCookman":"2065", "Binghamton":"2066",
    "BoiseState":"68", "BostonCollege":"103", "BostonUniversity":"104", "BowlingGreen":"189",
    "Bradley":"71", "Brown":"225", "Bryant":"2803", "Bucknell":"2083", "Buffalo":"2084",
    "Butler":"2086", "CSUBakersfield":"2934", "CSUN":"2463", "CalPoly":"13",
    "CalStateFullerton":"2239", "California":"25", "CaliforniaBaptist":"2856",
    "Campbell":"2097", "Canisius":"2099", "CentralArkansas":"2110", "CentralConnecticut":"2115",
    "CentralMichigan":"2117", "Charleston":"232", "CharlestonSouthern":"2127",
    "Charlotte":"2429", "Chattanooga":"236", "ChicagoState":"2130", "Cincinnati":"2132",
    "Clemson":"228", "ClevelandState":"325", "CoastalCarolina":"324", "Colgate":"2142",
    "Colorado":"38", "ColoradoState":"36", "Columbia":"171", "CoppinState":"2154",
    "Cornell":"172", "Creighton":"156", "Dartmouth":"159", "Davidson":"2166", "Dayton":"2168",
    "DePaul":"305", "Delaware":"48", "DelawareState":"2169", "Denver":"2172",
    "DetroitMercy":"2174", "Drake":"2181", "Drexel":"2182", "Duke":"150", "Duquesne":"2184",
    "EastCarolina":"151", "EastTennesseeState":"2193", "EasternIllinois":"2197",
    "EasternKentucky":"2198", "EasternMichigan":"2199", "EasternWashington":"331",
    "Elon":"2210", "Evansville":"339", "FIU":"2229", "Fairfield":"2217",
    "FairleighDickinson":"161", "Florida":"57", "FloridaAM":"50", "FloridaAtlantic":"2226",
    "FloridaGulfCoast":"526", "FloridaState":"52", "Fordham":"2230", "FresnoState":"278",
    "Furman":"231", "GardnerWebb":"2241", "GeorgeMason":"2244", "GeorgeWashington":"45",
    "Georgetown":"46", "Georgia":"61", "GeorgiaSouthern":"290", "GeorgiaState":"2247",
    "GeorgiaTech":"59", "Gonzaga":"2250", "GramblingState":"2755", "GrandCanyon":"2253",
    "GreenBay":"2739", "Hampton":"2261", "Harvard":"108", "Hawaii":"62", "HighPoint":"2272",
    "Hofstra":"2275", "HolyCross":"107", "Houston":"248", "HoustonChristian":"2277",
    "Howard":"47", "IUPUI":"85", "Idaho":"70", "IdahoState":"304", "Illinois":"356",
    "IllinoisState":"2287", "IncarnateWord":"2916", "Indiana":"84", "IndianaState":"282",
    "Iona":"314", "Iowa":"2294", "IowaState":"66", "JacksonState":"2296", "Jacksonville":"294",
    "JacksonvilleState":"55", "JamesMadison":"256", "Kansas":"2305", "KansasCity":"140",
    "KansasState":"2306", "KennesawState":"338", "KentState":"2309", "Kentucky":"96",
    "LIU":"112358", "LSU":"99", "LaSalle":"2325", "Lafayette":"322", "Lamar":"2320",
    "LeMoyne":"2330", "Lehigh":"2329", "Liberty":"2335", "Lindenwood":"2815", "Lipscomb":"288",
    "LittleRock":"2031", "LongBeachState":"299", "Longwood":"2344", "Louisiana":"309",
    "LouisianaMonroe":"2433", "LouisianaTech":"2348", "Louisville":"97", "LoyolaChicago":"2350",
    "LoyolaMD":"2352", "LoyolaMarymount":"2351", "Maine":"311", "Manhattan":"2363",
    "Marist":"2368", "Marquette":"269", "Marshall":"276", "Maryland":"120", "McNeese":"2377",
    "Memphis":"235", "Mercer":"2382", "Mercyhurst":"2385", "Merrimack":"2771", "MiamiFL":"2390",
    "MiamiOH":"193", "Michigan":"130", "MichiganState":"127", "MiddleTennessee":"2393",
    "Milwaukee":"270", "Minnesota":"135", "MississippiState":"344",
    "MississippiValleyState":"2400", "Missouri":"142", "MissouriState":"2623",
    "Monmouth":"2405", "Montana":"149", "MontanaState":"147", "MoreheadState":"2413",
    "MorganState":"2415", "MountStMarys":"116", "MurrayState":"93", "NCState":"152",
    "NJIT":"2885", "Navy":"2426", "Nebraska":"158", "Nevada":"2440", "NewHampshire":"160",
    "NewHaven":"2441", "NewMexico":"167", "NewMexicoState":"166", "NewOrleans":"2443",
    "Niagara":"315", "Nicholls":"2447", "NorfolkState":"2450", "NorthAlabama":"2453",
    "NorthCarolina":"153", "NorthCarolinaAT":"2448", "NorthCarolinaCentral":"2428",
    "NorthDakota":"155", "NorthDakotaState":"2449", "NorthFlorida":"2454", "NorthTexas":"249",
    "Northeastern":"111", "NorthernArizona":"2464", "NorthernColorado":"2458",
    "NorthernIllinois":"2459", "NorthernIowa":"2460", "NorthernKentucky":"94",
    "Northwestern":"77", "NorthwesternState":"2466", "NotreDame":"87", "Oakland":"2473",
    "Ohio":"195", "OhioState":"194", "Oklahoma":"201", "OklahomaState":"197",
    "OldDominion":"295", "OleMiss":"145", "Omaha":"2437", "OralRoberts":"198", "Oregon":"2483",
    "OregonState":"204", "Pacific":"279", "Penn":"219", "PennState":"213", "Pepperdine":"2492",
    "Pitt":"221", "Portland":"2501", "PortlandState":"2502", "PrairieViewAM":"2504",
    "Presbyterian":"2506", "Princeton":"163", "Providence":"2507", "Purdue":"2509",
    "PurdueFortWayne":"2870", "Queens":"2511", "Quinnipiac":"2514", "Radford":"2515",
    "RhodeIsland":"227", "Rice":"242", "Richmond":"257", "Rider":"2520", "RobertMorris":"2523",
    "Rutgers":"164", "SCState":"2569", "SELouisiana":"2545", "SEMissouriState":"2546",
    "SIUEdwardsville":"2565", "SMU":"2567", "SacramentoState":"16", "SacredHeart":"2529",
    "SaintFrancisPA":"2598", "SaintJosephs":"2603", "SaintLouis":"139", "SaintMarys":"2608",
    "SaintPeters":"2612", "SamHouston":"2534", "Samford":"2535", "SanDiego":"301",
    "SanDiegoState":"21", "SanFrancisco":"2539", "SanJoseState":"23", "SantaClara":"2541",
    "Seattle":"2547", "SetonHall":"2550", "Siena":"2561", "SouthAlabama":"6",
    "SouthCarolina":"2579", "SouthDakota":"233", "SouthDakotaState":"2571", "SouthFlorida":"58",
    "Southern":"2582", "SouthernIllinois":"79", "SouthernIndiana":"88", "SouthernMiss":"2572",
    "SouthernUtah":"253", "StBonaventure":"179", "StJohns":"2599", "StThomas":"2900",
    "Stanford":"24", "StephenFAustin":"2617", "Stetson":"56", "Stonehill":"284",
    "StonyBrook":"2619", "Syracuse":"183", "TCU":"2628", "TarletonState":"2627", "Temple":"218",
    "Tennessee":"2633", "TennesseeState":"2634", "TennesseeTech":"2635", "Texas":"251",
    "TexasAM":"245", "TexasAMCommerce":"2837", "TexasAMCorpusChristi":"357",
    "TexasSouthern":"2640", "TexasState":"326", "TexasTech":"2641", "TheCitadel":"2643",
    "Toledo":"2649", "Towson":"119", "Troy":"2653", "Tulane":"2655", "Tulsa":"202", "UAB":"5",
    "UCDavis":"302", "UCF":"2116", "UCIrvine":"300", "UCLA":"26", "UCRiverside":"27",
    "UCSanDiego":"28", "UCSantaBarbara":"2540", "UConn":"41", "UIC":"82", "UMBC":"2378",
    "UMES":"2379", "UMass":"113", "UMassLowell":"2349", "UNCAsheville":"2427",
    "UNCGreensboro":"2430", "UNCWilmington":"350", "UNLV":"2439", "USC":"30",
    "USCUpstate":"2908", "UTArlington":"250", "UTEP":"2638", "UTMartin":"2630", "UTRGV":"292",
    "UTSA":"2636", "Utah":"254", "UtahState":"328", "UtahTech":"3101", "UtahValley":"3084",
    "VCU":"2670", "VMI":"2678", "Valparaiso":"2674", "Vanderbilt":"238", "Vermont":"261",
    "Villanova":"222", "Virginia":"258", "VirginiaTech":"259", "Wagner":"2681",
    "WakeForest":"154", "Washington":"264", "WashingtonState":"265", "WeberState":"2692",
    "WestFlorida":"2697", "WestGeorgia":"2698", "WestVirginia":"277", "WesternCarolina":"2717",
    "WesternIllinois":"2710", "WesternKentucky":"98", "WesternMichigan":"2711",
    "WichitaState":"2724", "WilliamandMary":"2729", "Winthrop":"2737", "Wisconsin":"275",
    "Wofford":"2747", "WrightState":"2750", "Wyoming":"2751", "Xavier":"2752", "Yale":"43",
    "YoungstownState":"2754",
}


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
    """JSON for the page: {seasons: {year: {conf: [teams]}}, power, aliases, names, espn}."""
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
        "espn": ESPN_IDS,
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
    no_espn = sorted({t for s in SEASONS.values() for t in s} - set(ESPN_IDS))
    if no_espn:
        print(f"NO ESPN ID (add to ESPN_IDS): {no_espn}")
    ok &= not no_espn
    raise SystemExit(0 if ok else 1)
