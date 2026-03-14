"""
CBB Poll Ranking Simulator
Mirrors the JS scoring equation in userpoll.py exactly.

Scoring summary:
  - Base distance: each week's ballot vs finalRanking (5-week weighted avg of last 5 consensus)
  - Position weight: 1.0 at #1 → 0.5 at #25 (linear)
  - Week weight: 0.5 at week 1 → 1.0 at final week (linear)
  - Boldness: bold+correct calls vs consensus, accumulated (week-weighted), capped at 20% of avg
  - Miss penalty: +10 per missed week; 4+ misses → disqualified
  - Combined score: avg - min(boldAdj, avg * 0.20)  [lower is better]

Usage:
  python3 poll_simulator.py                          # run all built-in demos
  python3 poll_simulator.py --from-json ballots.json # score real ballot data
  python3 poll_simulator.py --from-json ballots.json --year 2025
  python3 poll_simulator.py --from-json ballots.json --year 2025 --week week-18-2025
  python3 poll_simulator.py --sensitivity            # sensitivity analysis
  python3 poll_simulator.py --scenario               # scenario testing
  python3 poll_simulator.py --params                 # parameter tuning
"""

import json
import random
import itertools
import argparse
from copy import deepcopy
from typing import Optional

# ---------------------------------------------------------------------------
# Parameters (mirrors JS constants — edit here to test sensitivity)
# ---------------------------------------------------------------------------
PARAMS = {
    "pos_weight_min":   0.5,    # weight at #25
    "pos_weight_max":   1.0,    # weight at #1
    "week_weight_min":  0.5,    # weight at week 1
    "week_weight_max":  1.0,    # weight at final week
    "boldness_scalar":  0.05,   # flat multiplier on boldness gain
    "boldness_cap":     0.0,    # disabled — set to 0 to remove cap entirely
    "miss_penalty":     10,     # added distance per missed week
    "max_misses":       4,      # misses >= this → disqualified
    "final_avg_weeks":  5,      # how many weeks to average for finalRanking
}

TEAMS = [f"T{i:02d}" for i in range(1, 51)]  # 50 teams to draw from


# ---------------------------------------------------------------------------
# Core scoring functions
# ---------------------------------------------------------------------------

def pos_weight(rank: int, p=None) -> float:
    """Position weight: p['pos_weight_max'] at #1, p['pos_weight_min'] at #25."""
    if p is None:
        p = PARAMS
    return p["pos_weight_max"] - (rank - 1) * (
        (p["pos_weight_max"] - p["pos_weight_min"]) / 24
    )


def week_weight(week_idx: int, total_weeks: int, p=None) -> float:
    """Week weight: p['week_weight_min'] at week 0, p['week_weight_max'] at final week."""
    if p is None:
        p = PARAMS
    if total_weeks <= 1:
        return 1.0
    return p["week_weight_min"] + (week_idx / (total_weeks - 1)) * (
        p["week_weight_max"] - p["week_weight_min"]
    )


def ballot_distance(ballot: list, reference: list, p=None) -> float:
    """
    Position-weighted distance between a ballot and reference ranking.
    Unranked teams treated as #26.
    """
    if p is None:
        p = PARAMS
    dist = 0.0
    for i, team in enumerate(reference):
        rank = i + 1
        vr = ballot.index(team) + 1 if team in ballot else 26
        dist += abs(rank - vr) * pos_weight(rank, p)
    for vi, team in enumerate(ballot):
        if team not in reference:
            dist += abs((vi + 1) - 26) * pos_weight(vi + 1, p)
    return dist


def build_final_ranking(consensus_weeks: list[list], p=None) -> list:
    """
    Build finalRanking as weighted avg of last N consensus weeks.
    Most recent week gets weight N, oldest gets weight 1.
    Mirrors JS finalRanking computation.
    """
    if p is None:
        p = PARAMS
    n = p["final_avg_weeks"]
    last_n = [w for w in consensus_weeks if w][-n:]
    if not last_n:
        return []
    points = {}
    for wi, ranking in enumerate(last_n):
        weight = len(last_n) - wi  # most recent = highest
        for i, team in enumerate(ranking):
            points[team] = points.get(team, 0) + (25 - i) * weight
    return [t for t, _ in sorted(points.items(), key=lambda x: -x[1])][:25]


