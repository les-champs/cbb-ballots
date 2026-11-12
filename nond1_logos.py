"""Logos for non-D1 opponents that ESPN has no logo for, downloaded at build time from NCAA.com.

ESPN's schedules list a logo for some non-D1 opponents (the Records tab hotlinks those), but
most D2/D3/NAIA schools come with an empty `logos` array. NCAA.com has SVG logos for every
NCAA school (D1–D3, not NAIA) at a URL keyed by its own slug, so we map ESPN ids to NCAA.com
slugs by hand in NCAA_SLUGS. Each SVG is rendered once by headless Chrome (some are 750 KB
of vector paths) and saved as a 150×150 WebP like our other logos: cbb-logos/ncaa-{espnId}.webp
(light backgrounds) and ncaa-{espnId}-dark.webp (NCAA.com's dark-background version, when it
differs). userpoll.py ships the ids that have files to the page as NCAA_LOGO_IDS /
NCAA_DARK_LOGO_IDS; nothing is fetched from NCAA.com at view time.

Needs Google Chrome (default macOS path; set CHROME=/path/to/chrome elsewhere).

Run through userpoll.py:
    python3 userpoll.py --ncaa-logos [--year YYYY]   # download missing files; list unmapped schools
    (--year 0 = every season shown on the site; default = the current season)

To add a school: run the command, check the suggestions it prints for unmapped opponents,
add the right ones to NCAA_SLUGS, run it again, then --rebuild.
"""
import difflib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import conferences

SCHEDULE_URL = ("https://site.web.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/"
                "teams/{id}/schedule?season={season}&seasontype=2")
NCAA_INDEX_URL = "https://www.ncaa.com/schools-index/{page}"
NCAA_LOGO_URL = "https://www.ncaa.com/sites/default/files/images/logos/schools/{bg}/{slug}.svg"
UA = {"User-Agent": "Mozilla/5.0"}
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
LOGO_SIZE = 150      # same as the ESPN-derived logos in cbb-logos/
RENDER_SIZE = 256    # rendered larger, then downscaled for smoother edges

