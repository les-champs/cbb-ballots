# Userpoll — CBB Poll Voter Visualizer

Scraper + static site generator for college basketball poll ballots. `userpoll.py` scrapes voter ballots (r/CollegeBasketball userpoll from cbbpoll.net / legacy cbbpoll.com, plus AP Top 25 from collegepolltracker.com) and generates `index.html` and `ap-ballots.html`, inlining `style.css` and `script.js` at build time.

- **Live:** https://www.userpoll-landscape.com/ (custom domain via `CNAME`; `les-champs.github.io/cbb-ballots/` redirects there)
- **Repo:** `les-champs/cbb-ballots`, branch `main` only. Push to `main` → GitHub Pages serves from root.
- No build tooling, no tests, no package manager. Python 3 stdlib + PIL; vanilla JS.

## Golden rules

1. **Edit only source files:** `script.js`, `style.css`, `userpoll.py` (and `poll_simulator.py`). Everything else at the root is generated.
2. **After any change to `script.js`, `style.css`, or HTML templates in `userpoll.py`, run `python3 userpoll.py --rebuild`.** This regenerates `index.html`, `ap-ballots.html`, and all fragment files. Commit source + regenerated output together.
3. **Never read generated or data files whole.** They are huge (`index.html` ≈ 5 MB, each `data-*.html` 3–7 MB, `cbbpoll-*.json`/`ap25-*.json` ~1–2 MB, `ballots.json` 2 MB). Use `grep -n`/`grep -c`, `head`, or `python3 -c` with `json` to inspect specific pieces. Do not open `ballots.json` at all.
4. **`script.js` is ~4,300 lines and `userpoll.py` ~2,300.** Locate code with `grep -n "function name"` and read targeted ranges rather than the whole file.
5. Features automatically appear on both `index.html` and `ap-ballots.html` (same inlined CSS/JS). Always consider both pages, and AP mode on `index.html`, when changing JS.
6. When changing the Précision formula in `computeVoterAvg()` (JS), keep `score_voters()` in `poll_simulator.py` in sync.

## Files

```
userpoll.py            # Scrapers + HTML generator + CLI (source)
script.js              # All client-side JS (source, inlined at build)
style.css              # All CSS (source, inlined at build)
poll_simulator.py      # Python mirror of the Précision formula for tuning
recover_2024.py        # One-off: recovered missing 2024 ballots via Wayback → cbbpoll-2024-recovery.json
index.html             # GENERATED — main site; only the current year's weeks are inline
ap-ballots.html        # GENERATED — standalone AP page
data-YEAR.html         # GENERATED — userpoll fragments for prior years
data-ap-YEAR.html      # GENERATED — AP fragments for index.html (IDs week-ap-YEAR-N, data-poll="ap")
data-appage-YEAR.html  # GENERATED — AP fragments for ap-ballots.html (IDs week-YEAR-N, no data-poll)
cbbpoll-YEAR.json      # Cached legacy cbbpoll.com scrapes (2016–2022)
ap25-YEAR.json         # Cached AP25 scrapes (2022–2027)
ballots.json           # Browser-exported poll data for poll_simulator.py --from-json (do not read)
cbb-logos/             # Team logos: Team.webp + Team-dark.webp (dark-mode variants from ESPN)
logos voters(png)/     # Untracked, not used by the build
thumbnail.png          # OG/Twitter card image
```

## CLI (`userpoll.py`)

```bash
python3 userpoll.py --rebuild                          # Regenerate all HTML from existing data (use after code changes)
python3 userpoll.py --week 18 --year 2026              # Scrape a cbbpoll.net week and add/replace it
python3 userpoll.py --week Pre-Season --year 2027 --store-week 0 --label Pre-Season   # Week slug ≠ stored number
python3 userpoll.py --delete --week 18 --year 2026     # Remove a week
python3 userpoll.py --ap25 --year 2027                 # Scrape AP25 season → ap25-YEAR.json (0 = all seasons)
python3 userpoll.py --ap25-build --year 2027           # Build AP fragments + update both pages (0 = all)
python3 userpoll.py --cbbpoll --year 2022              # Scrape legacy cbbpoll.com season (or --year all)
python3 userpoll.py --cbbpoll-build --year 2022        # Build legacy season HTML from cached JSON
python3 userpoll.py --to-webp                          # Convert PNG logos → WebP
python3 userpoll.py --dark-logos                       # Download ESPN dark-mode logos (ESPN_NAME_OVERRIDES)
# Data-repair one-offs: --apply-recovery, --fix-contamination, --remove-overwritten REF_YEAR (see --help)
```

Local testing: `python3 -m http.server 8000` → http://localhost:8000. Opening via `file://` breaks prior-year and AP loading (fetch blocked).

`DEBUG_LIMIT` at the top of `userpoll.py` caps ballot fetches during development.

## userpoll.py layout (search by function name)

