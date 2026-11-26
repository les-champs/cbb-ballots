"""Voter profiles → profiles-YEAR.json (the PIN-locked Profile window, voter menu › Profile).

How each official voter tends to vote over a season, measured against the rest of the poll,
ESPN's BPI / Strength of Record and game results. Computed at build time by write_index()
in userpoll.py (so every --rebuild and week scrape refreshes it) for Userpoll seasons
>= FIRST_SEASON. Provisional ballots are never used.

Measures (one value per voter, plus a per-week distance series):
    dist  Distance from consensus: weighted mean |voter rank - consensus rank| over the
          voter's teams + the consensus top 25, weighted toward the top (weight 26 - best of
          the two ranks). Consensus = points (25 for #1 .. 1 for #25) from every *other*
          official ballot that week. Unranked = #26 throughout.
    lead  Ahead of the poll: correlation between (voter rank - consensus rank) this week and
          the consensus's move to next week, pooled over the season.
    loss  Loss penalty: mean rank change of the voter's teams that lost since the previous
          poll minus that of the voter's teams that didn't (needs MIN_LOSSES losing teams).
    vol   Weekly movement: mean |rank change| per ballot slot between consecutive ballots.
    mid   Mid-major lean: mid-majors on the ballot minus mid-majors in the consensus top 25.
    lean  Résumé vs predictive (seasons >= LEAN_FROM): on teams where that week's BPI and SOR
          ranks (capped at 26) differ by LEAN_MIN_GAP+, (|r - BPI| - |r - SOR|) / |BPI - SOR|,
          averaged with weight |BPI - SOR|. -1 = sits on BPI, +1 = sits on SOR. Uses the BPI
          snapshot matched to the poll deadline the same way script.js's bpiSnapshotForTab()
          does. Seasons before 2027 have only a final snapshot, so no lean.

Game results come from games-YEAR.json (`--games`: every balloted team's ESPN schedule,
completed games only, with start times), refreshed daily for the current season by the
refresh-quads workflow. Without it, loss is null.

    {"season": 2027, "minBallots": 3, "weeks": [0, 2, 3], "leanWeeks": [2, 3],
     "consLean": 0.21, "fieldDist": {"2": 1.8}, "fieldLean": {"2": 0.2},
     "voters": [{"name", "ballots", "leanBallots", "nLoss", "dist", "lead", "loss", "vol",
                 "mid", "lean", "weekly": [[week, dist, lean|null], ...]}, ...]}
"""

import datetime
import json
import math
import os
import re
import statistics as st

import conferences
import quads

FIRST_SEASON = 2025
LEAN_FROM = 2027
CAP = 26
LEAN_MIN_GAP = 5
MIN_LOSSES = 5
BPI_MATCH_BEFORE = 4 * 86400        # seconds; same window as BPI_MATCH_*_MS in script.js
BPI_MATCH_AFTER = 12 * 3600
NOT_VOTERS = {"Official Overall", "AP Overall", "Recency"}


# ── Ballots ──────────────────────────────────────────────────────────────────

def parse_season(html, year):
    """Official ballots per week from a season's week blocks → [{week, deadline, ballots}].

    deadline = the week's latest ballot creation time (unix s) over all its ballots, like
    pollDeadline() in script.js; None when the week has no cbbpoll.net ballot ids."""
    weeks = []
    for block in re.split(rf'(?=<div [^>]*id="week-{year}-\d+")', html):
        m = re.match(rf'<div [^>]*id="week-{year}-(\d+)"', block)
        if not m:
            continue
        ids = re.findall(r'cbbpoll\.net/ballots/[^/"]+/([0-9a-f]{24})', block)
        deadline = max((int(i[:8], 16) for i in ids), default=None)
        off = re.search(rf'id="week-{year}-{m.group(1)}-official"(.*?)(?=id="week-{year}-{m.group(1)}-|$)', block, re.S)
        ballots = {}
        for row in re.findall(r'<tr class="voter-row">(.*?)</tr>', off.group(1) if off else "", re.S):
            name = re.search(r'class="voter-name"[^>]*>([^<]+)<', row)
            if not name or name.group(1).strip() in NOT_VOTERS:
                continue
            teams = re.findall(r'<img class="logo team-logo" data-team="([^"]+)"', row)
            if len(teams) >= 25:
                ballots[name.group(1).strip()] = teams[:25]
        if ballots:
            weeks.append({"week": int(m.group(1)), "deadline": deadline, "ballots": ballots})
    return sorted(weeks, key=lambda w: w["week"])


def season_html(base_dir, year):
    """A season's week blocks from disk: data-YEAR.html, else index.html (the current season)."""
    for name in (f"data-{year}.html", "index.html"):
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                html = f.read()
            if f'id="week-{year}-' in html:
                return html
    return ""


# ── Game results (games-YEAR.json) ───────────────────────────────────────────