def score_voters(
    voter_ballots: dict[str, list[Optional[list]]],
    consensus_weeks: list[list],
    p=None,
    verbose=False,
) -> dict[str, dict]:
    """
    Score all voters.

    Args:
        voter_ballots: {username: [ballot_week1, ballot_week2, ...]}
                       Each ballot is a list of 25 team names, or None if missed.
        consensus_weeks: [consensus_week1, consensus_week2, ...]
                         Each is a list of 25 team names.
        p: parameter dict (defaults to PARAMS)
        verbose: print per-voter breakdown

    Returns:
        {username: {avg, bold_adj, combined, missed, weeks}}
        Lower combined = better.
    """
    if p is None:
        p = PARAMS

    total_weeks = len(consensus_weeks)
    final_ranking = build_final_ranking(consensus_weeks, p)

    # Field average per week (for miss penalty fallback)
    field_avg = []
    for wk_idx, consensus in enumerate(consensus_weeks):
        dists = []
        for ballots in voter_ballots.values():
            b = ballots[wk_idx] if wk_idx < len(ballots) else None
            if b:
                dists.append(ballot_distance(b, final_ranking, p))
        field_avg.append(sum(dists) / len(dists) if dists else 0)

    results = {}
    for username, ballots in voter_ballots.items():
        total = 0.0
        total_ww = 0.0
        bold_adj = 0.0
        missed = 0
        last_ballot = None

        for wk_idx, consensus in enumerate(consensus_weeks):
            ww = week_weight(wk_idx, total_weeks, p)
            ballot = ballots[wk_idx] if wk_idx < len(ballots) else None

            if ballot:
                dist = ballot_distance(ballot, final_ranking, p)
                total += dist * ww
                total_ww += ww
                last_ballot = ballot

                # Boldness
                week_bold = 0.0
                week_weight_sum = 0.0
                for i, team in enumerate(final_ranking):
                    final_rank = i + 1
                    voter_rank = ballot.index(team) + 1 if team in ballot else 26
                    consensus_rank = consensus.index(team) + 1 if team in consensus else 26
                    deviation = abs(voter_rank - consensus_rank)
                    if deviation > 0:
                        scalar = p["boldness_scalar"]
                        weight = deviation
                        consensus_dist = abs(consensus_rank - final_rank)
                        voter_dist = abs(voter_rank - final_rank)
                        gain = consensus_dist - voter_dist
                        if gain > 0:
                            week_bold += gain * weight * scalar * pos_weight(final_rank, p)
                            week_weight_sum += weight
                if week_weight_sum > 0:
                    bold_adj += (week_bold / week_weight_sum) * ww

            else:
                miss_dist = (
                    ballot_distance(last_ballot, final_ranking, p)
                    if last_ballot
                    else field_avg[wk_idx]
                ) + p["miss_penalty"]
                total += miss_dist * ww
                total_ww += ww
                missed += 1

        if missed >= p["max_misses"]:
            results[username] = {
                "avg": float("inf"),
                "bold_adj": 0,
                "combined": float("inf"),
                "missed": missed,
                "weeks": total_weeks,
                "disqualified": True,
            }
            continue

        avg = total / total_ww if total_ww > 0 else 0
        combined = avg - bold_adj

        results[username] = {
            "avg": round(avg, 3),
            "bold_adj": round(bold_adj, 3),
            "bold_adj_capped": round(bold_adj, 3),
            "combined": round(combined, 3),
            "missed": missed,
            "weeks": total_weeks,
            "disqualified": False,
            "bold_capped": False,
        }

        if verbose:
            print(f"  {username:20s}  avg={avg:.3f}  bold={bold_adj:.3f}  combined={combined:.3f}  missed={missed}")

    return results