# ESPN team id → NCAA.com slug (www.ncaa.com/schools/<slug>). Only schools ESPN has no logo
# for. Each entry was checked against NCAA.com's full school name; keep the ESPN name in the
# comment so a wrong match is easy to spot. Left out because NCAA.com has only its generic
# placeholder shield for them: St. Francis (IL), Eastern Oregon, Puerto Rico-Bayamon,
# Puerto Rico-Mayaguez, Puerto Rico-Rio Piedras, Lincoln Christian, Penn State Brandywine.
NCAA_SLUGS = {
    "3136": "academy-of-art",      # Academy of Art
    "108820": "alfred-st",         # Alfred State
    "380": "anderson-sc",          # Anderson (SC)
    "407": "arcadia",              # Arcadia
    "3157": "ark-fort-smith",      # Arkansas Fort Smith
    "2036": "asbury",              # Asbury
    "2040": "aub-montgomery",      # Auburn Montgomery
    "2041": "gru-augusta",         # Augusta
    "5308": "babson",              # Babson
    "2053": "barry",               # Barry
    "2059": "benedict",            # Benedict
    "5345": "benedictine-il",      # Benedictine (IL)
    "2061": "berea",               # Berea
    "2070": "blackburn",           # Blackburn
    "2854": "bloomfield",          # Bloomfield
    "2073": "bluefield-st",        # Bluefield State
    "5426": "brandeis",            # Brandeis
    "109684": "bryn-athyn",        # Bryn Athyn
    "2088": "byu-hawaii",          # BYU-Hawaii
    "92": "cabrini",               # Cabrini
    "429": "cairn",                # Cairn
    "3216": "cairn",               # Cairn University
    "6183": "humboldt-st",         # Cal Poly Humboldt
    "2092": "cal-st-dom-hills",    # Cal State Dominguez Hills
    "2093": "cal-st-east-bay",     # Cal State East Bay
    "2863": "cal-st-monterey-bay", # Cal State Monterey Bay
    "3182": "cal-st-san-marcos",   # Cal State San Marcos
    "110450": "caltech",           # Caltech
    "123366": "calvin",            # Calvin
    "2096": "cameron",             # Cameron
    "2114": "centenary-nj",        # Centenary (NJ)
    "110412": "chatham",           # Chatham
    "469": "chestnut-hill",        # Chestnut Hill
    "2129": "cheyney",             # Cheyney (PA)
    "2131": "christian-bros",      # Christian Brothers
    "2133": "claflin",             # Claflin
    "2965": "clarke",              # Clarke
    "109636": "baptist-bible-pa",  # Clarks Summit
    "2861": "clayton-st",          # Clayton State
    "229": "coker",                # Coker
    "35": "colby-sawyer",          # Colby Sawyer
    "111171": "new-rochelle",      # College Of New Rochelle
    "2862": "colo-christian",      # Colorado Christian
    "413": "columbus-st",          # Columbus State
    "2153": "concordia-tx",        # Concordia (TX)
    "2150": "concordia-or",        # Concordia Oregon
    "39": "connecticut-col",       # Connecticut College
    "124947": "converse",          # Converse
    "2157": "covenant",            # Covenant
    "2163": "dallas",              # Dallas
    "3119": "daniel-webster",      # Daniel Webster College
    "2167": "davis-elkins",        # Davis & Elkins
    "111949": "desales",           # DeSales
    "2177": "dist-columbia",       # District of Columbia
    "2957": "dominican-ca",        # Dominican (CA)
    "2936": "dominican-il",        # Dominican (IL)
    "2189": "earlham",             # Earlham
    "2192": "east-mennonite",      # Eastern Mennonite
    "2204": "eckerd",              # Eckerd
    "5901": "elizabethtown",       # Elizabethtown
    "111948": "elms",              # Elms
    "520": "embry-riddle-fl",      # Embry Riddle (FL)
    "108842": "emerson",           # Emerson
    "2211": "emmanuel-ma",         # Emmanuel (MA)
    "2212": "emory",               # Emory
    "130199": "endicott",          # Endicott
    "2215": "erskine",             # Erskine
    "2866": "evergreen-st",        # Evergreen State
    "3149": "farmingdale-st",      # Farmingdale State
    "459": "fontbonne",            # Fontbonne
    "126956": "framingham-st",     # Framingham State
    "230": "francis-marion",       # Francis Marion
    "111170": "franciscan",        # Franciscan
    "2246": "georgia-college",     # Georgia College
    "3068": "ga-southwestern",     # Georgia Southwestern
    "12758": "ga-southwestern",    # Georgia Southwestern
    "111179": "georgian-court",    # Georgian Court
    "2248": "gettysburg",          # Gettysburg
    "108859": "goldey-beacom",     # Goldey Beacom
    "111172": "gordon",            # Gordon
    "2251": "goucher",             # Goucher
    "461": "gwynedd-mercy",        # Gwynedd Mercy
    "2267": "hawaii-hilo",         # Hawaiʻi Hilo
    "108854": "hood",              # Hood
    "538": "houghton",             # Houghton
    "542": "ill-springfield",      # Illinois Springfield
    "73": "iit",                   # Illinois Tech
    "107554": "immaculata",        # Immaculata
    "2295": "iowa-wesleyan",       # Iowa Wesleyan
    "3078": "jessup",              # Jessup
    "212": "john-jay",             # John Jay
    "353": "johnson-wales-ri",     # Johnson & Wales
    "6304": "keene-st",            # Keene State
    "6319": "keuka",               # Keuka
    "108860": "keystone",          # Keystone
    "2874": "la-roche",            # La Roche
    "3167": "la-sierra",           # La Sierra
    "267": "lakeland",             # Lakeland
    "123306": "lancaster-bible",   # Lancaster Bible
    "2322": "lander",              # Lander
    "6371": "lane",                # Lane College
    "2327": "lees-mcrae",          # Lees McRae
    "130190": "lehman",            # Lehman
    "2917": "lemoyne-owen",        # LeMoyne-Owen
    "477": "lesley",               # Lesley
    "2332": "lewis",               # Lewis
    "2355": "lynchburg",           # Lynchburg
    "2358": "lyon",                # Lyon
    "287": "me-farmington",        # Maine Farmington
    "274": "maine-maritime",       # Maine Maritime
    "2361": "me-presque-isle",     # Maine Presque Isle
    "556": "malone",               # Malone
    "2879": "manhattanville",      # Manhattanville
    "124851": "marian-wi",         # Marian (WI)
    "2942": "mary-washington",     # Mary Washington
    "2372": "marymount-va",        # Marymount
    "310": "maryville-mo",         # Maryville (MO)
    "2374": "marywood",            # Marywood
    "14632": "mcdaniel",           # McDaniel
    "476": "medaille",             # Medaille College
    "2380": "medgar-evers",        # Medgar Evers
    "2381": "menlo",               # Menlo
    "2384": "mercy",               # Mercy
    "2387": "messiah",             # Messiah
    "109014": "middle-georgia-st", # Middle Georgia
    "2395": "midwestern-st",       # Midwestern State
    "110437": "msoe",              # Milwaukee Engineering
    "111902": "misericordia",      # Misericordia
    "6760": "missouri-snt",        # Missouri S&T
    "141": "mo-st-louis",          # Missouri St. Louis
    "108838": "mitchell",          # Mitchell
    "2404": "molloy",              # Molloy
    "2409": "montevallo",          # Montevallo
    "111943": "mt-aloysius",       # Mount Aloysius
    "2418": "mount-olive",         # Mount Olive
    "329": "mt-st-vincent",        # Mount Saint Vincent
    "289": "mt-st-mary-ny",        # Mount St Mary
    "110426": "nazareth",          # Nazareth
    "157": "neb-wesleyan",         # Nebraska Wesleyan
    "422": "neumann",              # Neumann
    "3085": "u-new-england",       # New England
    "108818": "nyit",              # New York Institute Of Technology
    "108822": "newbury",           # Newbury College
    "580": "newman",               # Newman
    "121894": "north-central-mn",  # North Central (MN)
    "2455": "north-georgia",       # North Georgia
    "425": "northern-st",          # Northern State
    "2462": "northland",           # Northland
    "2887": "northwest-nazarene",  # Northwest Nazarene
    "128342": "notre-dame-md",     # Notre Dame (MD)
    "2468": "notre-dame-de-namur", # Notre Dame de Namur
    "2474": "oakland-city",        # Oakland City
    "2475": "occidental",          # Occidental
    "2476": "oglethorpe",          # Oglethorpe
    "2479": "ohio-valley",         # Ohio Valley
    "589": "okla-christian",       # Oklahoma Christian
    "2824": "okla-panhandle",      # Oklahoma Panhandle
    "3109": "ozarks-ar",           # Ozarks (AR)
    "2488": "paine",               # Paine
    "2489": "palm-beach-atl",      # Palm Beach Atlantic
    "3183": "penn-st-abington",    # Penn State Abington
    "478": "penn-st-altoona",      # Penn State Altoona
    "2944": "penn-st-behrend",     # Penn State Behrend
    "131640": "penn-st-berks",     # Penn State Berks
    "108874": "penn-st-harrisburg", # Penn State Harrisburg
    "2945": "pfeiffer",            # Pfeiffer
    "2496": "piedmont",            # Piedmont
    "109656": "pine-manor",        # Pine Manor
    "220": "pitt-bradford",        # Pittsburgh-Bradford
    "126821": "pitt-greensburg",   # Pittsburgh-Greensburg
    "177": "plattsburgh-st",       # Plattsburgh
    "214": "point-park",           # Point Park
    "2505": "pratt-institute",     # Pratt Institute
    "597": "presentation",         # Presentation College
    "131584": "principia",         # Principia
    "3103": "purchase-st",         # Purchase
    "2512": "queens-ny",           # Queens (NY)
    "3153": "randolph",            # Randolph
    "2517": "regis-ma",            # Regis College
    "2518": "regis-co",            # Regis University
    "128531": "roberts-wesleyan",  # Roberts Wesleyan
    "3122": "rogers-st",           # Rogers State
    "465": "rosemont",             # Rosemont
    "2892": "rust",                # Rust
    "370": "rutgers-camden",       # Rutgers-Camden
    "109658": "rutgers-newark",    # Rutgers-Newark
    "66786": "st-elizabeth",       # Saint Elizabeth
    "2602": "st-josephs-me",       # Saint Joseph's (ME)
    "2899": "st-marys-mn",         # Saint Mary's (MN)
    "22": "san-fran-st",           # San Francisco State
    "108862": "sarah-lawrence",    # Sarah Lawrence
    "2544": "schreiner",           # Schreiner
    "109567": "seton-hill",        # Seton Hill
    "2574": "sonoma-st",           # Sonoma State
    "7298": "south-dakota-mines",  # South Dakota Mines
    "2576": "southern-wesleyan",   # Southern Wesleyan
    "2589": "spalding",            # Spalding
    "2590": "spring-hill",         # Spring Hill
    "244": "st-edwards",           # St. Edward's
    "2990": "st-josephs-brkln",    # St. Joseph's Brooklyn
    "3196": "st-josephs-li",       # St. Joseph's Long Island
    "2601": "st-josephs-in",       # St. Josephs (IND)
    "2610": "st-marys-tx",         # St. Mary's (TX)
    "606": "st-thomas-fl",         # St. Thomas (FL)
    "2901": "staten-island",       # Staten Island
    "111950": "richard-stockton",  # Stockton
    "111947": "suny-canton",       # SUNY Canton
    "3156": "cobleskill-st",       # SUNY Cobleskill
    "126848": "suny-delhi",        # SUNY Delhi
    "2902": "fredonia-st",         # SUNY Fredonia
    "181": "suny-new-paltz",       # SUNY New Paltz
    "16231": "old-westbury",       # SUNY Old Westbury
    "355": "oneonta-st",           # SUNY Oneonta
    "18131": "sunyit",             # SUNY Polytechnic
    "2626": "tampa",               # Tampa
    "3082": "tex-am-intl",         # Texas A&M International
    "94822": "tex-permian-basin",  # Texas Permian Basin
    "2642": "texas-wesleyan",      # Texas Wesleyan
    "2645": "thomas-me",           # Thomas College
    "2646": "thomas-more",         # Thomas More
    "2906": "trevecca-nazarene",   # Trevecca Nazarene
    "3185": "merced",              # UC Merced
    "2662": "uc-santa-cruz",       # UC Santa Cruz
    "2660": "umass-boston",        # UMass Boston
    "2666": "urbana",              # Urbana
    "110414": "valley-forge-chrst", # Valley Forge
    "185": "vassar",               # Vassar
    "2672": "va-wesleyan",         # Virginia Wesleyan
    "2684": "warren-wilson-college", # Warren Wilson
    "408": "washington-adventist", # Washington Adventist
    "50024": "washington-adventist", # Washington Adventist
    "2693": "webster",             # Webster
    "124846": "wells",             # Wells College
    "2976": "wentworth",           # Wentworth
    "2846": "wesley",              # Wesley
    "112694": "western-st",        # Western Colorado
    "7933": "western-new-eng",     # Western New England
    "224": "westminster-ut",       # Westminster (UT)
    "2716": "westmont-college",    # Westmont
    "111242": "wheaton-ma",        # Wheaton (MA)
    "450": "wheelock",             # Wheelock College
    "2720": "whitman",             # Whitman
    "108807": "william-peace",     # William Peace
    "2732": "wilmington-de",       # Wilmington (DE)
    "111914": "wilson",            # Wilson
    "401": "wis-superior",         # Wisconsin Superior
    "122196": "york-ny",           # York (NY)
    "86853": "york-pa",            # York (PA)
}


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def collect_logoless_opponents(seasons, workers=8):
    """{espnId: ESPN location name} for every opponent of a D1 team in `seasons` that ESPN
    lists with no logo and that isn't one of our D1 schools (conferences.ESPN_IDS)."""
    d1 = set(conferences.ESPN_IDS.values())
    found = {}

    def one(args):
        team_id, season = args
        try:
            data = json.loads(_get(SCHEDULE_URL.format(id=team_id, season=season)))
        except Exception:
            return []
        out = []
        for ev in data.get("events", []):
            for c in ev.get("competitions", [{}])[0].get("competitors", []):
                t = c.get("team", {})
                if t.get("id") and t["id"] not in d1 and not t.get("logos"):
                    out.append((t["id"], t.get("location") or t.get("displayName") or "?"))
        return out

    jobs = [(i, s) for s in seasons for i in sorted(d1)]
    with ThreadPoolExecutor(workers) as pool:
        for n, res in enumerate(pool.map(one, jobs), 1):
            for tid, name in res:
                found.setdefault(tid, name)
            if n % 250 == 0:
                print(f"  …{n}/{len(jobs)} schedules, {len(found)} logo-less opponents")
    return found


