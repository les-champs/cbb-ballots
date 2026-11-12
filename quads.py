"""Quadrant records computed from game results + a team ranking → quads-YEAR.json.

The NCAA's official quadrants (net_rankings.py) only exist once NET is published, usually
early December. Before that, this module computes the same thing with ESPN's BPI rank
standing in for NET, so the site can show Q1–Q4 records from the first week of the season.

How a game is classified (official NCAA cutoffs, by the opponent's *current* rank and
the game site):

             Home      Neutral    Away
    Q1       1–30      1–50       1–75
    Q2       31–75     51–100     76–135
    Q3       76–160    101–200    136–240
    Q4       161+      201+       241+

Only games against D1 opponents count (as for NET); games vs non-D1 are tallied as nonD1.
Every completed game counts, including conference tournaments and the postseason.

Rank sources (--rank-source):
    bpi   ESPN's BPI rank (sports.core.api.espn.com powerindex, one request per team)
    net   NET ranks from net-YEAR.json (run --net first). Used to check this module against
          the NCAA's official quadrant counts, and to compute game-level quads after NET is out
    auto  (default) net if net-YEAR.json exists for the season, else bpi
Each team also gets its BPI score and offense / defense components (bpi, off, def), fetched
whatever the rank source (the Records tab shows them).

Data: ESPN schedules (site.web.api.espn.com, seasontype 2 and 3) for every D1 school in
conferences.SEASONS[year], i.e. ~730 schedule requests + ~365 BPI requests, 8 at a time.

Run through userpoll.py:
    python3 userpoll.py --quads [--year 2027] [--rank-source bpi|net|auto]
    python3 userpoll.py --quads --year 2026 --rank-source net --check   # compare vs net-2026.json
"""

import datetime
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import conferences

SCHEDULE_URL = ("https://site.web.api.espn.com/apis/site/v2/sports/basketball/"
                "mens-college-basketball/teams/{id}/schedule?season={season}&seasontype={type}")
BPI_URL = ("https://sports.core.api.espn.com/v2/sports/basketball/leagues/"
           "mens-college-basketball/seasons/{season}/powerindex/{id}")
WORKERS = 8

# Upper rank bound of Q1, Q2, Q3 per site (anything above the Q3 bound is Q4).
CUTOFFS = {"H": (30, 75, 160), "N": (50, 100, 200), "A": (75, 135, 240)}


def quadrant(opp_rank, site):
    for q, bound in enumerate(CUTOFFS[site], 1):
        if opp_rank <= bound:
            return q
    return 4