def print_leaderboard(results: dict, title="Leaderboard"):
    """Print sorted leaderboard."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(f"  {'Rank':<5} {'Voter':<20} {'Avg':>7} {'Bold':>7} {'Combined':>9} {'Missed':>7} {'Notes'}")
    print(f"  {'-'*60}")
    sorted_voters = sorted(results.items(), key=lambda x: x[1]["combined"])
    for rank, (username, r) in enumerate(sorted_voters, 1):
        if r.get("disqualified"):
            print(f"  {'DQ':<5} {username:<20} {'—':>7} {'—':>7} {'—':>9} {r['missed']:>7}  (too many misses)")
        else:
            cap = " ⚠ bold capped" if r.get("bold_capped") else ""
            print(f"  {rank:<5} {username:<20} {r['avg']:>7.3f} {r['bold_adj_capped']:>7.3f} {r['combined']:>9.3f} {r['missed']:>7}{cap}")


# ---------------------------------------------------------------------------
# --from-json: score real ballot data extracted from index.html
# ---------------------------------------------------------------------------

def derive_consensus(week_ballots: dict[str, list]) -> list:
    """
    Derive a consensus ranking from a week's set of voter ballots.
    Each voter's #1 pick gets 25 pts, #2 gets 24 pts, ..., #25 gets 1 pt.
    Returns top-25 teams sorted by total points.
    """
    points = {}
    for ballot in week_ballots.values():
        for i, team in enumerate(ballot[:25]):
            points[team] = points.get(team, 0) + (25 - i)
    return [t for t, _ in sorted(points.items(), key=lambda x: -x[1])][:25]


def load_and_score_json(
    json_path: str,
    filter_year: Optional[str] = None,
    filter_week: Optional[str] = None,
    verbose: bool = False,
):
    """
    Load ballots.json (produced by the browser extractor), build consensus
    weeks, and score all voters.

    JSON structure:
        {
          "2025": {
            "week-1-2025":  { "VoterA": ["TeamX", "TeamY", ...], ... },
            "week-2-2025":  { ... },
            ...
          },
          "2026": { ... }
        }
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    years = sorted(data.keys())
    if filter_year:
        if filter_year not in data:
            print(f"✗ Year '{filter_year}' not found. Available: {', '.join(years)}")
            return
        years = [filter_year]

    for year in years:
        year_data = data[year]

        # Sort weeks by their numeric week number embedded in the key (e.g. "week-18-2025" → 18)
        def week_sort_key(k):
            parts = k.split("-")
            for part in parts:
                if part.isdigit():
                    return int(part)
            return 0

        week_keys = sorted(year_data.keys(), key=week_sort_key)

        if filter_week:
            if filter_week not in year_data:
                print(f"✗ Week '{filter_week}' not found in {year}. Available: {', '.join(week_keys)}")
                continue
            week_keys = [filter_week]

        print(f"\n{'#'*60}")
        print(f"  Year: {year}  |  Weeks: {', '.join(week_keys)}")
        print(f"{'#'*60}")

        # Build ordered list of (week_key, ballots_dict)
        weeks_ordered = [(k, year_data[k]) for k in week_keys]

        # Collect all voters seen across all weeks
        all_voters = set()
        for _, week_ballots in weeks_ordered:
            all_voters.update(week_ballots.keys())

        # Build per-voter ballot list (None if voter missed a week)
        voter_ballots = {v: [] for v in all_voters}
        consensus_weeks = []

        for _, week_ballots in weeks_ordered:
            consensus = derive_consensus(week_ballots)
            consensus_weeks.append(consensus)
            for voter in all_voters:
                ballot = week_ballots.get(voter)  # None if voter missed this week
                voter_ballots[voter].append(ballot)

        print(f"\n  {len(all_voters)} voters across {len(weeks_ordered)} weeks")
        print(f"  finalRanking (top 10): {build_final_ranking(consensus_weeks)[:10]}")

        results = score_voters(voter_ballots, consensus_weeks, verbose=verbose)
        title = f"Leaderboard — {year}" + (f" {filter_week}" if filter_week else "")
        print_leaderboard(results, title)


# ---------------------------------------------------------------------------
# Data generators (used by demos)
# ---------------------------------------------------------------------------

def perfect_ballot(reference: list) -> list:
    return list(reference[:25])


def random_ballot(reference: list, noise: float = 5.0) -> list:
    teams = list(reference[:25])
    ranks = list(range(25))
    noisy = [(r + random.gauss(0, noise), t) for r, t in zip(ranks, teams)]
    noisy.sort(key=lambda x: x[0])
    return [t for _, t in noisy]


def ahead_of_consensus_ballot(reference: list, consensus: list, team: str, voter_rank: int) -> list:
    b = list(reference[:25])
    if team in b:
        b.remove(team)
    b.insert(voter_rank - 1, team)
    return b[:25]


