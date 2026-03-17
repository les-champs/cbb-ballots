#!/usr/bin/env python3
"""
recover_2024.py — Recover missing 2024 cbbpoll.net ballot data.

Workflow:
  1. AUDIT:   Parse data-2024.html to find which voters are present per week.
              Compare against data-2025.html to identify known voters missing from 2024.

  2. RECOVER: For each missing voter+week, try:
              a. Wayback CDX API → archived poll page → __NEXT_DATA__ ballot IDs
              b. Direct ballot URL access on live cbbpoll.net
              c. User profile page fallback

  3. REPORT:  Print summary. Save recovered ballot data to cbbpoll-2024-recovery.json.

Usage:
  python3 recover_2024.py --audit            # just show what's missing
  python3 recover_2024.py --recover          # audit + attempt recovery
  python3 recover_2024.py --recover --week 19  # recover a single week only
"""

import os, re, sys, json, time, argparse
import urllib.request, urllib.error
from urllib.parse import unquote

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
BASE_URL      = "https://www.cbbpoll.net"
RECOVERY_JSON = os.path.join(BASE_DIR, "cbbpoll-2024-recovery.json")

# 2024 season weeks
WEEKS_2024 = list(range(2, 21))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def fetch_url_or_none(url, timeout=20):
    try:
        return fetch_url(url, timeout=timeout)
    except Exception as e:
        return None


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def parse_voters_from_html(html, year, weeks=None):
    """
    Parse per-week voter data from a data-YEAR.html fragment.

    Returns: dict { week_int: { 'official': {username: ballot_url}, 'provisional': {username: ballot_url} } }
    """
    data = {}

    # Find all week blocks
    block_pattern = re.compile(
        r'id="week-{year}-(\d+)"(.*?)(?=id="week-{year}-\d+"|$)'.format(year=year),
        re.DOTALL
    )
    for m in block_pattern.finditer(html):
        week = int(m.group(1))
        if weeks and week not in weeks:
            continue
        block_html = m.group(2)
        data[week] = {'official': {}, 'provisional': {}}

        # Split into official / provisional sections
        off_match = re.search(
            r'id="week-{year}-{week}-official"(.*?)(?=id="week-{year}-{week}-provisional"|id="week-{year}-{week}-aggregate"|$)'.format(year=year, week=week),
            block_html, re.DOTALL
        )
        pro_match = re.search(
            r'id="week-{year}-{week}-provisional"(.*?)(?=id="week-{year}-{week}-aggregate"|$)'.format(year=year, week=week),
            block_html, re.DOTALL
        )

        for section_key, section_match in [('official', off_match), ('provisional', pro_match)]:
            if not section_match:
                continue
            section_html = section_match.group(1)
            # Each voter: data-ballot-url="URL" ... voter-name...>USERNAME<
            voter_re = re.compile(
                r'data-ballot-url="([^"]+)".*?voter-name[^>]*>([^<]+)<',
                re.DOTALL
            )
            for vm in voter_re.finditer(section_html):
                ballot_url = vm.group(1).strip()
                username   = vm.group(2).strip()
                data[week][section_key][username] = ballot_url

        # Also capture voters WITHOUT a ballot URL (data-ballot-url missing)
        # These rows have voter-name but no data-ballot-url
        for section_key, section_match in [('official', off_match), ('provisional', pro_match)]:
            if not section_match:
                continue
            section_html = section_match.group(1)
            noballot_re = re.compile(r'voter-name[^>]*>([^<]+)<', re.DOTALL)
            for vm in noballot_re.finditer(section_html):
                username = vm.group(1).strip()
                if username not in data[week][section_key]:
                    data[week][section_key][username] = None  # present but ballot URL missing

    return data


SYNTHETIC_ROWS = {"Official Overall", "5-Week Weighted", ""}