def _get_json(url, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == tries - 1:
                raise
        except (OSError, ValueError):
            if attempt == tries - 1:
                raise
        time.sleep(1 + attempt)


def _pmap(fn, items):
    """fn over items, WORKERS at a time → {item: result or Exception}."""
    def safe(x):
        try:
            return fn(x)
        except Exception as e:  # noqa: BLE001 — reported per item by the caller
            return e
    with ThreadPoolExecutor(WORKERS) as ex:
        return dict(zip(items, ex.map(safe, items)))


def d1_teams(season):
    """{espnId: ourKey} for every D1 school that season (conferences.py)."""
    teams = conferences.SEASONS.get(season)
    if not teams:
        raise ValueError(f"conferences.py has no D1 list for {season}")
    missing = [t for t in teams if t not in conferences.ESPN_IDS]
    if missing:
        raise ValueError(f"no ESPN id for {missing} (add to conferences.ESPN_IDS)")
    return {conferences.ESPN_IDS[t]: t for t in teams}


def bpi_ranks(season, ids):
    """{espnId: BPI rank}, {espnId: {bpi, off, def}} (scores, 1 decimal), the latest
    lastUpdated seen, and [(espnId, error)] for teams without a rank."""
    def one(i):
        d = _get_json(BPI_URL.format(season=season, id=i))
        if not d:
            return None
        stats = {s.get("name"): s.get("value") for s in d.get("stats", [])}
        rank = stats.get("bpirank")
        if not rank:
            return None
        score = {k: round(stats[n], 1) for k, n in
                 (("bpi", "bpi"), ("off", "bpioffense"), ("def", "bpidefense"))
                 if stats.get(n) is not None}
        return int(rank), score, d.get("lastUpdated")
    got = _pmap(one, list(ids))
    ranks, scores, stamps, bad = {}, {}, [], []
    for i, r in got.items():
        if isinstance(r, tuple):
            ranks[i], scores[i] = r[0], r[1]
            if r[2]:
                stamps.append(r[2])
        else:
            bad.append((i, r))
    return ranks, scores, max(stamps) if stamps else None, bad


def net_ranks(season, base_dir, key_to_id):
    path = os.path.join(base_dir, f"net-{season}.json")
    with open(path) as f:
        net = json.load(f)
    ranks = {key_to_id[k]: v["rank"] for k, v in net["teams"].items() if k in key_to_id}
    return ranks, net["through"], net


def schedule(season, team_id):
    """Completed and upcoming games (dedup by event id) → list of dicts."""
    events, seen = [], set()
    for t in (2, 3):
        d = _get_json(SCHEDULE_URL.format(id=team_id, season=season, type=t))
        if d is None and t == 2:   # 404 is normal for postseason (3), not the regular season
            raise ValueError(f"no regular-season schedule for ESPN id {team_id}")
        for ev in (d or {}).get("events", []):
            if ev["id"] not in seen:
                seen.add(ev["id"])
                events.append(ev)
    games = []
    for ev in events:
        c = (ev.get("competitions") or [None])[0]
        if not c:
            continue
        me = next((x for x in c["competitors"] if x["team"]["id"] == str(team_id)), None)
        op = next((x for x in c["competitors"] if x is not me), None)
        if not me or not op:
            continue
        done = bool(c.get("status", {}).get("type", {}).get("completed"))
        score = lambda x: (x.get("score") or {}).get("value")  # noqa: E731
        games.append({
            "id": ev["id"],
            "date": ev["date"],
            "site": "N" if c.get("neutralSite") else ("H" if me["homeAway"] == "home" else "A"),
            "oppId": op["team"]["id"],
            "result": ("W" if me.get("winner") else "L") if done else None,
            "us": score(me) if done else None,
            "them": score(op) if done else None,
        })
    games.sort(key=lambda g: g["date"])
    return games


def build(season, base_dir, rank_source="auto"):
    id_to_key = d1_teams(season)
    key_to_id = {k: i for i, k in id_to_key.items()}
    net_path = os.path.join(base_dir, f"net-{season}.json")
    if rank_source == "auto":
        rank_source = "net" if os.path.exists(net_path) else "bpi"

    print(f"  Ranks: {rank_source.upper()} for {len(id_to_key)} D1 teams...")
    # BPI scores (BPI / Off / Def) are fetched with either rank source.
    bpi_rank, bpi_scores, bpi_as_of, bad = bpi_ranks(season, id_to_key)
    if rank_source == "net":
        ranks, ranks_as_of, _ = net_ranks(season, base_dir, key_to_id)
    else:
        ranks, ranks_as_of = bpi_rank, bpi_as_of
    for i, err in bad:
        print(f"    ⚠ no BPI for {id_to_key[i]} ({err or 'not listed'})")
    if len(ranks) < 0.95 * len(id_to_key):
        raise ValueError(f"only {len(ranks)} of {len(id_to_key)} teams have a rank")

    print(f"  Schedules: {len(id_to_key)} teams × 2 requests...")
    scheds = _pmap(lambda i: schedule(season, i), list(id_to_key))
    failed = [id_to_key[i] for i, s in scheds.items() if isinstance(s, Exception)]
    if failed:
        raise ValueError(f"schedule fetch failed for {len(failed)} teams: {failed[:10]}")

    teams = {}
    for team_id, games in scheds.items():
        rec = {f"q{q}": [0, 0] for q in range(1, 5)}
        rec["nonD1"] = [0, 0]
        out = []
        for g in games:
            opp_rank = ranks.get(g["oppId"]) if g["oppId"] in id_to_key else None
            quad = quadrant(opp_rank, g["site"]) if opp_rank else None
            if g["result"]:
                bucket = f"q{quad}" if quad else ("nonD1" if g["oppId"] not in id_to_key else None)
                if bucket:
                    rec[bucket][0 if g["result"] == "W" else 1] += 1
            out.append({
                "date": g["date"][:10], "site": g["site"],
                "opp": id_to_key.get(g["oppId"]), "oppId": g["oppId"],
                "oppRank": opp_rank, "quad": quad,
                "result": g["result"], "us": g["us"], "them": g["them"],
            })
        entry = {"rank": ranks.get(team_id)}
        entry.update(bpi_scores.get(team_id, {}))
        entry.update({k: f"{w}-{l}" for k, (w, l) in rec.items()})
        entry["games"] = out
        teams[id_to_key[team_id]] = entry

    return {
        "season": season,
        "rankSource": rank_source,
        "ranksAsOf": ranks_as_of,
        "bpiAsOf": bpi_as_of,
        "fetched": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "cutoffs": CUTOFFS,
        "teams": dict(sorted(teams.items(), key=lambda kv: kv[1]["rank"] or 9999)),
    }


def check_against_net(payload, base_dir):
    """Compare computed Q1–Q4 records to the NCAA's official ones. Returns mismatch count."""
    with open(os.path.join(base_dir, f"net-{payload['season']}.json")) as f:
        net = json.load(f)["teams"]
    mismatches = []
    for key, mine in payload["teams"].items():
        off = net.get(key)
        if not off:
            continue
        diff = {q: (mine[q], off[q]) for q in ("q1", "q2", "q3", "q4") if mine[q] != off[q]}
        if diff:
            mismatches.append((key, diff))
    print(f"  Check vs official NET quads: {len(payload['teams']) - len(mismatches)}"
          f"/{len(payload['teams'])} teams match exactly")
    for key, diff in mismatches[:25]:
        print(f"    {key}: " + ", ".join(f"{q} ours {a} vs NCAA {b}" for q, (a, b) in diff.items()))
    if len(mismatches) > 25:
        print(f"    … {len(mismatches) - 25} more")
    return len(mismatches)


def run(base_dir, season, rank_source="auto", check=False):
    print(f"Computing quadrant records for {season}...")
    try:
        payload = build(season, base_dir, rank_source)
    except (OSError, ValueError) as e:
        print(f"  ✗ {e}")
        return False
    if check:
        check_against_net(payload, base_dir)
    path = os.path.join(base_dir, f"quads-{season}.json")
    with open(path, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
        f.write("\n")
    top = next(iter(payload["teams"].items()))
    print(f"  ✓ {len(payload['teams'])} teams, ranks: {payload['rankSource']} as of "
          f"{payload['ranksAsOf']} → {os.path.basename(path)} "
          f"({os.path.getsize(path) // 1024} KB; #1 {top[0]} Q1 {top[1]['q1']})")
    return True