def fetch_ncaa_index():
    """[(slug, short name, full name)] for every school on NCAA.com's schools index."""
    rows = []
    row_re = re.compile(r'<td><a href="/schools/([^"]+)">([^<]+)</a></td>\s*<td>([^<]*)</td>')
    page = 0
    while True:
        try:
            html = _get(NCAA_INDEX_URL.format(page=page)).decode("utf-8", "replace")
        except urllib.error.HTTPError:
            break
        got = row_re.findall(html)
        if not got:
            break
        rows += [(s, _unescape(a), _unescape(b)) for s, a, b in got]
        page += 1
    return rows


def _unescape(s):
    import html as html_mod
    return html_mod.unescape(s).strip()


def _norm(name):
    s = name.lower().replace("&", " and ")
    s = re.sub(r"\bst\.?(?=\s|$)", "state", s)          # "Adams St." → "adams state"
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\b(university|college|the|of|at)\b", " ", s)
    return re.sub(r"[^a-z0-9()]", "", s)


def suggest(missing, index):
    """Print the closest NCAA.com schools for each unmapped ESPN opponent."""
    keys = {}
    for slug, short, full in index:
        for n in (short, full):
            keys.setdefault(_norm(n), []).append((slug, short, full))
    for tid, name in sorted(missing.items(), key=lambda kv: kv[1]):
        n = _norm(name)
        exact = keys.get(n)
        close = exact or [r for k in difflib.get_close_matches(n, keys, n=3, cutoff=0.75) for r in keys[k]]
        tag = "EXACT" if exact else ("maybe" if close else "none ")
        opts = "; ".join(f"{s} = {f or sh}" for s, sh, f in dict.fromkeys(close)) or "—"
        print(f"  {tag}  {tid:>7}  {name:<34} {opts}")