def consensus_plus_one_ballot(consensus: list, final_ranking: list) -> list:
    b = list(consensus[:25])
    best_gain = 0
    best_swap = None
    for i, team in enumerate(final_ranking[:25]):
        final_rank = i + 1
        consensus_rank = consensus.index(team) + 1 if team in consensus else 26
        gain = abs(consensus_rank - final_rank)
        if gain > best_gain:
            best_gain = gain
            best_swap = (team, final_rank)
    if best_swap:
        team, target_rank = best_swap
        if team in b:
            b.remove(team)
        b.insert(min(target_rank - 1, len(b)), team)
    return b[:25]


def consensus_plus_1_miss_ballots(
    consensus_weeks: list,
    final_ranking: list,
    miss_rate: float = 0.3,
    standout_threshold: float = 5.0,
    spot_miss_rate: float = 0.0,
) -> list:
    ballots = []
    for consensus in consensus_weeks:
        best_gain = 0
        best_swap = None
        for i, team in enumerate(final_ranking[:25]):
            final_rank = i + 1
            consensus_rank = consensus.index(team) + 1 if team in consensus else 26
            gain = abs(consensus_rank - final_rank)
            if gain > best_gain:
                best_gain = gain
                best_swap = (team, final_rank)
        if best_gain < standout_threshold:
            ballots.append(list(consensus[:25]))
            continue
        if random.random() < spot_miss_rate:
            ballots.append(list(consensus[:25]))
            continue
        if random.random() < miss_rate:
            b = list(consensus[:25])
            team, final_rank = best_swap
            consensus_rank = consensus.index(team) + 1 if team in consensus else 26
            wrong_rank = min(25, final_rank + (consensus_rank - final_rank) * 2)
            if team in b:
                b.remove(team)
            b.insert(min(max(0, int(wrong_rank) - 1), len(b)), team)
            ballots.append(b[:25])
        else:
            ballots.append(consensus_plus_one_ballot(consensus, final_ranking))
    return ballots


def streaky_ballots(final_ranking: list, num_weeks: int, good_noise=1.5, bad_noise=12.0) -> list:
    ballots = []
    for wk in range(num_weeks):
        noise = good_noise if wk % 2 == 0 else bad_noise
        ballots.append(random_ballot(final_ranking, noise=noise))
    return ballots


def lucky_ballots(final_ranking: list, consensus_weeks: list, lucky_start: int = 10) -> list:
    ballots = []
    for wk, consensus in enumerate(consensus_weeks):
        if wk < lucky_start:
            ballots.append(random_ballot(consensus, noise=12.0))
        else:
            ballots.append(random_ballot(final_ranking, noise=1.5))
    return ballots


def contrarian_ballots(consensus_weeks: list, flip_fraction: float = 0.8) -> list:
    ballots = []
    for consensus in consensus_weeks:
        b = list(consensus[:25])
        n = int(len(b) * flip_fraction)
        top = b[:n]
        b[:n] = list(reversed(top))
        ballots.append(b)
    return ballots


def generate_season(
    num_weeks: int = 18,
    num_teams: int = 30,
    true_ranking: Optional[list] = None,
    consensus_noise: float = 3.0,
    clarity: float = 1.0,
) -> tuple[list, list]:
    if true_ranking is None:
        true_ranking = random.sample(TEAMS[:num_teams], 25)
    base_noise = consensus_noise * (2.0 - clarity)
    convergence_strength = 0.4 + clarity * 0.6
    consensus_weeks = []
    for wk in range(num_weeks):
        convergence = wk / max(num_weeks - 1, 1)
        noise = base_noise * (1 - convergence * convergence_strength)
        consensus_weeks.append(random_ballot(true_ranking, noise))
    return true_ranking, consensus_weeks


# ---------------------------------------------------------------------------
# Demos (unchanged from v1)
# ---------------------------------------------------------------------------