- **cbbpoll.net scraping:** `fetch_page_html`, `split_voter_sections`, `extract_next_data`, `fetch_ballot_url_for_week`, `process_voters`. Fallback chain: homepage → seasons archive → `__NEXT_DATA__` JSON → user profile pages. Regex-based parsing via `urllib.request`.
- **Logos:** `LOGO_NAME_MAP`, `canonical_logo_name`, `download_logos`, `download_dark_logos`, `convert_all_to_webp`.
- **Legacy cbbpoll.com:** `CBBPOLL_SEASONS`, `CBBPOLL_NAME_OVERRIDES`, `CBBPOLL_ALT_OVERRIDES`, `cbbpoll_scrape_season`, `cbbpoll_build_season`.
- **AP25:** `AP25_SITE_YEARS`, `AP25_NAME_OVERRIDES`, `_normalize_ap_team_name`, `ap25_fetch_grid`, `ap25_scrape_season`, `ap25_build_season`, `build_ap_week_block`, `build_appage_week_block`, `_update_ap_in_index`.
- **HTML generation:** `build_week_block` (Official / Provisional / Aggregate sections; one `<tr>` per voter, 25 logo `<td>`s), `THEAD_HTML`, `build_full_html` (the main page template, incl. keybind legend modal), `build_ap_html`, `save_html`, `load_existing_weeks`, `split_data_by_year`, `write_year_fragments`.
- **Rebuild:** `rebuild_html` (also patches legacy markup via regex migrations, preserves AP tabs via `get_ap_info`, calls `rebuild_ap_html`).
- **Markers in index.html:** `<!-- WEEK-TABS -->`, `<!-- WEEK-DATA -->`, `<!-- AP-TABS --> … <!-- /AP-TABS -->`.
- Team logos are referenced by name only (`data-src="Duke"`); JS resolves to `cbb-logos/Duke.webp` or `Duke-dark.webp` (`logoSrc()`).

## script.js layout (search by function name)

