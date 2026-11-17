"""Weekly ESPN BPI snapshots → bpi-YEAR.json (the "BPI" row of Data Ballots).

ESPN only serves BPI as of now (`powerindex` has no by-week form for college basketball:
"getSeasonPowerIndexesByWeek() not supported"), and a past season's endpoint returns its
final, post-tournament BPI. So the week-by-week history has to be recorded as it happens:
the daily refresh-quads workflow runs `--bpi`, which adds today's snapshot and keeps only the
latest one per poll week, i.e. the one taken on the poll's Monday morning (ESPN updates BPI
overnight, ~09:00 UTC; polls close Mondays 10 AM ET).

    {"season": 2027,
     "snapshots": [{"asOf": "2026-11-16T09:08Z", "final": false,
                    "teams": [[key, rank, bpi], ...]}, ...]}   # top KEEP teams by BPI rank

`asOf` is ESPN's lastUpdated. `key` is our canonical team name (conferences.ESPN_IDS), or
"espn:ID" for a team missing there. `final` marks a snapshot taken after the season ended
(April of the season year or later, or fetched once the season is over), which the page
matches to the season's last week.
Running `--bpi --year Y` for a past season records its final BPI; `--year 0` does all.
"""

import datetime
import json
import os
import urllib.request
from zoneinfo import ZoneInfo

import conferences

URL = ("https://site.web.api.espn.com/apis/fitt/v3/sports/basketball/mens-college-basketball/"
       "powerindex?region=us&lang=en&limit=500&season={season}")
KEEP = 100
ET = ZoneInfo("America/New_York")


def _parse_time(s):
    return datetime.datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M%z")


def is_final(season, as_of):
    """After the title game (April), or any snapshot of a season already over (2020 had none)."""
    over = datetime.datetime.now(ET) >= datetime.datetime(season, 5, 1, tzinfo=ET)
    return over or _parse_time(as_of) >= datetime.datetime(season, 4, 1, tzinfo=ET)


def poll_monday(as_of):
    """The poll a snapshot feeds: its own ET date if that's a Monday, else the next Monday."""
    d = _parse_time(as_of).astimezone(ET).date()
    return (d + datetime.timedelta(days=-d.weekday() % 7)).isoformat()


def fetch(season):
    req = urllib.request.Request(URL.format(season=season), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    names = data["categories"][0]["names"]
    i_bpi, i_rank = names.index("bpi"), names.index("bpirank")
    key_of = {str(v): k for k, v in conferences.ESPN_IDS.items()}
    rows = []
    for t in data.get("teams", []):
        cat = next((c for c in t["categories"] if c["name"] == "bpi"), None)
        if not cat or cat["values"][i_rank] is None:
            continue
        tid = str(t["team"]["id"])
        rows.append([key_of.get(tid, f"espn:{tid}"), int(cat["values"][i_rank]),
                     round(cat["values"][i_bpi], 1)])
    rows.sort(key=lambda r: (r[1], -r[2]))
    if len(rows) < 300:
        raise ValueError(f"only {len(rows)} teams in ESPN's BPI for {season}")
    as_of = data.get("lastUpdated")
    return {"asOf": as_of, "final": is_final(season, as_of), "teams": rows[:KEEP]}


def merge(snapshots, snap):
    """Add snap, keeping the latest snapshot per poll Monday (and one final)."""
    best = {}
    for s in snapshots + [snap]:
        group = "final" if s.get("final") else poll_monday(s["asOf"])
        if group not in best or s["asOf"] >= best[group]["asOf"]:
            best[group] = s
    return sorted(best.values(), key=lambda s: s["asOf"])


def run(base_dir, season):
    path = os.path.join(base_dir, f"bpi-{season}.json")
    try:
        snap = fetch(season)
    except (OSError, ValueError, KeyError) as e:
        print(f"  ✗ BPI {season}: {e}")
        return False
    old = {"season": season, "snapshots": []}
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
    payload = {"season": season, "snapshots": merge(old["snapshots"], snap)}
    if payload != old:
        with open(path, "w") as f:
            json.dump(payload, f, separators=(",", ":"))
            f.write("\n")
    unmapped = [t[0] for t in snap["teams"] if t[0].startswith("espn:")]
    print(f"  ✓ BPI {season} as of {snap['asOf']}{' (final)' if snap['final'] else ''}: "
          f"#1 {snap['teams'][0][0]}, {len(payload['snapshots'])} snapshot(s) → {os.path.basename(path)}"
          + (f"; not in ESPN_IDS: {', '.join(unmapped)}" if unmapped else ""))
    return True