def demo_sanity_check():
    print("\n" + "=" * 60)
    print("DEMO 1: Sanity Check")
    print("Perfect voter (matches finalRanking exactly) should rank #1")
    print("=" * 60)

    random.seed(42)
    true_ranking, consensus_weeks = generate_season(num_weeks=18)
    final_ranking = build_final_ranking(consensus_weeks)

    voter_ballots = {
        "perfect":              [perfect_ballot(final_ranking)] * 18,
        "near_perfect_a":       [random_ballot(final_ranking, noise=1.0) for _ in range(18)],
        "near_perfect_b":       [random_ballot(final_ranking, noise=1.0) for _ in range(18)],
        "average_a":            [random_ballot(final_ranking, noise=5.0) for _ in range(18)],
        "average_b":            [random_ballot(final_ranking, noise=5.0) for _ in range(18)],
        "noisy_a":              [random_ballot(final_ranking, noise=10.0) for _ in range(18)],
        "noisy_b":              [random_ballot(final_ranking, noise=10.0) for _ in range(18)],
        "contrarian_a":         contrarian_ballots(consensus_weeks, flip_fraction=0.8),
        "contrarian_b":         contrarian_ballots(consensus_weeks, flip_fraction=0.6),
        "consensus_plus_1_a":   [consensus_plus_one_ballot(c, final_ranking) for c in consensus_weeks],
        "consensus_plus_1_b":   [consensus_plus_one_ballot(c, final_ranking) for c in consensus_weeks],
        "cp1_miss30_a":         consensus_plus_1_miss_ballots(consensus_weeks, final_ranking, miss_rate=0.3, standout_threshold=5.0),
        "cp1_miss30_b":         consensus_plus_1_miss_ballots(consensus_weeks, final_ranking, miss_rate=0.3, standout_threshold=8.0, spot_miss_rate=0.2),
        "streaky_a":            streaky_ballots(final_ranking, 18, good_noise=1.5, bad_noise=12.0),
        "streaky_b":            streaky_ballots(final_ranking, 18, good_noise=3.0, bad_noise=9.0),
    }

    results = score_voters(voter_ballots, consensus_weeks, verbose=True)
    print_leaderboard(results, "Sanity Check — Perfect voter should be #1")


def demo_scenario():
    print("\n" + "=" * 60)
    print("DEMO 2: Scenario — voter ranks team at #1 for 6 weeks")
    print("Consensus only catches up in the final 5 weeks")
    print("=" * 60)

    random.seed(42)
    num_weeks = 18
    true_ranking, consensus_weeks = generate_season(num_weeks=num_weeks)

    true_ranking[0] = "T01"
    final_ranking = build_final_ranking(consensus_weeks)
    if "T01" in final_ranking:
        final_ranking.remove("T01")
    final_ranking.insert(0, "T01")

    modified_consensus = []
    for wk, c in enumerate(consensus_weeks):
        c2 = list(c)
        if "T01" in c2:
            c2.remove("T01")
        if wk < 13:
            c2.insert(19, "T01")
        else:
            c2.insert(wk - 13, "T01")
        modified_consensus.append(c2[:25])

    bold_ballots, consensus_ballots, avg_ballots = [], [], []
    for wk, c in enumerate(modified_consensus):
        bold_b = list(c)
        if "T01" in bold_b:
            bold_b.remove("T01")
        bold_b.insert(0, "T01")
        bold_ballots.append(bold_b[:25])
        consensus_ballots.append(list(c[:25]))
        avg_b = list(c)
        if "T01" in avg_b:
            avg_b.remove("T01")
        avg_b.insert(4, "T01")
        avg_ballots.append(avg_b[:25])

    voter_ballots = {
        "bold_correct":       bold_ballots,
        "consensus_follower": consensus_ballots,
        "middle_ground":      avg_ballots,
    }

    print(f"\n  T01 consensus rank by week: {[c.index('T01') + 1 if 'T01' in c else 26 for c in modified_consensus]}")
    print(f"  T01 final ranking position: {final_ranking.index('T01') + 1 if 'T01' in final_ranking else 'NR'}")

    results = score_voters(voter_ballots, modified_consensus, verbose=True)
    print_leaderboard(results, "Scenario — Bold correct voter vs consensus follower")