def _valid_svg(data):
    head = data[:400].lstrip().lower()
    if not (head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head):
        return False
    low = data.lower()
    return b"<script" not in low and b"foreignobject" not in low


def _rasterize(svg, dest):
    """Render SVG bytes with headless Chrome (transparent background) and save a WebP."""
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "logo.svg"), "wb") as f:
            f.write(svg)
        with open(os.path.join(tmp, "wrap.html"), "w") as f:
            f.write("<!doctype html><style>html,body{margin:0;background:transparent}"
                    f"img{{display:block;width:{RENDER_SIZE}px;height:{RENDER_SIZE}px;object-fit:contain}}"
                    '</style><img src="logo.svg">')
        png = os.path.join(tmp, "out.png")
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        f"--user-data-dir={os.path.join(tmp, 'profile')}",
                        "--default-background-color=00000000", f"--window-size={RENDER_SIZE},{RENDER_SIZE}",
                        f"--screenshot={png}", "file://" + os.path.join(tmp, "wrap.html")],
                       check=True, capture_output=True, timeout=90)
        im = Image.open(png).convert("RGBA")
        if not im.getbbox():
            raise ValueError("rendered blank")
        im.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS).save(dest, "WEBP", quality=90, method=6)


def _download_one(out_dir, tid, slug):
    light = os.path.join(out_dir, f"ncaa-{tid}.webp")
    dark = os.path.join(out_dir, f"ncaa-{tid}-dark.webp")
    data = _get(NCAA_LOGO_URL.format(bg="bgl", slug=slug))
    if not _valid_svg(data):
        raise ValueError("not a plain SVG")
    if b"_generic-logo" in data.lower():
        raise ValueError("NCAA.com only has its generic placeholder shield; remove it from NCAA_SLUGS")
    _rasterize(data, light)
    try:
        d = _get(NCAA_LOGO_URL.format(bg="bgd", slug=slug))
    except Exception:
        d = None   # no dark variant: the light one is used in dark mode
    if d and d != data and _valid_svg(d):
        _rasterize(d, dark)
    elif os.path.exists(dark):
        os.remove(dark)