def parse_known_voters(html_files):
    """
    Return set of real voter usernames seen across the given HTML fragment files.

    Uses data-ballot-url as a signal: only counts names that appear in voter-cell divs,
    which avoids matching JavaScript source code in index.html.
    """
    known = set()
    # Match voter-name spans that are inside a voter-cell div (have data-ballot-url nearby).
    # Uses a voter-cell class anchor to avoid false matches in embedded JS.
    voter_re = re.compile(
        r'class="voter-cell"[^>]*data-ballot-url="[^"]*".{0,400}?voter-name[^>]*>([^<]+)<',
        re.DOTALL
    )
    for path in html_files:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            html = f.read()
        for m in voter_re.finditer(html):
            name = m.group(1).strip()
            if name and name not in SYNTHETIC_ROWS:
                known.add(name)
    return known



# ---------------------------------------------------------------------------
# Ballot content fetching
# ---------------------------------------------------------------------------

# 2024 season: weeks 2-20 ran from ~Nov 13 2023 to ~Mar 21 2024
# MongoDB ObjectID first 4 bytes encode Unix timestamp.
# 2024 season ballots:   timestamps 1699800000 – 1711000000  (hex: 0x655A0000 – 0x65FA0000)
# Safe filter: first 3 hex chars in range 655–65f
BALLOT_ID_2024_PREFIX = tuple(f"{x:03x}" for x in range(0x655, 0x660))  # '655' to '65f'

def ballot_id_is_2024(ballot_id):
    """Return True if this MongoDB ObjectID was created during the 2024 CBB season."""
    return ballot_id[:3].lower() in BALLOT_ID_2024_PREFIX


def fetch_ballot_teams(ballot_url):
    """Fetch a ballot page and return ordered list of team names (up to 25)."""
    html = fetch_url_or_none(ballot_url)
    if not html:
        return None
    encoded = re.findall(r'%2Fstatic%2FD1%2F([^&"]+\.png)&(?:amp;)?w=64', html)
    teams = list(dict.fromkeys(unquote(e)[:-4] if unquote(e).lower().endswith('.png') else unquote(e)
                               for e in encoded))
    return teams[:25] if teams else None


def fetch_ballot_url_from_profile(username, week):
    """
    Find the 2024-season ballot URL for a voter's given week from their profile page.

    A voter may have TWO ballot entries for the same week number (one from 2024 season,
    one from 2026 season). We use the MongoDB ObjectID timestamp to select the 2024 one.
    """
    html = fetch_url_or_none(f"{BASE_URL}/users/{username}", timeout=15)
    if not html:
        return None
    all_ids = re.findall(rf'/ballots/{week}/([a-f0-9]{{24}})', html)
    # Prefer 2024-era ballot IDs
    for bid in all_ids:
        if ballot_id_is_2024(bid):
            return f"{BASE_URL}/ballots/{week}/{bid}"
    # Fall back to first found if no 2024 ID matched
    if all_ids:
        return f"{BASE_URL}/ballots/{week}/{all_ids[0]}"
    return None


# ---------------------------------------------------------------------------
# Core recovery logic
# ---------------------------------------------------------------------------

def recover_voter(username, weeks, profile_html=None, verbose=True):
    """
    Recover all available 2024-season ballots for one voter using their profile page.

    Fetches the profile once, then extracts all 2024 ballot IDs across all weeks.

    Returns: dict { week_int: {'ballot_url': str, 'teams': list|None, 'source': str} }
    """
    results = {}

    if profile_html is None:
        if verbose:
            print(f"  Fetching profile for {username}...")
        profile_html = fetch_url_or_none(f"{BASE_URL}/users/{username}", timeout=15)
        time.sleep(0.3)

    if not profile_html:
        if verbose:
            print(f"  ✗ Could not fetch profile for {username}")
        return results

    for week in weeks:
        all_ids = re.findall(rf'/ballots/{week}/([a-f0-9]{{24}})', profile_html)
        ballot_url = None
        for bid in all_ids:
            if ballot_id_is_2024(bid):
                ballot_url = f"{BASE_URL}/ballots/{week}/{bid}"
                break

        if not ballot_url:
            if verbose:
                print(f"  [{username}] Week {week}: no 2024 ballot ID on profile")
            continue

        if verbose:
            print(f"  [{username}] Week {week}: found 2024 ballot {ballot_url.split('/')[-1]}")
        teams = fetch_ballot_teams(ballot_url)
        time.sleep(0.3)
        if teams:
            results[week] = {'ballot_url': ballot_url, 'teams': teams, 'source': 'profile'}
            if verbose:
                print(f"    ✓ {len(teams)} teams: {teams[:3]}...")
        else:
            results[week] = {'ballot_url': ballot_url, 'teams': None, 'source': 'profile+nocontent'}
            if verbose:
                print(f"    ✗ ballot page unavailable")

    return results