def demo_sensitivity():
    print("\n" + "=" * 60)
    print("DEMO 3: Sensitivity Analysis")
    print("How much do parameter changes affect relative rankings?")
    print("=" * 60)

    random.seed(42)
    num_weeks = 18
    true_ranking, consensus_weeks = generate_season(num_weeks=num_weeks)
    final_ranking = build_final_ranking(consensus_weeks)

    voter_ballots = {
        "accurate_a":           [random_ballot(final_ranking, noise=2.0) for _ in range(18)],
        "accurate_b":           [random_ballot(final_ranking, noise=2.0) for _ in range(18)],
        "bold_a":               [random_ballot(final_ranking, noise=8.0) for _ in range(18)],
        "bold_b":               [random_ballot(final_ranking, noise=8.0) for _ in range(18)],
        "consensus_a":          [random_ballot(c, noise=1.0) for c in consensus_weeks],
        "consensus_b":          [random_ballot(c, noise=1.0) for c in consensus_weeks],
        "late_good_a":          [random_ballot(final_ranking, noise=10.0) for _ in range(9)] +
                                [random_ballot(final_ranking, noise=1.0) for _ in range(9)],
        "late_good_b":          [random_ballot(final_ranking, noise=10.0) for _ in range(9)] +
                                [random_ballot(final_ranking, noise=1.0) for _ in range(9)],
        "consensus_plus_1_a":   [consensus_plus_one_ballot(c, final_ranking) for c in consensus_weeks],
        "consensus_plus_1_b":   [consensus_plus_one_ballot(c, final_ranking) for c in consensus_weeks],
        "cp1_miss30_a":         consensus_plus_1_miss_ballots(consensus_weeks, final_ranking, miss_rate=0.3, standout_threshold=5.0),
        "cp1_miss30_b":         consensus_plus_1_miss_ballots(consensus_weeks, final_ranking, miss_rate=0.3, standout_threshold=8.0, spot_miss_rate=0.2),
        "streaky_a":            streaky_ballots(final_ranking, 18, good_noise=1.5, bad_noise=12.0),
        "streaky_b":            streaky_ballots(final_ranking, 18, good_noise=3.0, bad_noise=9.0),
        "contrarian_a":         contrarian_ballots(consensus_weeks, flip_fraction=0.8),
        "contrarian_b":         contrarian_ballots(consensus_weeks, flip_fraction=0.6),
    }

    param_variants = {
        "baseline":           dict(PARAMS),
        "no_pos_weight":      dict(PARAMS, pos_weight_min=1.0, pos_weight_max=1.0),
        "strong_pos_weight":  dict(PARAMS, pos_weight_min=0.1, pos_weight_max=1.0),
        "no_week_weight":     dict(PARAMS, week_weight_min=1.0, week_weight_max=1.0),
        "strong_week_weight": dict(PARAMS, week_weight_min=0.1, week_weight_max=1.0),
        "higher_bold_cap":    dict(PARAMS, boldness_cap=0.40),
        "no_bold_cap":        dict(PARAMS, boldness_cap=1.0),
        "weaker_boldness":    dict(PARAMS, boldness_scalar=20),
        "stronger_boldness":  dict(PARAMS, boldness_scalar=5),
    }

    print(f"\n  {'Variant':<22}", end="")
    voters = list(voter_ballots.keys())
    for v in voters:
        print(f"  {v:>12}", end="")
    print()
    print(f"  {'-'*80}")

    for variant_name, p in param_variants.items():
        results = score_voters(voter_ballots, consensus_weeks, p=p)
        sorted_voters = sorted(results.items(), key=lambda x: x[1]["combined"])
        ranks = {u: i + 1 for i, (u, _) in enumerate(sorted_voters)}
        print(f"  {variant_name:<22}", end="")
        for v in voters:
            print(f"  {'#'+str(ranks[v]):>12}", end="")
        print()


