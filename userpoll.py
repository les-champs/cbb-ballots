import os
import re
import json
import time
import argparse
import urllib.request
from io import BytesIO
from urllib.parse import unquote
from PIL import Image

# Output directory for logos
OUTPUT_DIR = "/Users/adam/Library/Mobile Documents/com~apple~CloudDocs/Code/Userpoll/cbb-logos"
BASE_HTML_DIR = "/Users/adam/Library/Mobile Documents/com~apple~CloudDocs/Code/Userpoll"
HTML_PATH = os.path.join(BASE_HTML_DIR, "index.html")

BASE_URL = "https://www.cbbpoll.net"
LOGO_PATH_PREFIX = "/static/D1/"

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

def fetch_ballot_url_for_week(username, week, year=None):
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
        # Store as WebP regardless of source filename
        webp_name = logo[:-4] + ".webp" if logo.lower().endswith(".png") else logo
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
                ballot_url = fetch_ballot_url_for_week(username, week, year=year)
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

# ── HTML Building ────────────────────────────────────────────────────────────

def build_table_rows(voters_with_ballots):
    rows = ""
    for logo_filename, username, ballot_url, ballot_logos in voters_with_ballots:
        team_name = logo_filename.replace(".png", "")
        ballot_attr = f' data-ballot-url="{ballot_url}"' if ballot_url else ''
        # Use actual src so images load when opening the file locally; keep data-src for compatibility
        img_path = logo_filename[:-4]  # team name only e.g. "Duke"
        inner = (
            f'<img class="logo" data-src="{img_path}" alt="{team_name}">'
            f'<span class="voter-name">{username}</span>'
        )
        voter_cell = f'<div class="voter-cell" {ballot_attr}>{inner}</div>'
        ballot_logo_cells = "".join(
            f'<td class="logo-cell"><img class="logo team-logo" data-team="{bl.replace(".png","")}" data-src="{bl[:-4]}"></td>'
            for bl in ballot_logos
        )
        rows += f'<tr class="voter-row"><td>{voter_cell}</td>{ballot_logo_cells}</tr>\n'
    return rows

def build_aggregate_row(official):
    """Build a single aggregate row from official ballots using points system (rank 1=25pts ... rank 25=1pt)."""
    points = {}
    for _, _, _, ballot_logos in official:
        for i, logo in enumerate(ballot_logos[:25]):
            team = logo.replace(".png", "")
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

RANK_HEADERS = "".join(f"<th>{i+1}</th>" for i in range(25))
THEAD_HTML = (
    f"<thead><tr>"
    f"<th><span class='voters-toggle' style='cursor:pointer; display:inline-block; transition:transform 0.1s ease;'>Alphabetic</span>"
    f"<span class='sort-picker'>"
    f"<span class='sort-option active' data-sort='alphabetic'>Alphabetic</span>"
    f"<span class='sort-option' data-sort='consensus'>Consensus</span>"
    f"<span class='sort-option' data-sort='ranking'>Précision</span>"
    f"<span class='sort-option' data-sort='tenure'>Tenure</span>"
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
    overflow-x: auto;
}

.table-container {
    width: 100%;
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

#voter-history-modal {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.55);
    z-index: 1000;
    justify-content: center;
    align-items: center;
}
#voter-history-modal.open {
    display: flex;
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
const highlightClasses = [
    "team-highlight-1","team-highlight-2","team-highlight-3",
    "team-highlight-4","team-highlight-5"
];

function lazyLoadWeek(block) {
    if (!block) return;
    block.querySelectorAll("img[data-src]").forEach(img => {
        img.src = "cbb-logos/" + img.dataset.src + ".webp";
        img.removeAttribute("data-src");
    });
}

function getSortedTabs() {
    return Array.from(document.querySelectorAll(".week-tab"))
        .sort((a, b) => parseInt(b.dataset.year) - parseInt(a.dataset.year) || parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum));
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

function hideRankHeaders(block) {
    if (!block) return;
    block.querySelectorAll("table thead th:not(:first-child)").forEach(th => { th.style.color = "transparent"; th.style.borderRight = "none"; });
}