def fetch_games(base_dir, season):
    """Completed games of every team on the season's official ballots → games-YEAR.json."""
    weeks = parse_season(season_html(base_dir, season), season)
    teams = sorted({t for w in weeks for b in w["ballots"].values() for t in b})
    if not teams:
        print(f"  ✗ games {season}: no ballots found")
        return False
    ids = {t: conferences.ESPN_IDS.get(conferences.canonical(t)) for t in teams}
    missing = [t for t, i in ids.items() if not i]
    todo = [t for t in teams if ids[t]]
    res = quads._pmap(lambda t: quads.schedule(season, ids[t]), todo)
    games, failed = {}, []
    for t in todo:
        g = res[t]
        if isinstance(g, Exception):
            failed.append(t)
            continue
        games[t] = [[x["date"], x["result"]] for x in g if x["result"]]
    path = os.path.join(base_dir, f"games-{season}.json")
    old = None
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
    if failed and old:   # keep the last good schedule of a team whose fetch failed
        for t in failed:
            if t in old.get("teams", {}):
                games[t] = old["teams"][t]
    payload = {"season": season, "teams": dict(sorted(games.items()))}
    if payload != old:
        with open(path, "w") as f:
            json.dump(payload, f, separators=(",", ":"))
            f.write("\n")
    print(f"  ✓ games {season}: {len(games)} teams → {os.path.basename(path)}"
          + (f"; fetch failed: {', '.join(failed)}" if failed else "")
          + (f"; no ESPN id: {', '.join(missing)}" if missing else ""))
    return not failed