def demo_parameter_tuning():
    print("\n" + "=" * 60)
    print("DEMO 4: Parameter Tuning")
    print("Which param combos most consistently rank 'accurate' voter #1?")
    print("=" * 60)

    random.seed(0)
    num_trials = 50
    num_weeks = 18

    pos_weight_mins = [0.3, 0.5, 0.7, 1.0]
    week_weight_mins = [0.3, 0.5, 0.7, 1.0]
    boldness_caps = [0.10, 0.20, 0.30]

    results_summary = {}

    for pw_min, ww_min, b_cap in itertools.product(pos_weight_mins, week_weight_mins, boldness_caps):
        p = dict(PARAMS, pos_weight_min=pw_min, week_weight_min=ww_min, boldness_cap=b_cap)
        accurate_wins = 0

        for _ in range(num_trials):
            true_ranking, consensus_weeks = generate_season(num_weeks=num_weeks)
            final_ranking = build_final_ranking(consensus_weeks, p)
            voter_ballots = {
                "accurate_a":         [random_ballot(final_ranking, noise=2.0) for _ in range(num_weeks)],
                "accurate_b":         [random_ballot(final_ranking, noise=2.0) for _ in range(num_weeks)],
                "average_a":          [random_ballot(final_ranking, noise=5.0) for _ in range(num_weeks)],
                "average_b":          [random_ballot(final_ranking, noise=5.0) for _ in range(num_weeks)],
                "bold_a":             [random_ballot(final_ranking, noise=9.0) for _ in range(num_weeks)],
                "bold_b":             [random_ballot(final_ranking, noise=9.0) for _ in range(num_weeks)],
                "consensus_a":        [random_ballot(c, noise=1.0) for c in consensus_weeks],
                "consensus_b":        [random_ballot(c, noise=1.0) for c in consensus_weeks],
                "consensus_plus_1_a": [consensus_plus_one_ballot(c, final_ranking) for c in consensus_weeks],
                "consensus_plus_1_b": [consensus_plus_one_ballot(c, final_ranking) for c in consensus_weeks],
                "cp1_miss30_a":       consensus_plus_1_miss_ballots(consensus_weeks, final_ranking, miss_rate=0.3),
                "cp1_miss30_b":       consensus_plus_1_miss_ballots(consensus_weeks, final_ranking, miss_rate=0.3),
                "streaky_a":          streaky_ballots(final_ranking, num_weeks, good_noise=1.5, bad_noise=12.0),
                "streaky_b":          streaky_ballots(final_ranking, num_weeks, good_noise=3.0, bad_noise=9.0),
                "contrarian_a":       contrarian_ballots(consensus_weeks, flip_fraction=0.8),
                "contrarian_b":       contrarian_ballots(consensus_weeks, flip_fraction=0.6),
            }
            r = score_voters(voter_ballots, consensus_weeks, p=p)
            sorted_r = sorted(r.items(), key=lambda x: x[1]["combined"])
            winner = sorted_r[0][0]
            if winner.startswith("accurate"):
                accurate_wins += 1

        key = f"pw={pw_min} ww={ww_min} bcap={b_cap}"
        results_summary[key] = accurate_wins / num_trials

    print(f"\n  {'Parameters':<35} {'Accurate wins #1':>18}")
    print(f"  {'-'*55}")
    for key, win_rate in sorted(results_summary.items(), key=lambda x: -x[1]):
        bar = "█" * int(win_rate * 20)
        print(f"  {key:<35} {win_rate:>6.1%}  {bar}")

    best = max(results_summary.items(), key=lambda x: x[1])
    print(f"\n  ✓ Best params: {best[0]}  ({best[1]:.1%} win rate for accurate voter)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CBB Poll Ranking Simulator")
    parser.add_argument("--from-json",   metavar="FILE",   help="Score real ballot data from ballots.json")
    parser.add_argument("--year",        metavar="YEAR",   help="Filter to a specific year (e.g. 2025)")
    parser.add_argument("--week",        metavar="WEEK",   help="Filter to a specific week key (e.g. week-18-2025)")
    parser.add_argument("--verbose",     action="store_true", help="Print per-voter breakdown")
    parser.add_argument("--sanity",      action="store_true", help="Run sanity check demo")
    parser.add_argument("--scenario",    action="store_true", help="Run scenario demo")
    parser.add_argument("--sensitivity", action="store_true", help="Run sensitivity analysis")
    parser.add_argument("--params",      action="store_true", help="Run parameter tuning")
    parser.add_argument("--all",         action="store_true", help="Run all demos")
    args = parser.parse_args()

    if args.from_json:
        load_and_score_json(
            json_path=args.from_json,
            filter_year=args.year,
            filter_week=args.week,
            verbose=args.verbose,
        )
    else:
        run_all = args.all or not any([args.sanity, args.scenario, args.sensitivity, args.params])
        if args.sanity or run_all:
            demo_sanity_check()
        if args.scenario or run_all:
            demo_scenario()
        if args.sensitivity or run_all:
            demo_sensitivity()
        if args.params or run_all:
            demo_parameter_tuning()