def download(out_dir, force=False, workers=6):
    """Download + rasterize light/dark logos for every NCAA_SLUGS entry that has no file yet
    (all of them with force). Returns (got, skipped, failed)."""
    todo = [(tid, slug) for tid, slug in sorted(NCAA_SLUGS.items(), key=lambda kv: kv[1])
            if force or not os.path.exists(os.path.join(out_dir, f"ncaa-{tid}.webp"))]
    failed = []

    def one(item):
        tid, slug = item
        try:
            _download_one(out_dir, tid, slug)
            return None
        except Exception as e:
            return f"{slug} ({tid}): {e}"

    with ThreadPoolExecutor(workers) as pool:
        for n, err in enumerate(pool.map(one, todo), 1):
            if err:
                failed.append(err)
            if n % 50 == 0:
                print(f"  …{n}/{len(todo)} logos")
    return len(todo) - len(failed), len(NCAA_SLUGS) - len(todo), failed


def logo_ids(out_dir):
    """(ids with ncaa-{id}.webp, ids with ncaa-{id}-dark.webp), each sorted."""
    light, dark = [], []
    for fname in os.listdir(out_dir):
        m = re.match(r"^ncaa-(\d+)(-dark)?\.webp$", fname)
        if m:
            (dark if m.group(2) else light).append(m.group(1))
    return sorted(light, key=int), sorted(dark, key=int)


def run(out_dir, seasons, force=False):
    print(f"Collecting logo-less non-D1 opponents from ESPN schedules ({', '.join(map(str, seasons))})…")
    missing = collect_logoless_opponents(seasons)
    unmapped = {i: n for i, n in missing.items() if i not in NCAA_SLUGS}
    print(f"{len(missing)} opponents with no ESPN logo; {len(missing) - len(unmapped)} in NCAA_SLUGS.")

    got, skipped, failed = download(out_dir, force)
    print(f"✓ NCAA.com logos: downloaded {got}, skipped {skipped} existing, {len(failed)} failed.")
    for f in failed:
        print(f"  ✗ {f}")

    if unmapped:
        print(f"\n{len(unmapped)} unmapped (no NCAA_SLUGS entry). Closest NCAA.com schools "
              "(NAIA and other non-NCAA schools have none; they keep the filler logo):")
        suggest(unmapped, fetch_ncaa_index())