function showRankHeaders(block) {
    if (!block) return;
    block.querySelectorAll("table thead th:not(:first-child)").forEach(th => { th.style.color = ""; th.style.borderRight = ""; });
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
    document.querySelectorAll(".consensus-dist").forEach(el => el.remove());
    document.querySelectorAll(".rank-score-label").forEach(el => el.remove());
    rankingSortActive = false;
    const sort = opt.dataset.sort;
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
        const weekId = activeTab.dataset.week;
        const sections = block.querySelectorAll(".ballot-section");
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

function showVoterHistory(username) {
    const allTabsSorted = getSortedTabs();

    // Build merged ballot data (official + provisional) for all weeks
    const mergedData = {};
    document.querySelectorAll(".week-tab").forEach(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        if (!block) return;
        mergedData[weekId] = {};
        block.querySelectorAll(".ballot-section").forEach(section => {
            section.querySelectorAll(".voter-row").forEach(row => {
                const uname = getVoterName(row);
                if (!uname || uname === "Official Overall") return;
                if (!mergedData[weekId][uname]) {
                    mergedData[weekId][uname] = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
                }
            });
        });
    });

    // Use the active week's year
    const activeTab = document.querySelector(".week-tab.active");
    const currentYear = activeTab?.dataset.year || allTabsSorted[0]?.dataset.year;
    const yearTabs = allTabsSorted
        .filter(t => t.dataset.year === currentYear)
        .reverse();

    const modal = document.getElementById("voter-history-modal");
    const title = document.getElementById("voter-history-title");
    const table = document.getElementById("voter-history-table");

    title.textContent = username + " — Season Ballots";
    table.innerHTML = "";

    // Header row: rank columns 1–25
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
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    yearTabs.forEach(tab => {
        const weekId = tab.dataset.week;
        const teams = mergedData[weekId]?.[username];
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
    table.appendChild(tbody);
    modal.classList.add("open");
    bindTeamLogos();
    // Apply any active highlight classes to the newly created logos
    highlightClasses.forEach(cls => {
        const highlighted = document.querySelector(`.team-logo.${cls}`);
        if (highlighted) {
            const team = highlighted.dataset.team;
            table.querySelectorAll(`.team-logo[data-team="${team}"]`).forEach(img => img.classList.add(cls));
        }
    });
}

document.getElementById("voter-history-modal").addEventListener("click", e => {
    if (e.target === e.currentTarget) e.currentTarget.classList.remove("open");
});

function bindTeamLogos() {
    document.querySelectorAll(".team-logo").forEach(logo => {
        if (logo.dataset.bound) return;
        logo.dataset.bound = "1";
        logo.addEventListener("click", () => {
            const team = logo.dataset.team;
            const teamElements = Array.from(document.querySelectorAll(`.team-logo[data-team="${team}"]`));
            const isHighlighted = teamElements.some(el => highlightClasses.some(c => el.classList.contains(c)));
            if (isHighlighted) {
                teamElements.forEach(el => highlightClasses.forEach(c => el.classList.remove(c)));
            } else {
                const usedColors = highlightClasses.filter(c => document.querySelector("." + c));
                const availableColor = highlightClasses.find(c => !usedColors.includes(c));
                if (availableColor) teamElements.forEach(el => el.classList.add(availableColor));
            }
        });
    });
}

let weekPickerPinned = false;
const isMobile = () => screen.width <= 768;

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
        btn.addEventListener("click", e => {
            e.stopPropagation();
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
    }

    const toggleText = document.getElementById("toggle-text").innerText;
    const isProvisional = !isMobile() && toggleText === "Provisional Ballots";
    const isAggregate = !isMobile() && toggleText === "Aggregate Ballots";
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
    bindVoterCells();
    bindVotersToggle();
    updateRankingOptionVisibility();
    if (currentSort && currentSort !== "ranking") {
        applyTableSort(currentSort);
    }
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
    updateRankingOptionVisibility();
    if (currentSort === "ranking") resetRankingSort();
    applyTableSort(currentSort);
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

function showAggregateSection() {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const activeBlock = document.getElementById(activeTab.dataset.week);
    if (!activeBlock) return;
    const sections = activeBlock.querySelectorAll(".ballot-section");
    if (!sections[2]) return;
    sections.forEach(s => s.style.display = "none");
    sections[2].style.display = "block";
    document.getElementById("toggle-text").innerText = "Aggregate Ballots";
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

function backgroundLoad() {
    const queue = getBackgroundImageQueue();
    if (queue.length === 0) return;

    let index = 0;
    const CONCURRENCY = 6; // load 6 images at a time
    let active = 0;

    function loadNext() {
        while (active < CONCURRENCY && index < queue.length) {
            // Skip images already loaded
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
    }

    // Stagger the start slightly to not compete with the current week's load
    setTimeout(loadNext, 1000);
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
    return data;
}

function buildDeltaData() {
    const isProvisional = document.getElementById("toggle-text")?.innerText === "Provisional Ballots";
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


// Keyboard shortcuts
let rankingSortActive = false;

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

document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
        document.getElementById("voter-history-modal").classList.remove("open");
    }
    if (!e.shiftKey) return;
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;

    const currentWeekNum = parseInt(activeTab.dataset.weeknum);
    const currentYear = activeTab.dataset.year;

    if (e.key === "A" || e.key === "a") {
        e.preventDefault();
        showAggregateSection();
        return;
    }

    if (e.key === "D" || e.key === "d") {
        e.preventDefault();
        toggleAllDeltas();
        return;
    }

    if (e.key === "J" || e.key === "j") {
        e.preventDefault();
        sortByRanking();
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
        const sortedAll = getSortedTabs().reverse();
        const idx = sortedAll.findIndex(t => t.dataset.week === activeTab.dataset.week);
        const target = e.key === "ArrowRight"
            ? sortedAll[idx + 1]
            : sortedAll[idx - 1];
        if (target) {
            showWeek(target.dataset.week);
            if (weekPickerPinned) rebuildWeekPicker();
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
        const yearTabs = tabs.filter(t => t.dataset.year === targetYear);
        const sameWeek = yearTabs.find(t => parseInt(t.dataset.weeknum) === currentWeekNum);
        const target = sameWeek || yearTabs.sort((a, b) => parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum))[0];
        if (target) {
            showWeek(target.dataset.week);
            if (weekPickerPinned) rebuildWeekPicker();
        }
    }
});

// Init
rebuildYearPicker();
rebuildWeekPicker();
const allTabs = getSortedTabs();
if (allTabs.length > 0) {
    showWeek(allTabs[0].dataset.week);
    setTimeout(() => backgroundLoad(), 1000);
}
"""

WEEK_TABS_MARKER = "<!-- WEEK-TABS -->"
WEEK_DATA_MARKER = "<!-- WEEK-DATA -->"

def build_full_html(week_tabs_html, week_data_html):
    return f"""<!DOCTYPE html>
<html>
<head>
<title>Userpoll Landscape</title>
<meta charset="UTF-8">
<meta name="viewport" content="width=1200, user-scalable=yes">
<link rel="icon" href="data:,">
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

{WEEK_DATA_MARKER}
{week_data_html}
<script>
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

    # Extract existing week data blocks
    data_match = re.search(
        r'<!-- WEEK-DATA -->\n(.*?)(?=\n\n?<script>)',
        content, re.DOTALL
    )
    data_html = data_match.group(1).strip() if data_match else ""

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

    full_html = build_full_html(tabs_html, data_html)
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
    tabs_html = remove_week_tab(tabs_html, week_id)
    data_html = remove_week_block(data_html, week_id)
    full_html = build_full_html(tabs_html.strip(), data_html.strip())
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

    full_html = build_full_html(tabs_html, data_html)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"✓ Rebuilt HTML with {len(week_ids)} weeks.")

def main():
    parser = argparse.ArgumentParser(description="Scrape CBB Poll ballots and generate HTML.")
    parser.add_argument("--week", type=int, help="Poll week number (e.g. 18)")
    parser.add_argument("--year", type=int, help="Poll year (e.g. 2026)")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild HTML from existing data without scraping")
    parser.add_argument("--to-webp", action="store_true", help="Convert all existing PNG logos to WebP and exit")
    parser.add_argument("--delete", action="store_true", help="Delete a specific week from the HTML")
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