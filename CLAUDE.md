# Userpoll — CBB Poll Voter Visualizer

Scraper + static site generator for college basketball poll ballots. `userpoll.py` scrapes voter ballots (r/CollegeBasketball userpoll from cbbpoll.net / legacy cbbpoll.com, plus AP Top 25 from collegepolltracker.com) and generates `index.html` and `ap-ballots.html`, inlining `style.css` and `script.js` at build time.

- **Live:** https://www.userpoll-landscape.com/ (custom domain via `CNAME`; `les-champs.github.io/cbb-ballots/` redirects there)
- **Repo:** `les-champs/cbb-ballots`, branch `main` only. Push to `main` → `.github/workflows/pages.yml` ("Deploy Pages") publishes `*.html`, `cbb-logos/`, `thumbnail.png` and `CNAME` to GitHub Pages (deploy timeout 30 min). Add any new runtime asset to its "Assemble site" step.
- **Deploys:** Pages source must stay **GitHub Actions** (Settings → Pages). Do not switch back to "Deploy from a branch": the legacy `pages-build-deployment` pipeline timed out at `syncing_files` on every deploy on 2026-11-10 and left uncancellable "queued" runs (#218, #222, #224; ignore them). If a deploy fails, re-run it with `gh workflow run pages.yml -R les-champs/cbb-ballots` (or Actions → Deploy Pages → Run workflow) rather than pushing an empty commit. Pushing workflow changes needs the `workflow` token scope (`gh auth refresh -h github.com -s workflow`).
- No build tooling, no tests, no package manager. Python 3 stdlib + PIL; vanilla JS.
- **`script.js` is minified at build** by `minify_js()` in `userpoll.py` (stdlib-only: strips comments, indentation and spaces next to punctuation; keeps line breaks and names; falls back to unminified with a ⚠ warning if its token check fails). So the inlined JS in generated HTML has no comments — read `script.js`, not `index.html`, for code. If a JS change makes the minify warning appear, fix the tokenizer rather than ignoring it.
- `_config.yml` only matters to the old Jekyll Pages build (unused since the switch to the Actions workflow); html2canvas is loaded on demand by `loadHtml2canvas()` (Save as PNG), not by a `<script>` tag.

## Golden rules

1. **Edit only source files:** `script.js`, `style.css`, `userpoll.py` (and `poll_simulator.py`). Everything else at the root is generated.
2. **After any change to `script.js`, `style.css`, or HTML templates in `userpoll.py`, run `python3 userpoll.py --rebuild`.** This regenerates `index.html`, `ap-ballots.html`, and all fragment files. Commit source + regenerated output together.
3. **Never read generated or data files whole.** They are huge (`index.html` ≈ 0.8 MB, each `data-*.html` 3–5 MB, `cbbpoll-*.json`/`ap25-*.json` ~1–2 MB, `ballots.json` 2 MB). Use `grep -n`/`grep -c`, `head`, or `python3 -c` with `json` to inspect specific pieces. Do not open `ballots.json` at all.
4. **`script.js` is ~4,700 lines and `userpoll.py` ~2,000.** Locate code with `grep -n "function name"` and read targeted ranges rather than the whole file.
5. Features automatically appear on both `index.html` and `ap-ballots.html` (same inlined CSS/JS). Always consider both pages, and AP mode on `index.html`, when changing JS.
6. When changing the Précision formula in `computeVoterAvg()` (JS), keep `score_voters()` in `poll_simulator.py` in sync.

## Files

```
userpoll.py            # Scrapers + HTML generator + CLI (source)
script.js              # All client-side JS (source, inlined at build)
style.css              # All CSS (source, inlined at build)
poll_simulator.py      # Python mirror of the Précision formula for tuning
nond1_logos.py         # NCAA.com logos for non-D1 opponents ESPN has none for: NCAA_SLUGS (ESPN id → NCAA.com slug) + downloader (--ncaa-logos)
conferences.py         # Season-dependent D1 conference + Power/Mid-Major mapping (2025+) and ESPN_IDS (team → ESPN id); injected as CONFERENCE_DATA
index.html             # GENERATED — main site; only the current year's weeks are inline
ap-ballots.html        # GENERATED — standalone AP page
data-YEAR.html         # GENERATED — userpoll fragments for prior years
data-ap-YEAR.html      # GENERATED — AP fragments for index.html (IDs week-ap-YEAR-N, data-poll="ap")
data-appage-YEAR.html  # GENERATED — AP fragments for ap-ballots.html (IDs week-YEAR-N, no data-poll)
data-2026.html etc.    # (userpoll fragments exist for 2016–2022, 2024–2026; index.html holds 2027 inline)
cbbpoll-YEAR.json      # Cached legacy cbbpoll.com scrapes (2016–2022)
ap25-YEAR.json         # Cached AP25 scrapes (2022–2027)
cbbpoll-2024-recovery.json  # Output of the removed one-off 2024 Wayback recovery (in git history)
ballots.json           # Browser-exported poll data for poll_simulator.py --from-json (do not read)
.github/workflows/pages.yml  # GitHub Pages deploy (source)
_config.yml            # Unused (legacy Jekyll excludes); safe to delete
cbb-logos/             # Team logos: Team.webp + Team-dark.webp (dark-mode variants from ESPN); ncaa-{espnId}.webp + -dark.webp (non-D1, rendered from NCAA.com SVGs)
logos voters(png)/     # Untracked, not used by the build
thumbnail.png          # OG/Twitter card image
```

## CLI (`userpoll.py`)

```bash
python3 userpoll.py --rebuild                          # Regenerate all HTML from existing data (use after code changes)
python3 userpoll.py --week 18 --year 2026              # Scrape a cbbpoll.net week and add/replace it
python3 userpoll.py --week Pre-Season --year 2027 --store-week 0 --label Pre-Season   # Week slug ≠ stored number
python3 userpoll.py --week Pre-Season --year 2027 --store-week 0 --label Pre-Season --official-only   # Skip the Provisional section
python3 userpoll.py --delete --week 18 --year 2026     # Remove a week
python3 userpoll.py --ap25 --year 2027                 # Scrape AP25 season → ap25-YEAR.json (0 = all seasons)
python3 userpoll.py --ap25-build --year 2027           # Build AP fragments + update both pages (0 = all)
python3 userpoll.py --cbbpoll --year 2022              # Scrape legacy cbbpoll.com season (or --year all)
python3 userpoll.py --cbbpoll-build --year 2022        # Build legacy season HTML from cached JSON
python3 userpoll.py --to-webp                          # Convert PNG logos → WebP
python3 userpoll.py --dark-logos                       # Download ESPN dark-mode logos (ESPN_NAME_OVERRIDES)
python3 userpoll.py --missing-logos                    # Download ESPN logos (+dark) for conferences.py schools with no logo (ESPN_ID_OVERRIDES)
python3 userpoll.py --ncaa-logos [--year 0] [--force]  # Download + rasterize NCAA.com logos for non-D1 opponents ESPN has no logo for (nond1_logos.NCAA_SLUGS); prints match suggestions for unmapped ones. --year 0 = all shown seasons, default current
```

Local testing: `python3 -m http.server 8000` → http://localhost:8000. Opening via `file://` breaks prior-year and AP loading (fetch blocked).

`DEBUG_LIMIT` at the top of `userpoll.py` caps ballot fetches during development.

## userpoll.py layout (search by function name)

- **cbbpoll.net scraping:** `fetch_page_html`, `split_voter_sections`, `extract_next_data`, `fetch_ballot_url_for_week`, `process_voters`. Fallback chain: seasons page (`/seasons/YEAR/WEEK`, ballot IDs from `__NEXT_DATA__`) → homepage (only if the seasons page has no voters yet) → user profile pages. The seasons page goes first because the homepage links ballots for the same week *number* from any season: for 2027 Week 2, 90 of its 129 ballots were from earlier seasons, and dropping them as stale lost 39 real voters. Regex-based parsing via `urllib.request`.
- **Ballot cleanup in `main()` (every cbbpoll.net scrape):** (1) provisional voters whose username (case-insensitive) is also listed as official are dropped — the official entry wins; (2) `drop_stale_ballots()` drops any ballot created before `season_start(year)` (July 1 of year−1). Ballot IDs are MongoDB ObjectIds, so `ballot_created_at()` reads the creation time from the first 8 hex chars. `process_voters()` repeats the stale check on URLs found via fallbacks. Both steps print what they dropped. Background: on the 2027 pre-season page, cbbpoll.net's Provisional list held only prior seasons' (2022–2025) ballots, 44 of them duplicating official voters.
- **`--official-only`:** skips the Provisional section entirely (stores 0 provisional ballots for that week). 2027 Pre-Season was scraped this way.
- **Logos:** `LOGO_NAME_MAP`, `canonical_logo_name`, `download_logos`, `download_dark_logos`, `download_missing_logos`, `convert_all_to_webp`.
- **Legacy cbbpoll.com:** `CBBPOLL_SEASONS`, `CBBPOLL_NAME_OVERRIDES`, `CBBPOLL_ALT_OVERRIDES`, `cbbpoll_scrape_season`, `cbbpoll_build_season`.
- **AP25:** `AP25_SITE_YEARS`, `AP25_NAME_OVERRIDES`, `_normalize_ap_team_name`, `ap25_fetch_grid`, `ap25_scrape_season`, `ap25_build_season`, `build_ap_week_block`, `build_appage_week_block`, `_update_ap_in_index`.
- **HTML generation:** `build_week_block` (Official / Provisional / Aggregate sections; one `<tr>` per voter, 25 logo `<td>`s), `THEAD_HTML` (only the Functions toggle + rank headers), `PICKER_HTML` (the Functions menu, emitted once per page as `<template id="picker-template">`; `createPicker()` in script.js clones it beside a toggle on first click — add menu items here, not to `THEAD_HTML`), `build_full_html` (the main page template, incl. keybind legend modal), `build_ap_html`, `save_html`, `load_existing_weeks`, `split_data_by_year`, `write_year_fragments`.
- **Rebuild:** `rebuild_html` (also patches legacy markup via regex migrations, preserves AP tabs via `get_ap_info`, calls `rebuild_ap_html`).
- **Markers in index.html:** `<!-- WEEK-TABS -->`, `<!-- WEEK-DATA -->`, `<!-- AP-TABS --> … <!-- /AP-TABS -->`.
- Team logos are referenced by name only (`data-src="Duke"`); JS resolves to `cbb-logos/Duke.webp` or `Duke-dark.webp` (`logoSrc()`).

## script.js layout (search by function name)

- **Globals/caches (top of file):** `_sortedTabsCache`, `_leaderboardDataCache`, `_deltaDataCache` (+`_deltaDataCacheIsProvisional`, invalidated on Official/Provisional toggle), `_officialDeltaDataCache` (official ballots only), `_apDeltaDataCache`, `_apCurrentYear`/`_apCurrentWeekNum` (non-null ⇒ AP mode on index.html), `HIDDEN_YEARS` (2023 + 2024 hidden from userpoll navigation and analysis; mirrors `EXCLUDED_YEARS` in `userpoll.py`), outlier constants.
- **Loading:** `loadYear(year)` fetches `${FRAG_PATH_PREFIX}${year}.html`; `loadApYear(year)` fetches `data-ap-YEAR.html`. Both inject into `#year-data-container`; `_loadedYears` (AP keyed `ap-YEAR`) and `_loadingYears` dedupe. `backgroundLoad()` lazy-loads images (16 concurrent) for weeks already in the DOM only; prior-year fragments load on demand when navigated to (eager preloading of every fragment caused a ~30 s DOM stall). All year-navigation paths must `await loadYear()` before `showWeek()`.
- **Week 1 / Pre-Season:** pre-season is stored as week 0 (`week-YEAR-0`; legacy 2017–2022 tabs have no label, newer ones `data-weeklabel="Pre-Season"`), but the UI shows it as **Week 1** everywhere (there is never a real week 1). `isPreseasonTab()` detects it, `displayWeekNum()` returns 1, and `weekTextLabel()` returns undefined so callers fall back to the number. Use these helpers for any user-facing week text — never `dataset.weeknum`/`dataset.weeklabel` directly. Week 1 is shown in the week picker and ←/→ navigation (no longer hidden). Keep storage as week 0: pre-season reclassification, Cmd+0 and AP data depend on it.
- **Navigation:** `showWeek()` (async), `showApWeek()`, `switchToApBallots()`, `exitApBallots()`, `rebuildWeekPicker()`, `rebuildYearPicker()`, `fitPicker()`, `updateFavicon()` (favicon shows current week number).
- **Functions menu:** cloned per table from `#picker-template` by `createPicker()` (see `PICKER_HTML`). Clicks are handled by one capture-phase `mousedown` listener; in-place actions (Settings, Credits, Dark Mode, Nav Arrows, Show toggles) keep it open. Settings and Credits swap the menu contents via `.settings-mode` / `.credits-mode` (`.settings-only` / `.credits-only` items; CSS in `style.css`). Credits is a single line that `fitCreditsText()` shrinks to end at the table's right edge (never below the table's min width). Credits text lives in `PICKER_HTML`.
- **Sorting:** `applyTableSort()` / `setGlobalSort()`. Modes: `alphabetic` (labelled "Functions"), `zetabetique` (reverse), `consensus`. Précision and Tenure are **leaderboard modals**, not sorts.
- **Rows:** `pinRow()` / `pinnedUsers` / `syncPinnedToAggregate()`, `bindVoterCells()`, `injectVeteranTags()`, `injectOverallRows()` / `toggleOverallRow()`.
- **Deltas:** `buildDeltaData(officialOnly)` — pass `true` for any aggregate/consensus calculation (provisional ballots must never affect aggregates); omit it only for per-voter deltas that should follow the Official/Provisional toggle. Also `applyDeltaToRow()`, `deltaWeeksBack`, `deltaSubMode` (`consensus-diff` | `recency`), `compute5WeekWeighted()`, `injectWeightedRankingRow()`, `injectApWeightedRankingRow()`.
- **Highlighting/outliers:** `toggleTeamHighlight()` (5 color slots), `applyOutliers()` (unranked counts as 26; high outliers capped at #20).
- **Charts/modals:** `showTeamRankChart()` (Shift+click logo), `showTeamSeasonDotPlot()`, `showWeekHighLowChart()` — the Stats › Week window (tabs `stats` Stats / `conf` Conference; Stats = `buildWeekChartPanel()` (Range / Spread / Outlook switcher styled like the title tabs, inside the plot's top-right corner, remembered in `localStorage` `weekStatsChart`; chart SVG from `buildWeekChartSvg()`, 380px tall) above the stats table, whose rows and the chart's marks/logos click to `toggleTeamHighlight()`; passing `highlow`/`dots`/`outlook` as the mode opens Stats with that chart shown; Conference (2025+) renders `buildConferenceView()` from `computeConferenceWeekStats()`: a per-conference stats table (T25, Pts, Share with its week-over-week Δ, plus a Teams column of every vote-getting team's logo by points; logos click to highlight); the stats table is `buildWeekStatsTableHtml()` in a nested `<table class="week-stats-table">`, opened by Shift+Y; Shift+G opens it with the chart shown), `computeOutlookBands()` (Likely ~50% / Outlook ~77.5% bands; band-edge percentiles come from `BAND_PCT`, one row per rank tier #1–5…#21–25 with separate Userpoll and AP tables, fit so each tier hits its target with misses split evenly; also feeds the Likely/Outlook columns of the Stats tab), `showSeasonStatsModal(mode)` — the Year window (Shift+U; title tabs `stats` Stats / `records` Records / `voters` Voters, built by `seasonModalTitleHtml()`, styled like the Week window's. Records = live ESPN W-L records with click-to-expand game lists; see **ESPN data** below. Voters is hidden: its tab only appears while it's open, reached by Shift+W (PIN-locked). Stats = per-team table incl. #1 Supporter / #1 Hater columns; Voters = `buildSeasonVotersTableHtml()`: one row per official voter with Weeks, Cons Δ (avg per-ballot distance from weekly consensus, sorted ascending), #1 Pick, Favorite / Least Fav. (largest avg signed per-team gap, per week voted). Cons Δ and Favorite / Least Fav. use the same measure as the homepage Consensus sort — shared helpers `makeLooConsensus()` (leave-one-out consensus), `consensusTeamGaps()` / `consensusGaps()` / `consensusDistance()`, `renderedConsensusOrder()`; change them there, not per caller; voters under the participation minimum sort last in italics), `showHeatmapModal()`, `showPrecisionModal()`, `showTenureModal()`, `showVoterHistory()`, `saveTableAsPng()`.
- **Précision:** `computeVoterAvg()`.
- **ESPN data layer + Records tab:** see **ESPN data** below (`fetchSeasonRecords()`, `fetchTeamSchedule()`, `showSeasonRecords()`).
- **Conferences:** `showConferenceModal(year)` (Shift+K) lists every D1 school by conference for a season (2025+) from `CONFERENCE_DATA`, which `build_full_html()` builds from `conferences.js_payload()`. Edit memberships only in `conferences.py` (`_BASE_2025` + per-season `_MOVES`), then `--rebuild`. `python3 conferences.py` checks every team on 2025+ ballots is mapped.
- **Conference ranking rows (Data Ballots, 2025+):** `_injectConferenceRows()` (called from `injectWeightedRankingRow()` and `injectApWeightedRankingRow()`) adds rows after Recency: one per Power conference, then Power and Mid-Major. Each ranks only that group's teams by Overall points (25…1) over official ballots, top 25, with delta vs. the previous week's same-group ranking. Rows carry `row-weighted-ranking` (so sort/outliers/pins skip them) plus `row-conference-ranking`.
- **Empty-week "N/A" overlay (end of file):** `#no-ballots-overlay` — a viewport-sized diagonal "N/A" in `--color-heading` shown when every visible `.week-block .ballot-section` lacks ballots (`sectionHasBallots()`: a `tr.voter-row` with a `.team-logo`, excluding `.row-weighted-ranking`/`.overall-row`). A `MutationObserver` on `style` changes of `.ballot-section`/`.week-block` triggers `updateNoBallotsOverlay()`, so no show/hide path needs to call it. `sizeNoBallotsOverlay()` fits the rotated text inside the viewport. Layering: overlay z-index 5 (`pointer-events: none`), `.header` z-index 6, modals 1000+.
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
| Y | Week Stats tab | G | Week Stats tab, chart shown |
| U | Season stats | H | Season heatmap |
| B | Bump/dot chart | P | Save PNG |
| K | Conference table | W | Year window Voters tab |
| ? | Legend | Cmd+0 | Jump to Week 1 (pre-season) |
| V then X | Toggle veteran tags (chord) | Esc | Close modal |

**Locked keybinds:** Shift+D/X/R/T/Y/G/U/W/H/K/P/? require a 9-digit PIN (`LOCKED_KEYS` / `PIN_HASH` above the `keydown` handler; `#pin-modal` in `build_full_html()`). The Year window's Voters tab is also locked, by any path (`showSeasonStatsModal("voters")` returns early while locked). **The PIN prompt opens only from Functions › Settings › Other › Dev** (`data-action='devPin'` → `openPinModal()`); while locked, locked keybinds and the Voters tab silently do nothing (no prompt). An unlock lasts for the viewer's local calendar day (`localStorage.keybindsUnlockedDate`, checked by `isKeybindsUnlocked()` on every locked action, so an open tab re-locks after midnight); the old `keybindsUnlocked` flag is removed on load. Only a salted PBKDF2 hash of the PIN (`PIN_SALT`/`PIN_HASH`, checked by `_pinMatches()` via `crypto.subtle`, which needs https or localhost) is in the page; the comment above it shows how to hash a new PIN. One wrong PIN closes the PIN window and makes Dev inert for 10 minutes (clicks ignored in the menu's `mousedown` handler). Dev is dimmed (`.sort-option.dimmed`, set in `refreshSettingsLabels()`) whenever the keybinds aren't unlocked today, lockout or not (`PIN_LOCKOUT_MS`, `localStorage.pinLockedUntil`, read by `_pinLockedOut()`). Other menu/click paths are not locked.

### Toggle states (`#toggle-text`)

- Userpoll on index.html: **Official Ballots ↔ Provisional Ballots**.
- AP mode on index.html (Shift+X / toggle): **Associated Press ↔ Associated Press Data**. Week/year navigation still runs on userpoll tabs; AP blocks ride along.
- ap-ballots.html: **Associated Press ↔ Data Ballots**.
- AP-aware functions detect AP mode via `weekId.startsWith("week-ap-")` or `_apCurrentYear !== null` and use `getSortedApTabs()` instead of `getSortedTabs()`.

### ap-ballots.html differences

- AP weeks are the primary `.week-tab`s (IDs `week-YEAR-N`, no `data-poll`), so standard JS paths work with `_apCurrentYear === null`.
- Injected constants: `IS_AP_PAGE = true`, `FRAG_PATH_PREFIX = 'data-appage-'`; `FRAGMENT_YEARS` = AP page years; `AP_FRAGMENT_YEARS = []`. `HIDDEN_YEARS` is ignored on this page.
- Header shows "← Userpoll" link instead of "AP Ballots →".

## ESPN data (W-L records and game results)

Live team records and game-by-game results come from ESPN's public, **undocumented** site APIs: no key needed, CORS open, called **from the browser at view time** (nothing is fetched at build, and nothing is stored in the repo). First used by the Year window's **Records** tab; the data layer is built to be reused anywhere else.

### Endpoints (verified 2026-11-12)

| Purpose | URL | Notes |
|---|---|---|
| Every D1 team's record for a season | `https://site.web.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings?group=50&season=YYYY` | One call, ~6 MB raw / ~170 KB gzipped, ~365 teams in 32 conference nodes (`children[]`, each with `standings.entries[]`; a conference may nest more `children`). Per team `stats[]` keyed by `type`: `wins`, `losses`, `total` ("3-1"), `vsconf`, `home`, `road`, `streak` ("W3"), `winpercent`, points for/against, `vsaprankedteams`. Works for past seasons (2020 checked) |
| One team's games | `https://site.web.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{espnId}/schedule?season=YYYY&seasontype=2` (and `=3`) | `seasontype=2` = regular season **including conference tournaments**; `seasontype=3` = NCAA/NIT/other postseason. Omitting it returns only type 2. `events[].competitions[0]` has `neutralSite`, `competitors[]` (`homeAway`, `winner`, `score.value`, `curatedRank.current`, `team.id`/`logos`), `status.type` (`state` pre/in/post, `completed`, `shortDetail`), `notes[0].headline` ("SEC Tournament - Final") |
| All games on a date (not used yet) | `https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates=YYYYMMDD&groups=50&limit=400` | Untested in the browser; use the `site.web.api.espn.com` host (see gotchas) |
| Team list (used by the Python logo tools) | `https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams?limit=1000` | `--dark-logos`, `--missing-logos` |
| Logos | `https://a.espncdn.com/i/teamlogos/ncaa/500/{espnId}.png` (`500-dark/` for dark) | `espnLogoUrl()` |

### Gotchas (learned the hard way)

- **Use the `site.web.api.espn.com` host from the browser.** `site.api.espn.com` returns **403 with no CORS header** to some user agents (e.g. `HeadlessChrome`), which the browser reports as a CORS failure. curl hides this because it sends no `Origin`/browser UA. Both hosts serve the same `/apis/site/v2/...` paths.
- **Records are overall records**: they include non-D1 opponents and the postseason (Florida 2025 = 36-4). NET team sheets (Warren Nolan) count **D1 games only**, so they'll show fewer wins for teams with non-D1 games. Use `summarizeGames(...).D1` for a D1-only record.
- **`curatedRank` means different things:** the opponent's **AP rank at game time** in regular-season games (99 = unranked), but its **tournament seed** in postseason games. `fetchTeamSchedule()` splits it into `oppRank` / `oppSeed`; never count seeds as rankings.
- Standings `home`/`road` exclude **neutral-site** games, so home + road ≠ total. The neutral split only exists in the schedule (`summarizeGames().neutral`).
- Standings `vsconf` excludes conference-tournament games; `summarizeGames().conf` matches it (same ESPN conference, not postseason, note without "Tournament"). Verified: Florida 2025 14-4 both ways.
- ESPN conference names (`shortName`) mostly differ from ours (e.g. "Am. East", "A-10", "Metro" vs our "MAAC"); for 2025+ group by `conferences.py`, not ESPN.
- Undocumented API: it can change without notice. All callers must handle failure (the data layer keeps the last good data and marks it `stale`; the UI shows an error + Retry).

### Team ID mapping

- `ESPN_IDS` in `conferences.py`: our canonical team name (the `data-src` logo name) → ESPN id, for **every school in every season** of `_BASE_2025`/`_MOVES` (366 schools). Shipped to the page as `CONFERENCE_DATA.espn`. IDs never change for a school.
- **New D1 school → add it to `ESPN_IDS` too.** `python3 conferences.py` exits non-zero and prints `NO ESPN ID` for any missing one. Find IDs in the standings JSON (`entries[].team.id`) or the team-list endpoint above.
- Ballot names that differ from canonical keys go through `CONFERENCE_DATA.aliases` (`ALIASES` in conferences.py); `espnIdFor()` applies them. Pre-2025 ballots use the same logo-name keys, so lookups mostly work for old seasons too (one 2020 week checked: all 108 vote-getters mapped); a school no longer in D1 since 2025 may be missing and shows "No ESPN ID".
- Separate, older mappings in `userpoll.py` (`ESPN_NAME_OVERRIDES`, `ESPN_ID_OVERRIDES`) only serve the logo download tools. `ESPN_IDS` is the source of truth for data.

### JS data layer (`script.js`, section "ESPN data layer", above the Records tab)

The full contract is in the comment block at the top of that section. Summary:

- `espnIdFor(team)` → ESPN id or null; `espnTeamKey(id)` → our canonical name or null (non-D1/unknown); `espnLogoUrl(id)`.
- `fetchSeasonRecords(season)` → `{byId: {id: {id, name, conf, wins, losses, pct, confRecord, home, road, streak}}, confs: [{name, ids}], at, stale?}`. A team missing from `byId` is not D1 that season.
- `fetchTeamSchedule(id, season)` → `{games: [{id, date, site H|A|N, opp: {id, name, key, logo}, oppRank, oppSeed, us, them, result W|L|null, state, status, postseason, note}], at, stale?}`, sorted by date; makes two requests (types 2 and 3; a type-3 failure is ignored).
- `recordAsOf(games, date)` → `{wins, losses}` from completed games before `date`.
- `summarizeGames(games, {teamId, records})` → `{overall, home, away, neutral, conf, vsTop25, nonD1, D1}`, each `{wins, losses}`; `conf`/`nonD1`/`D1` need the `records` context.
- Caching: `_espnCached(key, load)` memoizes per key (`records:YEAR`, `schedule:YEAR:ID`) for `ESPN_TTL_MS` (10 min), dedupes in-flight calls, returns the last good data with `stale: message` on failure. `espnCachedData(key)` reads the cache without fetching. Add new endpoints through `_espnCached` + `_espnJson`, not raw `fetch`.
- Seasons use the project convention (2027 = 2026-27), which is also ESPN's `season` parameter.

### Records tab (Year window, Shift+U › Records)

- `showSeasonRecords(year, isApMode, activeTab)` renders cached data (or "Loading…") immediately, then fetches; a render token drops stale renders. `buildRecordsTableHtml()` builds it; `seasonModalTitleHtml()` builds the shared Stats / Records / Voters title tabs.
- Sub-switch (`_recordsView`, small tabs in the window title after Stats / Records, Records only): **Voted** (the active week) lists vote-getters in points order (official ballots via `buildDeltaData(true)`, line after #25); **All** groups every team by conference (conferences.py for 2025+, ESPN's grouping before), Power first, sorted by conf win %, then overall. Columns: #, logo, Team, W-L, Pct, Conf (one vertical line, after Conf) (Home/Road splits are only in the expanded game list). **Voted** adds **Won** and **Lost** after Conf (All has neither): logos of the opponents each team beat / lost to over the season (completed games, by date; tooltip = rank, name, date, site, score). Won is capped at `RECORDS_WON_MAX` (22) logos by `trimWonOpponents()`: over the cap it drops wins oldest-first from non-D1 opponents, then unranked + unseeded Mid-Majors, then unranked + unseeded Power teams (conferences.py for 2025+, ESPN's conference before); ranked/seeded wins are never dropped. Lost is not capped. Clicking a Won/Lost logo (D1 opponents with our key; class `team-logo`) calls `toggleTeamHighlight()` instead of opening the game list. `fillRecordsOpponents()` fills them after render with one `fetchTeamSchedule()` per row (`RECORDS_OPPS_CONCURRENCY` = 6 at a time, cached schedules fill instantly, shared with the game lists); CSS `.records-opps*` / `.records-opp-logo`.
- Clicking a team row (`tr.records-team-row[data-espn]`) toggles a game list row (`toggleTeamGames()` → `buildTeamGamesHtml()`): a split summary (Conf / vs non-D1) and one line per game (date, vs/@/N, opponent logo with AP rank or (seed), result + score or start time, event note, non-D1 tag). Open lists persist across re-renders and view switches (`_recordsExpanded`, keyed `YEAR:espnId`).
- Works in AP mode (AP week's ballots) and on ap-ballots.html. A note right-aligned in the window title (`recordsNoteHtml()`, `.records-title-note`; the title becomes a flex row via `:has()`) reads "ESPN as of <time>" for the current season (date added only if the data isn't from today) and "ESPN · final" for past seasons.
- Logos: our file via `setLogoSrc()`, falling back to ESPN's logo, then a filler (`initRecordsLogos()`). Non-D1 opponents (`oppLogoSrc()`): ESPN's logo URL from the schedule; if ESPN lists none (most D2/D3/NAIA), our `cbb-logos/ncaa-{espnId}.webp` when the id is in `NCAA_LOGO_IDS` (`-dark.webp` in dark mode if in `NCAA_DARK_LOGO_IDS`; both injected by `build_full_html()` from the files on disk); otherwise, or if an image fails to load (`img[data-filler]`), `logoFillerHtml()`: a dashed circle with the school's initial (`.logo-filler`).
- **Non-D1 logo files (`nond1_logos.py`):** downloaded at build time, never fetched from NCAA.com at view time. NCAA.com covers NCAA D1–D3 only (URL `…/images/logos/schools/bgl|bgd/{slug}.svg`; unknown slugs return 403), so NAIA/NCCAA schools keep the filler. `--ncaa-logos` scans ESPN schedules for logo-less non-D1 opponents, downloads files for `NCAA_SLUGS` entries, and prints NCAA.com suggestions (from `www.ncaa.com/schools-index/N`) for unmapped ones. Check each suggestion's full school name before adding it (several "Bethel", "Concordia", "Union"… exist), then rerun and `--rebuild`. SVGs containing `<script>`/`foreignObject` are rejected. Each SVG is rendered once by headless Chrome (`CHROME` env var overrides the macOS path) and saved as a 150×150 WebP, since some are ~750 KB of vector paths; `-dark` only when NCAA.com's dark-background version differs. Johnson & Wales (Denver) has no NCAA.com logo (403).
- CSS: `#season-stats-table.season-records …` and `.records-*` / `.rg-*` in style.css. The Stats tab's column-border rules exclude `.season-records`; Records' own border rules use `> tbody > tr > td` so they don't hit the nested game table.

### Limitations and ideas for reuse

- **Records are "as of now," not "as of the poll week."** Week tabs carry no dates (`data-week`, `data-weeknum`, `data-year` only). To show the record each team had when a ballot was cast, store each week's release date at scrape time (cbbpoll.net / collegepolltracker pages), then use `recordAsOf(games, weekDate)`. That needs one schedule request per team, so batch it (or switch to scoreboard-by-date for a whole week).
- Other places this data could go: a record under logos in the Week Stats table or the Shift+click team chart; a "ranked with N losses" / "unbeaten but unranked" outlier view; voters' Précision vs. actual results; quality wins (W vs AP Top 25) alongside poll points; the weekly results of every ranked team (scoreboard endpoint).
- If a feature must work without ESPN (offline or for an archive), add a build-time snapshot in `userpoll.py` (stdlib `urllib`, same URLs) and inline it like `CONFERENCE_DATA`, then prefer live data when it loads.
- Headless browser testing: ESPN blocks the `HeadlessChrome` UA on `site.api.espn.com` (another reason for the web host). puppeteer-core with the system Chrome works (`executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'`). The user's `~/.npm` cache has root-owned files, so `npm i` needs `--cache <tmp dir>`.

## Précision scoring (EXPERIMENTAL — still being tuned)

`computeVoterAvg()` (JS) ≡ `score_voters()` (`poll_simulator.py`, params in `PARAMS` dict):
- Base distance: position-weighted distance of each ballot from `finalRanking` (5-week weighted avg of last 5 consensus rankings — unrelated to the Outlook graph).
- Position weight 1.0 at #1 → 0.5 at #25; week weight 0.5 at week 1 → 1.0 at final week.
- Boldness adjustment: reward for correctly deviating from weekly consensus toward final ranking (scalar 0.05, magnitude- and position-weighted).
- Miss penalty: +1 per missed week; ≥5 misses or ≥3 consecutive → disqualified.
- Combined = `avg - boldAdj + missedWeeks * penalty` (lower is better).
- Simulator: `python3 poll_simulator.py --sanity | --scenario | --sensitivity | --params`.

## AP25 (collegepolltracker.com)

- Grid: `https://collegepolltracker.com/basketball/grid/{site_year}/{week_slug}`; voter: `/basketball/pollster/{slug}/{site_year}/{week_slug}`.
- `site_year` = our year − 1. **New season → add `site_year: our_year` to `AP25_SITE_YEARS`.**
- Week slugs: `pre-season` (stored as 0), `week-2`…`week-19`, `final-rankings` (stored as 20). Week 1 doesn't exist; invalid weeks redirect to homepage.
- **Site year 2026 (our 2027) starts at `week-1`:** the first poll after pre-season is `week-1` (`week-2` 302s to it). Site years listed in `AP25_WEEK1_SITE_YEARS` shift slugs so `week-N` is stored as week N+1, which keeps our week numbering unchanged. Add new seasons there if the site keeps this scheme.
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
- More uses of ESPN records/game data (see **ESPN data › Limitations and ideas for reuse**), incl. record-as-of-poll-week