# ---------------------------------------------------------------------------
# Load / save recovery JSON
# ---------------------------------------------------------------------------

def load_recovery_json():
    if os.path.exists(RECOVERY_JSON):
        with open(RECOVERY_JSON) as f:
            return json.load(f)
    return {}


def save_recovery_json(data):
    with open(RECOVERY_JSON, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nSaved recovery data to {RECOVERY_JSON}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Recover missing 2024 cbbpoll.net ballot data")
    parser.add_argument("--audit",   action="store_true", help="Show what voters are missing (no network requests for ballots)")
    parser.add_argument("--recover", action="store_true", help="Audit + attempt recovery via Wayback/profiles")
    parser.add_argument("--week",    type=int,            help="Limit to a single week (optional)")
    args = parser.parse_args()

    if not args.audit and not args.recover:
        parser.print_help()
        sys.exit(1)

    recover_weeks = [args.week] if args.week else WEEKS_2024

    # --- Load 2024 HTML (always parse ALL weeks for the audit) ---
    path_2024 = os.path.join(BASE_DIR, "data-2024.html")
    if not os.path.exists(path_2024):
        print("ERROR: data-2024.html not found")
        sys.exit(1)
    print("Parsing data-2024.html...")
    with open(path_2024) as f:
        html_2024 = f.read()
    voters_2024 = parse_voters_from_html(html_2024, 2024)  # parse all weeks for audit

    # --- Build known-voter sets from adjacent years ---
    # Only use data-YEAR.html files (not index.html, which contains embedded JS that confuses parsing)
    print("Building voter reference lists from 2023/2025 data...")
    voters_2025_set = parse_known_voters([os.path.join(BASE_DIR, "data-2025.html")])
    voters_2023_set = parse_known_voters([os.path.join(BASE_DIR, "data-2024.html")])  # placeholder — use 2023 if available
    path_2023 = os.path.join(BASE_DIR, "data-2023.html")
    if os.path.exists(path_2023):
        voters_2023_set = parse_known_voters([path_2023])
        print(f"  → {len(voters_2023_set)} unique voters in 2023")
    else:
        voters_2023_set = set()
        print("  → data-2023.html not found; using 2025-only reference")
    print(f"  → {len(voters_2025_set)} unique voters in 2025")

    # All voters seen in ANY 2024 week
    voters_in_2024 = set()
    for wdata in voters_2024.values():
        for section in ('official', 'provisional'):
            voters_in_2024.update(wdata[section].keys())
    voters_in_2024 -= SYNTHETIC_ROWS
    print(f"  → {len(voters_in_2024)} unique voters found in 2024 data")

    # Target: voters in 2025 who are completely absent from all 2024 weeks
    # These are candidates for having had 2024 ballot links removed.
    # If we also have 2023 data, restrict to those who appear in 2023 too (continuous participants).
    absent_from_2024 = voters_2025_set - voters_in_2024
    if voters_2023_set:
        suspects_2024 = absent_from_2024 & voters_2023_set  # in 2023 AND 2025, but not in 2024
        newcomers_2025 = absent_from_2024 - voters_2023_set  # new in 2025, probably didn't vote in 2024
    else:
        suspects_2024 = absent_from_2024
        newcomers_2025 = set()

    print(f"\n=== AUDIT ===")
    print(f"Voters in 2025 but ABSENT from ALL 2024 weeks: {len(absent_from_2024)}")
    if voters_2023_set:
        print(f"  → Also in 2023 (likely 2024 data deleted): {len(suspects_2024)}")
        print(f"  → Not in 2023 (new in 2025, probably didn't vote 2024): {len(newcomers_2025)}")

    if suspects_2024:
        print(f"\n--- Likely-deleted 2024 ballot accounts ({len(suspects_2024)}) ---")
        for u in sorted(suspects_2024):
            print(f"  {u}")
    elif absent_from_2024:
        print(f"\n--- Voters in 2025 absent from all 2024 weeks ({len(absent_from_2024)}) ---")
        for u in sorted(absent_from_2024):
            print(f"  {u}")
    else:
        print("\n  No voters found absent from all 2024 weeks — data may already be complete!")

    print(f"\n--- 2024 week voter counts ---")
    for week in sorted(recover_weeks):
        wdata = voters_2024.get(week, {'official': {}, 'provisional': {}})
        n_off = len(wdata.get('official', {}))
        n_pro = len(wdata.get('provisional', {}))
        print(f"  Week {week:2d}: {n_off:3d} official, {n_pro:3d} provisional")

    # For recovery: build missing_by_week using only the suspects
    # A suspect is "missing" from a week if they don't appear in any section of that week
    missing_by_week = {}
    for week in sorted(recover_weeks):
        wdata = voters_2024.get(week, {'official': {}, 'provisional': {}})
        week_present = set(wdata.get('official', {}).keys()) | set(wdata.get('provisional', {}).keys())
        week_missing = sorted(suspects_2024 - week_present)
        if week_missing:
            missing_by_week[week] = week_missing

    # Count how many weeks each suspect is missing from
    absence_count = {}
    for week, missing in missing_by_week.items():
        for u in missing:
            absence_count[u] = absence_count.get(u, 0) + 1

    if not args.recover:
        return

    if not suspects_2024:
        print("\nNo recovery needed — no suspects identified.")
        return

    # --- Recovery ---
    # Recover per-voter across all requested weeks (one profile fetch per voter).
    target_voters = suspects_2024

    print(f"\n=== RECOVERY ({len(target_voters)} target voters) ===")
    print(f"Targeting: {sorted(target_voters)}\n")

    recovery_data = load_recovery_json()

    # Check which voters are already fully cached
    voters_to_run = []
    for username in sorted(target_voters):
        cached_weeks = {int(k.split(':')[0]) for k in recovery_data if k.endswith(f':{username}')}
        if set(recover_weeks).issubset(cached_weeks):
            print(f"  {username}: all weeks already cached, skipping")
        else:
            voters_to_run.append(username)

    print()
    for i, username in enumerate(voters_to_run, 1):
        print(f"[{i}/{len(voters_to_run)}] {username}")
        # Only recover weeks not yet cached for this voter
        cached_weeks = {int(k.split(':')[0]) for k in recovery_data if k.endswith(f':{username}')}
        weeks_to_try = [w for w in recover_weeks if w not in cached_weeks]
        voter_results = recover_voter(username, weeks_to_try, verbose=True)

        for week, info in voter_results.items():
            recovery_data[f"{week}:{username}"] = info

        # Also record weeks where no ballot was found (so we don't retry)
        for week in weeks_to_try:
            key = f"{week}:{username}"
            if key not in recovery_data:
                recovery_data[key] = {'ballot_url': None, 'teams': None, 'source': 'not_found'}

        # Save after each voter
        save_recovery_json(recovery_data)

    # --- Final summary ---
    print("\n=== RECOVERY SUMMARY ===")
    total_recovered   = sum(1 for v in recovery_data.values() if v.get('teams'))
    total_nocontent   = sum(1 for v in recovery_data.values() if v.get('ballot_url') and not v.get('teams'))
    total_not_found   = sum(1 for v in recovery_data.values() if not v.get('ballot_url'))
    print(f"  Full recovery (ballot + teams): {total_recovered}")
    print(f"  URL found but no content:       {total_nocontent}")
    print(f"  Not found on profile:           {total_not_found}")
    print(f"\nFull results saved to: {RECOVERY_JSON}")
    print("\nRun with --apply after reviewing to integrate into data-2024.html")


if __name__ == "__main__":
    main()