def _load_json(base_dir, name):
    path = os.path.join(base_dir, name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _losses_by_team(games):
    """{team: [loss start times (unix s)]}."""
    out = {}
    for team, gs in (games or {}).get("teams", {}).items():
        out[team] = [datetime.datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp()
                     for d, r in gs if r == "L"]
    return out


# ── BPI / SOR snapshots ──────────────────────────────────────────────────────

def _snapshot_for(snaps, deadline):
    """Latest snapshot within [deadline - 4 d, deadline + 12 h] (bpiSnapshotForTab())."""
    if not deadline:
        return None
    fit = [s for s in snaps if deadline - BPI_MATCH_BEFORE <= s["at"] <= deadline + BPI_MATCH_AFTER]
    return fit[-1] if fit else None


def _load_snaps(base_dir, season):
    d = _load_json(base_dir, f"bpi-{season}.json") or {}
    snaps = []
    for s in d.get("snapshots", []):
        if not s.get("sor"):
            continue
        at = datetime.datetime.strptime(s["asOf"].replace("Z", "+0000"), "%Y-%m-%dT%H:%M%z").timestamp()
        snaps.append({"at": at, "bpi": {t[0]: t[1] for t in s["teams"]}, "sor": {t[0]: t[1] for t in s["sor"]}})
    return sorted(snaps, key=lambda s: s["at"])


# ── Measures ─────────────────────────────────────────────────────────────────

def _cons_rank(ballots, exclude=None):
    pts = {}
    for v, b in ballots.items():
        if v == exclude:
            continue
        for i, t in enumerate(b):
            pts[t] = pts.get(t, 0) + 25 - i
    return {t: i + 1 for i, t in enumerate(sorted(pts, key=lambda t: (-pts[t], t)))}


def _rk(ranks, team):
    return min(ranks.get(team, CAP), CAP)


def _brank(ballot):
    return {t: i + 1 for i, t in enumerate(ballot)}


def _top25(ranks):
    return {t for t, r in ranks.items() if r <= 25}


def _dist(vr, cr):
    num = den = 0
    for t in sorted(set(vr) | _top25(cr)):
        a, c = _rk(vr, t), _rk(cr, t)
        w = CAP - min(a, c)
        num += w * abs(a - c)
        den += w
    return num / den if den else 0.0


def _lean_items(vr, snap):
    out = []
    for t in sorted(set(snap["bpi"]) | set(snap["sor"])):
        b, s = min(snap["bpi"].get(t, CAP), CAP), min(snap["sor"].get(t, CAP), CAP)
        if abs(b - s) < LEAN_MIN_GAP or min(b, s) > 25:
            continue
        r = _rk(vr, t)
        out.append(((abs(r - b) - abs(r - s)) / abs(b - s), abs(b - s)))
    return out


def _wmean(items):
    den = sum(w for _, w in items)
    return sum(v * w for v, w in items) / den if den else None


def _corr(x, y):
    if len(x) < 3:
        return None
    mx, my = st.mean(x), st.mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else None


def _r(x, nd=3):
    return None if x is None else round(x, nd)


def compute(season, weeks, losses, snaps):
    counts = {}
    for w in weeks:
        for v in w["ballots"]:
            counts[v] = counts.get(v, 0) + 1
    min_ballots = max(3, math.ceil(len(weeks) / 2))
    pop = sorted((v for v, n in counts.items() if n >= min_ballots), key=str.lower)
    tier = lambda t: conferences.tier(t, season)  # noqa: E731
    acc = {v: {"weekly": [], "lead": ([], []), "loss": [], "vol": [], "mid": [], "lean": [], "leanBallots": 0}
           for v in pop}
    field_dist, field_lean, cons_lean, lean_weeks = {}, {}, [], []

    for i, w in enumerate(weeks):
        B = w["ballots"]
        prv = weeks[i - 1] if i > 0 else None
        nxt = weeks[i + 1] if i + 1 < len(weeks) else None
        snap = _snapshot_for(snaps, w["deadline"]) if season >= LEAN_FROM and w["week"] != 0 else None
        if snap:
            lean_weeks.append(w["week"])
            cons_lean += _lean_items({t: r for t, r in _cons_rank(B).items() if r <= 25}, snap)
        dists, leans = [], []
        for v in pop:
            if v not in B:
                continue
            a = acc[v]
            vr, cr = _brank(B[v]), _cons_rank(B, v)
            d = _dist(vr, cr)
            dists.append(d)
            lean = None
            if snap:
                items = _lean_items(vr, snap)
                a["lean"] += items
                a["leanBallots"] += 1
                lean = _wmean(items)
                if lean is not None:
                    leans.append(lean)
            a["weekly"].append([w["week"], round(d, 2), _r(lean, 2)])
            a["mid"].append(sum(tier(t) == "Mid-Major" for t in B[v])
                            - sum(tier(t) == "Mid-Major" for t in _top25(cr)))
            if nxt:
                cn = _cons_rank(nxt["ballots"], v)
                for t in sorted(set(vr) | _top25(cr)):
                    a["lead"][0].append(_rk(vr, t) - _rk(cr, t))
                    a["lead"][1].append(_rk(cn, t) - _rk(cr, t))
            if prv and v in prv["ballots"]:
                pr = _brank(prv["ballots"][v])
                a["vol"].append(sum(abs(_rk(vr, t) - _rk(pr, t)) for t in sorted(set(pr) | set(vr))) / 25)
                if w["week"] != 0 and prv["deadline"] and w["deadline"] and losses:
                    for t in pr:
                        lost = any(prv["deadline"] < g <= w["deadline"] for g in losses.get(t, ()))
                        a["loss"].append((lost, _rk(vr, t) - _rk(pr, t)))
        if dists:
            field_dist[str(w["week"])] = round(st.median(dists), 2)
        if leans:
            field_lean[str(w["week"])] = round(st.median(leans), 2)

    voters = []
    for v in pop:
        a = acc[v]
        lost = [d for l, d in a["loss"] if l]
        kept = [d for l, d in a["loss"] if not l]
        voters.append({
            "name": v,
            "ballots": counts[v],
            "leanBallots": a["leanBallots"],
            "nLoss": len(lost),
            "dist": _r(st.mean(d for _, d, _ in a["weekly"])) if a["weekly"] else None,
            "lead": _r(_corr(*a["lead"])),
            "loss": _r(st.mean(lost) - st.mean(kept)) if len(lost) >= MIN_LOSSES and kept else None,
            "vol": _r(st.mean(a["vol"])) if a["vol"] else None,
            "mid": _r(st.mean(a["mid"])) if a["mid"] else None,
            "lean": _r(_wmean(a["lean"])),
            "weekly": a["weekly"],
        })
    return {
        "season": season,
        "minBallots": min_ballots,
        "weeks": [w["week"] for w in weeks],
        "leanWeeks": lean_weeks,
        "consLean": _r(_wmean(cons_lean)),
        "fieldDist": field_dist,
        "fieldLean": field_lean,
        "hasGames": bool(losses),
        "voters": voters,
    }


def build(base_dir, data_by_year, excluded=()):
    """Write profiles-YEAR.json for every season >= FIRST_SEASON in data_by_year ({year: html})."""
    for year, html in sorted(data_by_year.items()):
        season = int(year)
        if season < FIRST_SEASON or str(year) in excluded:
            continue
        weeks = parse_season(html, season)
        if not weeks:
            continue
        losses = _losses_by_team(_load_json(base_dir, f"games-{season}.json"))
        payload = compute(season, weeks, losses, _load_snaps(base_dir, season))
        path = os.path.join(base_dir, f"profiles-{season}.json")
        if payload != _load_json(base_dir, f"profiles-{season}.json"):
            with open(path, "w") as f:
                json.dump(payload, f, separators=(",", ":"))
                f.write("\n")
        print(f"  ✓ profiles {season}: {len(payload['voters'])} voters ({payload['minBallots']}+ ballots), "
              f"{len(weeks)} weeks, lean weeks {payload['leanWeeks'] or 'none'}"
              + ("" if losses else ", no games file (loss penalty off)"))