- **Globals/caches (top of file):** `_sortedTabsCache`, `_leaderboardDataCache`, `_deltaDataCache` (+`_deltaDataCacheIsProvisional`, invalidated on Official/Provisional toggle), `_apDeltaDataCache`, `_apCurrentYear`/`_apCurrentWeekNum` (non-null ⇒ AP mode on index.html), `HIDDEN_YEARS` (2024 hidden from userpoll pickers), outlier constants.
- **Loading:** `loadYear(year)` fetches `${FRAG_PATH_PREFIX}${year}.html`; `loadApYear(year)` fetches `data-ap-YEAR.html`. Both inject into `#year-data-container`; `_loadedYears` (AP keyed `ap-YEAR`) and `_loadingYears` dedupe. `backgroundLoad()` → current-year images (16 concurrent) → all fragments in parallel → their images. All year-navigation paths must `await loadYear()` before `showWeek()`.
- **Navigation:** `showWeek()` (async), `showApWeek()`, `switchToApBallots()`, `exitApBallots()`, `rebuildWeekPicker()`, `rebuildYearPicker()`, `fitPicker()`, `updateFavicon()` (favicon shows current week number).
- **Sorting:** `applyTableSort()` / `setGlobalSort()`. Modes: `alphabetic` (labelled "Functions"), `zetabetique` (reverse), `consensus`. Précision and Tenure are **leaderboard modals**, not sorts.
- **Rows:** `pinRow()` / `pinnedUsers` / `syncPinnedToAggregate()`, `bindVoterCells()`, `injectVeteranTags()`, `injectOverallRows()` / `toggleOverallRow()`.
- **Deltas:** `buildDeltaData()`, `applyDeltaToRow()`, `deltaWeeksBack`, `deltaSubMode` (`consensus-diff` | `recency`), `compute5WeekWeighted()`, `injectWeightedRankingRow()`, `injectApWeightedRankingRow()`.
- **Highlighting/outliers:** `toggleTeamHighlight()` (5 color slots), `applyOutliers()` (unranked counts as 26; high outliers capped at #20).
- **Charts/modals:** `showTeamRankChart()` (Shift+click logo), `showTeamSeasonDotPlot()`, `showWeekHighLowChart()`, `showAvgRankModal()`, `showSeasonStatsModal()`, `showHeatmapModal()`, `showPrecisionModal()`, `showTenureModal()`, `showVoterHistory()`, `saveTableAsPng()`.
- **Précision:** `computeVoterAvg()`.
- **Keyboard:** single `keydown` handler near the end of the file. Legend HTML lives in `build_full_html()` in `userpoll.py` — **update both when adding a shortcut.**

### Keyboard shortcuts (all Shift+key unless noted)

| Key | Action | Key | Action |
|---|---|---|---|
| ←/→ | Prev/next week | ↑/↓ | Prev/next year |
| A | Sort alphabetic | Z | Sort zétabétique |
| C | Sort consensus | D | Aggregate ("Data Ballots") view |
| E | Expand/collapse all deltas | J | Delta sub-label: consensus diff ↔ recency |
| 1–9 | Delta lookback window | O | Outlier highlighting |
| L | Overall row | X | Enter/exit AP mode |
| R | Précision leaderboard | T | Tenure leaderboard |
| Y | Week avg-rank table | G | Week rank-spread chart |
| U | Season stats | H | Season heatmap |
| B | Bump/dot chart | P | Save PNG |
| ? | Legend | Cmd+0 | Jump to pre-season |
| V then X | Toggle veteran tags (chord) | Esc | Close modal |

### Toggle states (`#toggle-text`)

- Userpoll on index.html: **Official Ballots ↔ Provisional Ballots**.
- AP mode on index.html (Shift+X / toggle): **Associated Press ↔ Associated Press Data**. Week/year navigation still runs on userpoll tabs; AP blocks ride along.
- ap-ballots.html: **Associated Press ↔ Data Ballots**.
- AP-aware functions detect AP mode via `weekId.startsWith("week-ap-")` or `_apCurrentYear !== null` and use `getSortedApTabs()` instead of `getSortedTabs()`.

### ap-ballots.html differences

- AP weeks are the primary `.week-tab`s (IDs `week-YEAR-N`, no `data-poll`), so standard JS paths work with `_apCurrentYear === null`.
- Injected constants: `IS_AP_PAGE = true`, `FRAG_PATH_PREFIX = 'data-appage-'`; `FRAGMENT_YEARS` = AP page years; `AP_FRAGMENT_YEARS = []`. `HIDDEN_YEARS` is ignored on this page.
- Header shows "← Userpoll" link instead of "AP Ballots →".

## Précision scoring (EXPERIMENTAL — still being tuned)

`computeVoterAvg()` (JS) ≡ `score_voters()` (`poll_simulator.py`, params in `PARAMS` dict):
- Base distance: position-weighted distance of each ballot from `finalRanking` (5-week weighted avg of last 5 consensus rankings).
- Position weight 1.0 at #1 → 0.5 at #25; week weight 0.5 at week 1 → 1.0 at final week.
- Boldness adjustment: reward for correctly deviating from weekly consensus toward final ranking (scalar 0.05, magnitude- and position-weighted).
- Miss penalty: +1 per missed week; ≥5 misses or ≥3 consecutive → disqualified.
- Combined = `avg - boldAdj + missedWeeks * penalty` (lower is better).
- Simulator: `python3 poll_simulator.py --sanity | --scenario | --sensitivity | --params`.

## AP25 (collegepolltracker.com)

- Grid: `https://collegepolltracker.com/basketball/grid/{site_year}/{week_slug}`; voter: `/basketball/pollster/{slug}/{site_year}/{week_slug}`.
- `site_year` = our year − 1. **New season → add `site_year: our_year` to `AP25_SITE_YEARS`.**
- Week slugs: `pre-season` (stored as 0), `week-2`…`week-19`, `final-rankings` (stored as 20). Week 1 doesn't exist; invalid weeks redirect to homepage.
- Seasons: 2022–2026 complete; 2027 in progress.
- `ap25_build_season` writes both fragment files and updates both pages **in one pass per year**. Do not reintroduce per-week `save_ap_html` — it caused O(n²) memory blowup.
- Team names: `_normalize_ap_team_name()` → PascalCase, then `AP25_NAME_OVERRIDES` (e.g. "Pittsburgh" → "Pitt").

## Legacy cbbpoll.com (complete — 2016–2022 scraped and built)

Different site from cbbpoll.net. Only needed if re-scraping.
- Pages: `/poll/YEAR/WEEK` (voter list split into Official / Provisional / "Voters who failed to submit a ballot"), `/ballot/ID` (25 teams; display name follows the logo `</span>`). `/overview/` is useless (always shows 2022).
- Week 1 never exists; invalid weeks and years < 2016 302-redirect. Valid weeks per year in `CBBPOLL_SEASONS`.
- Name mapping: strip spaces/periods/apostrophes/hyphens → PascalCase, then `CBBPOLL_NAME_OVERRIDES`; voter flair alt text ("University of Virginia Logo") via `CBBPOLL_ALT_OVERRIDES`.
- JSON cache: `{"year", "weeks": {"0": {"official": [{username, flair_alt, ballot_id, teams[]}], "provisional": [...]}}}`; resumable, 0.3 s rate limit.

## Common workflows

- **Weekly update:** `python3 userpoll.py --week N --year YYYY` (and `--ap25 --year YYYY` + `--ap25-build --year YYYY` for AP), spot-check locally, commit, push.
- **New season:** add to `AP25_SITE_YEARS`; first userpoll week of the new year becomes the inline year in `index.html` and the previous year is split to `data-YEAR.html` automatically.
- **UI/JS change:** edit `script.js`/`style.css` → `--rebuild` → test at localhost:8000 on both `index.html` and `ap-ballots.html` (incl. AP mode, prior year, dark mode, mobile width) → commit.

## Planned work

- Précision formula tuning (experimental)
- Minor UI/layout polish
- More analysis functions, graphs, and data analysis
