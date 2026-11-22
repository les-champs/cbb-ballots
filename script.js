const isDarkMode = () => document.body.classList.contains('dark');
const SVG_NS = "http://www.w3.org/2000/svg";

let _sortedTabsCache = null;
let _leaderboardDataCache = null;
let _deltaDataCache = null;
let _deltaDataCacheIsProvisional = null;
let _officialDeltaDataCache = null;  // official ballots only, regardless of toggle
let _apDeltaDataCache = {};
let _apCurrentYear = null;
let _apCurrentWeekNum = null;
let _hideVeteranTagsOverride = false;
let _chordPending = null;
let _chordTimer = null;

const _loadedYears = new Set();
const _loadingYears = {};
// Seasons before FIRST_SHOWN_YEAR stay in the data (fragments still load for tenure etc.) but are
// hidden from navigation: year picker, ←/→ and ↑/↓, for Userpoll and AP on both pages.
// Analysis exclusions are separate: EXCLUDED_YEARS in userpoll.py.
const FIRST_SHOWN_YEAR = 2025;
function isHiddenYear(y) { return parseInt(y) < FIRST_SHOWN_YEAR; }
// True on ap-ballots.html (IS_AP_PAGE is injected there only).
const ON_AP_PAGE = typeof IS_AP_PAGE !== "undefined" && IS_AP_PAGE;

const OUTLIER_OMISSION_TOP_N = 15;
const OUTLIER_HIGH_MAX_RANK = 20;
const OUTLIER_SD_THRESHOLD = 2.5;
let _outliersMode = false;

function svgColors() {
    const dark = isDarkMode();
    return {
        axisColor:   dark ? "#888" : "#999",
        gridColor:   dark ? "#383838" : "#e8e8e8",
        borderColor: dark ? "#444" : "#ddd",
        nrLineColor: dark ? "#444" : "#eee",
        nrGridColor: dark ? "#3a3a3a" : "#d8d8d8",
        nrTextColor: dark ? "#666" : "#ccc",
        circleStroke: dark ? "#1a1a1a" : "#fff",
    };
}

// Settings items live in the Settings window (#settings-modal, opened from Functions › Settings).
// Labels name what clicking does (e.g. "Nav Arrows ON" turns them on), so refresh them whenever it changes.
function refreshSettingsLabels(root = document) {
    root.querySelectorAll('.settings-item[data-action="darkMode"]').forEach(o => {
        o.textContent = isDarkMode() ? 'Light Mode' : 'Dark Mode';
    });
    const dimOn = document.body.classList.contains('highlight-dim');
    root.querySelectorAll('.settings-item[data-action="highlightMode"]').forEach(o => {
        o.textContent = dimOn ? 'Glow Highlights' : 'Dim Highlights';
    });
    const compactOn = document.body.classList.contains('compact-table');
    root.querySelectorAll('.settings-item[data-action="compactTable"]').forEach(o => {
        o.textContent = compactOn ? 'Standard Table' : 'Compact Table';
    });
    const arrowsOn = document.body.classList.contains('show-week-arrows');
    root.querySelectorAll('.settings-item[data-action="weekArrows"]').forEach(o => {
        o.textContent = arrowsOn ? 'Nav Arrows OFF' : 'Nav Arrows ON';
    });
    const avgLinesOn = document.body.classList.contains('show-avg-lines');
    root.querySelectorAll('.settings-item[data-action="avgLines"]').forEach(o => {
        o.textContent = avgLinesOn ? 'Avg Lines OFF' : 'Avg Lines ON';
    });
    // Dev is dimmed unless the locked keybinds are unlocked today. Reads storage directly
    // because this can run before the PIN-lock section (and its `let`s) near the end of the file.
    let devUnlocked = false;
    try {
        const d = new Date();
        const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        devUnlocked = localStorage.getItem('keybindsUnlockedDate') === today;
    } catch (e) {}
    root.querySelectorAll('.settings-item[data-action="devPin"]').forEach(o => o.classList.toggle('dimmed', !devUnlocked));
}
function updateDarkModeLabel() {
    refreshSettingsLabels();
}

function logoSrc(team) {
    const dark = isDarkMode();
    const suffix = (dark && DARK_LOGO_TEAMS.has(team)) ? '-dark' : '';
    return `cbb-logos/${team}${suffix}.webp`;
}

// Sets img.src via logoSrc and adds a one-shot onerror fallback to the
// light-mode logo so dark logo 404s (e.g. CDN propagation lag) degrade
// gracefully instead of showing broken-image icons.
function setLogoSrc(img, team) {
    const src = logoSrc(team);
    img.src = src;
    const dark = isDarkMode();
    if (dark && DARK_LOGO_TEAMS.has(team)) {
        img.addEventListener('error', () => {
            img.src = `cbb-logos/${team}.webp`;
        }, { once: true });
    }
}

// ─── CSS logos (Safari performance) ─────────────────────────
// Safari spends ~1.1–1.4 ms of main-thread time starting every <img> load of an
// http(s) URL (Chrome ~0.01 ms), even cached/cloned/lazy/blob: ones (measured
// 2026-11-22, Safari 26.2), and the page assigns ~6,600 ballot logos, so loading
// them froze clicks for seconds. data: URLs avoid that but make every style recalc
// ~5× slower (long attribute values). So in Safari, bulk ballot logos get no src:
// a per-team class whose rule sets `content: url(...)` (one load per team, shared
// by every img; dark variants via body.dark rules, so Dark Mode needs no per-img
// work). Such imgs carry data-css-logo and have naturalWidth 0;
// materializeCssLogos() gives them a real src where one is needed (Save as PNG).
// Other browsers keep plain src (Firefox's support for content on <img> is unsure).
const CSS_LOGOS = /AppleWebKit/.test(navigator.userAgent) && !/Chrome|Chromium|Edg|Android/.test(navigator.userAgent);
const _cssLogoTeams = new Set();
let _cssLogoStyle = null;

function cssLogoClass(team) { return `lg-${team.replace(/[^A-Za-z0-9_-]/g, c => "_" + c.charCodeAt(0).toString(16))}`; }

// Adds the content rules for any team in `teams` that doesn't have them yet.
function ensureCssLogoRules(teams) {
    const add = [];
    for (const t of new Set(teams)) if (t && !_cssLogoTeams.has(t)) { _cssLogoTeams.add(t); add.push(t); }
    if (!add.length) return;
    if (!_cssLogoStyle) {
        _cssLogoStyle = document.createElement("style");
        _cssLogoStyle.id = "css-logo-styles";
        document.head.appendChild(_cssLogoStyle);
    }
    const url = f => `url("cbb-logos/${f.replace(/["\\]/g, "\\$&")}.webp")`;
    _cssLogoStyle.appendChild(document.createTextNode(add.map(t => {
        const c = cssLogoClass(t);
        const light = `img.${c}{content:${url(t)}}`;
        return DARK_LOGO_TEAMS.has(t) ? `${light}body.dark img.${c}{content:${url(t + "-dark")}}` : light;
    }).join("")));
}

// Shows `team`'s logo on a bulk ballot img: CSS logo in Safari, else setLogoSrc().
function setBallotLogo(img, team) {
    if (!CSS_LOGOS) { setLogoSrc(img, team); return; }
    ensureCssLogoRules([team]);
    img.classList.add(cssLogoClass(team));
    img.dataset.cssLogo = "1";
}

// Sets every pending img's logo (team = data-src) in chunks, so clicks get through.
const LOGO_ASSIGN_CHUNK = 500;
async function assignBallotLogos(imgs) {
    imgs = Array.from(imgs);
    if (CSS_LOGOS) ensureCssLogoRules(imgs.map(img => img.dataset.src));
    for (let i = 0; i < imgs.length; i += LOGO_ASSIGN_CHUNK) {
        if (i) await new Promise(r => setTimeout(r, 0));
        imgs.slice(i, i + LOGO_ASSIGN_CHUNK).forEach(img => {
            const team = img.dataset.src;
            if (!team) return;  // done meanwhile by another path
            setBallotLogo(img, team);
            img.removeAttribute("data-src");
        });
    }
}

// Gives CSS-logo imgs under `root` a real src (current mode) and waits for them.
function materializeCssLogos(root) {
    const loads = [];
    root.querySelectorAll("img[data-css-logo]").forEach(img => {
        const src = logoSrc(img.dataset.team);
        if (img.getAttribute("src") === src && img.complete) return;
        img.src = src;
        loads.push(img.decode().catch(() => {}));
    });
    return Promise.all(loads);
}

function refreshBlockLogos(block) {
    // Update already-loaded logos in a single block to the current dark/light mode.
    // Images still pending lazy-load (data-src present) are skipped — they call
    // setLogoSrc() themselves when loaded and pick up the current mode automatically.
    // CSS logos follow body.dark by themselves (their content rule wins over any src).
    if (!block) return;
    block.querySelectorAll('img[data-team]:not([data-src]):not([data-css-logo])').forEach(img => {
        const team = img.dataset.team;
        if (DARK_LOGO_TEAMS.has(team)) setLogoSrc(img, team);
    });
}

function refreshLogos() {
    // Only refresh the visible block(s) — scanning the entire DOM for every toggle
    // is far too expensive once background loading has populated all week blocks.
    // Blocks that are currently hidden get refreshed on demand in showWeek/showApWeek.
    const activeTab = document.querySelector('.week-tab.active');
    if (activeTab) refreshBlockLogos(document.getElementById(activeTab.dataset.week));
    if (_apCurrentYear && _apCurrentWeekNum)
        refreshBlockLogos(document.getElementById(`week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`));
}

function toggleDarkMode() {
    document.body.classList.toggle('dark');
    localStorage.setItem('darkMode', isDarkMode() ? '1' : '0');
    updateDarkModeLabel();
    refreshLogos();
    applyHighlightStyles();
    updateAvgRankLines();
}

(function() {
    const stored = localStorage.getItem('darkMode');
    const prefersDark = stored !== null
        ? stored === '1'
        : window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (prefersDark) document.body.classList.add('dark');
    updateDarkModeLabel();
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
        if (localStorage.getItem('darkMode') === null) {
            document.body.classList.toggle('dark', e.matches);
            updateDarkModeLabel();
        }
    });
})();

const TEAM_NAME_OVERRIDES = {
    TexasAM: "Texas A&M",
    TexasAMCommerce: "East Texas A&M",
};

function formatTeamName(team) {
    if (TEAM_NAME_OVERRIDES[team]) return TEAM_NAME_OVERRIDES[team];
    // Always insert space before "State"
    let name = team.replace(/State/g, " State");
    // Insert space before uppercase letter when preceded by lowercase (camelCase boundary)
    name = name.replace(/([a-z])([A-Z])/g, "$1 $2");
    return name.replace(/  +/g, " ").trim();
}

function injectVeteranTags(root) {
    root.querySelectorAll(".voter-name").forEach(nameSpan => {
        if (nameSpan.querySelector(".veteran-tag")) return;
        const name = nameSpan.textContent.trim();
        const count = TENURE_COUNTS[name] ?? 0;
        if (count > 100) {
            const tag = document.createElement("span");
            tag.className = "veteran-tag" + (count >= 200 ? " veteran-elite" : "");
            tag.textContent = name.length > 17 ? "(v)" : "veteran";
            nameSpan.appendChild(tag);
        }
    });
}

async function loadYear(year) {
    if (_loadedYears.has(year)) return;
    if (_loadingYears[year]) return _loadingYears[year];
    if (!FRAGMENT_YEARS.includes(year)) {
        _loadedYears.add(year);
        return;
    }
    _loadingYears[year] = (async () => {
        try {
            document.body.classList.add('year-loading');
            const resp = await fetch(`${typeof FRAG_PATH_PREFIX !== 'undefined' ? FRAG_PATH_PREFIX : 'data-'}${year}.html`, { cache: "no-cache" });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const html = await resp.text();
            const container = document.getElementById('year-data-container');
            container.insertAdjacentHTML('beforeend', html);
            injectVeteranTags(container);
            _loadedYears.add(year);
            _sortedTabsCache = null;
            _leaderboardDataCache = null;
            _deltaDataCache = null;
            _officialDeltaDataCache = null;
        } catch (e) {
            console.error(`Failed to load year ${year}:`, e);
            throw e;
        } finally {
            delete _loadingYears[year];
            document.body.classList.remove('year-loading');
        }
    })();
    return _loadingYears[year];
}

async function loadApYear(year) {
    const key = `ap-${year}`;
    if (_loadedYears.has(key)) return;
    if (_loadingYears[key]) return _loadingYears[key];
    if (!AP_FRAGMENT_YEARS.includes(year)) {
        _loadedYears.add(key);
        return;
    }
    _loadingYears[key] = (async () => {
        try {
            const resp = await fetch(`data-ap-${year}.html`, { cache: "no-cache" });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const html = await resp.text();
            const container = document.getElementById('year-data-container');
            container.insertAdjacentHTML('beforeend', html);
            _loadedYears.add(key);
            _deltaDataCache = null;
            _officialDeltaDataCache = null;
            _apDeltaDataCache = {};
        } catch (e) {
            console.error(`Failed to load AP year ${year}:`, e);
        } finally {
            delete _loadingYears[key];
        }
    })();
    return _loadingYears[key];
}

const highlightClasses = [
    "team-highlight-1","team-highlight-2","team-highlight-3",
    "team-highlight-4","team-highlight-5"
];
const highlightColorSets = {
    light: {
        "team-highlight-1": "#0077cc",
        "team-highlight-2": "#ffcc00",
        "team-highlight-3": "#ff6666",
        "team-highlight-4": "#33cc33",
        "team-highlight-5": "#cc66ff"
    },
    dark: {
        "team-highlight-1": "#ffffff",
        "team-highlight-2": "#0099ff",
        "team-highlight-3": "#ff6666",
        "team-highlight-4": "#33cc33",
        "team-highlight-5": "#ffcc00"
    }
};
function getHighlightColors() {
    return isDarkMode() ? highlightColorSets.dark : highlightColorSets.light;
}

const highlightedTeams = {}; // "team-highlight-1" → team name, etc.

function applyHighlightStyles() {
    let el = document.getElementById("team-highlight-styles");
    if (!el) {
        el = document.createElement("style");
        el.id = "team-highlight-styles";
        document.head.appendChild(el);
    }
    const rules = [];
    const lit = highlightClasses.map(c => highlightedTeams[c]).filter(Boolean);
    // Dim mode (body.highlight-dim, Settings): fade every ballot logo that isn't highlighted.
    // Opacity only, no grayscale filter: any highlight change repaints most of the table, and
    // repainting ~2,000 filtered logos took ~250-400 ms per click in Safari (opacity ~70 ms).
    const nots = lit.map(t => `:not([data-team="${t}"])`).join("");
    if (lit.length) {
        rules.push(`body.highlight-dim:not(.outliers-on) td.logo-cell > .team-logo${nots} { opacity: 0.22; }`);
    }
    // Dim mode + Outliers: fade everything except outlier cells and highlighted teams.
    rules.push(`body.highlight-dim.outliers-on td.logo-cell:not(.outlier-high):not(.outlier-low) > .team-logo${nots} { opacity: 0.22; }`);
    highlightClasses.forEach(cls => {
        const team = highlightedTeams[cls];
        if (!team) return;
        const color = getHighlightColors()[cls];
        // Logos outside the ballot tables (modals, stats tables) keep the square glow.
        rules.push(`.team-logo[data-team="${team}"] { border-radius: 4px; box-shadow: 0 0 0 2px ${color}, 0 0 20px 6px ${color}; }`);
        // Ballot tables frame the cell instead: glowing frame in Glow mode, plain frame in
        // Dim mode and on rows showing Changes labels. Outlier marks live on the cell too (tag / bar).
        const cell = `td.logo-cell:has(> .team-logo[data-team="${team}"])`;
        rules.push(`td.logo-cell > .team-logo[data-team="${team}"] { box-shadow: none; }`);
        // The frame is a ::before layer: collapsed-border table cells ignore border-radius
        // and don't reliably paint an outer box-shadow.
        rules.push(`${cell} { position: relative; z-index: 1; }`);
        rules.push(`${cell}::before { content: ""; position: absolute; inset: 1px; border-radius: 3px; pointer-events: none; }`);
        rules.push(`body:not(.highlight-dim) ${cell}::before { box-shadow: inset 0 0 0 2px ${color}, 0 0 12px 2px ${color}; }`);
        rules.push(`body:not(.highlight-dim) .row-delta ${cell}::before, body.delta-move:not(.highlight-dim) ${cell}::before, body.delta-cons:not(.highlight-dim) ${cell}::before, body.highlight-dim ${cell}::before { box-shadow: inset 0 0 0 2px ${color}; }`);
        rules.push(`.chart-logo-ring[data-team="${team}"] { display: inline; stroke: ${color}; fill: ${color}; filter: url(#chart-glow-${cls}); }`);
        rules.push(`.chart-stroke[data-team="${team}"] { stroke: ${color}; filter: url(#chart-glow-${cls}); }`);
        rules.push(`.chart-fill[data-team="${team}"] { fill: ${color}; filter: url(#chart-glow-${cls}); }`);
        rules.push(`#voter-history-table .week-stats-table tr[data-team="${team}"] td { background: color-mix(in srgb, ${color} 22%, transparent); }`);
        rules.push(`#voter-history-table .week-stats-table tr[data-team="${team}"] td:first-child { box-shadow: inset 3px 0 0 ${color}; }`);
    });
    el.textContent = rules.join(" ");
    updateChartGlowFilters();
}

// SVG glow filters for highlighted week graph data. CSS drop-shadow() isn't rendered on
// SVG child elements in Safari, so use real <filter>s. userSpaceOnUse keeps zero-width
// bars and zero-height caps from getting an empty filter region.
function updateChartGlowFilters() {
    let defs = document.getElementById("chart-glow-defs");
    if (!defs) {
        defs = document.createElementNS(SVG_NS, "svg");
        defs.id = "chart-glow-defs";
        defs.setAttribute("width", "0"); defs.setAttribute("height", "0");
        defs.style.cssText = "position:absolute;width:0;height:0;overflow:hidden;";
        document.body.appendChild(defs);
    }
    defs.innerHTML = highlightClasses.map(cls => {
        const color = getHighlightColors()[cls];
        return `<filter id="chart-glow-${cls}" filterUnits="userSpaceOnUse" x="-1000" y="-1000" width="4000" height="4000">` +
            `<feDropShadow dx="0" dy="0" stdDeviation="3" flood-color="${color}" flood-opacity="1"/></filter>`;
    }).join("");
}

// Shared toggle used by ballot logos, rank headers, and week graph logos
function toggleTeamHighlight(team) {
    const isHighlighted = highlightClasses.some(c => highlightedTeams[c] === team);
    if (isHighlighted) {
        highlightClasses.forEach(c => { if (highlightedTeams[c] === team) delete highlightedTeams[c]; });
    } else {
        const availableColor = highlightClasses.find(c => !highlightedTeams[c]);
        if (availableColor) highlightedTeams[availableColor] = team;
    }
    applyHighlightStyles();
    updateAvgRankLines();
}

function getOffsetLeftInContainer(el, container) {
    let x = 0;
    while (el && el !== container) {
        x += el.offsetLeft;
        el = el.offsetParent;
    }
    return x;
}

function updateAvgRankLines() {
    document.querySelectorAll(".avg-rank-line").forEach(el => el.remove());
    // Clear previous consensus header highlights
    document.querySelectorAll("th[data-consensus-highlight]").forEach(th => {
        th.style.color = "";
        delete th.dataset.consensusHighlight;
        delete th.dataset.consensusColor;
    });
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const blockId = (_apCurrentYear && _apCurrentWeekNum)
        ? `week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`
        : activeTab.dataset.week;
    const block = document.getElementById(blockId);
    if (!block) return;
    const officialSection = block.querySelectorAll(".ballot-section")[0];
    if (!officialSection || officialSection.style.display === "none") return;
    const container = officialSection.querySelector(".table-container");
    if (!container) return;
    const voterRows = Array.from(officialSection.querySelectorAll(".voter-row"))
        .filter(r => !r.classList.contains("row-pinned-agg") && !r.classList.contains("row-weighted-ranking"));
    if (voterRows.length === 0) return;
    const sampleCells = voterRows[0].querySelectorAll("td");

    // Get the aggregate row for consensus rank lookup
    const aggSection = block.querySelectorAll(".ballot-section")[2];
    const aggRow = aggSection ? aggSection.querySelector(".voter-row") : null;

    // Official table header ths: th[0]=voter, th[1..25]=ranks
    const headerThs = officialSection.querySelectorAll("thead th");

    highlightClasses.forEach(cls => {
        const team = highlightedTeams[cls];
        if (!team) return;
        const color = getHighlightColors()[cls];
        const ranks = [];
        voterRows.forEach(row => {
            let found = false;
            row.querySelectorAll("td.logo-cell").forEach((cell, idx) => {
                if (cell.querySelector(`.team-logo[data-team="${team}"]`)) { ranks.push(idx + 1); found = true; }
            });
            if (!found) ranks.push(26);
        });
        const avg = ranks.reduce((a, b) => a + b, 0) / ranks.length;
        if (avg > 25) return;
        const floorR = Math.floor(avg);
        const ceilR = Math.ceil(avg);
        const frac = avg - floorR;
        const getX = r => {
            const cell = sampleCells[r];
            if (!cell) return 0;
            return getOffsetLeftInContainer(cell, container) + cell.offsetWidth / 2;
        };
        const x = floorR === ceilR ? getX(floorR) : getX(floorR) + (getX(ceilR) - getX(floorR)) * frac;
        const line = document.createElement("div");
        line.className = "avg-rank-line";
        line.style.left = x + "px";
        line.style.background = color;
        container.appendChild(line);

        // Color the consensus rank header number
        if (aggRow) {
            let consensusRank = -1;
            aggRow.querySelectorAll("td.logo-cell").forEach((cell, idx) => {
                if (cell.querySelector(`.team-logo[data-team="${team}"]`)) consensusRank = idx + 1;
            });
            if (consensusRank >= 1 && consensusRank <= 25 && headerThs[consensusRank]) {
                const th = headerThs[consensusRank];
                th.style.color = color;
                th.dataset.consensusHighlight = "1";
                th.dataset.consensusColor = color;
            }
        }
    });
}

function lazyLoadWeek(block) {
    if (!block) return;
    assignBallotLogos(block.querySelectorAll("img[data-src]"));
}

function getSortedTabs() {
    if (_sortedTabsCache) return _sortedTabsCache;
    _sortedTabsCache = Array.from(document.querySelectorAll(".week-tab"))
        .filter(t => t.dataset.poll !== "ap")
        .sort((a, b) => parseInt(b.dataset.year) - parseInt(a.dataset.year) || parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum));
    return _sortedTabsCache;
}

let _sortedApTabsCache = null;
function getSortedApTabs() {
    if (_sortedApTabsCache) return _sortedApTabsCache;
    _sortedApTabsCache = Array.from(document.querySelectorAll(".week-tab[data-poll='ap']"))
        .sort((a, b) => parseInt(b.dataset.year) - parseInt(a.dataset.year) || parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum));
    return _sortedApTabsCache;
}

function getVoterName(row) {
    // The injected "Overall" row stands in for the aggregate row (Official/AP Overall)
    if (row?.dataset?.voterAlias) return row.dataset.voterAlias;
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
                clone.querySelectorAll(".pin-btn, .history-btn, .ballot-link-btn").forEach(el => el.remove());
                clone.querySelectorAll(".voter-cell").forEach(el => el.dataset.bound = "");
                clone.querySelectorAll(".team-logo").forEach(el => el.dataset.bound = "");
                aggTbody.appendChild(clone);
                bindVoterCells(clone);
                bindTeamLogos(clone);
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

// Pinned usernames, in pin order. Source of truth for pin state so rows in
// lazily-loaded weeks/years pick up the pin when they are sorted.
const pinnedUsers = new Set();

function pinRow(row, tbody) {
    const username = getVoterName(row);
    // Skip aggregate-section clones: syncPinnedToAggregate adds/removes those.
    // Moving them here can push a clone above the Official Overall row.
    const allRows = getRowsByUsername(username).filter(r => !r.classList.contains("row-pinned-agg"));
    const isPinned = pinnedUsers.has(username) || row.classList.contains("row-pinned");

    if (isPinned) pinnedUsers.delete(username);
    else pinnedUsers.add(username);

    allRows.forEach(r => {
        const rTbody = r.closest("tbody");
        if (isPinned) {
            r.classList.remove("row-pinned");
            r.querySelector(".pin-btn")?.classList.remove("pinned");
            // Return to alphabetical position (non-visible weeks are re-sorted
            // with the current sort when they are shown)
            const siblings = Array.from(rTbody.querySelectorAll("tr"));
            const uname = username.toLowerCase();
            let insertBefore = null;
            for (const s of siblings) {
                if (s === r) continue;
                if (s.classList.contains("row-pinned") || s.classList.contains("overall-row")) continue;
                const sName = (getVoterName(s) || "").toLowerCase();
                if (sName > uname) { insertBefore = s; break; }
            }
            rTbody.insertBefore(r, insertBefore);
        } else {
            r.classList.add("row-pinned");
            r.querySelector(".pin-btn")?.classList.add("pinned");
            const siblings = Array.from(rTbody.querySelectorAll("tr"));
            const lastPinned = siblings.filter(s => s !== r && s.classList.contains("row-pinned")).pop();
            const overallRow = rTbody.querySelector(".overall-row");
            if (lastPinned) lastPinned.after(r);
            else if (overallRow) overallRow.after(r);
            else rTbody.prepend(r);
        }
    });
    syncPinnedToAggregate(username, !isPinned);
    // Hide the pin/calendar/ballot-link menu immediately on both pin and unpin.
    // The row is moved in the DOM, so mouseleave never fires to clear it.
    allRows.forEach(r => r.classList.remove("voter-cell-hover"));
    // Re-apply the active sort so an unpinned voter returns to their sorted
    // spot (e.g. consensus order) and pinned voters stay on top.
    applyTableSort(currentSort);
}
// ── Changes (deltas) ─────────────────────────────────────────────────────────
// One label under each logo, chosen in the Changes window (#changes-modal, Functions › Show › Values):
//   off  — no labels, except rows opened one at a time by clicking a voter's name
//   move — places moved since the comparison poll (deltaWeeksBack polls back); a team
//          unranked in that poll counts as coming from #26
//   cons — voter rank vs this week's consensus (+ = voter ranks the team higher); the
//          Overall and Data Ballots rows show points instead
// applyDeltaToRow() builds both labels (.delta-label = movement, .avg-label = consensus or
// points); the body classes delta-move / delta-cons decide what CSS shows, so a mode
// switch only recomputes rows that have no labels yet. Small changes (1–2) are always
// grayed. The mode is saved per viewer in localStorage; the lookback (Shift+1–9 or Compare With) is not.
let deltaWeeksBack = 1;
const DELTA_MODES = [["off", "Off"], ["move", "Movement"], ["cons", "vs Consensus"]];
let deltaMode = "off";
let _lastOnDeltaMode = "move";
try {
    const m = localStorage.getItem("deltaMode");
    if (DELTA_MODES.some(([id]) => id === m)) deltaMode = m;
} catch (e) {}
// Phones always start with Changes off (labels crowd the narrow table).
if (isMobileScreen()) deltaMode = "off";
if (deltaMode !== "off") _lastOnDeltaMode = deltaMode;

function isMobileScreen() { return screen.width <= 768; }

function applyDeltaBodyClasses() {
    document.body.classList.toggle("delta-move", deltaMode === "move");
    document.body.classList.toggle("delta-cons", deltaMode === "cons");
}

// Ballot rows that get computed labels (Data Ballots ranking rows build their own).
function deltaRows(root) {
    return Array.from(root.querySelectorAll(".voter-row:not(.row-weighted-ranking), .overall-row"));
}

function activeWeekBlock() {
    if (_apCurrentYear !== null) return document.getElementById(`week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`);
    const id = document.querySelector(".week-tab.active")?.dataset.week;
    return id ? document.getElementById(id) : null;
}

// While a mode is on, give every ballot row in the shown week its labels.
function ensureDeltaLabels(block = activeWeekBlock()) {
    if (!block || deltaMode === "off") return;
    const rows = deltaRows(block).filter(r => r._deltaBack !== deltaWeeksBack || !r.querySelector(".delta-label"));
    if (!rows.length) return;
    const deltaData = buildDeltaData();
    const sortedTabs = getSortedTabs();
    rows.forEach(r => {
        r._deltaBack = deltaWeeksBack;
        applyDeltaToRow(r, block.id, deltaData, sortedTabs);
    });
}

function setDeltaMode(mode) {
    deltaMode = mode;
    if (mode !== "off") _lastOnDeltaMode = mode;
    try { localStorage.setItem("deltaMode", mode); } catch (e) {}
    // Rows opened one at a time belong to Off; any mode switch starts from a clean table.
    document.querySelectorAll(".row-delta").forEach(r => r.classList.remove("row-delta"));
    applyDeltaBodyClasses();
    ensureDeltaLabels();
    syncDeltaControls();
}

// Shift+E: Off → Movement → vs Consensus → Off.
function cycleDeltaMode() {
    const i = DELTA_MODES.findIndex(([id]) => id === deltaMode);
    setDeltaMode(DELTA_MODES[(i + 1) % DELTA_MODES.length][0]);
}

function setDeltaWeeksBack(n) {
    deltaWeeksBack = n;
    const open = deltaRows(document).filter(r => r.classList.contains("row-delta"));
    deltaRows(document).forEach(r => {
        r._deltaBack = undefined;
        r.querySelectorAll(".delta-label, .avg-label").forEach(el => el.remove());
    });
    if (open.length) {
        const deltaData = buildDeltaData();
        const sortedTabs = getSortedTabs();
        open.forEach(r => {
            const wid = r.closest(".week-block")?.id;
            if (wid) { r._deltaBack = n; applyDeltaToRow(r, wid, deltaData, sortedTabs); }
        });
    }
    ensureDeltaLabels();
    syncDeltaControls();
}

// [[polls back, label], …] for the Changes window's Compare With dropdown: earlier polls of the shown week's season.
function deltaSinceOptions() {
    const isAp = _apCurrentYear !== null;
    const tabs = isAp ? getSortedApTabs() : getSortedTabs();
    const curId = isAp ? `week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`
        : document.querySelector(".week-tab.active")?.dataset.week;
    const i = tabs.findIndex(t => t.dataset.week === curId);
    const opts = [];
    if (i < 0) return opts;
    for (let k = 1; k <= 9; k++) {
        const t = tabs[i + k];
        if (!t || t.dataset.year !== tabs[i].dataset.year) break;
        opts.push([k, `Week ${displayWeekNum(t)}` + (k === 1 ? " (last poll)" : "")]);
    }
    return opts;
}

// Changes window (Functions › Show › Values; markup in build_full_html()): styled like
// Settings. Mode items and the Compare With dropdown act in place and keep it open. Compare
// With shows only in Movement (Off and vs Consensus have no lookback) and lists earlier polls of this season.
function showChangesModal() {
    const modal = document.getElementById("changes-modal");
    syncDeltaControls();
    modal.classList.add("open");
    (modal.querySelector(".settings-item.active") || modal.querySelector(".settings-item"))?.focus();
}

function initChangesModal() {
    const modal = document.getElementById("changes-modal");
    if (!modal) return;
    modal.addEventListener("click", e => {
        const b = e.target.closest(".settings-item");
        if (!b || b.disabled) return;
        if (b.dataset.deltaMode) setDeltaMode(b.dataset.deltaMode);
        // Mode buttons are relabelled above; keep focus on the clicked choice.
        modal.querySelector(`.settings-item[data-delta-mode="${b.dataset.deltaMode}"]`)?.focus();
    });
    modal.querySelector("#changes-since-select")?.addEventListener("change", e => {
        const n = parseInt(e.target.value, 10);
        if (n > 0) setDeltaWeeksBack(n);
    });
    syncDeltaControls();
}

function syncDeltaControls() {
    const modal = document.getElementById("changes-modal");
    if (modal) {
        modal.querySelectorAll("[data-delta-mode]").forEach(b => {
            const on = b.dataset.deltaMode === deltaMode;
            b.classList.toggle("active", on);
            b.setAttribute("aria-pressed", on ? "true" : "false");
        });
        const hideSince = deltaMode !== "move";
        modal.querySelector("#changes-since-group").hidden = hideSince;
        const sel = modal.querySelector("#changes-since-select");
        sel.hidden = hideSince;
        const opts = deltaSinceOptions();
        const cur = Math.min(deltaWeeksBack, Math.max(opts.length, 1));
        sel.innerHTML = opts.length
            ? opts.map(([k, label]) => `<option value="${k}"${k === cur ? " selected" : ""}>${label}</option>`).join("")
            : `<option value="0">No earlier poll this season</option>`;
        sel.disabled = !opts.length;
    }
    syncDeltasMenu();
}

// Underline Functions › Show › Values while a mode is on.
function syncDeltasMenu(root = document) {
    root.querySelectorAll("[data-action='expandDeltas']").forEach(el => el.classList.toggle("active", deltaMode !== "off"));
}

function initDeltaControls() {
    applyDeltaBodyClasses();
    initChangesModal();
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initDeltaControls);
else initDeltaControls();

// ── Distance from consensus (shared) ──────────────────────────────────────────
// One measure used everywhere a ballot is compared to its week's consensus: the
// homepage Consensus sort and the Year window's Voters tab.

// Leave-one-out consensus: an official voter is scored against the consensus of every
// *other* official ballot, so their own ballot doesn't pull the target toward them.
// Points mirror _compute_aggregate_points() (rank 1 = 25 … rank 25 = 1); ties keep the
// rendered aggregate order (aggOrder), then fall back to name. Voters not in
// officialBallots (provisional) get the full aggregate order.
//   officialBallots: { voter: [team, …] }   aggOrder: rendered Official Overall teams
function makeLooConsensus(officialBallots, aggOrder) {
    const totalPts = {};
    Object.values(officialBallots).forEach(teams =>
        teams.slice(0, 25).forEach((t, i) => { totalPts[t] = (totalPts[t] || 0) + (25 - i); }));
    const aggIdx = {};
    aggOrder.forEach((t, i) => { aggIdx[t] = i; });
    const cache = {};
    return name => {
        const own = officialBallots[name];
        if (!own) return aggOrder;
        if (cache[name]) return cache[name];
        const pts = { ...totalPts };
        own.slice(0, 25).forEach((t, i) => { pts[t] -= 25 - i; });
        const order = Object.keys(pts).filter(t => pts[t] > 0).sort((a, b) =>
            (pts[b] - pts[a]) || ((aggIdx[a] ?? 99) - (aggIdx[b] ?? 99)) || a.localeCompare(b));
        return (cache[name] = order.length ? order.slice(0, 25) : aggOrder);
    };
}

// Signed per-team gaps between a ballot and its consensus top 25 (cons), counted both ways:
// (1) each consensus team vs. where the voter has it (unranked = #26), then
// (2) each team the voter ranks that's outside the consensus top 25, treated as
//     consensus #26. The cap means an off-consensus pick never costs more than a
//     ranked team moving up from #26 would; without (2) it was nearly free.
// gap = consensus rank − voter rank, so positive = the voter has the team higher.
function consensusTeamGaps(teams, cons) {
    const out = [];
    for (let i = 0; i < cons.length; i++) {
        const vr = teams.indexOf(cons[i]);
        out.push({ team: cons[i], gap: i - (vr === -1 ? 25 : vr) });
    }
    const consSet = new Set(cons);
    teams.slice(0, 25).forEach((t, p) => { if (!consSet.has(t)) out.push({ team: t, gap: 25 - p }); });
    return out;
}
function consensusGaps(teams, cons) {
    return consensusTeamGaps(teams, cons).map(g => Math.abs(g.gap));
}

// Halved so a swap of two adjacent teams counts as 1, not 2. Every place a team
// moves up is matched by one moving down (omitted and off-consensus teams both
// sit at #26), so the raw sum is always even and the half is a whole number:
// "how many places this ballot's teams moved up vs. consensus".
function consensusDistance(teams, cons) {
    if (!teams?.length) return Infinity;
    return consensusGaps(teams, cons).reduce((s, g) => s + g, 0) / 2;
}

// Rendered Official Overall order from a week block's aggregate section.
function renderedConsensusOrder(sections) {
    const aggRow = sections[2]?.querySelector(".voter-row:not(.row-weighted-ranking):not(.row-pinned-agg)");
    return aggRow ? Array.from(aggRow.querySelectorAll(".team-logo")).map(img => img.dataset.team) : null;
}

// ── Outlier highlighting ──────────────────────────────────────────────────────

function getConsensusOrder(weekBlock) {
    const sections = weekBlock.querySelectorAll(".ballot-section");
    const aggRow = sections[2]?.querySelector(".voter-row:not(.row-weighted-ranking)");
    return aggRow
        ? Array.from(aggRow.querySelectorAll(".team-logo")).map(img => img.dataset.team)
        : null;
}

// Compute per-team mean rank and standard deviation across all voter rows in a section.
// Voters who left a team unranked count as rank 26, so omissions widen the spread
// instead of being ignored (matches the consensus side, which also treats missing as 26).
function computeTeamStats(section) {
    const teamRanks = {};
    let voterCount = 0;
    section.querySelectorAll(".voter-row").forEach(row => {
        if (row.classList.contains("row-weighted-ranking")) return;
        voterCount++;
        row.querySelectorAll(".logo-cell .team-logo").forEach((logo, idx) => {
            const team = logo.dataset.team;
            if (!teamRanks[team]) teamRanks[team] = [];
            teamRanks[team].push(idx + 1);
        });
    });
    const stats = {};
    for (const [team, rankedOnly] of Object.entries(teamRanks)) {
        const ranks = rankedOnly.concat(Array(Math.max(0, voterCount - rankedOnly.length)).fill(26));
        const n = ranks.length;
        const avg = ranks.reduce((s, r) => s + r, 0) / n;
        const sd = n >= 2
            ? Math.sqrt(ranks.reduce((s, r) => s + (r - avg) ** 2, 0) / n)
            : 0;
        stats[team] = { avg, sd };
    }
    return stats;
}

// The outlier test, shared by applyOutliers() and the vs Consensus labels:
// "high" / "low" / null for a team at voterRank on a ballot, given its consensus
// rank (26 = unranked) and its section stats from computeTeamStats().
function outlierKind(voterRank, cRank, stat) {
    const deviation = cRank - voterRank;
    if (!stat || !(stat.sd > 0) || Math.abs(deviation) < 3) return null;
    if (Math.abs(voterRank - stat.avg) / stat.sd < OUTLIER_SD_THRESHOLD) return null;
    // High outliers only count in the top 20; #21-25 is ordinary ballot filler.
    if (deviation > 0 && voterRank > OUTLIER_HIGH_MAX_RANK) return null;
    return deviation > 0 ? "high" : "low";
}

// computeTeamStats() per ballot section, cached (ballots in a section don't change).
const _sectionStatsCache = new WeakMap();
function sectionTeamStats(section) {
    if (!_sectionStatsCache.has(section)) _sectionStatsCache.set(section, computeTeamStats(section));
    return _sectionStatsCache.get(section);
}

function applyOutliers(weekBlock) {
    const consensus = getConsensusOrder(weekBlock);
    if (!consensus || consensus.length === 0) return;

    const consensusRankMap = {};
    consensus.forEach((team, i) => { consensusRankMap[team] = i + 1; });

    const sections = weekBlock.querySelectorAll(".ballot-section");
    // Target the visible voter section (Official or Provisional), not Aggregate
    const targetSection = Array.from(sections).find((s, i) => i < 2 && s.style.display !== "none")
        ?? (sections.length === 1 ? sections[0] : null);
    if (!targetSection) return;

    const teamStats = computeTeamStats(targetSection);

    targetSection.querySelectorAll(".voter-row").forEach(row => {
        if (row.classList.contains("row-weighted-ranking")) return;
        const logos = row.querySelectorAll(".logo-cell .team-logo");
        const voterTeams = new Set(Array.from(logos).map(img => img.dataset.team));
        let omitCount = 0;

        logos.forEach((logo, idx) => {
            const team = logo.dataset.team;
            const cell = logo.closest(".logo-cell");
            if (!cell) return;
            const voterRank = idx + 1;
            const cRank = consensusRankMap[team] ?? 26;
            const deviation = cRank - voterRank;
            const stat = teamStats[team];
            clearOutlierCell(cell);
            const kind = outlierKind(voterRank, cRank, stat);
            if (!kind) return;
            const z = Math.abs(voterRank - stat.avg) / stat.sd;
            const high = kind === "high";
            cell.classList.add(high ? "outlier-high" : "outlier-low");
            // Both modes show this tag plus a full-width bar (CSS).
            const tag = document.createElement("span");
            tag.className = "outlier-tag";
            // Unranked-by-consensus teams count as #26, so the number is the gap to unranked.
            tag.textContent = (high ? "+" : "−") + Math.abs(deviation);
            cell.appendChild(tag);
            cell.title = `${team}: #${voterRank} on this ballot · consensus ${cRank === 26 ? "unranked" : "#" + cRank} · avg ${stat.avg.toFixed(1)} · ${z.toFixed(1)}σ`;
        });

        const omittedTeams = [];
        for (let i = 0; i < Math.min(OUTLIER_OMISSION_TOP_N, consensus.length); i++) {
            if (consensus[i] && !voterTeams.has(consensus[i])) omittedTeams.push(consensus[i]);
        }
        omitCount = omittedTeams.length;

        let badge = row.querySelector(".voter-omission-badge");
        if (omitCount > 0) {
            if (!badge) {
                badge = document.createElement("span");
                badge.className = "voter-omission-badge";
                const nameEl = row.querySelector(".voter-name");
                if (nameEl) nameEl.after(badge);
            }
            badge.textContent = `⚠${omitCount}`;
            badge.title = omittedTeams.join(", ");
        } else if (badge) {
            badge.remove();
        }
    });
}

function clearOutlierCell(cell) {
    if (!cell.classList.contains("outlier-high") && !cell.classList.contains("outlier-low")) return;
    cell.classList.remove("outlier-high", "outlier-low");
    cell.removeAttribute("title");
    cell.querySelector(".outlier-tag")?.remove();
}

function clearOutliers(weekBlock) {
    weekBlock.querySelectorAll(".outlier-high, .outlier-low").forEach(clearOutlierCell);
    weekBlock.querySelectorAll(".voter-omission-badge").forEach(el => el.remove());
}

function toggleOutliers() {
    _outliersMode = !_outliersMode;
    document.body.classList.toggle("outliers-on", _outliersMode);
    applyHighlightStyles();
    document.querySelectorAll("[data-action='toggleOutliers']").forEach(el => {
        el.classList.toggle("active", _outliersMode);
    });
    const activeTab = document.querySelector(".week-tab.active");
    let block = null;
    if (_apCurrentYear && _apCurrentWeekNum) {
        block = document.getElementById(`week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`);
    } else if (activeTab) {
        block = document.getElementById(activeTab.dataset.week);
    }
    if (block) {
        if (_outliersMode) applyOutliers(block);
        else clearOutliers(block);
    }
}

function hideRankHeaders(block) {
    if (!block) return;
    block.querySelectorAll("table thead th:not(:first-child)").forEach(th => { th.style.color = "transparent"; th.style.borderRight = "none"; });
}

function showRankHeaders(block) {
    if (!block) return;
    block.querySelectorAll("table thead th:not(:first-child)").forEach(th => { th.style.color = th.dataset.consensusColor || ""; th.style.borderRight = ""; });
}

// Credits text runs on one line out to the table's right edge, shrinking its
// font only when the full line would not fit (never grows past the picker font).
function fitCreditsText(picker) {
    const text = picker.querySelector(".credits-text");
    const table = picker._toggle?.closest("table");
    if (!text || !table) return;
    text.style.fontSize = "";
    // Fit to the table, not the viewport: once the table hits its minimum width
    // and scrolls, the text stops shrinking with it.
    const avail = table.getBoundingClientRect().right - picker.getBoundingClientRect().left;
    const natural = text.scrollWidth;
    if (avail > 0 && natural > avail) {
        const base = parseFloat(getComputedStyle(text).fontSize);
        text.style.fontSize = (base * avail / natural) + "px";
    }
}
window.addEventListener("resize", () => {
    document.querySelectorAll(".sort-picker.open.credits-mode").forEach(fitCreditsText);
});

// Tables carry only the Functions toggle; the menu itself is cloned from the
// page's single <template id="picker-template"> on first use, then synced to
// the current sort and Show states (later changes reach it via the page-wide
// querySelectorAll updates in setGlobalSort, toggleOutliers and syncOverallMenu).
function createPicker(toggle) {
    const tpl = document.getElementById("picker-template");
    const picker = tpl?.content.firstElementChild?.cloneNode(true);
    if (!picker) return null;
    picker.querySelectorAll(".sort-option[data-sort]").forEach(o => {
        o.classList.toggle("active", o.dataset.sort === currentSort);
    });
    picker.querySelectorAll("[data-action='toggleOutliers']").forEach(o => o.classList.toggle("active", _outliersMode));
    picker.querySelectorAll("[data-action='toggleOverall']").forEach(o => o.classList.toggle("active", _showOverallRow));
    toggle.after(picker);
    return picker;
}

function bindVotersToggle() {
    document.querySelectorAll(".voters-toggle").forEach(toggle => {
        if (toggle.dataset.bound) return;
        toggle.dataset.bound = "1";
        toggle.addEventListener("click", e => {
            e.stopPropagation();
            const picker = toggle._picker || createPicker(toggle);
            if (!picker) return;
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
                const tableLeft = (toggle.closest("table") || toggle).getBoundingClientRect().left;
                picker.style.top = rect.top + "px";
                const th = toggle.closest("th");
                picker._thOffsetY = th ? rect.top - th.getBoundingClientRect().top : 0;
                picker.style.left = tableLeft + "px";
                // Match toggle font exactly
                const ts = getComputedStyle(toggle);
                picker.style.font = ts.font;
                toggle.style.display = "none";
                picker.classList.remove("credits-mode");
                syncDeltasMenu(picker);
                picker.classList.add("open");
                trackOpenSortPickers();
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
    const sort = opt.dataset.sort;
    const action = opt.dataset.action;
    const picker = opt.closest(".sort-picker");
    // Credits and the Show toggles act in place and keep the picker open. The
    // row can reflow under the cursor, so swallow the click that follows this
    // mousedown — otherwise it can land outside the picker and close it.
    const showToggles = ["toggleOverall", "toggleOutliers"];
    const inPlace = ["credits", ...showToggles].includes(action);
    if (inPlace) {
        const swallow = ev => ev.stopPropagation();
        window.addEventListener("click", swallow, { capture: true, once: true });
        setTimeout(() => window.removeEventListener("click", swallow, true), 1000);
    }
    if (action === "credits") {
        picker.classList.add("credits-mode");
        fitCreditsText(picker);
        return;
    }
    if (showToggles.includes(action)) {
        handlePickerAction(action);
        syncDeltasMenu(picker);
        return;
    }
    // Show the toggle again
    if (picker._toggle) picker._toggle.style.display = "";
    picker.classList.remove("open");
    // Restore rank headers when picker closes
    const block = picker._sourceBlock || picker.closest(".week-block");
    showRankHeaders(block);
    if (sort) {
        applyTableSort(sort);
    } else if (action) {
        handlePickerAction(action);
    }
}, true);

function handlePickerAction(action) {
    const activeTab = document.querySelector(".week-tab.active");
    const weekId = _apCurrentYear !== null
        ? `week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`
        : activeTab?.dataset.week;
    switch (action) {
        case "yearlyStats":
            showSeasonStatsModal();
            break;
        case "dotPlot":
            if (weekId) showWeekHighLowChart(weekId, "dots");
            break;
        case "highLow":
            if (weekId) showWeekHighLowChart(weekId, "highlow");
            break;
        case "heatmap":
            showHeatmapModal();
            break;
        case "results": {
            const isAp = _apCurrentYear !== null || ON_AP_PAGE;
            showVoterHistory(isAp ? "AP Overall" : "Official Overall");
            break;
        }
        case "toggleOverall":
            toggleOverallRow();
            break;
        case "expandDeltas":
            showChangesModal();
            break;
        case "toggleOutliers":
            toggleOutliers();
            break;
        case "settings":
            showSettingsModal();
            break;
    }
}

// Settings window (Functions › Settings): display toggles act in place and keep it open;
// the Other items close it first, then open their own window or run.
function showSettingsModal() {
    const modal = document.getElementById("settings-modal");
    refreshSettingsLabels(modal);
    modal.classList.add("open");
    modal.querySelector(".settings-item")?.focus();
}

document.getElementById("settings-modal").addEventListener("click", e => {
    const btn = e.target.closest(".settings-item");
    if (!btn) return;
    const action = btn.dataset.action;
    const close = () => document.getElementById("settings-modal").classList.remove("open");
    switch (action) {
        case "darkMode": toggleDarkMode(); break;
        case "weekArrows": setWeekArrowsVisible(!_showWeekArrows); break;
        case "highlightMode": setHighlightDim(!_highlightDim); break;
        case "avgLines": setAvgLinesVisible(!_showAvgLines); break;
        case "compactTable": setCompactTable(!_compactTable); break;
        case "savePng": close(); saveTableAsPng(); break;
        case "legend": close(); toggleKeybindLegend(); break;
        case "devPin":
            if (_pinLockedOut()) return;  // inert during the PIN lockout
            close(); openPinModal(); break;
    }
});

// Plain ↑/↓ move between items while the window is open (Enter/Space click the focused one).
// Same in the Changes window.
["settings-modal", "changes-modal"].forEach(id => document.getElementById(id).addEventListener("keydown", e => {
    if (e.shiftKey || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
    const items = [...e.currentTarget.querySelectorAll(".settings-item:not(:disabled)")].filter(el => el.offsetParent);
    const i = items.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
}));

let currentSort = "alphabetic";

const SORT_LABELS = { alphabetic: "Functions", zetabetique: "Zétabétique", consensus: "Consensus" };

function setGlobalSort(sort) {
    currentSort = sort;
    const label = SORT_LABELS[sort] || (sort.charAt(0).toUpperCase() + sort.slice(1));
    document.querySelectorAll(".voters-toggle").forEach(t => {
        if (t.style.display !== "none") t.textContent = label;
    });
    document.querySelectorAll(".sort-option[data-sort]").forEach(o => {
        o.classList.toggle("active", o.dataset.sort === sort);
    });
    document.body.classList.toggle("hide-veteran-tags", (sort !== "alphabetic" && sort !== "zetabetique") || _hideVeteranTagsOverride);
}


function applyTableSort(sort) {
    setGlobalSort(sort);
    // Close all sort pickers
    document.querySelectorAll(".sort-picker.open").forEach(p => {
        if (p._toggle) p._toggle.style.display = "";
        showRankHeaders(p._sourceBlock || p.closest(".week-block"));
        p.classList.remove("open");
    });
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const blockId = _apCurrentYear !== null
        ? `week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`
        : activeTab.dataset.week;
    const block = document.getElementById(blockId);
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

    const allRows = Array.from(tbody.querySelectorAll(".voter-row"));

    // Separate fixed-position rows (always shown first) from sortable voter rows
    const pinnedFirst = allRows.filter(r => {
        const n = getVoterName(r);
        return n === "Official Overall" || n === "AP Overall" || n === "Recency" || r.classList.contains("row-weighted-ranking");
    });
    // User-pinned voters stay directly below the fixed rows, in pin order
    const pinOrder = Array.from(pinnedUsers);
    const userPinned = allRows
        .filter(r => !pinnedFirst.includes(r) && pinnedUsers.has(getVoterName(r)))
        .sort((a, b) => pinOrder.indexOf(getVoterName(a)) - pinOrder.indexOf(getVoterName(b)));
    userPinned.forEach(r => {
        if (r.classList.contains("row-pinned-agg")) return;
        r.classList.add("row-pinned");
        r.querySelector(".pin-btn")?.classList.add("pinned");
    });
    pinnedFirst.push(...userPinned);
    const rows = allRows.filter(r => !pinnedFirst.includes(r));

    // Clear any existing consensus distance labels
    document.querySelectorAll(".consensus-dist").forEach(el => el.remove());

    const addVoterLabel = (row, text) => {
        const cell = row.querySelector(".voter-cell");
        if (!cell) return;
        const label = document.createElement("span");
        label.className = "consensus-dist";
        label.textContent = text;
        cell.appendChild(label);
    };

    if (sort === "alphabetic") {
        rows.sort((a, b) => getVoterName(a).localeCompare(getVoterName(b)));
        [...pinnedFirst, ...rows].forEach(r => tbody.appendChild(r));
        return;
    }

    if (sort === "zetabetique") {
        rows.sort((a, b) => getVoterName(b).localeCompare(getVoterName(a)));
        [...pinnedFirst, ...rows].forEach(r => tbody.appendChild(r));
        return;
    }

    if (sort === "consensus") {
        // Sort by deviation from official consensus (most conformist first)
        // Read consensus directly from the rendered aggregate row so it always
        // matches the Official Overall row exactly (avoids recompute divergence).
        const consensus = renderedConsensusOrder(sections);
        if (!consensus || !consensus.length) return;
        const rowTeams = r => Array.from(r.querySelectorAll(".team-logo")).map(img => img.dataset.team);

        // Leave-one-out consensus per official voter (see makeLooConsensus()).
        const officialBallots = {};
        sections[0]?.querySelectorAll("tbody .voter-row").forEach(r => {
            if (r.classList.contains("row-weighted-ranking") || r.classList.contains("row-pinned-agg") ||
                r.classList.contains("overall-row") || r.dataset.voterAlias) return;
            const teams = rowTeams(r);
            const u = getVoterName(r);
            if (u && teams.length) officialBallots[u] = teams;
        });
        const consensusFor = makeLooConsensus(officialBallots, consensus);
        const gapsFn = consensusGaps;
        const scoreFn = (teams, name) => consensusDistance(teams, consensusFor(name));
        // Get voter teams directly from visible rows
        const voterTeams = {};
        rows.forEach(r => { voterTeams[getVoterName(r)] = rowTeams(r); });
        const tiebreakFn = (ua, ub) => {
            const ta = voterTeams[ua], tb = voterTeams[ub];
            if (!ta?.length || !tb?.length) return 0;
            const ga = gapsFn(ta, consensusFor(ua)), gb = gapsFn(tb, consensusFor(ub));
            for (let i = 0; i < Math.min(ga.length, gb.length); i++) {
                if (ga[i] !== gb[i]) return ga[i] - gb[i];
            }
            return 0;
        };
        // Total for sorting, plus a trimmed per-team average in parentheses: drop the
        // ballot's two largest gaps, halve the rest like the total, divide by 25. Forgives one or two big
        // swings without hiding a ballot that differs from consensus everywhere.
        const TRIM_TOP_GAPS = 2;
        const distLabel = (dist, teams, name) => {
            const gaps = gapsFn(teams, consensusFor(name)).sort((a, b) => b - a);
            const trimmed = gaps.slice(TRIM_TOP_GAPS).reduce((s, g) => s + g, 0) / 2 / 25;
            return `${dist} (${trimmed.toFixed(2)})`;
        };
        const scores = {};
        rows.forEach(r => { const u = getVoterName(r); scores[u] = scoreFn(voterTeams[u], u); });
        rows.sort((a, b) => {
            const ua = getVoterName(a), ub = getVoterName(b);
            const sa = scores[ua], sb = scores[ub];
            return sa !== sb ? sa - sb : tiebreakFn(ua, ub);
        });
        pinnedFirst.forEach(r => {
            tbody.appendChild(r);
            if (userPinned.includes(r)) {
                const teams = rowTeams(r), name = getVoterName(r);
                const dist = scoreFn(teams, name);
                if (dist !== Infinity) addVoterLabel(r, distLabel(dist, teams, name));
            }
        });
        rows.forEach(r => {
            tbody.appendChild(r);
            const name = getVoterName(r);
            const dist = scores[name];
            if (dist !== Infinity) addVoterLabel(r, distLabel(dist, voterTeams[name], name));
        });
        return;
    }

}

function bindVoterCells(root) {
    (root || document).querySelectorAll(".voter-cell").forEach(cell => {
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

        // Add ballot link button if not already present and URL exists
        if (!cell.querySelector(".ballot-link-btn") && cell.dataset.ballotUrl) {
            const lnk = document.createElement("span");
            lnk.className = "ballot-link-btn";
            lnk.title = "Open ballot";
            lnk.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';
            lnk.addEventListener("click", e => {
                e.stopPropagation();
                const url = cell.dataset.ballotUrl;
                if (url) window.open(url, "_blank", "noopener,noreferrer");
            });
            cell.appendChild(lnk);
        }

        cell.addEventListener("mouseenter", () => {
            cell.closest("tr")?.classList.add("voter-cell-hover");
        });
        cell.addEventListener("mouseleave", () => {
            cell.closest("tr")?.classList.remove("voter-cell-hover");
        });

        cell.addEventListener("click", e => {
            const row = cell.closest("tr");
            if (deltaMode !== "off") return;

            // Special handling for the Recency aggregate row
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

// Compute the Recency top-25 teams for a given week.
// Accepts pre-built deltaData and the year's tabs (sorted oldest-last, i.e. getSortedTabs() order).
// Returns { ranked, teamAvgRankSum, totalVoters } or null if no data.
function compute5WeekWeighted(weekId, deltaData, yearTabs) {
    const currIdx = yearTabs.findIndex(t => t.dataset.week === weekId);
    if (currIdx === -1) return null;
    const last5WeekIds = [];
    for (let i = currIdx; i < yearTabs.length && last5WeekIds.length < 5; i++) {
        last5WeekIds.push(yearTabs[i].dataset.week);
    }
    if (last5WeekIds.length === 0) return null;
    const currentVoters = Object.keys(deltaData[weekId] || {}).filter(u => u !== "Official Overall");
    if (currentVoters.length === 0) return null;
    const allTeamsSeen = new Set();
    last5WeekIds.forEach(wid => {
        Object.entries(deltaData[wid] || {}).forEach(([u, ballot]) => {
            if (u !== "Official Overall" && ballot?.length) ballot.forEach(t => allTeamsSeen.add(t));
        });
    });
    const teamAvgRankSum = {};
    currentVoters.forEach(username => {
        const voterLast5 = last5WeekIds.map(wid => deltaData[wid]?.[username] || null);
        allTeamsSeen.forEach(team => {
            let weightedSum = 0, totalWeight = 0;
            voterLast5.forEach((ballot, wi) => {
                if (!ballot) return;
                const weight = last5WeekIds.length - wi;
                const pos = ballot.indexOf(team);
                weightedSum += (pos === -1 ? 26 : pos + 1) * weight;
                totalWeight += weight;
            });
            if (totalWeight > 0) teamAvgRankSum[team] = (teamAvgRankSum[team] || 0) + weightedSum / totalWeight;
        });
    });
    const ranked = Object.entries(teamAvgRankSum).sort((a, b) => a[1] - b[1]).slice(0, 25).map(([team]) => team);
    return ranked.length > 0 ? { ranked, teamAvgRankSum, totalVoters: currentVoters.length } : null;
}

// Build a map of { weekId -> teams[] | null } for the given username across all loaded weeks.
// Works for regular voters, "Official Overall" (aggregate row), and "Recency" (computed).
// Pass `tabs` to override which tabs (and their blocks) are scanned — used for AP mode.
function buildSeasonDataForUser(username, tabs) {
    const result = {};
    const allTabsSorted = tabs || getSortedTabs();
    if (username === "Recency") {
        const deltaData = buildDeltaData(true);
        const yearGroups = {};
        allTabsSorted.forEach(tab => {
            if (!yearGroups[tab.dataset.year]) yearGroups[tab.dataset.year] = [];
            yearGroups[tab.dataset.year].push(tab);
        });
        allTabsSorted.forEach(tab => {
            const w = compute5WeekWeighted(tab.dataset.week, deltaData, yearGroups[tab.dataset.year]);
            result[tab.dataset.week] = w ? w.ranked : null;
        });
        return result;
    }
    // For all named rows (regular voters and "Official Overall"):
    allTabsSorted.forEach(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        result[weekId] = null;
        if (!block) return;
        outer: for (const section of block.querySelectorAll(".ballot-section")) {
            for (const row of section.querySelectorAll(".voter-row")) {
                if (getVoterName(row) !== username) continue;
                result[weekId] = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
                break outer;
            }
        }
    });
    return result;
}

function renderVoterHistoryTable(mergedData, yearTabs, container) {
    container.innerHTML = "";
    container.style.cssText = "";

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
    container.appendChild(thead);

    const tbody = document.createElement("tbody");
    yearTabs.forEach(tab => {
        const weekId = tab.dataset.week;
        const teams = mergedData[weekId];
        if (!teams || teams.length === 0) return;
        const tr = document.createElement("tr");

        const weekTd = document.createElement("td");
        weekTd.className = "week-label";
        weekTd.textContent = weekTextLabel(tab) || ("Week " + displayWeekNum(tab));
        weekTd.style.cssText = "white-space:nowrap; padding-right:16px; width:1px; min-width:0;";
        tr.appendChild(weekTd);

        teams.slice(0, 25).forEach(team => {
            const td = document.createElement("td");
            const img = document.createElement("img");
            img.className = "logo team-logo";
            setLogoSrc(img, team);
            img.alt = team;
            img.dataset.team = team;
            td.appendChild(img);
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    container.appendChild(tbody);
}


function showVoterHistory(username) {
    const isAp = _apCurrentYear !== null;
    const allTabsSorted = isAp ? getSortedApTabs() : getSortedTabs();

    // Build ballot data for all weeks
    const mergedData = buildSeasonDataForUser(username, allTabsSorted);

    // Use the active week's year
    const activeTab = document.querySelector(".week-tab.active");
    const currentYear = isAp ? _apCurrentYear : (activeTab?.dataset.year || allTabsSorted[0]?.dataset.year);
    const yearTabs = allTabsSorted
        .filter(t => t.dataset.year === currentYear)
        .reverse();

    const modal = document.getElementById("voter-history-modal");
    const title = document.getElementById("voter-history-title");
    const table = document.getElementById("voter-history-table");
    table.classList.remove("week-stats-table");

    title.textContent = username + " \u2013 " + currentYear + " Ballots";

    renderVoterHistoryTable(mergedData, yearTabs, table);
    modal.classList.add("open");
    bindTeamLogos();
}

document.getElementById("voter-history-modal").addEventListener("click", e => {
    if (e.target === e.currentTarget) e.currentTarget.classList.remove("open");
});


function bindTeamLogos(root) {
    (root || document).querySelectorAll(".team-logo").forEach(logo => {
        if (logo.dataset.bound) return;
        logo.dataset.bound = "1";
        logo.addEventListener("click", (e) => {
            if (e.altKey) {
                e.stopPropagation();
                e.preventDefault();
                showTeamSeasonDotPlot(logo.dataset.team);
                return;
            }
            if (e.shiftKey) {
                e.stopPropagation();
                const team = logo.dataset.team;
                const row = logo.closest(".voter-row, .overall-row");
                const username = row ? getVoterName(row) : null;
                showTeamRankChart(team, username);
                return;
            }
            const team = logo.dataset.team;
            toggleTeamHighlight(team);
        });
    });
}

function bindRankHeaders() {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const block = document.getElementById(activeTab.dataset.week);
    if (!block) return;
    const officialSection = block.querySelectorAll(".ballot-section")[0];
    if (!officialSection) return;
    officialSection.querySelectorAll("thead .rank-header-num").forEach((span, i) => {
        if (span.dataset.rankBound) return;
        span.dataset.rankBound = "1";
        const rank = i + 1;
        span.addEventListener("click", () => {
            const aggSection = block.querySelectorAll(".ballot-section")[2];
            if (!aggSection) return;
            const aggRow = aggSection.querySelector(".voter-row:not(.row-weighted-ranking)");
            if (!aggRow) return;
            const logo = aggRow.querySelectorAll("td.logo-cell")[rank - 1]?.querySelector(".team-logo");
            if (!logo) return;
            const team = logo.dataset.team;
            toggleTeamHighlight(team);
        });
    });
}

function showTeamRankChart(team, username) {
    const isAp = _apCurrentYear !== null;
    const allTabsSorted = isAp ? getSortedApTabs() : getSortedTabs();

    // Build ballot data for all weeks (works for all row types)
    const mergedData = username ? buildSeasonDataForUser(username, allTabsSorted) : {};

    // Current year's weeks in chronological order
    const activeTab = document.querySelector(".week-tab.active");
    const currentYear = isAp ? _apCurrentYear : (activeTab?.dataset.year || allTabsSorted[0]?.dataset.year);
    const yearTabs = allTabsSorted.filter(t => t.dataset.year === currentYear).reverse();

    // Build data points: rank per week (null = not ranked, hasBallot = submitted a ballot that week)
    const dataPoints = yearTabs.map(tab => {
        const weekId = tab.dataset.week;
        const weekNum = parseInt(tab.dataset.weeknum);
        let rank = null;
        const teams = username ? mergedData[weekId] : null;
        const hasBallot = !!teams;
        if (teams) {
            const idx = teams.indexOf(team);
            if (idx !== -1) rank = idx + 1;
        }
        return { weekNum, rank, hasBallot };
    });

    const modal = document.getElementById("voter-history-modal");
    const title = document.getElementById("voter-history-title");
    const table = document.getElementById("voter-history-table");
    table.classList.remove("week-stats-table");

    title.innerHTML = `<img class="logo" src="${logoSrc(team)}" style="height:22px;vertical-align:middle;margin-right:6px;">${formatTeamName(team)} — ${username || "Unknown"}`;
    table.innerHTML = "";
    table.style.cssText = "display:block; white-space:normal; width:100%;";

    // SVG chart
    const svgNS = SVG_NS;
    const W = 900, H = 500;
    const mL = 44, mR = 20, mT = 28, mB = 40;
    const cW = W - mL - mR, cH = H - mT - mB;

    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.style.cssText = "width:min(860px,90vw);display:block;margin:0 auto;";

    const weeks = dataPoints.map(d => d.weekNum);
    const minW = Math.min(...weeks), maxW = Math.max(...weeks);
    const wRange = Math.max(maxW - minW, 1);
    const xPos = w => mL + ((w - minW) / wRange) * cW;
    const yPos = r => mT + ((r - 1) / 24) * cH;  // rank 1 at top

    const { axisColor, gridColor, borderColor, nrLineColor, nrTextColor, circleStroke } = svgColors();

    // Rank gridlines + y-axis labels
    [1, 5, 10, 15, 20, 25].forEach(r => {
        const y = yPos(r);
        const line = document.createElementNS(svgNS, "line");
        line.setAttribute("x1", mL); line.setAttribute("x2", mL + cW);
        line.setAttribute("y1", y); line.setAttribute("y2", y);
        line.setAttribute("stroke", gridColor); line.setAttribute("stroke-width", "1");
        svg.appendChild(line);
        const txt = document.createElementNS(svgNS, "text");
        txt.setAttribute("x", mL - 6); txt.setAttribute("y", y + 4);
        txt.setAttribute("text-anchor", "end"); txt.setAttribute("font-size", "11");
        txt.setAttribute("fill", axisColor);
        txt.textContent = r;
        svg.appendChild(txt);
    });

    // Chart border
    const border = document.createElementNS(svgNS, "rect");
    border.setAttribute("x", mL); border.setAttribute("y", mT);
    border.setAttribute("width", cW); border.setAttribute("height", cH);
    border.setAttribute("fill", "none"); border.setAttribute("stroke", borderColor);
    border.setAttribute("stroke-width", "1");
    svg.appendChild(border);

    // Y-axis label
    const yLbl = document.createElementNS(svgNS, "text");
    yLbl.setAttribute("x", 10); yLbl.setAttribute("y", mT + cH / 2);
    yLbl.setAttribute("text-anchor", "middle"); yLbl.setAttribute("font-size", "11");
    yLbl.setAttribute("fill", axisColor);
    yLbl.setAttribute("transform", `rotate(-90,10,${mT + cH / 2})`);
    yLbl.textContent = "Rank";
    svg.appendChild(yLbl);

    // X-axis ticks + week labels
    dataPoints.forEach(d => {
        const x = xPos(d.weekNum);
        const tick = document.createElementNS(svgNS, "line");
        tick.setAttribute("x1", x); tick.setAttribute("x2", x);
        tick.setAttribute("y1", mT + cH); tick.setAttribute("y2", mT + cH + 4);
        tick.setAttribute("stroke", axisColor);
        svg.appendChild(tick);
        const txt = document.createElementNS(svgNS, "text");
        txt.setAttribute("x", x); txt.setAttribute("y", mT + cH + 15);
        txt.setAttribute("text-anchor", "middle"); txt.setAttribute("font-size", "11");
        txt.setAttribute("fill", axisColor);
        txt.textContent = d.weekNum;
        svg.appendChild(txt);
    });

    // X-axis label
    const xLbl = document.createElementNS(svgNS, "text");
    xLbl.setAttribute("x", mL + cW / 2); xLbl.setAttribute("y", H - 4);
    xLbl.setAttribute("text-anchor", "middle"); xLbl.setAttribute("font-size", "11");
    xLbl.setAttribute("fill", axisColor);
    xLbl.textContent = "Week";
    svg.appendChild(xLbl);

    // Dashed vertical line for NR weeks (only when ballot was submitted but team not ranked)
    dataPoints.filter(d => d.rank === null && d.hasBallot).forEach(d => {
        const x = xPos(d.weekNum);
        const nrLine = document.createElementNS(svgNS, "line");
        nrLine.setAttribute("x1", x); nrLine.setAttribute("x2", x);
        nrLine.setAttribute("y1", mT); nrLine.setAttribute("y2", mT + cH);
        nrLine.setAttribute("stroke", nrLineColor); nrLine.setAttribute("stroke-width", "1");
        nrLine.setAttribute("stroke-dasharray", "3,3");
        svg.appendChild(nrLine);
        const nrTxt = document.createElementNS(svgNS, "text");
        nrTxt.setAttribute("x", x); nrTxt.setAttribute("y", mT + cH - 5);
        nrTxt.setAttribute("text-anchor", "middle"); nrTxt.setAttribute("font-size", "9");
        nrTxt.setAttribute("fill", nrTextColor);
        nrTxt.textContent = "NR";
        svg.appendChild(nrTxt);
    });

    // Line connecting ranked weeks
    const ranked = dataPoints.filter(d => d.rank !== null);
    if (ranked.length >= 2) {
        const poly = document.createElementNS(svgNS, "polyline");
        poly.setAttribute("points", ranked.map(d => `${xPos(d.weekNum)},${yPos(d.rank)}`).join(" "));
        poly.setAttribute("fill", "none"); poly.setAttribute("stroke", "#2277cc");
        poly.setAttribute("stroke-width", "2.5"); poly.setAttribute("stroke-linejoin", "round");
        poly.setAttribute("stroke-linecap", "round");
        svg.appendChild(poly);
    }

    // Data point circles + rank labels
    ranked.forEach(d => {
        const x = xPos(d.weekNum), y = yPos(d.rank);
        const circle = document.createElementNS(svgNS, "circle");
        circle.setAttribute("cx", x); circle.setAttribute("cy", y);
        circle.setAttribute("r", "5"); circle.setAttribute("fill", "#2277cc");
        circle.setAttribute("stroke", circleStroke); circle.setAttribute("stroke-width", "2");
        svg.appendChild(circle);
        const lbl = document.createElementNS(svgNS, "text");
        lbl.setAttribute("x", x); lbl.setAttribute("y", y - 9);
        lbl.setAttribute("text-anchor", "middle"); lbl.setAttribute("font-size", "11");
        lbl.setAttribute("fill", "#2277cc"); lbl.setAttribute("font-weight", "bold");
        lbl.textContent = d.rank;
        svg.appendChild(lbl);
    });

    // Message if never ranked
    if (ranked.length === 0) {
        const msg = document.createElementNS(svgNS, "text");
        msg.setAttribute("x", mL + cW / 2); msg.setAttribute("y", mT + cH / 2);
        msg.setAttribute("text-anchor", "middle"); msg.setAttribute("font-size", "14");
        msg.setAttribute("fill", "#999");
        msg.textContent = `${formatTeamName(team)} not ranked by ${username || "this voter"} this season`;
        svg.appendChild(msg);
    }

    table.appendChild(svg);
    modal.dataset.chartType = "teamrank";
    modal.classList.add("open");
}


function showTeamSeasonDotPlot(team, mode = "dots") {
    const isAp = _apCurrentYear !== null;
    const allTabsSorted = isAp ? getSortedApTabs() : getSortedTabs();
    const activeTab = document.querySelector(".week-tab.active");
    const currentYear = isAp ? _apCurrentYear : (activeTab?.dataset.year || allTabsSorted[0]?.dataset.year);
    if (!currentYear) return;

    // Chronological order (ascending weeknum)
    const yearTabs = allTabsSorted.filter(t => t.dataset.year === currentYear).reverse();
    if (yearTabs.length === 0) return;

    // For each week, collect per-rank voter lists for this team
    const weekData = yearTabs.map(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        const rankVoters = {};
        let totalBallots = 0;
        if (block) {
            const officialSection = block.querySelectorAll(".ballot-section")[0];
            if (officialSection) {
                const voterRows = Array.from(officialSection.querySelectorAll(".voter-row"))
                    .filter(r => getVoterName(r) !== "Official Overall");
                totalBallots = voterRows.length;
                voterRows.forEach(row => {
                    const voterName = getVoterName(row);
                    const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
                    const idx = teams.indexOf(team);
                    if (idx !== -1) {
                        const rank = idx + 1;
                        if (!rankVoters[rank]) rankVoters[rank] = [];
                        rankVoters[rank].push(voterName);
                    }
                });
            }
        }
        return {
            weekNum: parseInt(tab.dataset.weeknum),
            weekLabel: weekTextLabel(tab),
            displayNum: displayWeekNum(tab),
            rankVoters,
            totalBallots,
        };
    }).filter(w => w.totalBallots > 0);

    if (weekData.length === 0) return;

    const modal = document.getElementById("voter-history-modal");
    const title = document.getElementById("voter-history-title");
    const table = document.getElementById("voter-history-table");
    table.classList.remove("week-stats-table");

    title.innerHTML = `<img class="logo" src="${logoSrc(team)}" style="height:22px;vertical-align:middle;margin-right:6px;">${formatTeamName(team)} \u2013 ${currentYear} Season`;
    table.innerHTML = "";
    table.style.cssText = "display:block; white-space:normal; width:100%;";

    // Toggle buttons
    const escapedTeam = team.replace(/'/g, "\\'");
    const toggleDiv = document.createElement("div");
    toggleDiv.style.cssText = "text-align:center;margin-bottom:10px;";
    toggleDiv.innerHTML = `
        <button class="spread-toggle${mode === 'dots' ? ' active' : ''}"
                onclick="showTeamSeasonDotPlot('${escapedTeam}', 'dots')">Dot Plot</button>
        <button class="spread-toggle${mode === 'count' ? ' active' : ''}"
                onclick="showTeamSeasonDotPlot('${escapedTeam}', 'count')">Vote Count</button>`;
    table.appendChild(toggleDiv);

    const svgNS = SVG_NS;
    const W = 900, H = 460;
    const mL = 44, mR = 16, mT = 28, mB = 52;
    const cW = W - mL - mR, cH = H - mT - mB;

    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.style.cssText = "width:min(860px,90vw);display:block;margin:0 auto;";

    const n = weekData.length;
    const slotW = cW / n;
    const xPos = i => mL + (i + 0.5) * slotW;
    const yPos = r => mT + ((r - 1) / 24) * cH;
    const maxR = Math.min(slotW * 0.46, 13);

    const { axisColor, gridColor, borderColor } = svgColors();
    const dotFill = "#4488cc";

    // Y gridlines + labels
    [1, 5, 10, 15, 20, 25].forEach(r => {
        const y = yPos(r);
        const line = document.createElementNS(svgNS, "line");
        line.setAttribute("x1", mL); line.setAttribute("x2", mL + cW);
        line.setAttribute("y1", y); line.setAttribute("y2", y);
        line.setAttribute("stroke", gridColor);
        line.setAttribute("stroke-width", "1");
        svg.appendChild(line);
        const txt = document.createElementNS(svgNS, "text");
        txt.setAttribute("x", mL - 6); txt.setAttribute("y", y + 4);
        txt.setAttribute("text-anchor", "end"); txt.setAttribute("font-size", "11");
        txt.setAttribute("fill", axisColor);
        txt.textContent = r;
        svg.appendChild(txt);
    });

    // Chart border
    const border = document.createElementNS(svgNS, "rect");
    border.setAttribute("x", mL); border.setAttribute("y", mT);
    border.setAttribute("width", cW); border.setAttribute("height", cH);
    border.setAttribute("fill", "none"); border.setAttribute("stroke", borderColor);
    border.setAttribute("stroke-width", "1");
    svg.appendChild(border);

    // Y-axis label
    const yLbl = document.createElementNS(svgNS, "text");
    yLbl.setAttribute("x", 10); yLbl.setAttribute("y", mT + cH / 2);
    yLbl.setAttribute("text-anchor", "middle"); yLbl.setAttribute("font-size", "11");
    yLbl.setAttribute("fill", axisColor);
    yLbl.setAttribute("transform", `rotate(-90,10,${mT + cH / 2})`);
    yLbl.textContent = "Rank";
    svg.appendChild(yLbl);

    // Tooltip group
    const tipG = document.createElementNS(svgNS, "g");
    tipG.setAttribute("pointer-events", "none");
    tipG.style.display = "none";
    const tipRect = document.createElementNS(svgNS, "rect");
    tipRect.setAttribute("rx", "4"); tipRect.setAttribute("ry", "4");
    tipRect.setAttribute("fill", "#1a1a2e"); tipRect.setAttribute("fill-opacity", "0.92");
    tipRect.setAttribute("stroke", "#4488cc"); tipRect.setAttribute("stroke-width", "1");
    tipG.appendChild(tipRect);
    svg.appendChild(tipG);

    // Dots or count labels + X-axis week labels
    weekData.forEach((w, i) => {
        const x = xPos(i);

        Object.entries(w.rankVoters).forEach(([r, voters]) => {
            const cnt = voters.length;
            const cy = yPos(Number(r));

            if (mode === "count") {
                const txt = document.createElementNS(svgNS, "text");
                txt.setAttribute("x", x);
                txt.setAttribute("y", cy);
                txt.setAttribute("text-anchor", "middle");
                txt.setAttribute("dominant-baseline", "middle");
                txt.setAttribute("font-size", Math.min(Math.min(20, slotW * 0.45), 7 + Math.sqrt(cnt) * 1.7));
                txt.setAttribute("fill", dotFill);
                txt.setAttribute("font-weight", cnt >= 10 ? "700" : "400");
                txt.textContent = cnt;
                svg.insertBefore(txt, tipG);
            } else {
                const radius = Math.min(maxR, 2 + Math.sqrt(cnt) * 1.5);
                const circle = document.createElementNS(svgNS, "circle");
                circle.setAttribute("cx", x);
                circle.setAttribute("cy", cy);
                circle.setAttribute("r", radius);
                circle.setAttribute("fill", dotFill);
                circle.setAttribute("fill-opacity", "0.7");
                circle.style.cursor = "default";

                circle.addEventListener("mouseenter", () => {
                    const lines = voters.length <= 3 ? voters : [`${voters.length} voters`];
                    const pad = 8, lineH = 14, fontSize = 11;
                    const maxW = Math.max(...lines.map(l => l.length)) * fontSize * 0.6 + pad * 2;
                    const boxH = lines.length * lineH + pad * 1.5;
                    const cx = Number(circle.getAttribute("cx"));
                    const cr = Number(circle.getAttribute("r"));
                    let tx = cx - maxW / 2;
                    let ty = cy - cr - boxH - 4;
                    if (ty < mT) ty = cy + cr + 4;
                    tx = Math.max(2, Math.min(tx, W - maxW - 2));
                    tipRect.setAttribute("x", tx); tipRect.setAttribute("y", ty);
                    tipRect.setAttribute("width", maxW); tipRect.setAttribute("height", boxH);
                    while (tipG.childNodes.length > 1) tipG.removeChild(tipG.lastChild);
                    lines.forEach((line, li) => {
                        const t = document.createElementNS(svgNS, "text");
                        t.setAttribute("x", tx + maxW / 2);
                        t.setAttribute("y", ty + pad + li * lineH + lineH * 0.4);
                        t.setAttribute("text-anchor", "middle");
                        t.setAttribute("dominant-baseline", "middle");
                        t.setAttribute("font-size", fontSize);
                        t.setAttribute("fill", "#e0e8ff");
                        t.textContent = line;
                        tipG.appendChild(t);
                    });
                    tipG.style.display = "";
                });
                circle.addEventListener("mouseleave", () => { tipG.style.display = "none"; });
                svg.insertBefore(circle, tipG);

                if (radius >= 8) {
                    const lbl = document.createElementNS(svgNS, "text");
                    lbl.setAttribute("x", x);
                    lbl.setAttribute("y", cy);
                    lbl.setAttribute("text-anchor", "middle");
                    lbl.setAttribute("dominant-baseline", "middle");
                    lbl.setAttribute("font-size", Math.min(radius * 1.1, 11));
                    lbl.setAttribute("fill", "white");
                    lbl.setAttribute("font-weight", "600");
                    lbl.setAttribute("pointer-events", "none");
                    lbl.textContent = cnt;
                    svg.insertBefore(lbl, tipG);
                }
            }
        });

        // X-axis week label
        const wl = w.weekLabel || "";
        const lbl = document.createElementNS(svgNS, "text");
        lbl.setAttribute("x", x);
        lbl.setAttribute("y", mT + cH + 16);
        lbl.setAttribute("text-anchor", "middle");
        lbl.setAttribute("font-size", "9");
        lbl.setAttribute("fill", axisColor);
        lbl.textContent = wl.toLowerCase().includes("final") ? "Fin"
            : String(w.displayNum);
        svg.appendChild(lbl);
    });

    table.appendChild(svg);
    modal.dataset.chartType = "teamseason";
    modal.classList.add("open");
}


// Outlook bands for `teams` in week `weekId` (official ballots only). Returns an array
// sorted by this week's mean voter rank: { team, avg, hi, lo, innerHi, innerLo } where
// hi/lo = outer (~75%) band and innerHi/innerLo = inner (~50%) band, or null if no history.
// Used by the Outlook graph and the Week Stats tab. See notes in showWeekHighLowChart.
function computeOutlookBands(weekId, teams) {
    const percentileRank = (sortedArr, p) => {
        if (sortedArr.length === 1) return sortedArr[0];
        const idx = p * (sortedArr.length - 1);
        const lo = Math.floor(idx);
        const hi = Math.ceil(idx);
        return sortedArr[lo] + (idx - lo) * (sortedArr[hi] - sortedArr[lo]);
    };
    const wDelta = buildDeltaData(true);
    const wTab = document.querySelector(`.week-tab[data-week="${weekId}"]`);
    const wYear = wTab?.dataset.year || "";
    const isApWeek = weekId.startsWith("week-ap-");
    const wAllTabs = isApWeek ? getSortedApTabs() : getSortedTabs();
    const wYearTabs = wAllTabs.filter(t => t.dataset.year === wYear);
    const wCurrIdx = wYearTabs.findIndex(t => t.dataset.week === weekId);
    const wLast5 = [];
    for (let i = wCurrIdx; i < wYearTabs.length && wLast5.length < 5; i++) {
        wLast5.push(wYearTabs[i].dataset.week);
    }
    if (wLast5.length === 0) return null;
    const wVoters = Object.keys(wDelta[weekId] || {}).filter(u => u !== "Official Overall");
    const thisWeekRanks = team => wVoters.map(u => wDelta[weekId]?.[u]).filter(b => b?.length)
        .map(b => { const p = b.indexOf(team); return p === -1 ? 26 : p + 1; })
        .sort((a, b) => a - b);
    const twAvg = {};
    teams.forEach(t => {
        const r = thisWeekRanks(t);
        twAvg[t] = r.length ? r.reduce((a, b) => a + b, 0) / r.length : 26;
    });
    // Sorted by this week's avg so the graph's tier colors follow it.
    const wTeams = [...teams].sort((a, b) => twAvg[a] - twAvg[b]);
    // Each current voter's best and worst rank for a team across the last 5 weeks
    // (unranked = 26; weeks the voter skipped are left out). Unweighted on purpose:
    // the band is a ceiling/floor, so one big week counts in full.
    const voterBestWorst = (u, team) => {
        let best = null, worst = null;
        wLast5.forEach(wid => {
            const ballot = wDelta[wid]?.[u];
            if (!ballot?.length) return;
            const pos = ballot.indexOf(team);
            const r = pos === -1 ? 26 : pos + 1;
            if (best === null || r < best) best = r;
            if (worst === null || r > worst) worst = r;
        });
        return best === null ? null : { best, worst };
    };
    // Floor cap: the outer floor may sit at most FLOOR_CAP spots below this week's 90th
    // percentile ballot rank. Stops a rising team's old unranked weeks from forcing
    // an NR floor once this week's voters clearly rank it.
    const FLOOR_CAP = 5;
    const OUTER_MARGIN = [3.5, 3.0, 2.0, 1.5, 0][wLast5.length - 1];
    // Band-edge percentiles per rank tier (#1-5, 6-10, 11-15, 16-20, 21-25 by this week's avg):
    //   oh/ol = Outlook ceiling/floor, ih/il = Likely ceiling/floor (floor uses 1 - pct).
    // Each edge was fit so that ~11.25% (Outlook) or ~25% (Likely) of outcomes miss on its
    // side, so Likely holds ~50% and Outlook ~77.5% in every tier with misses split evenly.
    // Top teams get low floor percentiles because they fall further than they rise; bubble
    // teams get high ones because their old 26s otherwise pin every floor to NR.
    // AP has its own table: AP ballots are ~20-25% more tightly grouped than userpoll ballots
    // while AP consensus moves as much week to week, so userpoll-sized bands run narrow on AP.
    const BAND_PCT = (isApWeek || ON_AP_PAGE) ? [
        { oh: 0.28, ol: 0.02, ih: 0.25, il: 0.00 },
        { oh: 0.25, ol: 0.00, ih: 0.17, il: 0.03 },
        { oh: 0.11, ol: 0.01, ih: 0.17, il: 0.05 },
        { oh: 0.08, ol: 0.20, ih: 0.13, il: 0.11 },
        { oh: 0.08, ol: 0.53, ih: 0.12, il: 0.34 },
    ] : [
        { oh: 0.26, ol: 0.01, ih: 0.34, il: 0.02 },
        { oh: 0.22, ol: 0.03, ih: 0.19, il: 0.05 },
        { oh: 0.18, ol: 0.09, ih: 0.19, il: 0.09 },
        { oh: 0.13, ol: 0.27, ih: 0.18, il: 0.15 },
        { oh: 0.14, ol: 0.57, ih: 0.16, il: 0.36 },
    ];
    return wTeams.map((team, idx) => {
        const pc = BAND_PCT[Math.min(4, Math.floor(idx / 5))];
        const perVoter = wVoters.map(u => voterBestWorst(u, team)).filter(v => v !== null);
        const bests = perVoter.map(v => v.best).sort((a, b) => a - b);
        const worsts = perVoter.map(v => v.worst).sort((a, b) => a - b);
        const thisWeek = thisWeekRanks(team);
        const hi = Math.max(1, (bests.length > 0 ? percentileRank(bests, pc.oh) : 26) - OUTER_MARGIN);
        let lo = worsts.length > 0 ? percentileRank(worsts, 1 - pc.ol) : 26;
        if (thisWeek.length > 0) lo = Math.min(lo, percentileRank(thisWeek, 0.90) + FLOOR_CAP);
        lo = Math.min(26, Math.max(lo + OUTER_MARGIN, hi));
        let innerHi = hi, innerLo = lo;
        if (thisWeek.length > 0) {
            innerHi = Math.max(percentileRank(thisWeek, pc.ih), hi);
            innerLo = Math.max(Math.min(percentileRank(thisWeek, 1 - pc.il), lo), innerHi);
        }
        return { team, avg: twAvg[team], hi, lo, innerHi, innerLo };
    });
}

// Title (week label + Stats / Range / Spread / Outlook / Conference tabs) of the Stats > Week window.
function renderWeekChartTitle(weekId, mode) {
    const modal = document.getElementById("voter-history-modal");
    const title = document.getElementById("voter-history-title");
    const table = document.getElementById("voter-history-table");

    const titleTab = (_apCurrentYear !== null
        ? document.querySelector(`.week-tab[data-poll="ap"][data-year="${_apCurrentYear}"][data-weeknum="${_apCurrentWeekNum}"]`)
        : null) || document.querySelector(".week-tab.active");
    const weekNum = titleTab ? displayWeekNum(titleTab) : "";
    const year = titleTab?.dataset.year || "";
    const weekLabel = weekTextLabel(titleTab);
    const weekLabelText = weekLabel
        ? `${year} ${weekLabel}`
        : `${year} ${String(weekNum).padStart(2, "0")}`;
    const escapedId = weekId.replace(/'/g, "\\'");
    const modeTabs = [
        { key: 'stats', label: 'Stats' },
        { key: 'conf', label: 'Conferences' },
    ].map(m =>
        `<span class="modal-mode-tab${mode === m.key ? ' active' : ''}"
               onclick="showWeekHighLowChart('${escapedId}', '${m.key}')">${m.label}</span>`
    ).join('');
    title.innerHTML = `${modalWeekArrowsHtml()}${weekLabelText} — ${modeTabs}`;
    return { modal, table };
}

// Stats tab chart above the table: which one (Range / Spread / Outlook), remembered per
// viewer in localStorage.
const WEEK_CHART_KINDS = [
    { key: "highlow", label: "Range" },
    { key: "dots", label: "Spread" },
    { key: "outlook", label: "Outlook" },
];
let _weekChartKind = "highlow";
try {
    const k = localStorage.getItem("weekStatsChart");
    if (WEEK_CHART_KINDS.some(c => c.key === k)) _weekChartKind = k;
    localStorage.removeItem("weekStatsChartOpen");  // from the removed collapse control
} catch (e) {}
function setWeekChartKind(kind) {
    _weekChartKind = kind;
    try { localStorage.setItem("weekStatsChart", kind); } catch (e) {}
}

// Chart for the top of the Stats tab, with its switcher (Range Spread Outlook, styled like
// the window title's Stats / Conference tabs) inside the plot's top-right corner.
// Re-renders in place, so the table keeps its scroll.
function buildWeekChartPanel(weekId) {
    const panel = document.createElement("div");
    panel.className = "week-chart-panel";
    const switcher = document.createElement("div");
    switcher.className = "week-chart-switch";
    const body = document.createElement("div");
    body.className = "week-chart-body";

    const labels = WEEK_CHART_KINDS.map(({ key, label }) => {
        const s = document.createElement("span");
        s.className = "week-chart-kind";
        s.textContent = label;
        s.addEventListener("click", () => { setWeekChartKind(key); render(); });
        switcher.appendChild(s);
        return { key, s };
    });

    const render = () => {
        labels.forEach(({ key, s }) => s.classList.toggle("active", key === _weekChartKind));
        body.innerHTML = "";
        const svg = buildWeekChartSvg(weekId, _weekChartKind);
        if (svg) body.appendChild(svg);
    };
    render();
    panel.append(switcher, body);
    return panel;
}

// Opens the Stats › Week window. mode: "stats" (chart + table) or "conf". The old chart
// tab keys ("highlow" / "dots" / "outlook") still work: they open Stats with that chart shown.
function showWeekHighLowChart(weekId, mode = "stats") {
    if (WEEK_CHART_KINDS.some(c => c.key === mode)) {
        setWeekChartKind(mode);
        mode = "stats";
    }
    // Conference tab: charts + per-conference stats table (2025+)
    if (mode === "conf") {
        const view = buildConferenceView(weekId);
        if (view === null) return;
        const { modal, table } = renderWeekChartTitle(weekId, mode);
        table.classList.remove("week-stats-table");
        table.style.cssText = "display:block; white-space:normal; width:100%;";
        table.innerHTML = "";
        table.appendChild(view);
        initRecordsLogos(view);
        modal.dataset.chartType = "highlow";
        modal.dataset.chartMode = mode;
        modal.classList.add("open");
        return;
    }
    // Stats tab: chart panel on top, per-team week statistics table below. Clicking a
    // table row toggles that team's highlight, which also lights it up in the chart.
    const html = buildWeekStatsTableHtml(weekId);
    if (html === null) return;
    const { modal, table } = renderWeekChartTitle(weekId, "stats");
    table.classList.remove("week-stats-table");
    table.style.cssText = "display:block; white-space:normal; width:100%;";
    table.innerHTML = "";
    table.appendChild(buildWeekChartPanel(weekId));
    const statsTable = document.createElement("table");
    statsTable.className = "week-stats-table";
    statsTable.innerHTML = html;
    initRecordsLogos(statsTable);
    fillWeekResults(statsTable, weekId);
    fillWeekRecords(statsTable, weekId);
    statsTable.addEventListener("click", e => {
        // W / L opponent names highlight the opponent, not the row's team.
        const opp = e.target.closest(".ws-opp[data-team]");
        if (opp) { toggleTeamHighlight(opp.dataset.team); return; }
        const row = e.target.closest("tr[data-team]");
        if (row) toggleTeamHighlight(row.dataset.team);
    });
    table.appendChild(statsTable);
    modal.dataset.chartType = "highlow";
    modal.dataset.chartMode = "stats";
    modal.classList.add("open");
}

// Range ("highlow") / Spread ("dots") / Outlook chart SVG for a week, or null without
// official ballots. Logos and data marks click to toggle the team highlight.
function buildWeekChartSvg(weekId, mode) {
    const block = document.getElementById(weekId);
    if (!block) return null;
    const sections = block.querySelectorAll(".ballot-section");
    const officialSection = sections[0];
    if (!officialSection) return null;

    const voterRows = Array.from(officialSection.querySelectorAll(".voter-row"))
        .filter(r => getVoterName(r) !== "Official Overall");
    const totalVoters = voterRows.length;
    if (totalVoters === 0) return null;

    const teamRankSum = {};
    const teamVoterCount = {};
    const teamPoints = {};
    const teamRanks = {};
    const teamRankVoters = {};
    const allVoterNames = [];
    voterRows.forEach(row => {
        const voterName = getVoterName(row);
        allVoterNames.push(voterName);
        const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
        teams.slice(0, 25).forEach((team, i) => {
            const rank = i + 1;
            teamRankSum[team] = (teamRankSum[team] || 0) + rank;
            teamVoterCount[team] = (teamVoterCount[team] || 0) + 1;
            teamPoints[team] = (teamPoints[team] || 0) + (26 - rank);
            if (!teamRanks[team]) teamRanks[team] = [];
            teamRanks[team].push(rank);
            if (!teamRankVoters[team]) teamRankVoters[team] = {};
            if (!teamRankVoters[team][rank]) teamRankVoters[team][rank] = [];
            teamRankVoters[team][rank].push(voterName);
        });
    });
    // Populate NR voters (rank 26) for each team
    Object.keys(teamRankVoters).forEach(team => {
        const rankedSet = new Set(Object.values(teamRankVoters[team]).flat());
        const nrVoters = allVoterNames.filter(v => !rankedSet.has(v));
        if (nrVoters.length > 0) teamRankVoters[team][26] = nrVoters;
    });

    const percentileRank = (sortedArr, p) => {
        if (sortedArr.length === 1) return sortedArr[0];
        const idx = p * (sortedArr.length - 1);
        const lo = Math.floor(idx);
        const hi = Math.ceil(idx);
        return sortedArr[lo] + (idx - lo) * (sortedArr[hi] - sortedArr[lo]);
    };

    const top25 = Object.entries(teamPoints).sort((a, b) => b[1] - a[1]).map(([t]) => t).slice(0, 25);
    let chartData = top25.map(team => {
        const avg = teamRankSum[team] / teamVoterCount[team];
        const count = teamVoterCount[team];
        const allRanks = [...teamRanks[team], ...Array(totalVoters - count).fill(26)].sort((a, b) => a - b);
        const hi = percentileRank(allRanks, 0.10);
        const lo = percentileRank(allRanks, 0.90);
        const rankVoters = teamRankVoters[team] || {};
        return { team, avg, hi, lo, allRanks, rankVoters };
    });

    // Outlook mode (official ballots only, never provisional):
    //   circle = this week's mean voter rank (unranked = 26). A 5-week weighted mean was
    //            tried here and predicted the next 1-4 weeks worse (MAE 3.3/3.8 vs 2.5/3.3).
    //   inner band (Likely, ~50%): percentiles of this week's ballot ranks.
    //   outer band (Outlook, ~77.5%): ceiling = a low percentile of each current voter's best
    //            rank over the last 5 polls, floor = a high percentile of their worst rank,
    //            capped at this week's 90th percentile + 5; then widened by OUTER_MARGIN ranks
    //            on each side, which shrinks as history builds (1 poll of history: 3.5 ... 5: 0).
    //            Inner is clamped inside outer.
    //   Percentiles come from BAND_PCT in computeOutlookBands (per rank tier, separate tables
    //   for Userpoll and AP). Backtested leave-one-season-out on Userpoll 2016-2022 + 2025-2026
    //   and AP 2022-2026 (#1-25 teams, consensus rank in each of the next 4 polls): Likely
    //   ~50% and Outlook ~77-78% in every tier, misses split about evenly above and below.
    if (mode === "outlook") {
        const bands = computeOutlookBands(weekId, top25);
        if (!bands) return null;
        chartData = bands.map(b => ({ ...b, allRanks: [], rankVoters: {} }));
    }

    // Tier coloring: fixed rank zones so a color means roughly the same area week to week.
    // Nominal zones: 1-4, 5-8, 9-14, 15-20, 21-25. Only the edge teams of each boundary can
    // change color, by one position, when separated by a large jump (>= TIER_JUMP) in avg rank.
    const tierColors = [
        { fill: "#cc3333", stroke: "#aa1111" },  // red    (1-4)
        { fill: "#e88c1a", stroke: "#c06a00" },  // orange (5-8)
        { fill: "#2ea043", stroke: "#1a7f37" },  // green  (9-14)
        { fill: "#4488cc", stroke: "#2266aa" },  // blue   (15-20)
        { fill: "#999",    stroke: "#777"    },  // gray   (21-25)
    ];
    const TIER_JUMP = 1.5;
    const nominalBreaks = [4, 8, 14, 20];  // 0-based index of first team in the next zone
    const avgs = chartData.map(d => d.avg);
    // True if there's a large jump between team idx-1 and team idx (epsilon absorbs float error)
    const isJump = idx => idx >= 1 && idx < avgs.length && avgs[idx] - avgs[idx - 1] >= TIER_JUMP - 1e-9;
    const breakIdxs = nominalBreaks.map(b => {
        if (isJump(b)) return b;          // boundary already sits on a large jump: no change
        if (isJump(b - 1)) return b - 1;  // upper edge team drops to the lower color
        if (isJump(b + 1)) return b + 1;  // lower edge team moves up to the higher color
        return b;
    });
    // Assign tier index to each team
    chartData.forEach((d, i) => {
        let tier = 0;
        for (const bi of breakIdxs) { if (i >= bi) tier++; }
        d.tier = tier;
        d.color = tierColors[d.tier];
    });

    // Outlook graph: order by this week's overall rank (colors follow each team's
    // tier by this week's avg voter rank).
    if (mode === "outlook") {
        const overallPos = t => { const p = top25.indexOf(t); return p === -1 ? Infinity : p; };
        chartData = chartData
            .map((d, i) => ({ d, i }))
            .sort((a, b) => (overallPos(a.d.team) - overallPos(b.d.team)) || (a.i - b.i))
            .map(x => x.d);
    }

    const svgNS = SVG_NS;
    // Shorter than the old standalone chart (460) so the table below stays in view.
    // No "Rank" axis title (the 1…25 ticks speak for themselves), so mL only fits the ticks.
    const W = 900, H = 380;
    const mL = 28, mR = 16, mT = 28, mB = 52;
    const cW = W - mL - mR, cH = H - mT - mB;

    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.style.cssText = "width:min(860px,90vw);display:block;margin:0 auto;";

    const n = chartData.length;
    const slotW = cW / n;
    const xPos = i => mL + (i + 0.5) * slotW;
    const yPos = r => mT + ((r - 1) / 25) * cH;  // rank 1 at top, 26 (NR) at bottom

    const { axisColor, gridColor, borderColor, nrGridColor, circleStroke } = svgColors();

    // Rank gridlines + y-axis labels
    [1, 5, 10, 15, 20, 25, 26].forEach(r => {
        const y = yPos(r);
        const line = document.createElementNS(svgNS, "line");
        line.setAttribute("x1", mL); line.setAttribute("x2", mL + cW);
        line.setAttribute("y1", y); line.setAttribute("y2", y);
        line.setAttribute("stroke", r === 26 ? nrGridColor : gridColor);
        line.setAttribute("stroke-width", "1");
        if (r === 26) line.setAttribute("stroke-dasharray", "3,3");
        svg.appendChild(line);
        if (r === 26) return;  // unranked line has no label
        const txt = document.createElementNS(svgNS, "text");
        txt.setAttribute("x", mL - 6); txt.setAttribute("y", y + 4);
        txt.setAttribute("text-anchor", "end"); txt.setAttribute("font-size", "11");
        txt.setAttribute("fill", axisColor);
        txt.textContent = r;
        svg.appendChild(txt);
    });

    // Chart border
    const border = document.createElementNS(svgNS, "rect");
    border.setAttribute("x", mL); border.setAttribute("y", mT);
    border.setAttribute("width", cW); border.setAttribute("height", cH);
    border.setAttribute("fill", "none"); border.setAttribute("stroke", borderColor);
    border.setAttribute("stroke-width", "1");
    svg.appendChild(border);

    const logoSize = Math.min(20, slotW - 4);
    const clickToHighlight = (el, team) => {
        el.style.cursor = "pointer";
        el.addEventListener("click", () => toggleTeamHighlight(team));
    };

    // Clickable team logo below the x-axis; the ring behind it lights up via the
    // same highlight rules as ballot logos, so state stays in sync both ways.
    // Consensus rank (when given) is printed below the logo in the Conference tab's rank
    // badge style (.chart-logo-rank mirrors .conf-team-rank's font/color/weight).
    const appendChartLogo = (team, x, rank = null) => {
        const lx = x - logoSize / 2, ly = mT + cH + 6;
        const ring = document.createElementNS(svgNS, "rect");
        ring.setAttribute("class", "chart-logo-ring");
        ring.dataset.team = team;
        ring.setAttribute("x", lx - 2); ring.setAttribute("y", ly - 2);
        ring.setAttribute("width", logoSize + 4); ring.setAttribute("height", logoSize + 4);
        ring.setAttribute("rx", "4"); ring.setAttribute("ry", "4");
        svg.appendChild(ring);

        const img = document.createElementNS(svgNS, "image");
        img.setAttribute("class", "chart-logo");
        img.dataset.team = team;
        img.setAttribute("href", logoSrc(team));
        img.setAttribute("x", lx);
        img.setAttribute("y", ly);
        img.setAttribute("width", logoSize); img.setAttribute("height", logoSize);
        img.style.cursor = "pointer";
        img.addEventListener("click", () => toggleTeamHighlight(team));
        svg.appendChild(img);

        if (rank !== null) {
            const rankTxt = document.createElementNS(svgNS, "text");
            rankTxt.setAttribute("class", "chart-logo-rank");
            rankTxt.setAttribute("x", x); rankTxt.setAttribute("y", mT + cH + logoSize + 18);
            rankTxt.setAttribute("text-anchor", "middle");
            rankTxt.textContent = rank;
            svg.appendChild(rankTxt);
        }
    };

    if (mode === "highlow" || mode === "outlook") {
        const capW = Math.min(7, slotW * 0.28);

        // Shared tooltip group
        const tipG = document.createElementNS(svgNS, "g");
        tipG.setAttribute("pointer-events", "none");
        tipG.style.display = "none";
        const tipRect = document.createElementNS(svgNS, "rect");
        tipRect.setAttribute("rx", "4"); tipRect.setAttribute("ry", "4");
        tipRect.setAttribute("fill", "#1a1a2e"); tipRect.setAttribute("fill-opacity", "0.92");
        tipRect.setAttribute("stroke", "#4488cc"); tipRect.setAttribute("stroke-width", "1");
        tipG.appendChild(tipRect);
        svg.appendChild(tipG);

        chartData.forEach(({ team, avg, hi, lo, innerHi, innerLo, color }, i) => {
            const x = xPos(i);
            const yHi = yPos(hi);
            const yLo = yPos(lo);
            const yAvg = yPos(avg);

            if (mode === "outlook") {
                // Two nested bands: pale outer (~75%), solid inner (~50%)
                const bandW = Math.max(4, Math.min(10, slotW * 0.42));
                const band = (y1, y2, opacity) => {
                    const b = document.createElementNS(svgNS, "line");
                    b.setAttribute("x1", x); b.setAttribute("x2", x);
                    b.setAttribute("y1", y1); b.setAttribute("y2", Math.max(y2, y1 + 1.5));
                    b.setAttribute("stroke", color.fill);
                    b.setAttribute("stroke-width", bandW);
                    b.setAttribute("stroke-linecap", "butt");
                    b.setAttribute("stroke-opacity", opacity);
                    b.setAttribute("class", "chart-stroke"); b.dataset.team = team;
                    clickToHighlight(b, team);
                    svg.insertBefore(b, tipG);
                };
                band(yHi, yLo, 0.3);
                band(yPos(innerHi), yPos(innerLo), 0.9);
            } else {

                // Vertical high-low line
                const vLine = document.createElementNS(svgNS, "line");
                vLine.setAttribute("x1", x); vLine.setAttribute("x2", x);
                vLine.setAttribute("y1", yHi); vLine.setAttribute("y2", yLo);
                vLine.setAttribute("stroke", color.fill);
                vLine.setAttribute("stroke-width", "2.5");
                vLine.setAttribute("stroke-linecap", "round");
                vLine.setAttribute("class", "chart-stroke"); vLine.dataset.team = team;
                clickToHighlight(vLine, team);
                svg.insertBefore(vLine, tipG);

                // Top cap (P90+)
                const topCap = document.createElementNS(svgNS, "line");
                topCap.setAttribute("x1", x - capW); topCap.setAttribute("x2", x + capW);
                topCap.setAttribute("y1", yHi); topCap.setAttribute("y2", yHi);
                topCap.setAttribute("stroke", color.fill); topCap.setAttribute("stroke-width", "2");
                topCap.setAttribute("class", "chart-stroke"); topCap.dataset.team = team;
                clickToHighlight(topCap, team);
                svg.insertBefore(topCap, tipG);

                // Bottom cap (P10-)
                const botCap = document.createElementNS(svgNS, "line");
                botCap.setAttribute("x1", x - capW); botCap.setAttribute("x2", x + capW);
                botCap.setAttribute("y1", yLo); botCap.setAttribute("y2", yLo);
                botCap.setAttribute("stroke", color.fill); botCap.setAttribute("stroke-width", "2");
                botCap.setAttribute("class", "chart-stroke"); botCap.dataset.team = team;
                clickToHighlight(botCap, team);
                svg.insertBefore(botCap, tipG);
            }

            // Tooltip anchored above (or below, if near the top) a point; r = marker half-height
            const showTip = (label, ax, ay, r) => {
                const pad = 8, fontSize = 11;
                const boxW = label.length * fontSize * 0.6 + pad * 2;
                const boxH = fontSize + pad * 1.5;
                let tx = ax - boxW / 2;
                let ty = ay - r - boxH - 4;
                if (ty < mT) ty = ay + r + 4;
                tx = Math.max(2, Math.min(tx, W - boxW - 2));

                tipRect.setAttribute("x", tx); tipRect.setAttribute("y", ty);
                tipRect.setAttribute("width", boxW); tipRect.setAttribute("height", boxH);

                while (tipG.childNodes.length > 1) tipG.removeChild(tipG.lastChild);
                const t = document.createElementNS(svgNS, "text");
                t.setAttribute("x", tx + boxW / 2);
                t.setAttribute("y", ty + boxH / 2);
                t.setAttribute("text-anchor", "middle");
                t.setAttribute("dominant-baseline", "middle");
                t.setAttribute("font-size", fontSize);
                t.setAttribute("fill", "#e0e8ff");
                t.textContent = label;
                tipG.appendChild(t);
                tipG.style.display = "";
            };
            const hideTip = () => { tipG.style.display = "none"; };

            // Mean circle
            const circle = document.createElementNS(svgNS, "circle");
            circle.setAttribute("cx", x); circle.setAttribute("cy", yAvg);
            circle.setAttribute("r", "4");
            circle.setAttribute("fill", circleStroke);
            circle.setAttribute("stroke", color.stroke); circle.setAttribute("stroke-width", "2.5");
            circle.setAttribute("class", "chart-stroke"); circle.dataset.team = team;
            clickToHighlight(circle, team);

            circle.addEventListener("mouseenter", () => showTip(avg.toFixed(1), x, yAvg, 4));
            circle.addEventListener("mouseleave", hideTip);

            svg.insertBefore(circle, tipG);

            appendChartLogo(team, x, mode === "outlook" ? (top25.indexOf(team) + 1 || "NR") : i + 1);

        });
    } else {
        // Dot plot: one dot per (team, rank), sized by voter count at that rank
        // Dot radii scale with the plot height so overlap matches the original 460px chart.
        const rScale = cH / 380;
        const maxR = Math.min(slotW * 0.46, 13) * rScale;

        // Shared tooltip group
        const tipG = document.createElementNS(svgNS, "g");
        tipG.setAttribute("pointer-events", "none");
        tipG.style.display = "none";
        const tipRect = document.createElementNS(svgNS, "rect");
        tipRect.setAttribute("rx", "4"); tipRect.setAttribute("ry", "4");
        tipRect.setAttribute("fill", "#1a1a2e"); tipRect.setAttribute("fill-opacity", "0.92");
        tipRect.setAttribute("stroke", "#4488cc"); tipRect.setAttribute("stroke-width", "1");
        tipG.appendChild(tipRect);
        svg.appendChild(tipG);

        chartData.forEach(({ team, allRanks, rankVoters, color }, i) => {
            const x = xPos(i);

            // Count votes per integer rank
            const rankCounts = {};
            allRanks.forEach(r => { rankCounts[r] = (rankCounts[r] || 0) + 1; });

            Object.entries(rankCounts).forEach(([r, cnt]) => {
                const radius = Math.min(maxR, (2 + Math.sqrt(cnt) * 1.5) * rScale);
                const circle = document.createElementNS(svgNS, "circle");
                circle.setAttribute("cx", x);
                circle.setAttribute("cy", yPos(Number(r)));
                circle.setAttribute("r", radius);
                circle.setAttribute("fill", color.fill);
                circle.setAttribute("fill-opacity", "0.7");
                circle.setAttribute("class", "chart-fill"); circle.dataset.team = team;
                clickToHighlight(circle, team);

                circle.addEventListener("mouseenter", (e) => {
                    const voters = rankVoters[r] || [];
                    const lines = voters.length <= 3
                        ? voters
                        : [`${voters.length} voters`];
                    const pad = 8, lineH = 14, fontSize = 11;
                    const maxW = Math.max(...lines.map(l => l.length)) * fontSize * 0.6 + pad * 2;
                    const boxH = lines.length * lineH + pad * 1.5;

                    // Position: prefer above the circle, flip if too close to top
                    const cx = Number(circle.getAttribute("cx"));
                    const cy = Number(circle.getAttribute("cy"));
                    const cr = Number(circle.getAttribute("r"));
                    let tx = cx - maxW / 2;
                    let ty = cy - cr - boxH - 4;
                    if (ty < mT) ty = cy + cr + 4;
                    tx = Math.max(2, Math.min(tx, W - maxW - 2));

                    tipRect.setAttribute("x", tx); tipRect.setAttribute("y", ty);
                    tipRect.setAttribute("width", maxW); tipRect.setAttribute("height", boxH);

                    // Remove old text nodes
                    while (tipG.childNodes.length > 1) tipG.removeChild(tipG.lastChild);

                    lines.forEach((line, li) => {
                        const t = document.createElementNS(svgNS, "text");
                        t.setAttribute("x", tx + maxW / 2);
                        t.setAttribute("y", ty + pad + li * lineH + lineH * 0.4);
                        t.setAttribute("text-anchor", "middle");
                        t.setAttribute("dominant-baseline", "middle");
                        t.setAttribute("font-size", fontSize);
                        t.setAttribute("fill", "#e0e8ff");
                        t.textContent = line;
                        tipG.appendChild(t);
                    });

                    tipG.style.display = "";
                });

                circle.addEventListener("mouseleave", () => { tipG.style.display = "none"; });

                svg.insertBefore(circle, tipG);
            });

            appendChartLogo(team, x, i + 1);

        });
    }

    return svg;
}

let weekPickerPinned = false;
const isMobile = () => screen.width <= 768;

let _lastFaviconWeek = null;
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (_lastFaviconWeek !== null) updateFavicon(_lastFaviconWeek);
});

function updateFavicon(n) {
    _lastFaviconWeek = n;
    const size = 64;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');

    const dark = isDarkMode();

    const label = String(n);
    let fontSize = size;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    do {
        ctx.font = `bold ${fontSize}px sans-serif`;
        fontSize--;
    } while (ctx.measureText(label).width > size * 0.88 && fontSize > 4);

    ctx.fillStyle = dark ? '#ffffff' : '#222222';
    ctx.fillText(label, size / 2, size / 2);

    const url = canvas.toDataURL('image/png');
    const old = document.getElementById('favicon');
    if (old) old.parentNode.removeChild(old);
    const link = document.createElement('link');
    link.id = 'favicon';
    link.rel = 'icon';
    link.type = 'image/png';
    link.href = url;
    document.head.appendChild(link);
}

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
    const isAp = _apCurrentYear !== null;
    const allTabs = isAp ? getSortedApTabs() : Array.from(document.querySelectorAll(".week-tab")).filter(t => t.dataset.poll !== "ap");
    const byYear = {};
    allTabs.forEach(t => {
        const y = t.dataset.year;
        if (!byYear[y]) byYear[y] = [];
        byYear[y].push(t);
    });
    const years = Object.keys(byYear).filter(y => !isHiddenYear(y)).sort();

    const yearPicker = document.getElementById("year-picker");
    yearPicker.innerHTML = "";
    const activeYear = isAp ? _apCurrentYear : (document.querySelector(".week-tab.active")?.dataset.year ?? null);
    years.forEach(y => {
        const btn = document.createElement("button");
        btn.className = "picker-btn";
        btn.textContent = y;
        btn.dataset.year = y;
        if (y === activeYear) btn.style.textDecoration = "underline";
        btn.addEventListener("click", async e => {
            e.stopPropagation();
            const weekWasPinned = weekPickerPinned;
            const yearPicker = document.getElementById("year-picker");
            yearPicker.classList.remove("open");
            document.getElementById("year-text").style.display = "";

            if (isAp) {
                await loadApYear(y);
                const apTabsForYear = getSortedApTabs().filter(t => t.dataset.year === y);
                const sameWeek = apTabsForYear.find(t => t.dataset.weeknum === _apCurrentWeekNum);
                const target = sameWeek || apTabsForYear[0];
                if (target) await showApWeek(target.dataset.year, target.dataset.weeknum);
            } else {
                try { await loadYear(y); } catch { return; }
                const activeTab = document.querySelector(".week-tab.active");
                const currentWeekNum = activeTab ? parseInt(activeTab.dataset.weeknum) : null;
                const sameWeek = currentWeekNum !== null ? byYear[y].find(t => parseInt(t.dataset.weeknum) === currentWeekNum) : null;
                const target = sameWeek || byYear[y][byYear[y].length - 1];
                showWeek(target.dataset.week);
                backgroundLoad();
            }

            if (weekWasPinned) {
                weekPickerPinned = true;
                const weekPicker = document.getElementById("week-picker");
                rebuildWeekPicker();
                weekPicker.classList.add("open");
                document.getElementById("week-text").style.display = "none";
            } else {
                closeAllPickers();
            }
        });
        yearPicker.appendChild(btn);
    });
}

// Pre-Season ballots are stored as week 0 (older seasons have no label, newer ones
// are labelled "Pre-Season"); everywhere in the UI they are shown as Week 1.
function isPreseasonTab(tab) {
    return !!tab && (parseInt(tab.dataset.weeknum) === 0 || /pre/i.test(tab.dataset.weeklabel || ""));
}

// Text label for a week, or undefined when it should be shown by number. Pre-Season → undefined (shown as 1).
function weekTextLabel(tab) {
    return isPreseasonTab(tab) ? undefined : tab?.dataset.weeklabel;
}

// Number shown for a week in the picker/header. Pre-Season (stored as week 0) shows
// as 1; Final (stored as week 20) shows as one past the season's last regular week,
// so the numbers run in order (e.g. 02 … 18 19 for an 18-week season).
function displayWeekNum(tab) {
    const label = (tab.dataset.weeklabel || "").toLowerCase();
    const wn = parseInt(tab.dataset.weeknum);
    if (isPreseasonTab(tab)) return 1;
    if (label.includes("final")) {
        const pollSel = tab.dataset.poll === "ap" ? '[data-poll="ap"]' : ':not([data-poll="ap"])';
        const regular = Array.from(document.querySelectorAll(`.week-tab[data-year="${tab.dataset.year}"]${pollSel}`))
            .filter(t => !/final/i.test(t.dataset.weeklabel || ""))
            .map(t => parseInt(t.dataset.weeknum));
        return regular.length ? Math.max(...regular) + 1 : wn;
    }
    return wn;
}

const padWeekNum = n => (n < 10 ? "0" : "") + n;

function rebuildWeekPicker() {
    const isAp = _apCurrentYear !== null;
    const currentYear = isAp ? _apCurrentYear : document.getElementById("year-text").innerText;
    const weekPicker = document.getElementById("week-picker");
    weekPicker.innerHTML = "";

    if (isAp) {
        const tabs = getSortedApTabs()
            .filter(t => t.dataset.year === currentYear)
            .sort((a, b) => parseInt(a.dataset.weeknum) - parseInt(b.dataset.weeknum));
        tabs.forEach(t => {
            const btn = document.createElement("button");
            btn.className = "picker-btn";
            btn.textContent = padWeekNum(displayWeekNum(t));
            if (t.dataset.weeknum === _apCurrentWeekNum) btn.style.textDecoration = "underline";
            btn.addEventListener("click", async e => {
                e.stopPropagation();
                if (weekPickerPinned) {
                    if (t.dataset.weeknum === _apCurrentWeekNum) {
                        weekPickerPinned = false;
                        closeAllPickers();
                    } else {
                        await showApWeek(t.dataset.year, t.dataset.weeknum);
                        rebuildWeekPicker();
                    }
                } else {
                    await showApWeek(t.dataset.year, t.dataset.weeknum);
                    closeAllPickers();
                }
            });
            weekPicker.appendChild(btn);
        });
    } else {
        const activeTab = document.querySelector(".week-tab.active");
        const tabs = Array.from(document.querySelectorAll(`.week-tab[data-year="${currentYear}"]`))
            .filter(t => t.dataset.poll !== "ap")
            .sort((a, b) => parseInt(a.dataset.weeknum) - parseInt(b.dataset.weeknum));
        tabs.forEach(t => {
            const btn = document.createElement("button");
            btn.className = "picker-btn";
            btn.textContent = padWeekNum(displayWeekNum(t));
            btn.dataset.week = t.dataset.week;
            if (activeTab && t.dataset.week === activeTab.dataset.week) btn.style.textDecoration = "underline";
            btn.addEventListener("click", e => {
                e.stopPropagation();
                if (weekPickerPinned) {
                    if (activeTab && activeTab.dataset.week === t.dataset.week) {
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
}

// ── "Overall" row ────────────────────────────────────────────────────────────
// A copy of the week's aggregate row (Official Overall / AP Overall) shown at
// the top of the Official and Provisional tables, above pinned voters. It has
// no .voter-row class so voter scans (stats, sorting, caches) ignore it.
// Hidden by default; the viewer's choice is remembered in localStorage.
let _showOverallRow = false;
try { _showOverallRow = localStorage.getItem("showOverallRow") === "1"; } catch (e) {}
document.body.classList.toggle("show-overall-row", _showOverallRow);

function syncOverallMenu() {
    document.querySelectorAll("[data-action='toggleOverall']").forEach(el => {
        el.classList.toggle("active", _showOverallRow);
    });
}

function toggleOverallRow() {
    _showOverallRow = !_showOverallRow;
    document.body.classList.toggle("show-overall-row", _showOverallRow);
    syncOverallMenu();
    try { localStorage.setItem("showOverallRow", _showOverallRow ? "1" : "0"); } catch (e) {}
}

function injectOverallRows(block) {
    if (!block) return;
    const sections = block.querySelectorAll(".ballot-section");
    const aggRow = sections[2]?.querySelector(".voter-row:not(.row-weighted-ranking):not(.row-pinned-agg)");
    if (!aggRow) return;
    const aggName = getVoterName(aggRow);
    [sections[0], sections[1]].forEach(section => {
        const tbody = section?.querySelector("tbody");
        if (!tbody || tbody.querySelector(".overall-row")) return;
        if (!tbody.querySelector(".voter-row")) return; // no ballots in this section
        const row = aggRow.cloneNode(true);
        row.className = "overall-row";
        row.dataset.voterAlias = aggName;
        row.querySelectorAll(".pin-btn, .history-btn, .ballot-link-btn, .delta-label, .avg-label, .consensus-dist")
            .forEach(el => el.remove());
        row.querySelectorAll(".team-logo").forEach(img => { img.dataset.bound = ""; });
        const nameEl = row.querySelector(".voter-name");
        if (nameEl) nameEl.textContent = "Overall";
        const cell = row.querySelector(".voter-cell");
        if (cell) {
            cell.dataset.bound = "1"; // skip bindVoterCells (no pin/history buttons)
            cell.addEventListener("click", () => {
                if (deltaMode !== "off") return;
                if (row.classList.toggle("row-delta")) {
                    applyDeltaToRow(row, block.id, buildDeltaData(), getSortedTabs());
                } else {
                    row.querySelectorAll(".delta-label, .avg-label").forEach(el => el.remove());
                }
            });
        }
        tbody.prepend(row);
    });
}

async function showWeek(weekId) {
    document.querySelectorAll(".week-block").forEach(b => b.style.display = "none");
    document.querySelectorAll(".week-tab").forEach(t => t.classList.remove("active"));
    const block = document.getElementById(weekId);
    if (block) block.style.display = "block";
    const tab = document.querySelector(`.week-tab[data-week="${weekId}"]`);
    if (tab) tab.classList.add("active");

    if (tab) {
        const wn = parseInt(tab.dataset.weeknum);
        if (!isMobile()) {
            document.getElementById("week-text").innerText = "#" + padWeekNum(displayWeekNum(tab));
            document.getElementById("year-text").innerText = tab.dataset.year;
            rebuildWeekPicker();
        }
        updateFavicon(wn);
    }

    const toggleText = document.getElementById("toggle-text").innerText;
    const isProvisional = !isMobile() && toggleText === "Provisional Ballots";
    const isAggregate = !isMobile() && toggleText === "Data Ballots";
    if (block) {
        block.querySelectorAll(".ballot-section").forEach(s => s.style.display = "none");
        const sections = block.querySelectorAll(".ballot-section");
        let targetSection;
        if (isAggregate && sections[2]) targetSection = sections[2];
        else if (isProvisional) targetSection = sections[1];
        else targetSection = sections[0];
        if (targetSection) targetSection.style.display = "block";
        else if (sections[0]) sections[0].style.display = "block";
        injectOverallRows(block);
        syncOverallMenu();
        lazyLoadWeek(block);
        refreshBlockLogos(block);
        if (isAggregate) {
            const newActiveTab = document.querySelector(".week-tab.active");
            if (newActiveTab) {
                if (ON_AP_PAGE) {
                    injectApWeightedRankingRow(block, newActiveTab.dataset.week, newActiveTab.dataset.year);
                } else {
                    injectWeightedRankingRow(newActiveTab, block);
                }
            }
        }
    }

    bindTeamLogos();
    bindRankHeaders();
    bindVoterCells();
    bindVotersToggle();
    applyTableSort(currentSort);
    updateAvgRankLines();
    if (block) { if (_outliersMode) applyOutliers(block); else clearOutliers(block); }
    ensureDeltaLabels(block);
    syncDeltaControls();
}

// Show a specific AP week — the AP-mode equivalent of showWeek().
// Updates _apCurrentYear/_apCurrentWeekNum, hides the previous AP block,
// loads the year fragment if needed, shows the new block, and rebuilds pickers.
async function showApWeek(year, weekNum) {
    year = String(year);
    weekNum = String(weekNum);

    // Hide previous AP block
    if (_apCurrentYear && _apCurrentWeekNum) {
        const prev = document.getElementById(`week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`);
        if (prev) prev.style.display = "none";
    }
    _apCurrentYear = year;
    _apCurrentWeekNum = weekNum;

    await loadApYear(year);
    const apBlock = document.getElementById(`week-ap-${year}-${weekNum}`);
    if (apBlock) {
        apBlock.style.display = "";
        apBlock.querySelectorAll(".ballot-section").forEach(s => s.style.display = "none");
        const apSections = apBlock.querySelectorAll(".ballot-section");
        const apToggleText = document.getElementById("toggle-text").innerText;
        const showApAggregate = !isMobile() && apToggleText === "Associated Press Data";
        if (showApAggregate && apSections[2]) {
            apSections[2].style.display = "block";
        } else if (apSections[0]) {
            apSections[0].style.display = "block";
        }
        injectOverallRows(apBlock);
        syncOverallMenu();
        lazyLoadWeek(apBlock);
        refreshBlockLogos(apBlock);
        if (showApAggregate) injectApWeightedRankingRow(apBlock, `week-ap-${year}-${weekNum}`, year);
        ensureDeltaLabels(apBlock);
    }
    syncDeltaControls();

    if (!isMobile()) {
        const apTab = document.querySelector(`.week-tab[data-poll="ap"][data-year="${year}"][data-weeknum="${weekNum}"]`);
        const wn = parseInt(weekNum);
        const weekDisplay = "#" + padWeekNum(apTab ? displayWeekNum(apTab) : wn);
        document.getElementById("week-text").innerText = weekDisplay;
        document.getElementById("year-text").innerText = year;
        rebuildYearPicker();
        rebuildWeekPicker();
    }

    bindTeamLogos();
    bindRankHeaders();
    bindVoterCells();
    bindVotersToggle();
    applyTableSort(currentSort);
    updateAvgRankLines();
    if (apBlock && _outliersMode) applyOutliers(apBlock);
}

// Enter Associated Press mode from whatever userpoll week is currently active.
async function switchToApBallots() {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab || activeTab.dataset.poll === "ap") return;
    const year = activeTab.dataset.year;
    const weekNum = activeTab.dataset.weeknum;

    document.getElementById("toggle-text").innerText = "Associated Press";

    // Hide userpoll block
    const activeBlock = document.getElementById(activeTab.dataset.week);
    if (activeBlock) activeBlock.style.display = "none";

    // Load AP year so we can find which weeks exist
    await loadApYear(year);
    let targetWeekNum = weekNum;
    const apTabsForYear = getSortedApTabs().filter(t => t.dataset.year === year);
    const exactMatch = apTabsForYear.find(t => t.dataset.weeknum === weekNum);
    if (!exactMatch && apTabsForYear.length > 0) {
        // Find the closest available AP week
        const closest = apTabsForYear.reduce((best, t) =>
            Math.abs(parseInt(t.dataset.weeknum) - parseInt(weekNum)) <
            Math.abs(parseInt(best.dataset.weeknum) - parseInt(weekNum)) ? t : best
        );
        targetWeekNum = closest.dataset.weeknum;
    }

    await showApWeek(year, targetWeekNum);
}

// Exit Associated Press mode and restore the userpoll view.
function exitApBallots() {
    if (!_apCurrentYear || !_apCurrentWeekNum) return;

    // Hide current AP block
    const apBlock = document.getElementById(`week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`);
    if (apBlock) apBlock.style.display = "none";

    _apCurrentYear = null;
    _apCurrentWeekNum = null;

    document.getElementById("toggle-text").innerText = "Official Ballots";

    // Restore userpoll block for the current userpoll active tab
    const activeTab = document.querySelector(".week-tab.active");
    if (activeTab && activeTab.dataset.poll !== "ap") {
        const activeBlock = document.getElementById(activeTab.dataset.week);
        if (activeBlock) {
            activeBlock.style.display = "";
            activeBlock.querySelectorAll(".ballot-section").forEach(s => s.style.display = "none");
            const sections = activeBlock.querySelectorAll(".ballot-section");
            if (sections[0]) sections[0].style.display = "block";
        }
        if (!isMobile()) {
            document.getElementById("week-text").innerText = "#" + padWeekNum(displayWeekNum(activeTab));
            document.getElementById("year-text").innerText = activeTab.dataset.year;
            rebuildYearPicker();
            rebuildWeekPicker();
        }
    }

    _deltaDataCache = null;
    applyTableSort(currentSort);
    updateAvgRankLines();
    if (_outliersMode) {
        const curTab = document.querySelector(".week-tab.active");
        if (curTab) { const b = document.getElementById(curTab.dataset.week); if (b) applyOutliers(b); }
    }
}

// Toggle: Official ↔ Provisional (userpoll), Associated Press ↔ Associated Press Data (AP index mode), Associated Press ↔ Data Ballots (ap-ballots.html)
document.getElementById("toggle-text").addEventListener("click", async () => {
    const current = document.getElementById("toggle-text").innerText;

    // AP mode on index.html: cycle Associated Press ↔ Associated Press Data
    if (_apCurrentYear && _apCurrentWeekNum) {
        if (current === "Associated Press") {
            showAggregateSection();
        } else if (current === "Associated Press Data") {
            const apBlock = document.getElementById(`week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`);
            if (!apBlock) return;
            const sections = apBlock.querySelectorAll(".ballot-section");
            sections.forEach(s => s.style.display = "none");
            if (sections[0]) sections[0].style.display = "block";
            document.getElementById("toggle-text").innerText = "Associated Press";
            _deltaDataCache = null;
            applyTableSort(currentSort);
            updateAvgRankLines();
            if (_outliersMode) applyOutliers(apBlock);
        }
        return;
    }

    // ap-ballots.html: cycle Associated Press ↔ Data Ballots
    if (ON_AP_PAGE) {
        if (current === "Associated Press") {
            showAggregateSection();
        } else {
            // Data Ballots → Associated Press
            const activeTab = document.querySelector(".week-tab.active");
            if (!activeTab) return;
            const activeBlock = document.getElementById(activeTab.dataset.week);
            if (!activeBlock) return;
            const sections = activeBlock.querySelectorAll(".ballot-section");
            sections.forEach(s => s.style.display = "none");
            if (sections[0]) sections[0].style.display = "block";
            document.getElementById("toggle-text").innerText = "Associated Press";
            _deltaDataCache = null;
            applyTableSort(currentSort);
            updateAvgRankLines();
            if (_outliersMode) applyOutliers(activeBlock);
        }
        return;
    }

    // Normal userpoll toggle: Official ↔ Provisional
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const activeBlock = document.getElementById(activeTab.dataset.week);
    if (!activeBlock) return;
    const sections = activeBlock.querySelectorAll(".ballot-section");
    sections.forEach(s => s.style.display = "none");

    if (current === "Official Ballots") {
        if (sections[1]) sections[1].style.display = "block";
        document.getElementById("toggle-text").innerText = "Provisional Ballots";
    } else {
        // Provisional → Official
        if (sections[0]) sections[0].style.display = "block";
        document.getElementById("toggle-text").innerText = "Official Ballots";
    }
    _deltaDataCache = null;
    applyTableSort(currentSort);
    updateAvgRankLines();
    if (_outliersMode) applyOutliers(activeBlock);
});


function injectWeightedRankingRow(activeTab, activeBlock) {
    const activeYear = activeTab.dataset.year;
    const yearTabs = getSortedTabs().filter(t => t.dataset.year === activeYear);
    const deltaData = buildDeltaData(true);
    _injectTenureRows(activeBlock, activeTab.dataset.week, yearTabs, deltaData);
    applyDataBallotOrder(activeBlock);
    injectEspnApRow(activeBlock, activeTab.dataset.week);
    injectBpiRow(activeBlock, activeTab.dataset.week);
    injectSorRow(activeBlock, activeTab.dataset.week);
}

// {conf: [teams]} for a season (later seasons reuse the last defined one), or null before 2025.
function conferenceTable(year) {
    if (typeof CONFERENCE_DATA === "undefined") return null;
    const seasons = Object.keys(CONFERENCE_DATA.seasons).map(Number).sort((a, b) => a - b);
    year = Number(year);
    if (!seasons.length || year < seasons[0]) return null;
    return CONFERENCE_DATA.seasons[Math.min(year, seasons[seasons.length - 1])];
}

// Overall points for one week's official ballots: {team: pts}.
function weekBallotPoints(weekBallots) {
    const pts = {};
    Object.entries(weekBallots || {}).forEach(([user, teams]) => {
        if (user === "Official Overall" || user === "AP Overall") return;
        teams.slice(0, 25).forEach((t, i) => { pts[t] = (pts[t] || 0) + (25 - i); });
    });
    return pts;
}

// One ranking row (name cell + 25 logo cells with delta and points labels).
// pts = {team: points}; prevRankOf = {team: last week's rank in the same ranking}.
// key = the row's id for the saved drag order (defaults to the label).
function _buildPointsRankingRow(label, ranked, pts, prevRankOf, hasPrev, key = label) {
    const tr = document.createElement("tr");
    tr.className = "voter-row row-weighted-ranking";
    tr.dataset.group = key;
    const nameTd = document.createElement("td");
    nameTd.innerHTML = `<div class="voter-cell"><span class="voter-name"></span></div>`;
    nameTd.querySelector(".voter-name").textContent = label;
    tr.appendChild(nameTd);

    for (let i = 0; i < 25; i++) {
        const td = document.createElement("td");
        td.className = "logo-cell";
        const team = ranked[i];
        if (team) {
            const img = document.createElement("img");
            img.className = "logo team-logo";
            img.dataset.team = team;
            setBallotLogo(img, team);
            td.appendChild(img);

            const delta = document.createElement("span");
            delta.className = "delta-label";
            if (!hasPrev) { delta.textContent = "—"; delta.classList.add("delta-same"); }
            else setDeltaLabel(delta, (prevRankOf[team] || 26) - (i + 1)); // unranked = #26
            td.appendChild(delta);

            const ptsLabel = document.createElement("span");
            ptsLabel.className = "avg-label";
            ptsLabel.textContent = pts[team];
            ptsLabel.title = "Overall points";
            td.appendChild(ptsLabel);
        }
        tr.appendChild(td);
    }
    return tr;
}

// ── Tenure rankings (Data Ballots, Userpoll only) ────────────────────────────
// Overall points from only the official ballots of voters in a tenure band
// (TENURE_COUNTS = career ballots, the same numbers as the Tenure leaderboard).
const TENURE_GROUPS = [
    // Non-overlapping bands; a season is roughly 18–20 ballots. `key` is the old label,
    // kept as the drag-order id so saved orders (localStorage dataBallotOrder) still apply.
    { key: "Rookies",     label: "20- Ballots",   test: n => n <= 20 },
    { key: "2–5 Seasons", label: "21-99 Ballots", test: n => n > 20 && n < 100 },
    { key: "Veterans",    label: "100+ Ballots",  test: n => n >= 100 },
];

function tenureBallots(weekBallots, test) {
    const out = {};
    Object.entries(weekBallots || {}).forEach(([user, teams]) => {
        if (user === "Official Overall" || user === "AP Overall") return;
        if (test(TENURE_COUNTS[user] ?? 0)) out[user] = teams;
    });
    return out;
}

function _injectTenureRows(block, weekId, yearTabs, deltaData) {
    const aggTbody = block.querySelectorAll(".ballot-section")[2]?.querySelector("tbody");
    if (!aggTbody) return;
    const expanded = new Set();
    aggTbody.querySelectorAll(".row-tenure-ranking").forEach(r => {
        if (r.classList.contains("row-delta")) expanded.add(r.dataset.group);
        r.remove();
    });

    const currIdx = yearTabs.findIndex(t => t.dataset.week === weekId);
    const prevWeekId = currIdx + 1 < yearTabs.length ? yearTabs[currIdx + 1].dataset.week : null;

    // After the last ranking row (else Overall)
    const rankRows = aggTbody.querySelectorAll(".row-weighted-ranking");
    let anchor = rankRows[rankRows.length - 1] || aggTbody.querySelector(".voter-row:not(.row-pinned-agg)");
    TENURE_GROUPS.forEach(group => {
        const ballots = tenureBallots(deltaData[weekId], group.test);
        const pts = weekBallotPoints(ballots);
        if (!Object.keys(pts).length) return;
        const voters = Object.values(ballots).filter(t => t && t.length).length;
        const ranked = Object.keys(pts).sort((a, b) => pts[b] - pts[a]).slice(0, 25);
        const prevPts = prevWeekId ? weekBallotPoints(tenureBallots(deltaData[prevWeekId], group.test)) : {};
        const hasPrev = Object.keys(prevPts).length > 0;
        const prevRankOf = {};
        Object.keys(prevPts).sort((a, b) => prevPts[b] - prevPts[a]).slice(0, 25)
            .forEach((t, i) => { prevRankOf[t] = i + 1; });

        const tr = _buildPointsRankingRow(`${group.label} (${voters})`, ranked, pts, prevRankOf, hasPrev, group.key);
        tr.classList.add("row-tenure-ranking");
        if (expanded.has(group.key)) tr.classList.add("row-delta");
        if (anchor) anchor.after(tr); else aggTbody.appendChild(tr);
        anchor = tr;
    });
    bindTeamLogos();
}

// ── AP Top 25 row (Data Ballots, Userpoll only) ─────────────────────────────
// The official AP poll for the same week, live from ESPN's core API (CORS open, history back
// to at least 2017). ESPN AP week N = userpoll week N (pre-season = ESPN week 1); checked by
// ranking similarity for 2017/2020/2022 and by date for 2026. ESPN's numbering has holes and
// misfiled weeks (2026: week 9 missing, week 2 holds the final poll dated Apr 7), so weeks with
// a poll deadline must also match by date (ESPN dates AP polls Monday 07:00/08:00 UTC, our
// deadline is the same Monday 10 AM ET); if type-2 week N misses, the postseason (type 3) polls
// are tried. Legacy weeks (no deadline) trust the number and never use postseason polls.
const ESPN_CORE_BASE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball";
const ESPN_AP_MATCH_MS = 3 * 86400000;
const ESPN_AP_LABEL = "AP Top 25";

// {date, ranks: [{id, rank, prev, pts, fpv}]}, or {missing: true} when ESPN has no such poll.
function fetchEspnApPoll(season, type, week) {
    return _espnCached(`ap:${season}:${type}:${week}`, async () => {
        let json;
        try { json = await _espnJson(`${ESPN_CORE_BASE}/seasons/${season}/types/${type}/weeks/${week}/rankings/1`); }
        catch (e) { if (/HTTP 404\b/.test(e.message)) return { missing: true }; throw e; }
        const ranks = (json.ranks || []).map(e => ({
            id: (/teams\/(\d+)/.exec(e.team?.$ref || "") || [])[1] || null,
            rank: e.current, prev: e.previous || 0,
            pts: Math.round(e.points || 0), fpv: e.firstPlaceVotes || 0,
        })).filter(e => e.id && e.rank).sort((a, b) => a.rank - b.rank);
        return { date: json.date, ranks };
    });
}

async function espnApPollForWeek(weekId) {
    const tab = getSortedTabs().find(t => t.dataset.week === weekId);
    if (!tab) return null;
    const season = tab.dataset.year;
    const pre = isPreseasonTab(tab);
    // Pre-season ballots can be saved long after the poll (2025's were re-saved in Feb): no date check.
    const deadline = pre ? null : pollDeadline(weekId);
    const ok = p => p && !p.missing && p.ranks.length &&
        (!deadline || Math.abs(Date.parse(p.date) - deadline) <= ESPN_AP_MATCH_MS);
    const first = await fetchEspnApPoll(season, 2, pre ? 1 : Number(tab.dataset.weeknum));
    if (ok(first)) return first;
    if (!deadline) return null;
    for (const w of [1, 2, 3]) {
        const p = await fetchEspnApPoll(season, 3, w);
        if (ok(p)) return p;   // no early exit on 404: 2026 has only type-3 week 3
    }
    return null;
}

async function injectEspnApRow(block, weekId) {
    if (ON_AP_PAGE || !block || weekId.startsWith("week-ap-")) return;
    const token = block._espnApToken = {};
    let poll;
    try { poll = await espnApPollForWeek(weekId); } catch { poll = null; }
    if (block._espnApToken !== token) return;
    const aggTbody = block.querySelectorAll(".ballot-section")[2]?.querySelector("tbody");
    if (!aggTbody) return;
    const old = aggTbody.querySelector(".row-espn-ap");
    const expanded = old?.classList.contains("row-delta");
    old?.remove();
    if (!poll) return;

    // Teams missing from ESPN_IDS get a placeholder key, then ESPN's logo below.
    const keyOf = e => espnTeamKey(e.id) || `espn:${e.id}`;
    const ranked = poll.ranks.slice(0, 25).map(keyOf);
    const pts = {}, prevRankOf = {};
    poll.ranks.forEach(e => { pts[keyOf(e)] = e.pts; if (e.prev) prevRankOf[keyOf(e)] = e.prev; });
    const hasPrev = poll.ranks.some(e => e.prev);
    const tr = _buildPointsRankingRow(ESPN_AP_LABEL, ranked, pts, prevRankOf, hasPrev);
    tr.classList.add("row-espn-ap");
    if (expanded) tr.classList.add("row-delta");
    const nameCell = tr.querySelector(".voter-name");
    nameCell.title = `AP poll via ESPN, ${new Date(poll.date).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
    tr.querySelectorAll("img.team-logo").forEach((img, i) => {
        const e = poll.ranks[i];
        const ptsLabel = img.parentElement.querySelector(".avg-label");
        if (ptsLabel) ptsLabel.title = e.fpv ? `AP points (${e.fpv} first-place)` : "AP points";
        if (img.dataset.team.startsWith("espn:")) {
            img.classList.remove("team-logo");
            delete img.dataset.team;
            img.src = espnLogoUrl(e.id);
        }
    });

    _insertSourceRow(block, aggTbody, tr);
}

// Rows from outside sources (ESPN AP poll, BPI, SOR) go right after Overall, in this order,
// whichever arrives first; the saved drag order then applies.
const SOURCE_ROW_ORDER = ["Overall", "AP Top 25", "BPI", "SOR"];
function _insertSourceRow(block, aggTbody, tr) {
    const mine = SOURCE_ROW_ORDER.indexOf(tr.dataset.group);
    const rows = Array.from(aggTbody.querySelectorAll(":scope > .voter-row:not(.row-pinned-agg)"));
    const before = rows.filter(r => { const i = SOURCE_ROW_ORDER.indexOf(dataBallotRowKey(r)); return i !== -1 && i < mine; });
    const anchor = before[before.length - 1];
    if (anchor) anchor.after(tr); else aggTbody.prepend(tr);
    applyDataBallotOrder(block);
    bindVoterCells(block);
    bindTeamLogos(block);
}

// ── BPI row (Data Ballots, Userpoll only) ───────────────────────────────────
// ESPN's BPI top 25 as of the poll, from bpi-YEAR.json (bpi_history.py, --bpi; same origin,
// BPI_FILES lists the seasons). ESPN keeps no BPI history, so the daily refresh workflow
// records one snapshot per poll week (Monday morning, after ESPN's overnight update).
// A week with a deadline uses the latest snapshot within BPI_MATCH_BEFORE_MS before to
// BPI_MATCH_AFTER_MS after it; a week without one (legacy 2016–2022) only gets the season's
// final snapshot, and only if it is the season's last week (those are post-tournament polls).
const BPI_MATCH_BEFORE_MS = 4 * 86400000;
const BPI_MATCH_AFTER_MS = 12 * 3600000;
const _bpiHistory = {};   // season → Promise<snapshots[]>

function fetchBpiHistory(season) {
    if (typeof BPI_FILES === "undefined" || !BPI_FILES.includes(Number(season))) return Promise.resolve([]);
    if (!_bpiHistory[season]) {
        _bpiHistory[season] = fetch(`bpi-${season}.json`)
            .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
            .then(d => (d.snapshots || []).map(s => ({ ...s, at: Date.parse(s.asOf) })))
            .catch(e => { delete _bpiHistory[season]; throw e; });
    }
    return _bpiHistory[season];
}

// tabs = the season's tabs, newest first (getSortedTabs order).
function bpiSnapshotForTab(snaps, tabs, i) {
    const tab = tabs[i];
    if (!tab) return null;
    const deadline = isPreseasonTab(tab) ? null : pollDeadline(tab.dataset.week);
    if (!deadline) return i === 0 ? snaps.find(s => s.final) || null : null;
    const fit = snaps.filter(s => s.at >= deadline - BPI_MATCH_BEFORE_MS && s.at <= deadline + BPI_MATCH_AFTER_MS);
    return fit[fit.length - 1] || null;
}

// BPI and SOR rows share the snapshots: `teams` = [key, rank, bpi] by BPI rank, `sor` =
// [key, sorrank, wins, losses] by SOR rank (2025+ only; older snapshots have none, so no row).
const SNAPSHOT_ROWS = {
    BPI: {
        cls: "row-bpi", tokenKey: "_bpiToken", list: s => s.teams,
        title: "ESPN Basketball Power Index",
        label: t => t[2].toFixed(1), tip: t => `BPI rating (rank #${t[1]})`,
    },
    SOR: {
        cls: "row-sor", tokenKey: "_sorToken", list: s => s.sor,
        title: "ESPN Strength of Record",
        label: t => `${t[2]}-${t[3]}`, tip: t => `SOR rank #${t[1]}; record ${t[2]}-${t[3]}`,
    },
};

function injectBpiRow(block, weekId) { return _injectSnapshotRow(block, weekId, "BPI"); }
function injectSorRow(block, weekId) { return _injectSnapshotRow(block, weekId, "SOR"); }

async function _injectSnapshotRow(block, weekId, kind) {
    if (ON_AP_PAGE || !block || weekId.startsWith("week-ap-")) return;
    const cfg = SNAPSHOT_ROWS[kind];
    const token = block[cfg.tokenKey] = {};
    const tabs0 = getSortedTabs();
    const season = tabs0.find(t => t.dataset.week === weekId)?.dataset.year;
    let snaps;
    try { snaps = season ? await fetchBpiHistory(season) : []; } catch { snaps = []; }
    if (block[cfg.tokenKey] !== token) return;
    const aggTbody = block.querySelectorAll(".ballot-section")[2]?.querySelector("tbody");
    if (!aggTbody) return;
    const old = aggTbody.querySelector("." + cfg.cls);
    const expanded = old?.classList.contains("row-delta");
    old?.remove();

    const tabs = getSortedTabs().filter(t => t.dataset.year === season);
    const i = tabs.findIndex(t => t.dataset.week === weekId);
    const snap = bpiSnapshotForTab(snaps, tabs, i);
    const list = snap && cfg.list(snap);
    if (!list?.length) return;
    const prevSnap = bpiSnapshotForTab(snaps, tabs, i + 1);
    const prevList = prevSnap && cfg.list(prevSnap);
    const top = list.slice(0, 25);
    const ranked = top.map(t => t[0]);
    const pts = {}, prevRankOf = {};
    top.forEach(t => { pts[t[0]] = cfg.label(t); });
    (prevList || []).forEach(t => { prevRankOf[t[0]] = t[1]; });
    const tr = _buildPointsRankingRow(kind, ranked, pts, prevRankOf, !!prevList?.length);
    tr.classList.add(cfg.cls);
    if (expanded) tr.classList.add("row-delta");
    const when = new Date(snap.at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    tr.querySelector(".voter-name").title = `${cfg.title}${snap.final ? ", final" : ""}, as of ${when}`;
    tr.querySelectorAll("img.team-logo").forEach((img, j) => {
        const t = top[j];
        const label = img.parentElement.querySelector(".avg-label");
        if (label) label.title = cfg.tip(t);
        if (t[0].startsWith("espn:")) {
            img.classList.remove("team-logo");
            delete img.dataset.team;
            img.src = espnLogoUrl(t[0].slice(5));
        }
    });
    _insertSourceRow(block, aggTbody, tr);
}

// ── Data Ballots row order (drag to reorder) ────────────────────────────────
// The Overall row and the tenure ranking rows can be dragged up and down by
// their name cell. The order is a per-viewer preference saved in localStorage
// (by row label) and re-applied whenever the rows are rebuilt.
const DATA_BALLOT_ORDER_KEY = "dataBallotOrder";

function dataBallotRowKey(row) {
    if (row.classList.contains("row-weighted-ranking")) return row.dataset.group || null;
    const n = getVoterName(row);
    return n === "Official Overall" || n === "AP Overall" ? "Overall" : null;
}

// The reorderable rows of an aggregate tbody, in DOM order.
function dataBallotRows(tbody) {
    return Array.from(tbody?.querySelectorAll(":scope > .voter-row:not(.row-pinned-agg)") || [])
        .filter(r => dataBallotRowKey(r));
}

function loadDataBallotOrder() {
    try { return JSON.parse(localStorage.getItem(DATA_BALLOT_ORDER_KEY)) || []; } catch { return []; }
}

function applyDataBallotOrder(block) {
    const tbody = block?.querySelectorAll(".ballot-section")[2]?.querySelector("tbody");
    const rows = dataBallotRows(tbody);
    rows.forEach(r => r.classList.add("row-data-draggable"));
    const order = loadDataBallotOrder();
    if (rows.length < 2 || !order.length) return;
    const pos = r => { const i = order.indexOf(dataBallotRowKey(r)); return i === -1 ? order.length + rows.indexOf(r) : i; };
    const sorted = rows.slice().sort((a, b) => pos(a) - pos(b));
    if (sorted.every((r, i) => r === rows[i])) return;
    const marker = document.createComment("");
    rows[0].before(marker);
    sorted.forEach(r => marker.before(r));
    marker.remove();
}

(function initDataBallotDrag() {
    let drag = null;
    document.addEventListener("pointerdown", e => {
        if (e.button !== 0 || e.shiftKey || e.metaKey || e.ctrlKey) return;
        const cell = e.target.closest?.("td:first-child");
        const row = cell?.closest("tr.row-data-draggable");
        if (!row || !row.closest('.ballot-section[id$="-aggregate"]')) return;
        const tbody = row.parentElement;
        if (dataBallotRows(tbody).length < 2) return;
        drag = { row, tbody, startY: e.clientY, active: false };
    });
    document.addEventListener("pointermove", e => {
        if (!drag) return;
        if (!drag.active) {
            if (Math.abs(e.clientY - drag.startY) < 5) return;
            drag.active = true;
            drag.row.classList.add("row-dragging");
            document.body.classList.add("data-ballot-dragging");
        }
        e.preventDefault();
        const others = dataBallotRows(drag.tbody).filter(r => r !== drag.row);
        const mid = r => { const b = r.getBoundingClientRect(); return b.top + b.height / 2; };
        const before = others.find(r => e.clientY < mid(r));
        if (before) {
            if (drag.row.nextElementSibling !== before) before.before(drag.row);
        } else {
            const last = others[others.length - 1];
            if (last && last.nextElementSibling !== drag.row) last.after(drag.row);
        }
    });
    const end = () => {
        if (!drag) return;
        const { active, row, tbody } = drag;
        drag = null;
        if (!active) return;
        row.classList.remove("row-dragging");
        document.body.classList.remove("data-ballot-dragging");
        // Swallow the click that follows the drop so the row doesn't toggle its deltas
        const swallow = ev => { ev.stopPropagation(); ev.preventDefault(); };
        window.addEventListener("click", swallow, true);
        setTimeout(() => window.removeEventListener("click", swallow, true), 0);
        const order = dataBallotRows(tbody).map(dataBallotRowKey);
        const saved = loadDataBallotOrder().filter(k => !order.includes(k));
        try { localStorage.setItem(DATA_BALLOT_ORDER_KEY, JSON.stringify([...order, ...saved])); } catch {}
        document.querySelectorAll(".week-block").forEach(b => { if (b !== tbody.closest(".week-block")) applyDataBallotOrder(b); });
    };
    document.addEventListener("pointerup", end);
    document.addEventListener("pointercancel", end);
})();

// Movement text for a rank change (positive diff = moved up): ▲3 / ▼3, blank for no
// change. Moves of 1–4 get delta-small, which are always grayed out.
function setDeltaLabel(label, diff) {
    if (diff > 0) {
        label.textContent = "▲" + diff;
        label.classList.add("delta-up");
    } else if (diff < 0) {
        label.textContent = "▼" + -diff;
        label.classList.add("delta-down");
    } else {
        label.textContent = "";
        label.classList.add("delta-same");
    }
    if (diff !== 0 && Math.abs(diff) <= 4) label.classList.add("delta-small");
}

function apYearTabs(year) {
    const tabs = ON_AP_PAGE ? getSortedTabs() : getSortedApTabs();
    return tabs.filter(t => t.dataset.year === String(year));
}

function buildApDeltaData(year) {
    if (_apDeltaDataCache[year]) return _apDeltaDataCache[year];
    const data = {};
    apYearTabs(year).forEach(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        if (!block) return;
        data[weekId] = {};
        const section = block.querySelectorAll(".ballot-section")[0];
        if (!section) return;
        section.querySelectorAll(".voter-row").forEach(row => {
            const username = getVoterName(row);
            if (!username) return;
            data[weekId][username] = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
        });
    });
    _apDeltaDataCache[year] = data;
    return data;
}

// AP Data Ballots has only the AP Overall row now (Recency and conference rows were removed).
function injectApWeightedRankingRow(apBlock, apWeekId, year) {
    const aggTbody = apBlock?.querySelectorAll(".ballot-section")[2]?.querySelector("tbody");
    aggTbody?.querySelectorAll(".row-weighted-ranking").forEach(r => r.remove());
    applyDataBallotOrder(apBlock);
}

// Week Stats table (the "Stats" tab of the Stats > Week window). Returns the
// table's inner HTML, or null when the week has no official ballots.
function buildWeekStatsTableHtml(weekId) {
    const block = document.getElementById(weekId);
    if (!block) return null;
    const sections = block.querySelectorAll(".ballot-section");
    const officialSection = sections[0];
    if (!officialSection) return null;

    // Collect all voter rows (exclude Official Overall)
    const voterRows = Array.from(officialSection.querySelectorAll(".voter-row"))
        .filter(r => getVoterName(r) !== "Official Overall");
    const totalVoters = voterRows.length;
    if (totalVoters === 0) return null;

    // Compute rank sums, voter counts, points, and rank lists per team
    const teamRankSum = {};
    const teamVoterCount = {};
    const teamPoints = {};
    const teamRanks = {};
    const teamFirsts = {};
    voterRows.forEach(row => {
        const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
        teams.slice(0, 25).forEach((team, i) => {
            const rank = i + 1;
            teamRankSum[team] = (teamRankSum[team] || 0) + rank;
            teamVoterCount[team] = (teamVoterCount[team] || 0) + 1;
            teamPoints[team] = (teamPoints[team] || 0) + (26 - rank);
            if (rank === 1) teamFirsts[team] = (teamFirsts[team] || 0) + 1;
            if (!teamRanks[team]) teamRanks[team] = [];
            teamRanks[team].push(rank);
        });
    });

    const computeMedian = ranks => {
        const sorted = [...ranks].sort((a, b) => a - b);
        const mid = Math.floor(sorted.length / 2);
        return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
    };

    // Sort by points descending (same order as Official Overall)
    const allTeams = Object.entries(teamPoints).sort((a, b) => b[1] - a[1]).map(([t]) => t);
    const top25 = allTeams.slice(0, 25);
    const receivingVotes = allTeams.slice(25);

    // Use cached delta data for previous week's Official Overall ranking
    const isApWeek = weekId.startsWith("week-ap-");
    const allTabsSorted = isApWeek ? getSortedApTabs() : getSortedTabs();
    const currTabIdx = allTabsSorted.findIndex(t => t.dataset.week === weekId);
    const currYear = allTabsSorted[currTabIdx]?.dataset.year;
    const prevTab = allTabsSorted[currTabIdx + 1];
    const prevTeamRank = {};
    const prevTeamPoints = {};
    let prevVoters = 0;
    const deltaDataForNew = buildDeltaData(true);
    if (prevTab && prevTab.dataset.year === currYear) {
        const prevWeek = deltaDataForNew[prevTab.dataset.week];
        const prevTeams = prevWeek?.["Official Overall"];
        if (prevTeams) prevTeams.forEach((t, i) => { prevTeamRank[t] = i + 1; });
        // Previous week's points from its official ballots (same 25..1 scoring as this week)
        Object.entries(prevWeek || {}).forEach(([voter, teams]) => {
            if (voter === "Official Overall") return;
            prevVoters++;
            teams.slice(0, 25).forEach((t, i) => { prevTeamPoints[t] = (prevTeamPoints[t] || 0) + (25 - i); });
        });
    }
    const hasPrevWeek = Object.keys(prevTeamRank).length > 0;

    // Outlook graph bands (inner ~50%, outer ~77.5%) for this week's top 25
    const outlookBands = {};
    (computeOutlookBands(weekId, top25) || []).forEach(b => { outlookBands[b.team] = b; });
    const fmtBandRank = r => { const n = Math.round(r); return n >= 26 ? "NR" : n; };
    const fmtBand = (a, b) => {
        const x = fmtBandRank(a), y = fmtBandRank(b);
        return x === y ? `${x}` : `${x}–${y}`;
    };

    const percentileRank = (sortedArr, p) => {
        if (sortedArr.length === 1) return sortedArr[0];
        const idx = p * (sortedArr.length - 1);
        const lo = Math.floor(idx);
        const hi = Math.ceil(idx);
        return sortedArr[lo] + (idx - lo) * (sortedArr[hi] - sortedArr[lo]);
    };

    const buildRow = (team, rank) => {
        const avg = teamRankSum[team] / teamVoterCount[team];
        const median = computeMedian(teamRanks[team]);
        const count = teamVoterCount[team];
        const pts = teamPoints[team];
        const allRanks = [...teamRanks[team], ...Array(totalVoters - count).fill(26)].sort((a, b) => a - b);
        const hi = percentileRank(allRanks, 0.10);
        const lo = percentileRank(allRanks, 0.90);
        const sdRaw = count / totalVoters > 0.84
            ? Math.sqrt(teamRanks[team].reduce((s, r) => s + (r - avg) ** 2, 0) / teamRanks[team].length)
            : null;
        let rankDelta = '—';
        if (hasPrevWeek && rank <= 25) {
            const prevRank = prevTeamRank[team] || 26; // unranked = #26
            {
                const diff = prevRank - rank;
                if (diff > 0) {
                    rankDelta = `<span class="delta-up">${diff}</span>`;
                } else if (diff < 0) {
                    rankDelta = `<span class="delta-down">${Math.abs(diff)}</span>`;
                } else {
                    rankDelta = `<span class="delta-same">—</span>`;
                }
            }
        }
        // Change in share of points available (25 per voter), since voter counts vary week to week
        let ptsDelta = '—';
        if (prevVoters) {
            const d = Math.round(1000 * (pts / (25 * totalVoters) - (prevTeamPoints[team] || 0) / (25 * prevVoters))) / 10;
            ptsDelta = d > 0 ? `<span class="delta-up">${d.toFixed(1)}%</span>`
                : d < 0 ? `<span class="delta-down">${(-d).toFixed(1)}%</span>`
                : `<span class="delta-same">—</span>`;
        }
        const firsts = teamFirsts[team] || 0;
        const inTop25 = rank <= 25;
        const rankDisplay = `<div style="font-variant-numeric:tabular-nums;text-align:center">${rank}</div>`;
        const band = outlookBands[team];
        const cellLikely = band ? `<td style="white-space:nowrap">${fmtBand(band.innerHi, band.innerLo)}</td>` : '<td>—</td>';
        const cellOutlook = band ? `<td style="white-space:nowrap">${fmtBand(band.hi, band.lo)}</td>` : '<td>—</td>';
        const teamAttr = team.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
        const espnId = espnIdFor(team);
        const espnAttr = espnId ? ` data-espn="${espnId}"` : "";
        return `<tr data-team="${teamAttr}">
            <td>${rankDisplay}</td>
            <td style="padding:2px 4px;"><img class="logo-sm records-logo" data-team="${teamAttr}"${espnAttr} alt=""></td>
            <td class="team-col">${formatTeamName(team)}<span class="ws-rec"></span></td>
            <td style="white-space:nowrap">${rankDelta}</td>
            <td>${count}</td>
            <td>${pts}</td>
            <td>${firsts || ""}</td>
            <td style="white-space:nowrap">${ptsDelta}</td>
            <td>${inTop25 ? (Number.isInteger(hi) ? hi : hi.toFixed(1)) : ""}</td>
            <td>${inTop25 ? avg.toFixed(1) : ""}</td>
            <td>${inTop25 ? (Number.isInteger(lo) ? lo : lo.toFixed(1)) : ""}</td>
            <td>${inTop25 ? (sdRaw != null ? sdRaw.toFixed(1) : "—") : ""}</td>
            ${inTop25 ? cellLikely : "<td></td>"}
            ${inTop25 ? cellOutlook : "<td></td>"}
            <td class="ws-res"${espnAttr}></td>
        </tr>`;
    };

    // No fixed column widths: columns fit their content, like the Records table.
    let html = `<thead><tr>
        <th>#</th><th></th>
        <th class="team-col">Team</th>
        <th title="Rank change">Δ</th>
        <th>Voters</th>
        <th>Pts</th>
        <th title="First-place votes">#1</th>
        <th title="Points change, % of max (25 × voters)">Δ Pts</th>
        <th title="10th percentile rank">P<sub>90+</sub></th>
        <th>Avg</th>
        <th title="90th percentile rank">P<sub>10−</sub></th>
        <th title="Rank standard deviation">Dev</th>
        <th title="Likely rank range (~50%), next few polls">50%</th>
        <th title="Outlook rank range (~77.5%), next few polls">77%</th>
        <th class="ws-res">Games</th>
    </tr></thead><tbody>`;
    top25.forEach((team, i) => { html += buildRow(team, i + 1); });
    if (receivingVotes.length > 0) {
        html += `<tr class="rv-divider"><td colspan="15">Receiving Votes</td></tr>`;
        receivingVotes.forEach((team, i) => { html += buildRow(team, 26 + i); });
    }
    html += "</tbody>";
    return html;
}

// "(W-L)" after each team name in the Week Stats table: the team's overall record (ESPN, incl.
// non-D1 and postseason) as of the poll's deadline (pollDeadline(), i.e. what voters had seen),
// from each team's schedule via recordAsOf(). Weeks without a deadline (AP, legacy 2016–2022)
// show the live standings record only for the latest week of the current season; otherwise,
// and for pre-season, nothing.
function fillWeekRecords(statsTable, weekId) {
    const isAp = weekId.startsWith("week-ap-");
    const tabs = isAp ? getSortedApTabs() : getSortedTabs();
    const i = tabs.findIndex(t => t.dataset.week === weekId);
    if (i === -1 || tabs[i].dataset.weeknum === "0") return;
    const season = tabs[i].dataset.year;
    const deadline = isAp ? null : pollDeadline(weekId);
    const isLatest = i === 0;
    if (!deadline && !isLatest) return;
    const rows = Array.from(statsTable.querySelectorAll("tr[data-team]"))
        .map(tr => ({ id: tr.querySelector("td.ws-res")?.dataset.espn, span: tr.querySelector(".ws-rec") }))
        .filter(r => r.id && r.span);
    const show = (span, wins, losses, tip) => {
        if (!statsTable.isConnected) return;
        span.textContent = ` (${wins}-${losses})`;
        span.title = tip;
    };
    if (!deadline) {
        fetchSeasonRecords(season).then(({ byId }) => {
            rows.forEach(r => {
                const t = byId[r.id];
                if (t) show(r.span, t.wins, t.losses, "Current record (ESPN)");
            });
        }, () => {});
        return;
    }
    const asOf = new Date(deadline).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    rows.forEach(r => {
        fetchTeamSchedule(r.id, season).then(({ games }) => {
            const { wins, losses } = recordAsOf(games, deadline);
            show(r.span, wins, losses, `Record at the poll deadline (${asOf}), ESPN`);
        }, () => {});
    });
}

// Games column of the Week Stats table: every game each team played, in date order, each as
// site (vs / @ / N) + opponent logo + score (opponent's AP rank at game time, or seed in the postseason, and name only in the tooltip),
// at most WEEK_RESULTS_MAX per team (see trimWeekGames()),
// wins in green and losses in red, between the previous poll's deadline and this poll's (pollResultsWindow()),
// i.e. the results voters had seen since their last ballot. Live from ESPN's scoreboard.
// Weeks without a window (pre-season, AP, pre-2025) hide the column via .ws-no-results.
function fillWeekResults(statsTable, weekId) {
    const win = pollResultsWindow(weekId);
    if (!win) { statsTable.classList.add("ws-no-results"); return; }
    const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const fmt = ms => new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    const span = `${fmt(win.start)} – ${fmt(win.end)}`;
    statsTable.querySelector("th.ws-res").title = `Games since last poll (${span})`;
    const cells = () => statsTable.querySelectorAll("td.ws-res");
    cells().forEach(td => { td.innerHTML = `<span class="ws-res-msg">…</span>`; });
    // One game: site (vs home / @ away / N neutral), opponent logo, score (ours first). Opponent's AP rank (or seed) and name are in the tooltip only.
    const oppHtml = g => {
        const siteWord = g.site === "H" ? "vs" : g.site === "A" ? "@" : "neutral vs";
        const name = g.opp.key ? conferenceDisplayName(g.opp.key) : g.opp.name || "?";
        const rank = g.oppRank ? `${g.oppRank}` : g.oppSeed ? `(${g.oppSeed})` : "";
        const day = new Date(g.date).toLocaleDateString([], { month: "short", day: "numeric" });
        const tip = esc(`${g.result} ${g.us}-${g.them} ${siteWord} ${g.oppRank ? `#${rank} ` : rank ? rank + " " : ""}${name} · ${day}${g.note ? ` · ${g.note}` : ""}`);
        const src = g.opp.key ? null : oppLogoSrc(g.opp) || (g.opp.id ? espnLogoUrl(g.opp.id) : null);
        const logo = g.opp.key
            ? `<img class="records-opp-logo records-logo" data-team="${esc(g.opp.key)}" data-espn="${g.opp.id}" alt="">`
            : src ? `<img class="records-opp-logo" src="${esc(src)}" data-filler="${esc(name)}" alt="">`
            : logoFillerHtml("records-opp-logo", name, "");
        return `<span class="ws-opp ${g.result === "W" ? "ws-win" : "ws-loss"}"${g.opp.key ? ` data-team="${esc(g.opp.key)}"` : ""} title="${tip}"><span class="ws-opp-site">${g.site === "H" ? "vs" : g.site === "A" ? "@" : "N"}</span>${logo}<span class="ws-opp-score">${g.us}-${g.them}</span></span>`;
    };
    // Opponent ratings for trimWeekGames(): NET / BPI rank from the season's quads file when there is one.
    const tab = (weekId.startsWith("week-ap-") ? getSortedApTabs() : getSortedTabs()).find(t => t.dataset.week === weekId);
    const season = tab?.dataset.year;
    const quads = season && quadsAvailable(season) ? fetchQuads(season).catch(() => null) : Promise.resolve(null);
    Promise.all([fetchResultsBetween(win.start, win.end), quads]).then(([{ byTeam }, q]) => {
        if (!statsTable.isConnected) return;
        cells().forEach(td => {
            const id = td.dataset.espn;
            const games = id ? trimWeekGames((byTeam[id] || []).filter(g => g.result === "W" || g.result === "L"), q?.teams) : null;
            td.innerHTML = games === null
                ? `<span class="ws-res-msg" title="No ESPN id for this team">?</span>`
                : games.length ? `<div class="ws-res-list">${games.map(oppHtml).join("")}</div>` : "—";
        });
        initRecordsLogos(statsTable);
    }, err => {
        if (!statsTable.isConnected) return;
        const msg = esc(`Couldn't load results from ESPN (${err.message})`);
        cells().forEach(td => { td.innerHTML = `<span class="ws-res-msg" title="${msg}">!</span>`; });
    });
}

// Games column cap: with more than WEEK_RESULTS_MAX games, drop wins over the lowest-rated
// opponents until it fits (losses are always kept, so a team with 3+ losses shows them all).
// Rating = the opponent's NET / BPI rank from quads-YEAR.json / net-YEAR.json (current, not at
// game time) when the season has one, else its AP rank at game time; unrated and non-D1
// opponents rate lowest. Ties drop the later game. Keeps date order.
const WEEK_RESULTS_MAX = 2;
function trimWeekGames(games, quadTeams) {
    if (games.length <= WEEK_RESULTS_MAX) return games;
    const rating = g => quadTeams?.[g.opp.key]?.rank ?? (quadTeams ? null : g.oppRank) ?? Infinity;
    const drop = new Set(games.map((g, i) => ({ g, i })).filter(x => x.g.result === "W")
        .sort((a, b) => rating(b.g) - rating(a.g) || b.i - a.i)
        .slice(0, games.length - WEEK_RESULTS_MAX).map(x => x.g));
    return games.filter(g => !drop.has(g));
}

// ── Stats › Week › Conference tab (2025+) ────────────────────────────────────
// One stats row per conference that received votes.
// Official ballots only. Points: rank 1 = 25 … rank 25 = 1 (same as Overall).

// Every number the Conference tab shows for one week, or {year, noData: true} before 2025.
function computeConferenceWeekStats(weekId) {
    const isApWeek = weekId.startsWith("week-ap-");
    const tabs = isApWeek ? getSortedApTabs() : getSortedTabs();
    const idx = tabs.findIndex(t => t.dataset.week === weekId);
    if (idx === -1) return null;
    const year = tabs[idx].dataset.year;
    const table = conferenceTable(year);
    if (!table) return { year, noData: true };

    const aliases = CONFERENCE_DATA.aliases || {};
    const confOfTeam = {};
    Object.entries(table).forEach(([c, ts]) => ts.forEach(t => { confOfTeam[t] = c; }));
    const confOf = t => confOfTeam[aliases[t] || t] || "Unmapped";

    const deltaData = buildDeltaData(true);
    const ballotsOf = wid => Object.entries(deltaData[wid] || {})
        .filter(([u]) => u !== "Official Overall" && u !== "AP Overall")
        .map(([, ts]) => ts.slice(0, 25));
    const ballots = ballotsOf(weekId);
    if (!ballots.length) return null;
    const pointsOf = bs => {
        const pts = {};
        bs.forEach(b => b.forEach((t, i) => { pts[t] = (pts[t] || 0) + (25 - i); }));
        return pts;
    };
    // Same order as Official Overall / the Stats tab (points desc, ties in ballot order)
    const orderOf = pts => Object.entries(pts).sort((a, b) => b[1] - a[1]).map(([t]) => t);

    const pts = pointsOf(ballots);
    const order = orderOf(pts);
    const rankOf = {};
    order.forEach((t, i) => { rankOf[t] = i + 1; });
    const totalPts = Object.values(pts).reduce((s, p) => s + p, 0);

    const prevTab = tabs[idx + 1];
    const prevBallots = prevTab && prevTab.dataset.year === year ? ballotsOf(prevTab.dataset.week) : [];
    const hasPrev = prevBallots.length > 0;
    const prevPts = hasPrev ? pointsOf(prevBallots) : {};
    const prevTotal = Object.values(prevPts).reduce((s, p) => s + p, 0);

    const groupStats = (label, isMember) => {
        const teams = order.filter(t => isMember(confOf(t)));
        const ranked = teams.filter(t => rankOf[t] <= 25);
        const gPts = teams.reduce((s, t) => s + pts[t], 0);
        const share = totalPts ? gPts / totalPts : 0;
        let prevShare = null;
        if (hasPrev) {
            const pPts = Object.entries(prevPts).filter(([t]) => isMember(confOf(t))).reduce((s, [, p]) => s + p, 0);
            prevShare = prevTotal ? pPts / prevTotal : 0;
        }
        return {
            label, teams,
            t25: ranked.length,
            pts: gPts, share, prevShare,
        };
    };

    const confs = Object.keys(table).map(c => groupStats(c, x => x === c));
    if (order.some(t => confOf(t) === "Unmapped")) confs.push(groupStats("Unmapped", x => x === "Unmapped"));
    const voted = confs.filter(c => c.pts > 0).sort((a, b) => b.pts - a.pts);
    return { year, voted, rankOf, totalVoters: ballots.length };
}

// The Conference tab's content as a DOM node.
function buildConferenceView(weekId) {
    const root = document.createElement("div");
    root.className = "conf-view";
    const stats = computeConferenceWeekStats(weekId);
    if (!stats) return null;
    if (stats.noData) {
        root.innerHTML = `<div class="conf-empty">Conference data starts with the 2025 season.</div>`;
        return root;
    }
    const pct = x => (x > 0 && x < 0.0005 ? "<0.1" : (x * 100).toFixed(1)) + "%";

    // ── Stats table ──────────────────────────────────────────────────────────
    const deltaSpan = (d, fmt = x => x) => {
        if (d === null) return "—";
        if (Math.abs(+fmt(Math.abs(d))) === 0) return `<span class="delta-same">—</span>`;
        return `<span class="${d > 0 ? "delta-up" : "delta-down"}">${d > 0 ? "+" : "−"}${fmt(Math.abs(d))}</span>`;
    };
    const row = g => `<tr>
            <td class="team-col">${g.label}</td>
            <td>${g.t25}</td>
            <td>${g.pts.toLocaleString()}</td>
            <td>${pct(g.share)}</td>
            <td>${g.prevShare === null ? "—" : deltaSpan((g.share - g.prevShare) * 100, x => x.toFixed(1))}</td>
            <td class="conf-teams">${g.teams.map(t => {
                const r = stats.rankOf[t];
                return `<span class="conf-team">${r <= 25 ? `<span class="conf-team-rank">${r}</span>` : ""}<img class="logo-sm team-logo records-logo" data-team="${t}" title="${formatTeamName(t)}${r <= 25 ? ` (#${r})` : ""}"></span>`;
            }).join("")}</td>
        </tr>`;
    const tbl = document.createElement("table");
    tbl.className = "conf-stats-table";
    tbl.innerHTML = `<colgroup><col style="width:130px"><col style="width:44px"><col style="width:64px"><col style="width:60px"><col style="width:48px"><col></colgroup><thead><tr>
        <th class="team-col">Conference</th>
        <th title="Teams in the Top 25">T25</th>
        <th title="Ballot points (#1 = 25 … #25 = 1)">Pts</th>
        <th title="Share of all points">Share</th>
        <th title="Share change (pp)">Δ</th>
        <th class="conf-teams" title="Teams with votes, by points (number = rank)">Teams</th>
    </tr></thead><tbody>
        ${stats.voted.map(row).join("")}
    </tbody>`;

    tbl.classList.add("conf-section");
    tbl.querySelectorAll(".conf-teams img").forEach(img =>
        img.addEventListener("click", () => toggleTeamHighlight(img.dataset.team)));
    root.append(tbl);
    return root;
}

function showAggregateSection() {
    // AP mode on index.html: operate on the current AP block
    if (_apCurrentYear && _apCurrentWeekNum) {
        const apBlock = document.getElementById(`week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`);
        if (!apBlock) return;
        const sections = apBlock.querySelectorAll(".ballot-section");
        if (!sections[2]) return;
        sections.forEach(s => s.style.display = "none");
        sections[2].style.display = "block";
        document.getElementById("toggle-text").innerText = "Associated Press Data";
        _deltaDataCache = null;
        injectApWeightedRankingRow(apBlock, `week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`, _apCurrentYear);
        bindVoterCells();
        bindTeamLogos();
        applyTableSort(currentSort);
        if (_outliersMode) applyOutliers(apBlock); else clearOutliers(apBlock);
        return;
    }
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const activeBlock = document.getElementById(activeTab.dataset.week);
    if (!activeBlock) return;
    const sections = activeBlock.querySelectorAll(".ballot-section");
    if (!sections[2]) return;
    sections.forEach(s => s.style.display = "none");
    sections[2].style.display = "block";
    document.getElementById("toggle-text").innerText = "Data Ballots";
    _deltaDataCache = null;
    if (ON_AP_PAGE) {
        injectApWeightedRankingRow(activeBlock, activeTab.dataset.week, activeTab.dataset.year);
    } else {
        injectWeightedRankingRow(activeTab, activeBlock);
    }
    bindVoterCells();
    bindTeamLogos();
    applyTableSort(currentSort);
    if (_outliersMode) applyOutliers(activeBlock); else clearOutliers(activeBlock);
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

// ─── Picker fitting ─────────────────────────────────────────
// Keeps the inline year/week pickers from extending past the right edge of the
// visible ballot table. Spacing and font shrink together, continuously, by just
// enough to fit — so the picker tracks the table edge smoothly as the window
// narrows. Past the floor it collapses to a window around the active item with "…".
const PICKER_FONT_MAX = 1.5, PICKER_FONT_MIN = 1.1;   // rem
const PICKER_GAP_MAX = 0.4, PICKER_GAP_MIN = 0.15;    // em

// t = 0 → full size, t = 1 → most condensed
function setPickerCondense(picker, t) {
    const font = PICKER_FONT_MAX - (PICKER_FONT_MAX - PICKER_FONT_MIN) * t;
    const gap = PICKER_GAP_MAX - (PICKER_GAP_MAX - PICKER_GAP_MIN) * t;
    picker.style.setProperty("--picker-font", font.toFixed(4) + "rem");
    picker.style.setProperty("--picker-gap", gap.toFixed(4) + "em");
}

function pickerLimitRight() {
    let right = 0;
    document.querySelectorAll(".week-block .table-container table").forEach(t => {
        if (t.offsetParent === null) return;
        right = Math.max(right, t.getBoundingClientRect().right);
    });
    return right;
}

function headerContentRight() {
    let right = 0;
    document.querySelectorAll(".header h1 #toggle-text, .header h1 #year-text, .header h1 #week-text, .header h1 .picker-btn")
        .forEach(el => { right = Math.max(right, el.getBoundingClientRect().right); });
    return right;
}

function pickerButtons(picker) {
    return Array.from(picker.querySelectorAll(".picker-btn:not(.picker-ellipsis)"));
}

function renderPickerWindow(picker, center, r) {
    picker.querySelectorAll(".picker-ellipsis").forEach(b => b.remove());
    const btns = pickerButtons(picker);
    const n = btns.length;
    const w = 2 * r + 1;
    if (n <= w + 2) { btns.forEach(b => b.style.display = ""); return; }
    let start = Math.max(1, Math.min(center - r, n - 1 - w));
    let end = start + w - 1;
    // An ellipsis standing in for a single item is pointless — show the item instead
    if (start === 2) start = 1;
    if (end === n - 3) end = n - 2;
    btns.forEach((b, i) => {
        b.style.display = (i === 0 || i === n - 1 || (i >= start && i <= end)) ? "" : "none";
    });
    const makeEllipsis = dir => {
        const el = document.createElement("button");
        el.className = "picker-btn picker-ellipsis";
        el.textContent = "…";
        el.title = dir < 0 ? "Earlier" : "Later";
        el.addEventListener("click", e => {
            e.stopPropagation();
            picker._center = Math.max(0, Math.min(n - 1, picker._center + dir * w));
            renderPickerWindow(picker, picker._center, picker._radius);
            _pickerObserver.takeRecords();
        });
        return el;
    };
    if (start > 1) picker.insertBefore(makeEllipsis(-1), btns[start]);
    if (end < n - 2) picker.insertBefore(makeEllipsis(1), btns[n - 1]);
}

function fitPicker(picker) {
    picker.querySelectorAll(".picker-ellipsis").forEach(b => b.remove());
    const btns = pickerButtons(picker);
    btns.forEach(b => b.style.display = "");
    picker.style.removeProperty("--picker-font");
    picker.style.removeProperty("--picker-gap");
    if (!picker.classList.contains("open") || !btns.length) return;

    const limit = pickerLimitRight();
    if (!limit) return;
    const fits = () => headerContentRight() <= limit + 0.5;
    if (fits()) return;

    // 1. Condense continuously: binary-search the smallest amount that fits
    setPickerCondense(picker, 1);
    if (fits()) {
        let lo = 0, hi = 1;
        for (let i = 0; i < 12; i++) {
            const mid = (lo + hi) / 2;
            setPickerCondense(picker, mid);
            if (fits()) hi = mid; else lo = mid;
        }
        setPickerCondense(picker, hi);
        return;
    }

    // 2. Still too wide at the floor — collapse to a window around the active item
    const active = btns.findIndex(b => b.style.textDecoration === "underline");
    picker._center = active >= 0 ? active : btns.length - 1;
    for (let r = Math.ceil(btns.length / 2); r >= 0; r--) {
        picker._radius = r;
        renderPickerWindow(picker, picker._center, r);
        if (fits()) return;
    }
}

function refitOpenPickers() {
    ["year-picker", "week-picker"].forEach(id => {
        const picker = document.getElementById(id);
        if (picker) fitPicker(picker);
    });
    _pickerObserver.takeRecords(); // discard mutations made by fitting itself
}

// Refit whenever a picker opens/closes or is rebuilt, or the header text changes
// (week/year switch, Official/Provisional/AP toggle).
const _pickerObserver = new MutationObserver(refitOpenPickers);
["year-picker", "week-picker"].forEach(id => {
    const el = document.getElementById(id);
    if (el) _pickerObserver.observe(el, { attributes: true, attributeFilter: ["class"], childList: true });
});
["toggle-text", "year-text", "week-text"].forEach(id => {
    const el = document.getElementById(id);
    if (el) _pickerObserver.observe(el, { childList: true, characterData: true, subtree: true });
});
let _pickerResizeRaf = 0;
window.addEventListener("resize", () => {
    cancelAnimationFrame(_pickerResizeRaf);
    _pickerResizeRaf = requestAnimationFrame(refitOpenPickers);
});

// Keep open sort pickers pinned to their header cell. The picker is
// position:fixed on <body> and its toggle is hidden, so track the toggle's
// <th> (sticky) using the offset recorded when it opened. Runs on scroll and
// every frame while a picker is open, so it also follows the table when the
// layout above it shifts (e.g. the Changes toolbar appearing/disappearing).
function pinOpenSortPickers() {
    const open = document.querySelectorAll(".sort-picker.open");
    open.forEach(p => {
        const th = p._toggle && p._toggle.closest("th");
        if (!th || !th.isConnected) return;
        const top = (th.getBoundingClientRect().top + (p._thOffsetY || 0)) + "px";
        const left = (th.closest("table") || th).getBoundingClientRect().left + "px";
        if (p.style.top !== top) p.style.top = top;
        if (p.style.left !== left) p.style.left = left;
    });
    return open.length > 0;
}
let _sortPickerTrackRaf = 0;
function trackOpenSortPickers() {
    if (_sortPickerTrackRaf) return;
    const tick = () => {
        _sortPickerTrackRaf = pinOpenSortPickers() ? requestAnimationFrame(tick) : 0;
    };
    _sortPickerTrackRaf = requestAnimationFrame(tick);
}
document.addEventListener("scroll", pinOpenSortPickers, { passive: true });

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

function loadImageQueue(queue) {
    if (queue.length === 0) return Promise.resolve();
    // Safari: no per-img loads to throttle (see "CSS logos"), just chunked assignment.
    if (CSS_LOGOS) return assignBallotLogos(queue);
    return new Promise(resolve => {
        let index = 0;
        const CONCURRENCY = 16;
        let active = 0;
        let resolved = false;
        function loadNext() {
            while (active < CONCURRENCY && index < queue.length) {
                while (index < queue.length && !queue[index].dataset.src) index++;
                if (index >= queue.length) break;
                const img = queue[index++];
                active++;
                const team = img.dataset.src;
                setLogoSrc(img, team);
                img.removeAttribute("data-src");
                const onDone = () => {
                    active--;
                    loadNext();
                };
                img.addEventListener("load", onDone, { once: true });
                img.addEventListener("error", onDone, { once: true });
            }
            if (active === 0 && !resolved) { resolved = true; resolve(); }
        }
        loadNext();
    });
}

function backgroundLoad() {
    // Load images for the current year (already in DOM) only.
    // Prior-year fragments are loaded on demand when the user navigates to them.
    // Eagerly preloading all fragments caused a ~30s DOM explosion that trashed
    // all three caches and stalled the main thread.
    const queue = getBackgroundImageQueue();
    if (queue.length > 0) {
        setTimeout(() => loadImageQueue(queue), 1000);
    }
}

// Save as PNG lays a long table out as side-by-side panels so the image is
// roughly screen-shaped (Reddit/Discord shrink tall images until logos are
// unreadable). Each panel repeats the rank header and, if shown, the Overall row.
const PNG_TARGET_ASPECT = 16 / 9;
const PNG_MAX_PANELS = 4;
const PNG_PANEL_GAP = 16;       // between panels, and as the image's right margin
// Capture scale: as sharp as possible while keeping the canvas under Safari's
// 16.7 MP limit (also keeps the PNG small enough for Discord/Reddit uploads).
const PNG_MAX_PIXELS = 16e6;
const PNG_MIN_SCALE = 2;
const PNG_MAX_SCALE = 4;

// Width the voter-name column needs in the image: the widest visible flair +
// name (veteran tags and hover buttons are hidden in the image), plus the
// sort label when it is shown. Never wider than the column already is.
function pngNameColumnWidth(table, rowIdx) {
    const rows = table.tBodies[0].rows;
    const firstTh = table.tHead?.rows[0]?.cells[0];
    const current = parseFloat(getComputedStyle(firstTh || rows[0].cells[0]).width);
    let max = 0;
    // Measure text and image boxes directly: veteran tags sit inside the name
    // span, and a range's box isn't clipped by the cell's overflow.
    // Consensus-sort distances are dropped from the image (preparePngClone).
    const skip = ".veteran-tag, .pin-btn, .history-btn, .ballot-link-btn, .consensus-dist";
    const range = document.createRange();
    const measure = (cell, root) => {
        const left = cell.getBoundingClientRect().left + parseFloat(getComputedStyle(cell).paddingLeft);
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
        for (let n = walker.currentNode; n; n = walker.nextNode()) {
            let r;
            if (n.nodeType === Node.TEXT_NODE) {
                if (!n.textContent.trim() || n.parentElement.closest(skip)) continue;
                range.selectNodeContents(n);
                r = range.getBoundingClientRect();
            } else if (n.tagName === "IMG" && !n.closest(skip)) {
                r = n.getBoundingClientRect();
            } else continue;
            if (r.width) max = Math.max(max, r.right - left);
        }
    };
    rowIdx.forEach(i => {
        const cell = rows[i].cells[0];
        const vc = cell.querySelector(".voter-cell");
        if (vc) measure(cell, vc);
    });
    const label = firstTh?.querySelector(".voters-toggle");
    if (label && label.textContent.trim() !== SORT_LABELS.alphabetic) measure(firstTh, label);
    return { current, width: max ? Math.min(current, Math.ceil(max) + 2) : current };
}

// Measure the live table and pick the panel count whose image aspect ratio is
// closest to PNG_TARGET_ASPECT. Rows are given as tbody indices so the same
// split can be applied to html2canvas's structurally identical clone.
function pngPanelPlan(table) {
    const rows = Array.from(table.tBodies[0]?.rows || []);
    const repeat = [], body = [];
    let bodyHeight = 0;
    rows.forEach((r, i) => {
        if (r.offsetParent === null) return; // hidden row
        if (r.classList.contains("overall-row")) repeat.push(i);
        else { body.push(i); bodyHeight += r.offsetHeight; }
    });
    const nameCol = rows.length ? pngNameColumnWidth(table, repeat.concat(body)) : { current: 0, width: 0 };
    const tableWidth = table.offsetWidth - (nameCol.current - nameCol.width);
    const fixedHeight = (table.tHead?.offsetHeight || 0) +
        repeat.reduce((h, i) => h + rows[i].offsetHeight, 0);
    const rowHeight = body.length ? bodyHeight / body.length : 1;
    const size = n => ({
        w: n * tableWidth + n * PNG_PANEL_GAP, // gaps between panels + right margin
        h: fixedHeight + Math.ceil(body.length / n) * rowHeight,
    });
    let panels = 1, best = Infinity;
    for (let n = 1; n <= Math.min(PNG_MAX_PANELS, body.length); n++) {
        const { w, h } = size(n);
        const miss = Math.abs(Math.log((w / h) / PNG_TARGET_ASPECT));
        if (miss < best) { best = miss; panels = n; }
    }
    const { w, h } = size(panels);
    const fit = Math.floor(Math.sqrt(PNG_MAX_PIXELS / (w * h)) * 4) / 4;
    const scale = Math.max(PNG_MIN_SCALE, Math.min(PNG_MAX_SCALE, fit));
    return { panels, repeat, body, nameWidth: nameCol.width, width: w, scale };
}

// Downscale an image to w×h by repeated halving with high-quality smoothing.
// html2canvas draws a 500 px logo straight into a ~50 px box, which aliases
// ("grainy" logos); handing it a pre-resampled copy at the exact pixel size avoids that.
function resampleImage(img, w, h) {
    let src = img, cw = img.naturalWidth, ch = img.naturalHeight;
    const step = (nw, nh) => {
        const c = document.createElement("canvas");
        c.width = nw; c.height = nh;
        const ctx = c.getContext("2d");
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(src, 0, 0, nw, nh);
        src = c; cw = nw; ch = nh;
    };
    while (cw / 2 >= w && ch / 2 >= h) step(Math.round(cw / 2), Math.round(ch / 2));
    step(w, h);
    return src.toDataURL("image/png");
}

// src → resampled data URL for every loaded logo in the table, at its displayed
// size × scale. Logos that fail (e.g. tainted canvas) keep their original src.
function pngSharpLogos(table, scale) {
    const out = new Map();
    table.querySelectorAll("img.logo").forEach(img => {
        const src = img.currentSrc || img.src;
        if (!src || out.has(src) || !img.complete || !img.naturalWidth || !img.offsetWidth) return;
        try {
            out.set(src, resampleImage(img, Math.round(img.offsetWidth * scale), Math.round(img.offsetHeight * scale)));
        } catch (e) { /* leave as is */ }
    });
    return out;
}

// onclone step: size the capture to the content, narrow the name column, swap
// in the resampled logos, and replace the table with plan.panels tables in a row.
function preparePngClone(doc, plan, logos) {
    const container = doc.querySelector("[data-png-target]");
    const table = container?.querySelector("table");
    if (!table || !table.tBodies[0]) return;
    // Let the panels overflow the page width instead of being clipped/squeezed,
    // and capture only the content plus a right margin.
    const scroll = container.closest(".table-scroll");
    if (scroll) scroll.style.overflow = "visible";
    container.style.width = "max-content";
    container.style.paddingRight = `${PNG_PANEL_GAP}px`;
    // Positioned for the on-screen table; wrong once the columns move.
    container.querySelectorAll(".avg-rank-line").forEach(el => el.remove());
    // Consensus-sort distances: the row order already shows the sort, and
    // dropping them lets the name column shrink.
    container.querySelectorAll(".consensus-dist").forEach(el => el.remove());
    const nw = `${plan.nameWidth}px`;
    const style = doc.createElement("style");
    style.textContent = `[data-png-target] th:first-child, [data-png-target] td:first-child { width: ${nw} !important; min-width: ${nw} !important; max-width: ${nw} !important; }`;
    doc.head.appendChild(style);
    // html2canvas reads each image's naturalWidth/currentSrc, which stay 0/old
    // until the new src decodes, so the caller must wait for these loads.
    const loads = [];
    container.querySelectorAll("img.logo").forEach(img => {
        const sharp = logos.get(img.currentSrc || img.src);
        if (!sharp) return;
        img.removeAttribute("srcset");
        img.src = sharp;
        loads.push(img.decode().catch(() => {}));
    });
    splitPngTable(doc, table, plan);
    return Promise.all(loads);
}

function splitPngTable(doc, table, plan) {
    if (plan.panels < 2) return;
    const rows = Array.from(table.tBodies[0].rows);
    const perPanel = Math.ceil(plan.body.length / plan.panels);
    const wrap = doc.createElement("div");
    wrap.style.cssText = `display:flex;align-items:flex-start;gap:${PNG_PANEL_GAP}px`;
    for (let p = 0; p < plan.panels; p++) {
        const panel = table.cloneNode(false);
        panel.style.minWidth = "0";
        const head = table.tHead.cloneNode(true);
        head.querySelectorAll("th").forEach(th => { th.style.position = "static"; });
        // Only the first panel keeps the Functions/sort label.
        if (p > 0) head.querySelectorAll(".voters-toggle").forEach(el => { el.style.visibility = "hidden"; });
        const tbody = doc.createElement("tbody");
        plan.repeat.forEach(i => tbody.appendChild(rows[i].cloneNode(true)));
        plan.body.slice(p * perPanel, (p + 1) * perPanel).forEach(i => tbody.appendChild(rows[i]));
        panel.append(head, tbody);
        wrap.appendChild(panel);
    }
    table.replaceWith(wrap);
}

// Save table as PNG (Shift+P)
function saveTableAsPng() {
    // In AP mode on index.html the visible table lives in the AP block, not the
    // active userpoll tab's block (which is hidden while AP mode is on).
    const inApMode = _apCurrentYear !== null;
    const tab = inApMode
        ? document.querySelector(`.week-tab[data-poll="ap"][data-year="${_apCurrentYear}"][data-weeknum="${_apCurrentWeekNum}"]`)
        : document.querySelector(".week-tab.active");
    const blockId = inApMode ? `week-ap-${_apCurrentYear}-${_apCurrentWeekNum}` : tab?.dataset.week;
    const block = blockId ? document.getElementById(blockId) : null;
    if (!block) return;
    const section = block.querySelector(".ballot-section[style*='block'], .ballot-section:not([style])");
    const table = section ? section.querySelector("table") : null;
    if (!table) return;
    const container = table.closest(".table-container") || table;
    const plan = pngPanelPlan(table);
    container.dataset.pngTarget = "1";
    // CSS logos (Safari) have no src for html2canvas or resampling: give them one first.
    let logos;
    Promise.all([loadHtml2canvas(), materializeCssLogos(table)]).then(() => {
        logos = pngSharpLogos(table, plan.scale);
    }).then(() => html2canvas(container, {
        useCORS: true,
        scale: plan.scale,
        // The clone's iframe must be wide enough to lay the panels out side by side.
        windowWidth: Math.max(window.innerWidth, plan.width + 100),
        // Even rows are transparent; html2canvas fills those with white by default,
        // which leaves dark-mode text unreadable. Use the page background instead.
        backgroundColor: getComputedStyle(document.body).backgroundColor,
        // Edit only the clone: hide veteran tags, blank the header's default
        // "Functions" label (other sort labels stay, so the image says how it's sorted),
        // and drop the hover state so the row under the cursor doesn't show its
        // pin/history buttons.
        onclone: doc => {
            doc.body.classList.add("hide-veteran-tags");
            doc.querySelectorAll(".voters-toggle").forEach(el => {
                if (el.textContent.trim() === SORT_LABELS.alphabetic) el.style.visibility = "hidden";
            });
            doc.querySelectorAll(".voter-cell-hover").forEach(el => el.classList.remove("voter-cell-hover"));
            return preparePngClone(doc, plan, logos);
        },
    })).finally(() => {
        delete container.dataset.pngTarget;
    }).then(canvas => {
        const link = document.createElement("a");
        const week = tab ? (weekTextLabel(tab) || padWeekNum(displayWeekNum(tab))) : _apCurrentWeekNum;
        const year = tab ? tab.dataset.year : _apCurrentYear;
        const toggleText = document.getElementById("toggle-text").innerText;
        const isAp = inApMode || ON_AP_PAGE;
        const label = isAp
            ? (toggleText.includes("Data") ? "data" : "ballots")
            : (toggleText.includes("Provisional") ? "provisional" : "official");
        link.download = `${isAp ? "ap" : "cbb-poll"}-${year}-week${week}-${label}.png`;
        link.href = canvas.toDataURL("image/png");
        link.click();
    }).catch(e => console.error("Save as PNG failed:", e));
}

// html2canvas (~200 KB) is only needed for Save as PNG, so fetch it on first
// use instead of blocking page load with a <script> tag.
let _html2canvasPromise = null;
function loadHtml2canvas() {
    if (typeof html2canvas !== "undefined") return Promise.resolve();
    if (!_html2canvasPromise) {
        _html2canvasPromise = new Promise((resolve, reject) => {
            const s = document.createElement("script");
            s.src = "https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js";
            s.onload = resolve;
            s.onerror = () => { _html2canvasPromise = null; reject(new Error("html2canvas failed to load")); };
            document.head.appendChild(s);
        });
    }
    return _html2canvasPromise;
}

// Delta feature

function buildLeaderboardData() {
    if (_leaderboardDataCache) return _leaderboardDataCache;
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
    _leaderboardDataCache = data;
    return data;
}

// officialOnly = true always reads official ballots (for aggregate calculations, which
// provisional ballots must never affect); otherwise follows the Official/Provisional toggle
// (for per-voter deltas, so provisional voters' rows can show their own changes).
function buildDeltaData(officialOnly = false) {
    if (officialOnly) {
        if (_officialDeltaDataCache === null) _officialDeltaDataCache = _readDeltaData(false);
        return _officialDeltaDataCache;
    }
    const isProvisional = document.getElementById("toggle-text")?.innerText === "Provisional Ballots";
    if (_deltaDataCache !== null && _deltaDataCacheIsProvisional === isProvisional) return _deltaDataCache;
    _deltaDataCache = _readDeltaData(isProvisional);
    _deltaDataCacheIsProvisional = isProvisional;
    return _deltaDataCache;
}

function _readDeltaData(isProvisional) {
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


function applyDeltaToRow(row, weekId, deltaData, allTabsSorted) {
    // buildDeltaData() indexes every block's aggregate row as "Official Overall"
    const username = row.classList.contains("overall-row") ? "Official Overall" : getVoterName(row);
    if (!username) return;
    // AP blocks on index.html (week-ap-*) live outside the userpoll tab list
    if (weekId.startsWith("week-ap-")) allTabsSorted = getSortedApTabs();
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
    // No earlier ballot this season: no movement labels, but consensus/points still apply.

    // Overall row: its consensus label shows the team's points from this week's
    // official ballots (25 for #1 … 1 for #25) instead of a consensus diff.
    let overallPts = null;
    if (row.classList.contains("overall-row")) {
        overallPts = {};
        const officialSection = row.closest(".week-block")?.querySelectorAll(".ballot-section")[0];
        officialSection?.querySelectorAll(".voter-row:not(.row-weighted-ranking)").forEach(r => {
            Array.from(r.querySelectorAll(".team-logo")).slice(0, 25).forEach((img, i) => {
                const t = img.dataset.team;
                overallPts[t] = (overallPts[t] || 0) + (25 - i);
            });
        });
    }
    const isAggSection = row.closest(".ballot-section")?.id?.endsWith("-aggregate");
    const consensusTeams = deltaData[weekId]?.["Official Overall"] || [];
    // Outlier stats for this row's section: outlier diffs keep full green/red, others are lighter.
    const rowSection = row.closest(".ballot-section");
    const teamStats = !overallPts && !isAggSection && rowSection ? sectionTeamStats(rowSection) : null;

    const logos = row.querySelectorAll(".team-logo");
    logos.forEach((logo, idx) => {
        const team = logo.dataset.team;
        const wrapper = logo.closest("td");
        if (!wrapper) return;

        wrapper.querySelector(".delta-label")?.remove();
        wrapper.querySelector(".avg-label")?.remove();

        // Movement label (under the logo; shown in Movement mode and for rows opened in Off)
        if (prevTeams) {
            const prevIdx2 = prevTeams.indexOf(team);
            const label = document.createElement("span");
            label.className = "delta-label";
            // Unranked last period counts as coming from #26
            const effectivePrev = prevIdx2 === -1 ? 25 : prevIdx2; // 0-indexed, so 25 = rank 26
            setDeltaLabel(label, effectivePrev - idx);
            logo.after(label);
        }

        // Consensus label (vs Consensus mode): points on the Overall row, none in Data Ballots
        const avgLabel = document.createElement("span");
        avgLabel.className = "avg-label";
        if (overallPts) {
            avgLabel.textContent = String(overallPts[team] || 0);
            avgLabel.title = "Overall points";
        } else if (isAggSection) {
            return;
        } else {
            // Unranked by consensus counts as #26 (0-indexed 25), same as the outlier tags
            const foundIdx = consensusTeams.indexOf(team);
            const consensusIdx = foundIdx === -1 ? 25 : foundIdx;
            // + = this voter ranks the team higher than the consensus does
            const diff = consensusIdx - idx;
            avgLabel.textContent = diff > 0 ? "+" + diff : diff < 0 ? "−" + -diff : "";
            if (diff > 0) avgLabel.classList.add("cons-hi");
            else if (diff < 0) avgLabel.classList.add("cons-lo");
            if (diff !== 0 && Math.abs(diff) <= 3) avgLabel.classList.add("delta-small");  // vs Consensus grays 1–3 (Movement: 1–4)
            else if (teamStats && outlierKind(idx + 1, consensusIdx + 1, teamStats[team])) avgLabel.classList.add("cons-outlier");
            if (foundIdx === -1) avgLabel.title = "Unranked by consensus (counted as #26)";
        }
        wrapper.appendChild(avgLabel);
    });
}

// Default is Records. The Stats tab (per-team season table) is kept but nothing opens it:
// its title tab is hidden and every entry point uses the default; call with "stats" to reach it.
function showSeasonStatsModal(mode = "records") {
    // Voters tab is PIN-locked (same PIN and daily unlock as the locked keybinds).
    // While locked it does nothing; the PIN is only entered via Settings › Dev.
    if (mode === "voters" && !isKeybindsUnlocked()) return;
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const currentYear = _apCurrentYear !== null ? _apCurrentYear : activeTab.dataset.year;

    const isApMode = _apCurrentYear !== null;
    const allTabs = isApMode ? getSortedApTabs() : getSortedTabs();
    const yearTabs = allTabs.filter(t => t.dataset.year === currentYear).reverse();
    if (yearTabs.length === 0) return;

    if (mode === "records") {
        showSeasonRecords(currentYear, isApMode, activeTab);
        return;
    }

    const totalWeeks = yearTabs.length;

    // Accumulate per-team stats from official ballot sections only
    const teamTotalPts = {};
    const teamRankSum = {};
    const teamVoterWeeks = {};  // voter-ballot appearances where team was ranked
    let totalVoterWeekSlots = 0; // total (voter × week) slots across all weeks
    const teamWeeksRanked = {}; // distinct weeks the team appeared in any ballot
    const teamBestRank = {};
    const teamBestConsensusRank = {};  // best (lowest #) consensus rank across weeks
    const teamWorstConsensusRank = {}; // worst (highest #) consensus rank across weeks
    const weekBallots = []; // per week: [{voter, ranks: {team: rank}}] for supporter/hater calc

    yearTabs.forEach(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        if (!block) return;
        const sections = block.querySelectorAll(".ballot-section");
        const officialSection = sections[0];
        if (!officialSection) return;

        const seenThisWeek = new Set();
        let weekVoterCount = 0;
        const ballotsThisWeek = [];
        officialSection.querySelectorAll(".voter-row").forEach(row => {
            const voterName = getVoterName(row);
            const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
            if (voterName && voterName !== "Official Overall" && voterName !== "AP Overall" && voterName !== "Recency"
                && !row.classList.contains("row-weighted-ranking")) {
                const ranks = {};
                teams.slice(0, 25).forEach((team, i) => { if (team) ranks[team] = i + 1; });
                const flair = row.querySelector(".voter-cell img.logo:not(.team-logo)")?.dataset.team || null;
                ballotsThisWeek.push({ voter: voterName, ranks, flair, teams });
            }
            if (voterName === "Official Overall") {
                // Track best/worst consensus rank from the weekly aggregate (userpoll mode)
                teams.slice(0, 25).forEach((team, i) => {
                    const rank = i + 1;
                    if (!teamBestConsensusRank[team] || rank < teamBestConsensusRank[team]) teamBestConsensusRank[team] = rank;
                    if (!teamWorstConsensusRank[team] || rank > teamWorstConsensusRank[team]) teamWorstConsensusRank[team] = rank;
                });
                return;
            }
            weekVoterCount++;
            teams.slice(0, 25).forEach((team, i) => {
                const rank = i + 1;
                teamTotalPts[team] = (teamTotalPts[team] || 0) + (25 - i);
                teamRankSum[team] = (teamRankSum[team] || 0) + rank;
                teamVoterWeeks[team] = (teamVoterWeeks[team] || 0) + 1;
                seenThisWeek.add(team);
                if (!teamBestRank[team] || rank < teamBestRank[team]) teamBestRank[team] = rank;
            });
        });
        totalVoterWeekSlots += weekVoterCount;
        weekBallots.push({ ballots: ballotsThisWeek, teams: seenThisWeek, consensusOrder: renderedConsensusOrder(sections) });
        seenThisWeek.forEach(team => {
            teamWeeksRanked[team] = (teamWeeksRanked[team] || 0) + 1;
        });
        // Track consensus ranks from the aggregate section (sections[2])
        if (sections[2]) {
            const aggRow = sections[2].querySelector(".voter-row");
            if (aggRow) {
                Array.from(aggRow.querySelectorAll(".team-logo")).map(img => img.dataset.team)
                    .slice(0, 25).forEach((team, i) => {
                        const rank = i + 1;
                        if (!teamBestConsensusRank[team] || rank < teamBestConsensusRank[team]) teamBestConsensusRank[team] = rank;
                        if (!teamWorstConsensusRank[team] || rank > teamWorstConsensusRank[team]) teamWorstConsensusRank[team] = rank;
                    });
            }
        }
    });

    // Sort by total season points descending
    const allTeams = Object.keys(teamTotalPts).sort((a, b) => teamTotalPts[b] - teamTotalPts[a]);

    // #1 supporter / hater: voter whose rank of a team deviates most from that week's
    // consensus average (unranked = 26), averaged over the weeks the voter voted and the team
    // appeared on any ballot. Voters must have voted in at least 16 weeks
    // (capped at the weeks played so far, so in-progress seasons still qualify someone).
    const voterWeeksVoted = {};
    const devSum = {};   // devSum[team][voter] = Σ (consensusAvg − voterRank); positive = supporter
    const devCount = {};
    weekBallots.forEach(({ ballots, teams }) => {
        const n = ballots.length;
        if (n === 0) return;
        ballots.forEach(b => { voterWeeksVoted[b.voter] = (voterWeeksVoted[b.voter] || 0) + 1; });
        teams.forEach(team => {
            let sum = 0;
            ballots.forEach(b => { sum += b.ranks[team] || 26; });
            const avg = sum / n;
            const ds = devSum[team] || (devSum[team] = {});
            const dc = devCount[team] || (devCount[team] = {});
            ballots.forEach(b => {
                ds[b.voter] = (ds[b.voter] || 0) + (avg - (b.ranks[team] || 26));
                dc[b.voter] = (dc[b.voter] || 0) + 1;
            });
        });
    });
    const MIN_FAN_WEEKS = 16;
    const minWeeksVoted = Math.max(1, Math.min(MIN_FAN_WEEKS, weekBallots.filter(w => w.ballots.length).length));
    const teamSupporter = {};
    const teamHater = {};
    const TIE_EPS = 1e-9;
    const byName = (a, b) => a.localeCompare(b, undefined, { sensitivity: "base" });
    allTeams.forEach(team => {
        const ds = devSum[team] || {};
        // Collect every voter tied for the extreme (float epsilon), alphabetized.
        // Prefer voters meeting the participation minimum; if none of them deviate in the
        // needed direction (e.g. only low-participation voters ever ranked the team),
        // fall back to all voters and flag the result as low-sample.
        const pick = (qualifiedOnly) => {
            let best = null, worst = null;
            Object.keys(ds).forEach(voter => {
                if (qualifiedOnly && voterWeeksVoted[voter] < minWeeksVoted) return;
                const d = ds[voter] / devCount[team][voter];
                if (!best || d > best.d + TIE_EPS) best = { d, voters: [voter] };
                else if (Math.abs(d - best.d) <= TIE_EPS) best.voters.push(voter);
                if (!worst || d < worst.d - TIE_EPS) worst = { d, voters: [voter] };
                else if (Math.abs(d - worst.d) <= TIE_EPS) worst.voters.push(voter);
            });
            return { best, worst };
        };
        const finish = (f, lowSample) => {
            f.voters.sort(byName);
            f.lowSample = lowSample;
            return f;
        };
        const q = pick(true);
        let all = null;
        if (q.best && q.best.d > 0) teamSupporter[team] = finish(q.best, false);
        else if ((all = all || pick(false)).best && all.best.d > 0) teamSupporter[team] = finish(all.best, true);
        if (q.worst && q.worst.d < 0) teamHater[team] = finish(q.worst, false);
        else if ((all = all || pick(false)).worst && all.worst.d < 0) teamHater[team] = finish(all.worst, true);
    });
    const esc = str => String(str).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const FAN_TIE_MAX = 5; // more tied voters than this → "Too Many"
    const fmtFan = f => {
        if (!f) return "—";
        const dev = `<span class="fan-dev">${f.d > 0 ? "+" : "−"}${Math.abs(f.d).toFixed(1)}</span>`;
        const n = f.voters.length;
        const tips = [];
        if (n > FAN_TIE_MAX) tips.push(`${n} voters tied`);
        else if (n > 1) tips.push(`Tied:&#10;${f.voters.slice(1).map(esc).join("&#10;")}`);
        const label = n > FAN_TIE_MAX ? "Too Many" : esc(f.voters[0]);
        const cls = "fan-name" + (tips.length ? " fan-tie" : "") + (f.lowSample ? " fan-low-sample" : "");
        const title = tips.length ? ` title="${tips.join("&#10;&#10;")}"` : "";
        return `<span class="${cls}"${title}>${label}</span> ${dev}`;
    };

    const modal = document.getElementById("season-stats-modal");
    const title = document.getElementById("season-stats-title");
    const table = document.getElementById("season-stats-table");

    title.innerHTML = seasonModalTitleHtml(currentYear, isApMode, mode);
    table.classList.toggle("season-voters", mode === "voters");
    table.classList.remove("season-records");
    table.classList.remove("season-mmp12");

    if (mode === "voters") {
        table.innerHTML = buildSeasonVotersTableHtml(weekBallots, voterWeeksVoted, minWeeksVoted, totalWeeks, esc);
        modal.classList.add("open");
        return;
    }

    let html = `<colgroup>
        <col style="width:24px">
        <col style="width:26px">
        <col>
        <col style="width:52px">
        <col style="width:44px">
        <col style="width:60px">
        <col style="width:36px">
        <col>
        <col>
    </colgroup><thead><tr>
        <th>#</th><th></th>
        <th class="team-col">Team</th>
        <th>Weeks</th>
        <th>Pts</th>
        <th>Avg Rank</th>
        <th>Best</th>
        <th class="fan-col">#1 Supporter</th>
        <th class="fan-col">#1 Hater</th>
    </tr></thead><tbody>`;

    allTeams.forEach((team, i) => {
        const unrankedSlots = totalVoterWeekSlots - (teamVoterWeeks[team] || 0);
        const avgRank = ((teamRankSum[team] + unrankedSlots * 26) / totalVoterWeekSlots).toFixed(2);
        html += `<tr>
            <td>${i + 1}</td>
            <td><img class="logo-sm" src="${logoSrc(team)}"></td>
            <td class="team-col">${formatTeamName(team)}</td>
            <td>${teamWeeksRanked[team]}/${totalWeeks}</td>
            <td>${teamTotalPts[team]}</td>
            <td>${avgRank}</td>
            <td>${teamBestConsensusRank[team] || "—"}</td>
            <td class="fan-col">${fmtFan(teamSupporter[team])}</td>
            <td class="fan-col">${i < 50 ? fmtFan(teamHater[team]) : "—"}</td>
        </tr>`;
    });

    html += `</tbody>`;
    table.innerHTML = html;
    modal.classList.add("open");
}

// Year window title: "YEAR Season — Records Voters", tabs styled like the Week
// window's Stats / Conference. Voters is hidden: its tab only shows while it's open
// (reached by Shift+W, PIN-locked).
function seasonModalTitleHtml(currentYear, isApMode, mode) {
    const modeTabs = [
        { key: "stats", label: "Stats", hidden: true },  // unused; kept for showSeasonStatsModal("stats")
        { key: "records", label: "Records" },
        { key: "voters", label: "Voters", hidden: mode !== "voters" },
    ].filter(m => !m.hidden).map(m =>
        `<span class="modal-mode-tab${mode === m.key ? " active" : ""}"
               onclick="showSeasonStatsModal('${m.key}')">${m.label}</span>`
    ).join("");
    return `${currentYear}${isApMode ? " AP" : ""} Season — ${modeTabs}`;
}

// ── ESPN data layer ─────────────────────────────────────────────────────────
// Live team data from ESPN's public, undocumented site APIs (no key; CORS open, so the
// browser calls them directly). Anything that needs W-L records or game results should
// go through these helpers rather than fetching ESPN itself: they share one cache, map
// ESPN IDs to our team names, and keep the last good data if a refresh fails.
//
//   espnIdFor(team)              our team name (data-src / conferences.py key, aliases ok) → ESPN id | null
//   espnTeamKey(id)              ESPN id → our canonical team name | null
//   espnLogoUrl(id)              ESPN CDN logo (fallback when we have no logo file)
//   fetchSeasonRecords(season)   → {byId: {id: {id, name, conf, wins, losses, pct, confRecord,
//                                   home, road, streak}}, confs: [{name, ids}], at, stale?}
//                                   One request for every D1 team (~6 MB raw, ~170 KB gzipped).
//                                   Overall records incl. non-D1 and postseason games.
//   fetchTeamSchedule(id, season) → {games: [game], at, stale?}; game = {id, date (ISO), site:
//                                   "H"|"A"|"N", opp: {id, name, key, logo}, oppRank (AP rank
//                                   at game time, regular season only, or null), oppSeed
//                                   (tournament seed, postseason only), us, them, result:
//                                   "W"|"L"|null, state: "pre"|"in"|"post", status, postseason,
//                                   note (e.g. "SEC Tournament - Final")}. Two requests
//                                   (seasontype=2 regular season incl. conference tournaments,
//                                   seasontype=3 NCAA/NIT/etc.), sorted by date.
//   recordAsOf(games, date)      W-L from completed games before `date` (Date or ISO string)
//   summarizeGames(games, ctx)   splits: overall, home, away, neutral, conf, vsTop25, nonD1, D1
//   fetchScoreboardDay(day)      → {games: [{id, date, completed, postseason, neutral, note,
//                                   teams: [{id, home, winner, score, rank, name, logo}] ×2]}}
//                                   Every D1 game on one US Eastern date ("YYYYMMDD"); one request.
//   fetchResultsBetween(s, e)    → {byTeam: {espnId: [game]}, stale?}: completed games that
//                                   started in (s, e] (ms), game in fetchTeamSchedule()'s shape
//                                   (no state/status). One scoreboard request per ET date.
//
// Both fetchers cache for ESPN_TTL_MS and dedupe concurrent calls. Seasons use the project's
// convention (2027 = 2026-27), which is also ESPN's `season` parameter.
const ESPN_TTL_MS = 10 * 60 * 1000;
// site.web.api.espn.com, not site.api.espn.com: the latter 403s some user agents (e.g.
// HeadlessChrome) without a CORS header, so the browser reports a CORS failure.
const ESPN_BASE = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball";
const ESPN_STANDINGS_URL = season =>
    `https://site.web.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings?group=50&season=${season}`;
const _espnCache = {};   // key → { at, data, promise }

function espnIdFor(team) {
    if (typeof CONFERENCE_DATA === "undefined" || !CONFERENCE_DATA.espn) return null;
    const aliases = CONFERENCE_DATA.aliases || {};
    return CONFERENCE_DATA.espn[aliases[team] || team] || CONFERENCE_DATA.espn[team] || null;
}

let _espnKeyOf = null;
function espnTeamKey(id) {
    if (!_espnKeyOf) {
        _espnKeyOf = {};
        if (typeof CONFERENCE_DATA !== "undefined")
            Object.entries(CONFERENCE_DATA.espn || {}).forEach(([k, i]) => { _espnKeyOf[i] = k; });
    }
    return _espnKeyOf[id] || null;
}

function espnLogoUrl(id) {
    return `https://a.espncdn.com/i/teamlogos/ncaa/500/${id}.png`;
}

// Shared cache wrapper: load() → Promise<data>; validate by throwing inside load().
function _espnCached(key, load) {
    const hit = _espnCache[key] || (_espnCache[key] = {});
    if (hit.data && Date.now() - hit.at < ESPN_TTL_MS) return Promise.resolve(hit.data);
    if (hit.promise) return hit.promise;
    hit.promise = load()
        .then(data => {
            data.at = Date.now();
            Object.assign(hit, { data, at: data.at });
            return data;
        })
        .catch(err => {
            if (hit.data) return { ...hit.data, stale: err.message };
            throw err;
        })
        .finally(() => { hit.promise = null; });
    return hit.promise;
}

// Cached data without fetching (null if never loaded).
function espnCachedData(key) { return _espnCache[key]?.data || null; }

async function _espnJson(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`ESPN returned HTTP ${r.status}`);
    return r.json();
}

function fetchSeasonRecords(season) {
    return _espnCached(`records:${season}`, async () => {
        const json = await _espnJson(ESPN_STANDINGS_URL(season));
        const byId = {}, confs = [];
        // Top-level children are conferences; a conference may nest divisions.
        const entriesOf = node => [
            ...(node.standings?.entries || []),
            ...(node.children || []).flatMap(entriesOf),
        ];
        (json.children || []).forEach(conf => {
            const name = conf.shortName || conf.abbreviation || conf.name;
            const ids = [];
            entriesOf(conf).forEach(e => {
                const st = {};
                (e.stats || []).forEach(s => { if (s.type) st[s.type] = s; });
                const dv = k => st[k]?.displayValue || "";
                const wins = Number(st.wins?.value) || 0;
                const losses = Number(st.losses?.value) || 0;
                byId[e.team.id] = {
                    id: e.team.id,
                    name: e.team.shortDisplayName || e.team.location || e.team.displayName,
                    conf: name, wins, losses,
                    pct: wins + losses ? wins / (wins + losses) : null,
                    confRecord: dv("vsconf"), home: dv("home"), road: dv("road"),
                    streak: dv("streak"),
                };
                ids.push(e.team.id);
            });
            if (ids.length) confs.push({ name, ids });
        });
        const n = Object.keys(byId).length;
        if (n < 250) throw new Error(`ESPN returned only ${n} teams`);
        return { byId, confs };
    });
}

function fetchTeamSchedule(id, season) {
    return _espnCached(`schedule:${season}:${id}`, async () => {
        const url = t => `${ESPN_BASE}/teams/${id}/schedule?season=${season}&seasontype=${t}`;
        const [reg, post] = await Promise.all([
            _espnJson(url(2)),
            _espnJson(url(3)).catch(() => ({ events: [] })),   // postseason is optional
        ]);
        const seen = new Set();
        const games = [];
        [...(reg.events || []), ...(post.events || [])].forEach(ev => {
            if (seen.has(ev.id)) return;
            seen.add(ev.id);
            const c = ev.competitions?.[0];
            if (!c) return;
            const me = c.competitors.find(x => x.team?.id === String(id));
            const op = c.competitors.find(x => x !== me);
            if (!me || !op) return;
            const score = x => x.score?.value ?? (x.score?.displayValue ? Number(x.score.displayValue) : null);
            const state = c.status?.type?.state || "pre";
            const rank = op.curatedRank?.current;
            const postseason = ev.seasonType?.type === 3;
            games.push({
                id: ev.id,
                date: ev.date,
                site: c.neutralSite ? "N" : me.homeAway === "home" ? "H" : "A",
                opp: {
                    id: op.team.id,
                    name: op.team.shortDisplayName || op.team.location || op.team.displayName,
                    key: espnTeamKey(op.team.id),
                    logo: op.team.logos?.[0]?.href || op.team.logo || null,
                },
                // curatedRank is the AP rank at game time, but the tournament seed in postseason games.
                oppRank: !postseason && rank && rank <= 25 ? rank : null,
                oppSeed: postseason && rank && rank <= 16 ? rank : null,
                us: state === "pre" ? null : score(me),
                them: state === "pre" ? null : score(op),
                result: c.status?.type?.completed ? (me.winner ? "W" : "L") : null,
                state,
                status: c.status?.type?.shortDetail || "",
                postseason,
                note: c.notes?.[0]?.headline || "",
            });
        });
        games.sort((a, b) => a.date.localeCompare(b.date));
        return { games };
    });
}

function recordAsOf(games, date) {
    const cutoff = new Date(date).toISOString();
    let wins = 0, losses = 0;
    games.forEach(g => {
        if (g.date < cutoff && g.result) g.result === "W" ? wins++ : losses++;
    });
    return { wins, losses };
}

// W-L splits for a team's games. ctx (optional) = {teamId, records: fetchSeasonRecords() data}
// enables conf (same ESPN conference, excluding conference-tournament games), nonD1 and D1.
function summarizeGames(games, ctx = {}) {
    const mk = () => ({ wins: 0, losses: 0 });
    const s = { overall: mk(), home: mk(), away: mk(), neutral: mk(), conf: mk(), vsTop25: mk(), nonD1: mk(), D1: mk() };
    const byId = ctx.records?.byId;
    const myConf = byId?.[ctx.teamId]?.conf;
    games.forEach(g => {
        if (!g.result) return;
        const add = k => { g.result === "W" ? s[k].wins++ : s[k].losses++; };
        add("overall");
        add(g.site === "H" ? "home" : g.site === "A" ? "away" : "neutral");
        if (g.oppRank) add("vsTop25");
        if (byId) {
            add(byId[g.opp.id] ? "D1" : "nonD1");
            if (myConf && byId[g.opp.id]?.conf === myConf && !g.postseason && !/tournament/i.test(g.note)) add("conf");
        }
    });
    return s;
}

// One US Eastern date of D1 games ("YYYYMMDD"; ESPN's scoreboard dates are Eastern).
// groups=50 = Division I (incl. D1 vs non-D1 games); a single date per request, since
// date ranges return HTTP 400. Checked 2026-11-15: Nov 2–9, 2026 matched every D1 team's
// game count from its schedule.
function fetchScoreboardDay(day) {
    return _espnCached(`scoreboard:${day}`, async () => {
        const json = await _espnJson(`${ESPN_BASE}/scoreboard?dates=${day}&groups=50&limit=1000`);
        if (!Array.isArray(json.events)) throw new Error("ESPN scoreboard had no events list");
        const games = [];
        json.events.forEach(ev => {
            const c = ev.competitions?.[0];
            const type = ev.season?.type ?? ev.seasonType?.type;
            if (!c || c.competitors?.length !== 2 || type === 1) return;   // 1 = preseason / exhibitions
            games.push({
                id: ev.id,
                date: ev.date,
                completed: !!c.status?.type?.completed,
                postseason: type === 3,
                neutral: !!c.neutralSite,
                note: c.notes?.[0]?.headline || "",
                teams: c.competitors.map(x => ({
                    id: x.team?.id ? String(x.team.id) : null,
                    home: x.homeAway === "home",
                    winner: !!x.winner,
                    score: Number(x.score?.value ?? x.score),
                    rank: x.curatedRank?.current ?? null,
                    name: x.team?.shortDisplayName || x.team?.location || x.team?.displayName || "",
                    logo: x.team?.logo || x.team?.logos?.[0]?.href || null,
                })),
            });
        });
        return { games };
    });
}

function fetchResultsBetween(start, end) {
    const fmt = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" });
    const days = new Set();
    // 12 h steps so a DST change can't skip a date
    for (let t = start; t < end; t += 12 * 3600 * 1000) days.add(fmt.format(t).replace(/-/g, ""));
    days.add(fmt.format(end).replace(/-/g, ""));
    return Promise.all([...days].map(fetchScoreboardDay)).then(results => {
        const byTeam = {}, seen = new Set();
        results.forEach(r => r.games.forEach(g => {
            if (seen.has(g.id)) return;
            seen.add(g.id);
            const t = Date.parse(g.date);
            if (!g.completed || !(t > start && t <= end)) return;
            g.teams.forEach((me, i) => {
                const op = g.teams[1 - i];
                if (!me.id) return;
                if (!byTeam[me.id]) byTeam[me.id] = [];
                byTeam[me.id].push({
                    id: g.id,
                    date: g.date,
                    site: g.neutral ? "N" : me.home ? "H" : "A",
                    opp: { id: op.id, name: op.name, key: op.id ? espnTeamKey(op.id) : null, logo: op.logo },
                    // curatedRank is the AP rank at game time, but the tournament seed in postseason games.
                    oppRank: !g.postseason && op.rank && op.rank <= 25 ? op.rank : null,
                    oppSeed: g.postseason && op.rank && op.rank <= 16 ? op.rank : null,
                    us: me.score,
                    them: op.score,
                    result: me.winner ? "W" : "L",
                    postseason: g.postseason,
                    note: g.note,
                });
            });
        }));
        Object.values(byTeam).forEach(list => list.sort((a, b) => a.date.localeCompare(b.date)));
        return { byTeam, stale: results.find(r => r.stale)?.stale };
    });
}

// ── Poll deadlines (Week Stats W / L columns) ───────────────────────────────
// Week tabs carry no dates, but cbbpoll.net ballot ids are MongoDB ObjectIds whose first
// 8 hex chars are the ballot's creation time, so a week's latest ballot ≈ its deadline.
// In-season polls close Mondays at 10 AM ET (2025–2027: latest ballot 14:00–15:00 UTC
// every week). Legacy cbbpoll.com ballots (2016–2022) have numeric ids and AP ballots none,
// so those weeks get null. AP week numbers can't borrow userpoll dates: they drift (AP 2026
// week 18 = Mar 9, userpoll week 19).
function pollDeadline(weekId) {
    const block = document.getElementById(weekId);
    if (!block) return null;
    let max = 0;
    block.querySelectorAll("[data-ballot-url]").forEach(el => {
        const m = /cbbpoll\.net\/ballots\/[^/]+\/([0-9a-f]{24})/.exec(el.dataset.ballotUrl);
        if (m) max = Math.max(max, parseInt(m[1].slice(0, 8), 16) * 1000);
    });
    return max || null;
}

// {start, end} (ms): games that count toward a week's poll, from the previous poll's deadline
// to this one's. null for pre-season, AP, and weeks without ballot timestamps. The first
// in-season week starts at the pre-season deadline; if the previous deadline is missing
// or later than this one (2025's pre-season ballots were re-saved in Feb), it falls back
// to POLL_WINDOW_FALLBACK_DAYS before the deadline.
const POLL_WINDOW_FALLBACK_DAYS = 21;
function pollResultsWindow(weekId) {
    if (weekId.startsWith("week-ap-")) return null;
    const tabs = getSortedTabs();
    const i = tabs.findIndex(t => t.dataset.week === weekId);
    if (i === -1 || tabs[i].dataset.weeknum === "0") return null;
    const end = pollDeadline(weekId);
    if (!end) return null;
    const prev = tabs[i + 1];
    let start = prev && prev.dataset.year === tabs[i].dataset.year ? pollDeadline(prev.dataset.week) : null;
    if (!start || start >= end) start = end - POLL_WINDOW_FALLBACK_DAYS * 86400000;
    return { start, end };
}

// ── Quadrant data (NET / BPI) ───────────────────────────────────────────────
// Build-time JSON files, same origin (deployed by pages.yml; QUAD_FILES, injected by
// get_quad_files() in userpoll.py, says which exist per season):
//   net-YEAR.json    official NCAA NET rank + Q1–Q4 totals (net_rankings.py, --net)
//   quads-YEAR.json  computed per-game quads from ESPN schedules (quads.py, --quads):
//                    BPI ranks before NET is published, NET ranks after
// Totals come from net-YEAR.json when it exists (official), else quads-YEAR.json (unofficial).
// Per-game quads come from quads-YEAR.json only if it used the same ranking as the totals.
//
//   quadsAvailable(season)  → "net" | "bpi" | null (the ranking the columns will show)
//   fetchQuads(season)      → Promise<{source, official, asOf, teams: {key: {rank, q1..q4,
//                              bpi, off, def, sor, sos}},  (ESPN BPI scores + SOR / SOS ranks
//                              from quads-YEAR.json when present)
//                              games: {key: {"YYYY-MM-DD:oppEspnId": 1-4}}}>; result also
//                              kept in _quadsData[season] (or {error}) for synchronous renders
//   quadOfGame(season, key, game)  → 1-4 | null, for a fetchTeamSchedule() game
const _quadsPromise = {};
const _quadsData = {};
// First season whose Records tab shows ESPN's SOR / SOS rank columns.
const RESUME_FROM_SEASON = 2027;
function quadsAvailable(season) {
    const f = typeof QUAD_FILES !== "undefined" ? QUAD_FILES[season] : null;
    return f ? (f.net ? "net" : f.quads ? "bpi" : null) : null;
}
function fetchQuads(season) {
    if (_quadsPromise[season]) return _quadsPromise[season];
    const f = QUAD_FILES[season];
    const get = name => fetch(`${name}-${season}.json`).then(r => {
        if (!r.ok) throw new Error(`${name}-${season}.json: HTTP ${r.status}`);
        return r.json();
    });
    const p = Promise.all([f.net ? get("net") : null, f.quads ? get("quads") : null]).then(([net, q]) => {
        const base = net || q;
        const source = net ? "net" : q.rankSource;
        const teams = {};
        Object.entries(base.teams).forEach(([k, t]) => {
            teams[k] = { rank: t.rank, q1: t.q1, q2: t.q2, q3: t.q3, q4: t.q4 };
        });
        // BPI score / offense / defense + SOR / SOS ranks (quads.py fetches them whatever the
        // rank source).
        if (q) Object.entries(q.teams).forEach(([k, t]) => {
            if (t.bpi == null) return;
            const m = teams[k] || (teams[k] = {});
            m.bpi = t.bpi; m.off = t.off; m.def = t.def; m.sor = t.sor; m.sos = t.sos;
        });
        // Unplayed games per team (any rank source), for the Records Next column.
        const upcoming = {};
        if (q) Object.entries(q.teams).forEach(([k, t]) => {
            upcoming[k] = t.games.filter(g => !g.result).map(g => ({
                date: g.start || g.date, dateOnly: !g.start, site: g.site,
                opp: { id: g.oppId, key: g.opp || espnTeamKey(g.oppId), name: g.oppName || (g.opp ? null : "non-D1"), logo: null },
                quad: g.quad,
            }));
        });
        // Completed games per team (schedule-game shape, date = UTC day), for the Picker's wins.
        const played = {};
        if (q) Object.entries(q.teams).forEach(([k, t]) => {
            played[k] = t.games.filter(g => g.result).map(g => ({
                date: g.date, site: g.site, result: g.result, us: Math.round(g.us), them: Math.round(g.them),
                opp: { id: g.oppId, key: g.opp || espnTeamKey(g.oppId), name: g.oppName || (g.opp ? null : "non-D1"), logo: null },
                quad: g.quad,
            }));
        });
        const games = {};
        if (q && q.rankSource === source) {
            Object.entries(q.teams).forEach(([k, t]) => {
                const m = games[k] = {};
                t.games.forEach(g => { if (g.quad) m[`${g.date}:${g.oppId}`] = g.quad; });
            });
        }
        return (_quadsData[season] = { source, official: !!net, asOf: net ? net.through : q.ranksAsOf, teams, games, upcoming, played,
            fetched: q ? Date.parse(q.fetched) : null, cutoffs: q?.cutoffs || null });
    });
    p.catch(err => { _quadsData[season] = { error: err.message }; delete _quadsPromise[season]; });
    return (_quadsPromise[season] = p);
}
function quadOfGame(season, key, game) {
    const m = _quadsData[season]?.games?.[key];
    return (m && m[`${game.date.slice(0, 10)}:${game.opp.id}`]) || null;
}

// A team's next RECORDS_NEXT_COUNT games for the Records Next column. Prefers the
// live ESPN schedule when it's already cached (opened game list, Voted view), else the unplayed
// games in quads-YEAR.json (daily snapshot). Snapshot games that started more than
// NEXT_GAME_GRACE_MS ago are assumed played since; date-only entries (older files) count until
// the end of their UTC day. Returns null when there's no data for the team yet.
const RECORDS_NEXT_COUNT = 2;
const NEXT_GAME_GRACE_MS = 3 * 3600 * 1000;
function nextGamesFor(season, key, espnId) {
    const live = espnId ? espnCachedData(`schedule:${season}:${espnId}`) : null;
    if (live) return live.games.filter(g => !g.result && g.state !== "post").slice(0, RECORDS_NEXT_COUNT);
    const list = _quadsData[season]?.upcoming?.[key];
    if (!list) return null;
    const now = Date.now();
    return list.filter(g => g.dateOnly
        ? new Date(`${g.date}T23:59:59Z`).getTime() >= now
        : new Date(g.date).getTime() >= now - NEXT_GAME_GRACE_MS).slice(0, RECORDS_NEXT_COUNT);
}
function nextGamesHtml(games, records, season, key) {
    const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    if (!games.length) return `<span class="records-opps-msg">—</span>`;
    return `<div class="records-next-list">${games.map(g => {
        const d = new Date(g.dateOnly ? `${g.date}T12:00:00Z` : g.date);
        const day = d.toLocaleDateString([], { month: "short", day: "numeric", ...(g.dateOnly ? { timeZone: "UTC" } : {}) });
        const time = g.dateOnly ? "" : ` ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
        const site = g.site === "H" ? "vs" : g.site === "A" ? "@" : "N";
        const name = g.opp.key ? conferenceDisplayName(g.opp.key) : g.opp.name || "?";
        const quad = g.quad ?? (key ? quadOfGame(season, key, g) : null);
        const rank = g.oppRank ? `#${g.oppRank} ` : g.oppSeed ? `(${g.oppSeed}) ` : "";
        const tip = esc(`${site === "N" ? "Neutral site vs" : site} ${rank}${name} · ${day}${time}${quad ? ` · Q${quad}` : ""}${records.byId[g.opp.id] ? "" : " · non-D1"}`);
        const src = g.opp.key ? null : oppLogoSrc(g.opp) || (g.opp.id ? espnLogoUrl(g.opp.id) : null);
        const logo = g.opp.key
            ? `<img class="records-opp-logo records-logo team-logo" data-team="${esc(g.opp.key)}" data-espn="${g.opp.id}" alt="">`
            : src ? `<img class="records-opp-logo" src="${esc(src)}" data-filler="${esc(name)}" alt="">`
            : logoFillerHtml("records-opp-logo", name, "");
        return `<span class="records-next-game" title="${tip}"><span class="records-next-site">${site}</span>${logo}<span class="records-next-date">${esc(day)}</span></span>`;
    }).join("")}</div>`;
}

// ── Records tab (Year window) ───────────────────────────────────────────────
// Uses the ESPN data layer above. Sub-views: "week" = teams receiving votes in the
// active week, in points order; "all" = every D1 team grouped by conference (ours for
// 2025+, ESPN's before). Clicking a team row expands its game list (fetchTeamSchedule);
// expanded teams are remembered in _recordsExpanded across re-renders.
let _recordsView = "week";  // "week" | "all"
let _recordsRenderToken = 0;
const _recordsExpanded = new Set();   // `${season}:${espnId}`

function showSeasonRecords(currentYear, isApMode, activeTab) {
    const modal = document.getElementById("season-stats-modal");
    const title = document.getElementById("season-stats-title");
    const table = document.getElementById("season-stats-table");
    // Title: "YYYY Records — Userpoll Conferences Tool", the switch styled like the Week window's tabs.
    // Picker only where it has its data (pickerAvailable()).
    const hasPicker = pickerAvailable(currentYear);
    if (_recordsView === "picker" && !hasPicker) _recordsView = "week";
    const views = [["week", "Userpoll"], ["all", "Conferences"], ...(hasPicker ? [["picker", "Tool"]] : [])];
    const switcher = `<span class="records-switch">${views.map(([k, l]) =>
        `<span class="records-view${_recordsView === k ? " active" : ""}" data-view="${k}">${l}</span>`).join("")}</span>`;
    // Picker adds a small "Score BPI Record Quad" switch (what the Last 7 Games chips show, pickerShowMode()).
    const showSwitch = _recordsView === "picker"
        ? `<span class="records-switch tp-show-switch">${PICKER_SHOW.map(([k, l]) =>
            `<span class="records-view${pickerShowMode() === k ? " active" : ""}" data-show="${k}">${l}</span>`).join("")}</span>`
        : "";
    title.innerHTML = `<span class="records-title-main">${currentYear}${isApMode ? " AP" : ""} Records — ${switcher}${showSwitch}</span>`
        + `<span class="records-note records-title-note"></span>`;
    title.querySelectorAll(".records-view[data-view]").forEach(el => el.addEventListener("click", () => {
        if (el.classList.contains("active")) return;
        _recordsView = el.dataset.view;
        showSeasonRecords(currentYear, isApMode, activeTab);
    }));
    table.classList.remove("season-voters", "season-mmp12");
    table.classList.add("season-records");

    const weekId = isApMode && _apCurrentWeekNum !== null
        ? `week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`
        : activeTab.dataset.week;
    const weekTab = isApMode
        ? getSortedApTabs().find(t => t.dataset.week === weekId) || activeTab
        : activeTab;
    const weekLabel = weekTextLabel(weekTab) || `Week ${displayWeekNum(weekTab)}`;

    const token = ++_recordsRenderToken;
    let last = [null, null];   // latest ESPN result, so the quad data can re-render with it
    const render = (data, error) => {
        if (token !== _recordsRenderToken || !table.classList.contains("season-records")) return;
        last = [data, error];
        const isPicker = _recordsView === "picker";
        table.classList.toggle("season-teampicker", isPicker);
        table.innerHTML = isPicker
            ? buildPickerTableHtml(currentYear, data, error)
            : buildRecordsTableHtml(currentYear, weekId, weekLabel, data, error);
        const noteEl = title.querySelector(".records-title-note");
        if (noteEl) {
            noteEl.innerHTML = (isPicker && pickerSavedOrder(currentYear)
                ? `<span class="records-retry tp-reset" title="Restore eligibility order">Reset order</span> · ` : "")
                + recordsNoteHtml(currentYear, data);
            noteEl.querySelector(".tp-reset")?.addEventListener("click", () => {
                pickerSaveOrder(currentYear, null);
                render(...last);
            });
        }
        table.querySelector(".records-retry")?.addEventListener("click", () =>
            showSeasonRecords(currentYear, isApMode, activeTab));
        initRecordsLogos(table);
        if (!data) return;
        const tbody = table.querySelector("tbody");
        if (isPicker) initPickerDrag(tbody, currentYear, () => {
            // The first drag adds the Reset link to the note.
            if (noteEl && !noteEl.querySelector(".tp-reset")) render(...last);
        });
        tbody.addEventListener("click", e => {
            // Next-game opponent logos highlight the team everywhere instead of opening the game list.
            const opp = e.target.closest("img.records-opp-logo[data-team]");
            if (opp) { toggleTeamHighlight(opp.dataset.team); return; }
            const tr = e.target.closest("tr.records-team-row");
            if (!tr || !tbody.contains(tr)) return;
            toggleTeamGames(tr, currentYear, data);
        });
        // Re-open game lists that were open before this render.
        tbody.querySelectorAll("tr.records-team-row").forEach(tr => {
            if (_recordsExpanded.has(`${currentYear}:${tr.dataset.espn}`)) toggleTeamGames(tr, currentYear, data, true);
        });
    };

    title.querySelectorAll(".records-view[data-show]").forEach(el => el.addEventListener("click", () => {
        if (el.classList.contains("active")) return;
        setPickerShowMode(el.dataset.show);
        title.querySelectorAll(".records-view[data-show]").forEach(x => x.classList.toggle("active", x === el));
        render(...last);
    }));

    const cached = espnCachedData(`records:${currentYear}`);
    render(cached, null);   // cached data (or a loading row) right away
    modal.classList.add("open");
    if (quadsAvailable(currentYear) && (!_quadsData[currentYear] || _quadsData[currentYear].error)) {
        const again = () => render(...last);
        fetchQuads(currentYear).then(again, again);
    }
    if (!cached || Date.now() - cached.at >= ESPN_TTL_MS) {
        fetchSeasonRecords(currentYear).then(d => render(d, null), err => render(null, err.message));
    }
    // Picker: games finished since the quads snapshot (scoreboard), so recent wins are current.
    if (_recordsView === "picker") {
        const again = () => render(...last);
        fetchQuads(currentYear).then(() => pickerFetchRecent(currentYear)).then(again, () => {});
    }
}

// Logo for a schedule opponent we have no key for (non-D1): ESPN's from the schedule, else
// our NCAA.com file (cbb-logos/ncaa-{espnId}.webp, from nond1_logos.py; ids in NCAA_LOGO_IDS),
// else null, and the caller shows logoFillerHtml().
function oppLogoSrc(opp) {
    if (opp.logo) return opp.logo;
    const id = String(opp.id);
    if (typeof NCAA_LOGO_IDS === "undefined" || !NCAA_LOGO_IDS.has(id)) return null;
    return `cbb-logos/ncaa-${id}${isDarkMode() && NCAA_DARK_LOGO_IDS.has(id) ? "-dark" : ""}.webp`;
}

// Filler logo for schools with no logo file and none on ESPN (most non-D1 teams): a dashed
// circle with the school's initial. cls carries the size of the logo it stands in for.
function logoFillerHtml(cls, name, title = name) {
    const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const initial = (String(name ?? "").match(/[A-Za-z0-9]/) || ["?"])[0].toUpperCase();
    return `<span class="${cls} logo-filler"${title ? ` title="${esc(title)}"` : ""}>${initial}</span>`;
}
function replaceWithLogoFiller(img, name) {
    const tpl = document.createElement("template");
    tpl.innerHTML = logoFillerHtml(img.className.replace(/\b(records-logo|team-logo)\b/g, "").trim(), name, img.title || name);
    img.replaceWith(tpl.content.firstChild);
}

// Our logo files for img.records-logo[data-team], falling back to ESPN's logo, then to a
// filler; ESPN-only images (img[data-filler]) fall back to the filler directly.
function initRecordsLogos(root) {
    let imgs = [...root.querySelectorAll("img.records-logo[data-team]:not([data-logo-init])")];
    imgs.forEach(img => { img.dataset.logoInit = "1"; });
    // Safari: teams with a logo file get CSS logos (see "CSS logos"); a few hundred
    // src loads made the Records views take 1–2 s there. No error fallback is needed,
    // since LOGO_TEAMS lists only files that exist.
    if (CSS_LOGOS && typeof LOGO_TEAMS !== "undefined") {
        const css = imgs.filter(img => LOGO_TEAMS.has(img.dataset.team));
        ensureCssLogoRules(css.map(img => img.dataset.team));
        css.forEach(img => setBallotLogo(img, img.dataset.team));
        imgs = imgs.filter(img => !img.dataset.cssLogo);
    }
    imgs.forEach(img => {
        const onError = () => {
            if (img.dataset.espn && !img.dataset.fallback) {
                img.dataset.fallback = "1";
                img.src = espnLogoUrl(img.dataset.espn);
                return;
            }
            img.removeEventListener("error", onError);
            replaceWithLogoFiller(img, conferenceDisplayName(img.dataset.team));
        };
        img.addEventListener("error", onError);
        setLogoSrc(img, img.dataset.team);
    });
    root.querySelectorAll("img[data-filler]").forEach(img => {
        const fail = () => replaceWithLogoFiller(img, img.dataset.filler);
        if (img.complete && img.naturalWidth === 0 && img.getAttribute("src")) fail();
        else img.addEventListener("error", fail, { once: true });
    });
}

// Expand/collapse a Records row's game list (a full-width row inserted after it).
function toggleTeamGames(tr, season, records, forceOpen = false) {
    const id = tr.dataset.espn;
    const key = `${season}:${id}`;
    const next = tr.nextElementSibling;
    if (next?.classList.contains("records-games-row")) {
        if (forceOpen) return;
        next.remove();
        tr.classList.remove("expanded");
        _recordsExpanded.delete(key);
        return;
    }
    _recordsExpanded.add(key);
    tr.classList.add("expanded");
    const row = document.createElement("tr");
    row.className = "records-games-row";
    row.innerHTML = `<td colspan="${tr.children.length}"><div class="records-games-msg">Loading games…</div></td>`;
    tr.after(row);
    const cell = row.firstElementChild;
    const load = () => fetchTeamSchedule(id, season).then(sched => {
        if (!row.isConnected) return;
        cell.innerHTML = buildTeamGamesHtml(sched, id, records, season);
        initRecordsLogos(cell);
    }, err => {
        if (!row.isConnected) return;
        cell.innerHTML = `<div class="records-games-msg">Couldn't load games from ESPN (${err.message.replace(/[<>&]/g, "")}).
            <span class="records-retry">Retry</span></div>`;
        cell.querySelector(".records-retry").addEventListener("click", ev => { ev.stopPropagation(); load(); });
    });
    load();
}

// One team's games: split summary + one line per game (completed, live, then upcoming).
function buildTeamGamesHtml(sched, teamId, records, season) {
    const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const games = sched.games;
    if (!games.length) return `<div class="records-games-msg">No games listed by ESPN.</div>`;
    const s = summarizeGames(games, { teamId, records });
    const wl = x => `${x.wins}-${x.losses}`;
    const split = (label, x, title = "") => x.wins + x.losses
        ? `<span class="records-split"${title ? ` title="${title}"` : ""}>${label} <b>${wl(x)}</b></span>` : "";
    const summary = [
        split("Conf", s.conf, "Regular-season games vs. the same ESPN conference"),
    ].filter(Boolean).join("");
    const fmtDate = iso => new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
    // Quadrant tag per game (only when per-game quads exist for this season; see fetchQuads()).
    const teamKey = espnTeamKey(teamId);
    const qd = _quadsData[season];
    const showQuads = !!(teamKey && qd?.games?.[teamKey]);
    const quadTip = qd ? (qd.source === "net" ? "NET quadrant" : "Unofficial BPI quadrant") : "";
    const lines = games.map(g => {
        const site = g.site === "H" ? "vs" : g.site === "A" ? "@" : "N";
        const quad = showQuads ? quadOfGame(season, teamKey, g) : null;
        // Always emit the quad cell (empty when there's no data) so every team's list has the same columns.
        const quadCell = `<td class="rg-quad">${quad ? `<span class="rg-quad-tag rg-q${quad}" title="${quadTip}">Q${quad}</span>` : ""}</td>`;
        const logo = g.opp.key
            ? `<img class="records-games-logo records-logo" data-team="${esc(g.opp.key)}" data-espn="${g.opp.id}" alt="">`
            : oppLogoSrc(g.opp) ? `<img class="records-games-logo" src="${esc(oppLogoSrc(g.opp))}" data-filler="${esc(g.opp.name)}" alt="">`
            : logoFillerHtml("records-games-logo", g.opp.name);
        const name = g.opp.key ? conferenceDisplayName(g.opp.key) : g.opp.name;
        const oppRec = records.byId[g.opp.id];
        const nonD1 = oppRec ? "" : `<span class="records-tag" title="Not a Division I team">non-D1</span>`;
        const recTag = oppRec ? `<span class="rg-opp-rec" title="${esc(name)}'s record">(${oppRec.wins}-${oppRec.losses})</span>` : "";
        let res;
        if (g.result) res = `<span class="${g.result === "W" ? "delta-up" : "delta-down"}">${g.result}</span> ${g.us}-${g.them}`;
        else if (g.state === "in") res = `<span class="records-live">Live</span> ${g.us ?? ""}-${g.them ?? ""}`;
        else res = `<span class="records-upcoming">${esc(g.status.replace(/^\d+\/\d+\s*-\s*/, ""))}</span>`;
        return `<tr class="${g.result ? "" : "records-game-pending"}">
            <td class="rg-date">${fmtDate(g.date)}</td>
            <td class="rg-site" title="${g.site === "N" ? "Neutral site" : g.site === "H" ? "Home" : "Away"}">${site}</td>
            <td class="rg-opp" title="${esc(name)}">${logo}${g.oppRank ? `<span class="rg-rank" title="AP rank at game time">${g.oppRank}</span>` : ""}${g.oppSeed ? `<span class="rg-rank" title="Seed">(${g.oppSeed})</span>` : ""}${esc(name)}${recTag}${nonD1}</td>${quadCell}
            <td class="rg-res">${res}</td>
            <td class="rg-note">${esc(g.note)}${g.postseason && !g.note ? "Postseason" : ""}</td>
        </tr>`;
    }).join("");
    const stale = sched.stale ? `<span class="records-note"> · couldn't refresh (${esc(sched.stale)})</span>` : "";
    return `<div class="records-games">
        <div class="records-splits">${summary}${stale}</div>
        <table class="records-games-table"><colgroup><col class="rg-c-date"><col class="rg-c-site"><col class="rg-c-opp"><col class="rg-c-quad"><col class="rg-c-res"><col class="rg-c-note"></colgroup><tbody>${lines}</tbody></table>
    </div>`;
}

// Right-aligned note in the Records title: "ESPN 2:15 AM" (date added if the data
// isn't from today), "ESPN · final" for past seasons.
function recordsNoteHtml(currentYear, data) {
    const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const isCurrentSeason = Number(currentYear) >= Math.max(...getSortedTabs().map(t => Number(t.dataset.year)));
    let note = "ESPN";
    if (data) {
        const at = new Date(data.at);
        const t = at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        const today = at.toDateString() === new Date().toDateString();
        note += isCurrentSeason
            ? ` ${today ? t : `${at.toLocaleDateString([], { month: "short", day: "numeric" })}, ${t}`}`
            : " · final";
        if (data.stale) note += ` · couldn't refresh (${esc(data.stale)})`;
    }
    // Where the Q1–Q4 columns come from.
    const qd = _quadsData[currentYear];
    if (qd?.error) note += ` · quads unavailable (${esc(qd.error)})`;
    else if (qd) {
        const d = new Date(qd.official ? `${qd.asOf}T12:00:00` : qd.asOf)
            .toLocaleDateString([], { month: "short", day: "numeric" });
        note += qd.official
            ? ` · Quads: NCAA NET through ${d}`
            : "";
    }
    return note;
}

const RECORDS_NAME_MAX = 17;   // longest display name kept as is ("Mississippi State")
function buildRecordsTableHtml(currentYear, weekId, weekLabel, data, error) {
    const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const view = _recordsView;
    // Quad columns after Conf when the season has NET / quad data (fetchQuads()): NET rank
    // ESPN SOR + SOS ranks (from quads-YEAR.json, RESUME_FROM_SEASON onwards; left of the
    // line after Conf), then NET rank (once NET is out), then ESPN BPI score + offense +
    // defense (when quads-YEAR.json exists), then Q1–Q4.
    const quadSrc = quadsAvailable(currentYear);
    const qd = _quadsData[currentYear];
    const showNet = quadSrc === "net";
    const showBpi = !!quadSrc && !!QUAD_FILES[currentYear]?.quads;
    const showResume = showBpi && Number(currentYear) >= RESUME_FROM_SEASON;
    // Current season: each team's next two games (nextGamesFor(); needs quads-YEAR.json).
    const isCurrentSeason = Number(currentYear) >= Math.max(...getSortedTabs().map(t => Number(t.dataset.year)));
    const showNext = showBpi && isCurrentSeason;
    const COLS = 6 + (quadSrc ? 4 : 0) + (showNet ? 1 : 0) + (showBpi ? 3 : 0) + (showResume ? 2 : 0) + (showNext ? 1 : 0);
    const quadTip = quadSrc === "net"
        ? "NCAA quadrant record (D1 only)"
        : "Unofficial quadrant record, BPI for NET (D1 only)";
    const bpiCols = [
        ["bpi", "BPI", "ESPN BPI: points above an average D1 team per 70 possessions"],
        ["off", "Off", "BPI offense (points per 70 poss. above avg)"],
        ["def", "Def", "BPI defense (points per 70 poss. above avg)"],
    ];
    const resumeCols = [
        ["sor", "SOR", "ESPN Strength of Record rank (lower is better)"],
        ["sos", "SOS", "ESPN Strength of Schedule rank (1 = hardest)"],
    ];
    const quadHead = quadSrc
        ? (showResume ? resumeCols.map(([k, l, tip]) =>
                `<th class="records-resume-col${k === "sos" ? " records-sos-col" : ""}" title="${tip}">${l}</th>`).join("") : "")
            + (showNet ? `<th title="NET rank">NET</th>` : "")
            + (showBpi ? bpiCols.map(([, l, tip]) => `<th class="records-bpi-col" title="${tip}">${l}</th>`).join("") : "")
            + [1, 2, 3, 4].map(q =>
                `<th class="records-quad-col${q === 1 ? " records-q1-col" : ""}${q === 4 ? " records-q4-col" : ""}" title="${quadTip}">Q${q}</th>`).join("") : "";

    const head = `<colgroup>
        <col style="width:28px"><col style="width:26px"><col>
        <col style="width:52px"><col style="width:44px"><col style="width:52px">
        ${showResume ? "<col style=\"width:40px\">".repeat(2) : ""}${showNet ? `<col style="width:38px">` : ""}${showBpi ? "<col style=\"width:42px\">".repeat(3) : ""}
        ${quadSrc ? "<col style=\"width:40px\">".repeat(4) : ""}
        ${showNext ? "<col>" : ""}
    </colgroup><thead><tr>
        <th>#</th><th></th><th class="team-col">Team</th>
        <th>W-L</th><th>Pct</th><th>Conf</th>${quadHead}${showNext ? `<th class="records-opps-col records-next-col" title="Next ${RECORDS_NEXT_COUNT} games">Next</th>` : ""}
    </tr></thead>`;
    const quadCells = key => {
        if (!quadSrc) return "";
        const t = qd?.teams?.[(CONFERENCE_DATA.aliases || {})[key] || key];
        const blank = qd ? "—" : "…";
        const num = v => v == null ? blank : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1);
        return (showResume ? resumeCols.map(([k]) =>
                `<td class="records-resume${k === "sos" ? " records-sos" : ""}">${t?.[k] ?? blank}</td>`).join("") : "")
            + (showNet ? `<td class="records-quad-rank">${t?.rank ?? blank}</td>` : "")
            + (showBpi ? bpiCols.map(([k]) =>
                `<td class="records-bpi${k === "bpi" ? " records-bpi-main" : ""}">${num(t?.[k])}</td>`).join("") : "")
            + `${[1, 2, 3, 4].map(q =>
            `<td class="records-quad${q === 1 ? " records-q1" : ""}${q === 4 ? " records-q4" : ""}">${t ? esc(t[`q${q}`]) : blank}</td>`).join("")}`;
    };

    if (!data) {
        const msg = error
            ? `Couldn't load records from ESPN (${esc(error)}). <span class="records-retry">Retry</span>`
            : "Loading";
        return `${head}<tbody><tr><td colspan="${COLS}" class="records-msg">${msg}</td></tr></tbody>`;
    }

    const keyOf = id => espnTeamKey(id);
    const pct = r => r.pct === null ? "—" : r.pct.toFixed(3).replace(/^0/, "");
    const row = (num, team, id, extraCls = "") => {
        const r = id ? data.byId[id] : null;
        const key = team || (id && keyOf(id)) || null;
        const fullName = key ? conferenceDisplayName(key) : r?.name || "?";
        // Long names (mostly low-major schools in All) would widen the Team column past what
        // the poll teams need: use ESPN's short name instead, full name on hover.
        const name = fullName.length > RECORDS_NAME_MAX && r?.name && r.name.length < fullName.length ? r.name : fullName;
        const logo = key
            ? `<img class="logo-sm records-logo" data-team="${esc(key)}"${id ? ` data-espn="${id}"` : ""} alt="">`
            : id ? `<img class="logo-sm" src="${espnLogoUrl(id)}" data-filler="${esc(name)}" alt="">` : "";
        const cells = (r
            ? `<td class="records-wl">${r.wins}-${r.losses}</td><td>${pct(r)}</td><td>${esc(r.confRecord || "—")}</td>`
            : `<td colspan="3" class="records-missing">${id ? "Not in ESPN's standings" : "No ESPN ID"}</td>`)
            + quadCells(key);
        let nextCell = "";
        if (showNext) {
            const ng = r && key ? nextGamesFor(currentYear, (CONFERENCE_DATA.aliases || {})[key] || key, id) : null;
            nextCell = `<td class="records-next">${ng ? nextGamesHtml(ng, data, currentYear, key)
                : `<span class="records-opps-msg">${r && !qd ? "…" : "—"}</span>`}</td>`;
        }
        const cls = [extraCls, r ? "records-team-row" : ""].filter(Boolean).join(" ");
        return `<tr${cls ? ` class="${cls}"` : ""}${r ? ` data-espn="${id}"` : ""}><td>${num}</td><td>${logo}</td>
            <td class="team-col"${name !== fullName ? ` title="${esc(fullName)}"` : ""}>${esc(name)}</td>${cells}${nextCell}</tr>`;
    };

    // Poll points in the active week (official ballots) set the Week view's order.
    const ballots = Object.entries(buildDeltaData(true)[weekId] || {})
        .filter(([u]) => u !== "Official Overall" && u !== "AP Overall")
        .map(([, ts]) => ts.slice(0, 25));
    const pts = {};
    ballots.forEach(b => b.forEach((t, i) => { if (t) pts[t] = (pts[t] || 0) + (25 - i); }));

    let body = "";
    if (view === "week") {
        // Same order as Official Overall / the Stats tab (points desc, ties in ballot order)
        const order = Object.entries(pts).sort((a, b) => b[1] - a[1]).map(([t]) => t);
        if (!order.length) {
            body = `<tr><td colspan="${COLS}" class="records-msg">No ballots for ${esc(weekLabel)}.</td></tr>`;
        }
        order.forEach((team, i) => {
            body += row(i + 1, team, espnIdFor(team), i === 24 && order.length > 25 ? "records-t25-end" : "");
        });
    } else {
        // Our conferences for 2025+ (same as Shift+K); ESPN's grouping for earlier seasons.
        const ours = conferenceTable(currentYear);
        const groups = ours
            ? Object.entries(ours).map(([name, teams]) => ({ name, members: teams.map(t => [t, espnIdFor(t)]) }))
            : data.confs.map(c => ({ name: c.name, members: c.ids.map(id => [keyOf(id), id]) }));
        const isPower = g => (CONFERENCE_DATA.power || []).includes(g.name);
        groups.sort((a, b) => (isPower(b) - isPower(a)) || a.name.localeCompare(b.name));
        const confPct = r => {
            const m = /^(\d+)-(\d+)/.exec(r?.confRecord || "");
            return m && +m[1] + +m[2] ? +m[1] / (+m[1] + +m[2]) : -1;
        };
        groups.forEach(g => {
            const members = g.members.slice().sort(([, a], [, b]) => {
                const ra = data.byId[a], rb = data.byId[b];
                return (confPct(rb) - confPct(ra)) || ((rb?.pct ?? -1) - (ra?.pct ?? -1))
                    || ((rb?.wins ?? 0) - (ra?.wins ?? 0));
            });
            body += `<tr class="records-conf-row"><td colspan="${COLS}">${esc(g.name)}</td></tr>`;
            members.forEach(([team, id], i) => {
                body += row(i + 1, team, id);
            });
        });
    }
    return `${head}<tbody>${body}</tbody>`;
}

// ── Records › Picker ────────────────────────────────────────────────────────
// The PICKER_COUNT most eligible teams for a Top 25, for a voter to drag into their own order.
// Eligibility = average of three ranks among D1 teams: ESPN SOR rank (quads-YEAR.json), BPI rank
// (by BPI score, quads-YEAR.json) and W-L rank (ESPN standings win %, then more wins, then fewer
// losses); lower is better, ties by SOR then BPI. Current season only, from RESUME_FROM_SEASON
// (needs SOR). The # column is positional: dragging moves the team, the numbers stay put.
// A dragged order is saved per viewer in localStorage for the poll it's being picked for (next
// Monday 10 AM ET deadline, pickerPollKey()); a new week starts from the last saved order until
// a drag saves it under the new week. Reset in the title note clears it. Teams that enter the top PICKER_COUNT later slot in at their eligibility spot.
// Last PICKER_GAMES games (wins and losses): quads-YEAR.json's completed games plus the ESPN scoreboard since that
// snapshot (pickerFetchRecent()), as Week Stats Games chips. With more games than fit, trimPickerGames() drops
// non-D1 wins, then Q4 wins, then Q3 wins (oldest first in each), then the oldest games left.
const PICKER_COUNT = 100;
const PICKER_GAMES = 7;
const _pickerRecent = {};   // season → {espnId: [game]} finished since the quads snapshot
// What the Last 7 Games chips show after the opponent logo (small title switch "Score BPI Record Quad"):
// the game score, the opponent's current BPI rating, the opponent's current W-L, or the game's quadrant.
// Saved per viewer in localStorage pickerShow.
const PICKER_SHOW = [["score", "Score"], ["bpi", "BPI"], ["record", "Record"], ["quad", "Quad"]];
function pickerShowMode() {
    try { const v = localStorage.getItem("pickerShow"); if (PICKER_SHOW.some(([k]) => k === v)) return v; } catch { }
    return "score";
}
function setPickerShowMode(v) { try { localStorage.setItem("pickerShow", v); } catch { } }
let _pickerSuppressClickUntil = 0;

function pickerAvailable(season) {
    if (!quadsAvailable(season) || !QUAD_FILES[season]?.quads || Number(season) < RESUME_FROM_SEASON) return false;
    return Number(season) >= Math.max(...getSortedTabs().map(t => Number(t.dataset.year)));
}

// "YYYY-MM-DD" of the next poll deadline (Mondays 10 AM ET).
function pickerPollKey() {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
        weekday: "short", hour: "numeric", hourCycle: "h23",
    }).formatToParts(new Date()).map(x => [x.type, x.value]));
    const dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(p.weekday);
    let add = (8 - dow) % 7;
    if (add === 0 && Number(p.hour) >= 10) add = 7;
    return new Date(Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day) + add)).toISOString().slice(0, 10);
}
function pickerStorageKey(season) { return `pickerOrder:${season}:${pickerPollKey()}`; }
// This poll's saved order, else the newest one saved for an earlier poll of the same season
// (so an order carries into the next week until a drag saves it under the new key).
function pickerSavedOrder(season) {
    try {
        const k = pickerStorageKey(season);
        let raw = localStorage.getItem(k);
        if (raw == null) {
            const prefix = `pickerOrder:${season}:`;
            const prev = Object.keys(localStorage).filter(x => x.startsWith(prefix) && x < k).sort().pop();
            raw = prev ? localStorage.getItem(prev) : null;
        }
        const v = JSON.parse(raw || "null");
        return Array.isArray(v) && v.length ? v : null;
    } catch { return null; }
}
function pickerSaveOrder(season, keys) {
    try {
        const k = pickerStorageKey(season);
        // Drop orders saved for earlier polls (a save replaces a carried-over order;
        // Reset, keys = null, clears every saved order so nothing carries back in).
        Object.keys(localStorage).filter(x => x.startsWith("pickerOrder:") && x !== k).forEach(x => localStorage.removeItem(x));
        if (keys) localStorage.setItem(k, JSON.stringify(keys));
        else localStorage.removeItem(k);
    } catch { /* storage unavailable: the order just isn't remembered */ }
}

// Top PICKER_COUNT teams by eligibility: [{key, id, r (standings), t (quads), sorRank, bpiRank, wlRank, score}].
function pickerCandidates(season, records) {
    const qd = _quadsData[season];
    if (!qd?.teams) return [];
    const list = [];
    Object.entries(qd.teams).forEach(([key, t]) => {
        if (t.sor == null || t.bpi == null) return;
        const id = espnIdFor(key);
        const r = id ? records.byId[id] : null;
        if (!r) return;
        const gp = r.wins + r.losses;
        list.push({ key, id, r, t, pct: gp ? r.wins / gp : 0, sorRank: t.sor });
    });
    // Competition ranking (1, 2, 2, 4) by cmp.
    const rankBy = (cmp, field) => {
        const s = list.slice().sort(cmp);
        s.forEach((x, i) => { x[field] = i && cmp(s[i - 1], x) === 0 ? s[i - 1][field] : i + 1; });
    };
    rankBy((a, b) => b.t.bpi - a.t.bpi, "bpiRank");
    rankBy((a, b) => (b.pct - a.pct) || (b.r.wins - a.r.wins) || (a.r.losses - b.r.losses), "wlRank");
    list.forEach(x => { x.score = (x.sorRank + x.bpiRank + x.wlRank) / 3; });
    list.sort((a, b) => (a.score - b.score) || (a.sorRank - b.sorRank) || (a.bpiRank - b.bpiRank));
    return list.slice(0, PICKER_COUNT);
}

// Games finished since the quads snapshot (6 h overlap catches games in progress then;
// pickerGames() drops duplicates). Results land in _pickerRecent[season].
function pickerFetchRecent(season) {
    const qd = _quadsData[season];
    if (!qd?.fetched) return Promise.resolve();
    return fetchResultsBetween(qd.fetched - 6 * 3600 * 1000, Date.now())
        .then(r => { _pickerRecent[season] = r.byTeam; });
}
function pickerGames(season, key, id) {
    const base = _quadsData[season]?.played?.[key] || [];
    const tag = g => `${g.date.slice(0, 10)}:${g.opp.id}`;
    const seen = new Set(base.map(tag));
    const extra = (_pickerRecent[season]?.[id] || []).filter(g => !seen.has(tag(g)))
        .map(g => ({ ...g, quad: pickerRecentQuad(season, key, g) }));
    return trimPickerGames(base.concat(extra).filter(g => g.result === "W" || g.result === "L")
        .sort((a, b) => a.date.localeCompare(b.date)));
}
// Quad of a game finished since the quads snapshot: the snapshot's own quad for it (it was listed
// as upcoming, same opponent, start within a day), else from the opponent's current rank, the site
// and the file's cutoffs. null for non-D1 or unranked opponents.
function pickerRecentQuad(season, key, g) {
    const qd = _quadsData[season];
    if (!g.opp.key) return null;
    const t = Date.parse(g.date);
    const up = (qd?.upcoming?.[key] || []).find(u => u.opp.id === g.opp.id && Math.abs(Date.parse(u.date) - t) < 864e5);
    if (up?.quad) return up.quad;
    const rank = qd?.teams?.[g.opp.key]?.rank;
    const bounds = qd?.cutoffs?.[g.site];
    if (!rank || !bounds) return null;
    const i = bounds.findIndex(b => rank <= b);
    return i < 0 ? 4 : i + 1;
}
// Picker cell cap: with more than PICKER_GAMES games (date order), drop non-D1 wins, then Q4 wins,
// then Q3 wins (oldest first within each), then the oldest games left. Keeps date order.
function trimPickerGames(games) {
    if (games.length <= PICKER_GAMES) return games;
    const prio = g => g.result !== "W" ? 3 : !g.opp.key ? 0 : g.quad === 4 ? 1 : g.quad === 3 ? 2 : 3;
    const drop = new Set(games.map((g, i) => ({ g, i, p: prio(g) }))
        .sort((a, b) => a.p - b.p || a.i - b.i)
        .slice(0, games.length - PICKER_GAMES).map(x => x.g));
    return games.filter(g => !drop.has(g));
}

function buildPickerTableHtml(season, data, error) {
    const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const qd = _quadsData[season];
    const COLS = 11;
    const quadTip = qd?.source === "net"
        ? "NCAA quadrant record (D1 only)"
        : "Unofficial quadrant record, BPI for NET (D1 only)";
    const head = `<colgroup>
        <col style="width:28px"><col style="width:26px"><col>
        <col style="width:44px"><col style="width:40px"><col style="width:46px">
        ${"<col style=\"width:34px\">".repeat(4)}<col>
    </colgroup><thead><tr>
        <th>#</th><th></th><th class="team-col">Team</th><th>W-L</th>
        <th title="ESPN Strength of Record rank (lower is better)">SOR</th>
        <th title="ESPN BPI: points above an average D1 team per 70 possessions">BPI</th>
        ${[1, 2, 3, 4].map(q => `<th class="records-quad-col${q === 1 ? " records-q1-col" : ""}${q === 4 ? " records-q4-col" : ""}" title="${quadTip}">Q${q}</th>`).join("")}
        <th class="records-opps-col tp-wins-col" title="Last ${PICKER_GAMES} games; non-D1, Q4, then Q3 wins drop out first">Last ${PICKER_GAMES} Games</th>
    </tr></thead>`;
    const msg = text => `${head}<tbody><tr><td colspan="${COLS}" class="records-msg">${text}</td></tr></tbody>`;
    if (!data) return msg(error ? `Couldn't load records from ESPN (${esc(error)}). <span class="records-retry">Retry</span>` : "Loading");
    if (qd?.error) return msg(`Couldn't load SOR / BPI (${esc(qd.error)}).`);
    if (!qd) return msg("Loading");

    const cands = pickerCandidates(season, data);
    if (!cands.length) return msg("No SOR / BPI data yet.");
    const byKey = new Map(cands.map(c => [c.key, c]));
    let order = cands.map(c => c.key);
    const saved = pickerSavedOrder(season);
    if (saved) {
        const kept = saved.filter(k => byKey.has(k));
        const keptSet = new Set(kept);
        cands.forEach((c, i) => { if (!keptSet.has(c.key)) kept.splice(Math.min(i, kept.length), 0, c.key); });
        order = kept;
    }

    const rankLabel = qd.source === "net" ? "NET" : "BPI";
    const num = v => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1);
    const show = pickerShowMode();
    // Chip value after the logo: score, the opponent's current BPI / W-L, or the game's quad ("—" for non-D1 or missing).
    const chipValue = g => {
        if (show === "bpi") { const b = g.opp.key ? qd.teams[g.opp.key]?.bpi : null; return b == null ? "—" : num(b); }
        if (show === "record") { const r = g.opp.key ? data.byId[g.opp.id] : null; return r ? `${r.wins}-${r.losses}` : "—"; }
        if (show === "quad") return g.quad ? `Q${g.quad}` : "—";
        return `${g.us}-${g.them}`;
    };
    const chip = g => {
        const siteWord = g.site === "H" ? "vs" : g.site === "A" ? "@" : "neutral vs";
        const name = g.opp.key ? conferenceDisplayName(g.opp.key) : g.opp.name || "?";
        const oppRank = g.opp.key ? qd.teams[g.opp.key]?.rank : null;
        const dateOnly = g.date.length <= 10;
        const day = new Date(dateOnly ? `${g.date}T12:00:00Z` : g.date)
            .toLocaleDateString([], { month: "short", day: "numeric", ...(dateOnly ? { timeZone: "UTC" } : {}) });
        const tip = esc(`${g.result} ${g.us}-${g.them} ${siteWord} ${name}${oppRank ? ` (${rankLabel} #${oppRank})` : g.opp.key ? "" : " (non-D1)"} · ${day}${g.quad ? ` · Q${g.quad}` : ""}${g.note ? ` · ${g.note}` : ""}`);
        const src = g.opp.key ? null : oppLogoSrc(g.opp) || (g.opp.id ? espnLogoUrl(g.opp.id) : null);
        const logo = g.opp.key
            ? `<img class="records-opp-logo records-logo" data-team="${esc(g.opp.key)}" data-espn="${g.opp.id}" alt="">`
            : src ? `<img class="records-opp-logo" src="${esc(src)}" data-filler="${esc(name)}" alt="">`
            : logoFillerHtml("records-opp-logo", name, "");
        return `<span class="ws-opp ${g.result === "W" ? "ws-win" : "ws-loss"}"${g.opp.key ? ` data-team="${esc(g.opp.key)}"` : ""} title="${tip}"><span class="ws-opp-site">${g.site === "H" ? "vs" : g.site === "A" ? "@" : "N"}</span>${logo}<span class="ws-opp-score">${chipValue(g)}</span></span>`;
    };
    const body = order.map((k, i) => {
        const c = byKey.get(k);
        const fullName = conferenceDisplayName(c.key);
        const name = fullName.length > RECORDS_NAME_MAX && c.r.name && c.r.name.length < fullName.length ? c.r.name : fullName;
        const tip = `Eligibility ${c.score.toFixed(1)} (#${cands.indexOf(c) + 1}): avg of SOR #${c.sorRank}, BPI #${c.bpiRank}, W-L #${c.wlRank}`;
        const games = pickerGames(season, c.key, c.id);
        return `<tr class="tp-row records-team-row${i === 24 ? " records-t25-end" : ""}" data-team="${esc(c.key)}" data-espn="${c.id}">
            <td class="tp-num tp-handle">${i + 1}</td>
            <td class="tp-handle"><img class="logo-sm records-logo" data-team="${esc(c.key)}" data-espn="${c.id}" alt=""></td>
            <td class="team-col tp-handle" title="${esc(`${fullName} · ${tip}`)}">${esc(name)}</td>
            <td class="records-wl">${c.r.wins}-${c.r.losses}</td>
            <td class="records-resume">${c.sorRank}</td>
            <td class="records-bpi records-bpi-main" title="BPI #${c.bpiRank}">${num(c.t.bpi)}</td>
            ${[1, 2, 3, 4].map(q => `<td class="records-quad${q === 1 ? " records-q1" : ""}${q === 4 ? " records-q4" : ""}">${esc(c.t[`q${q}`] ?? "—")}</td>`).join("")}
            <td class="ws-res tp-wins">${games.length ? `<div class="ws-res-list">${games.map(chip).join("")}</div>` : `<span class="records-opps-msg">—</span>`}</td>
        </tr>`;
    }).join("");
    return `${head}<tbody class="tp-body">${body}</tbody>`;
}

// Drag-to-reorder for the Picker rows. Mouse: drag anywhere on a row; touch/pen: drag by the
// #, logo or name cells (touch-action: none there) so the rest of the row still scrolls.
// The DOM isn't touched until the drop: row geometry is measured once at pointer-down-and-move,
// then each frame (pointer moves are coalesced to one update per animation frame) only sets
// `transform`s: the dragged row follows the pointer and the rows it passes slide out of its way
// (CSS transition on .tp-drag-active rows). That keeps dragging off the layout / nth-child
// restyle path of a 100-row auto-layout table. A row takes a neighbour's slot once the pointer
// is PICKER_SWAP_AT (a quarter) of the way into it; moving back needs a quarter into the other
// row again, so rows don't flicker at the boundary. Positional bits (the # cells, zebra stripes
// via .tp-alt, the line after #25 via .tp-line) follow the slots with paint-only changes.
// Drop = one DOM reorder, then the dragged row settles into its slot. Near the window's
// top/bottom edge it autoscrolls. A row's open game list (records-games-row, from a click;
// toggleTeamGames()) moves with it as one unit.
const PICKER_SWAP_AT = 0.25;
const PICKER_SLIDE_MS = 140;
function initPickerDrag(tbody, season, onDrop) {
    const box = tbody.closest("#season-stats-box") || document.scrollingElement;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let drag = null;
    const rows = () => [...tbody.querySelectorAll("tr.tp-row")];
    const gamesOf = tr => tr.nextElementSibling?.classList.contains("records-games-row") ? tr.nextElementSibling : null;
    const boxTop = () => box === document.scrollingElement ? 0 : box.getBoundingClientRect().top;
    // Pointer y in scroll-content coordinates, so autoscroll needs no re-measuring.
    const contentY = clientY => clientY - drag.boxTop + box.scrollTop;
    const setTransform = (u, dy) => {
        if (u.dy === dy) return;
        u.dy = dy;
        const t = dy ? `translateY(${dy}px)` : "";
        for (const el of u.els) el.style.transform = t;
    };

    const start = () => {
        drag.boxTop = boxTop();
        const scroll = box.scrollTop;
        // One unit per team: its row plus an open game list. Tops/heights in content coordinates.
        drag.units = rows().map((tr, i) => {
            const els = [tr, gamesOf(tr)].filter(Boolean);
            const r0 = els[0].getBoundingClientRect(), r1 = els.at(-1).getBoundingClientRect();
            return { tr, els, top: r0.top - drag.boxTop + scroll, h: r1.bottom - r0.top, dy: 0, slot: i };
        });
        drag.unit = drag.units.find(u => u.tr === drag.tr);
        drag.order = drag.units.slice();            // current visual order, dragged unit included
        drag.base = drag.units[0].top;
        drag.grabOff = contentY(drag.y) - drag.unit.top;
        drag.tr.classList.add("tp-dragging");
        tbody.classList.add("tp-drag-active");
        if (reduceMotion) tbody.classList.add("tp-no-slide");
        drag.order.forEach((u, i) => u.tr.classList.toggle("tp-alt", i % 2 === 1));
        drag.units[24]?.tr.classList.add("tp-line");
    };

    // Re-lay the visual order from the pointer position; only the changed units get new styles.
    const update = () => {
        drag.raf = 0;
        if (!tbody.isConnected) return;
        const y = contentY(drag.lastY);
        const { order, unit } = drag;
        const from = order.indexOf(unit);
        // Slot tops for the current order.
        const tops = [];
        let acc = drag.base;
        for (const u of order) { tops.push(acc); acc += u.h; }
        let to = from;
        for (let i = from - 1; i >= 0; i--) {         // up: a quarter of the way up into each row above
            if (y < tops[i] + order[i].h * (1 - PICKER_SWAP_AT)) to = i; else break;
        }
        if (to === from) {                             // down: a quarter of the way down into each row below
            for (let i = from + 1; i < order.length; i++) {
                if (y > tops[i] + order[i].h * PICKER_SWAP_AT) to = i; else break;
            }
        }
        if (to !== from) {
            order.splice(from, 1);
            order.splice(to, 0, unit);
            let top = drag.base;
            order.forEach((u, i) => {
                if (u !== unit) setTransform(u, top - u.top);
                if (u.slot !== i) {
                    u.slot = i;
                    u.tr.firstElementChild.textContent = i + 1;
                    u.tr.classList.toggle("tp-alt", i % 2 === 1);
                    u.tr.classList.toggle("tp-line", i === 24);
                }
                top += u.h;
            });
        }
        // The dragged unit sits under the pointer where it was grabbed, kept inside the table.
        const want = Math.max(drag.base, Math.min(acc - unit.h, y - drag.grabOff));
        setTransform(unit, want - unit.top);
    };
    const schedule = () => { if (!drag.raf) drag.raf = requestAnimationFrame(update); };

    const autoScroll = () => {
        if (!drag?.started || !tbody.isConnected) return;
        const b = box === document.scrollingElement ? { top: 0, bottom: innerHeight } : box.getBoundingClientRect();
        const edge = 48;
        const dy = drag.lastY < b.top + edge ? drag.lastY - (b.top + edge)
            : drag.lastY > b.bottom - edge ? drag.lastY - (b.bottom - edge) : 0;
        if (dy) {
            const before = box.scrollTop;
            box.scrollTop += Math.max(-24, Math.min(24, dy / 2));
            if (box.scrollTop !== before) update();
        }
        requestAnimationFrame(autoScroll);
    };

    tbody.addEventListener("pointerdown", e => {
        if (e.button !== 0) return;
        const tr = e.target.closest("tr.tp-row");
        if (!tr) return;
        if (e.pointerType !== "mouse" && !e.target.closest(".tp-handle")) return;
        drag = { tr, id: e.pointerId, x: e.clientX, y: e.clientY, lastY: e.clientY, started: false, raf: 0 };
    });
    tbody.addEventListener("pointermove", e => {
        if (!drag || e.pointerId !== drag.id) return;
        drag.lastY = e.clientY;
        if (!drag.started) {
            if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 5) return;
            drag.started = true;
            try { tbody.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
            start();
            requestAnimationFrame(autoScroll);
        }
        e.preventDefault();
        schedule();
    });
    const end = e => {
        if (!drag || e.pointerId !== drag.id) return;
        const d = drag;
        drag = null;
        if (!d.started) return;
        if (d.raf) cancelAnimationFrame(d.raf);
        if (!tbody.isConnected) return;
        // Where the dragged unit is drawn now, so it can glide from there into its slot.
        const shown = d.unit.top + d.unit.dy;
        // One DOM reorder into the visual order, then drop every drag-time style.
        const frag = document.createDocumentFragment();
        for (const u of d.order) frag.append(...u.els);
        tbody.append(frag);
        tbody.classList.add("tp-no-slide");
        for (const u of d.units) {
            for (const el of u.els) el.style.transform = "";
            u.tr.classList.remove("tp-alt", "tp-line");
        }
        d.order.forEach((u, i) => {
            u.tr.firstElementChild.textContent = i + 1;
            u.tr.classList.toggle("records-t25-end", i === 24);
        });
        d.tr.classList.remove("tp-dragging");
        tbody.classList.remove("tp-drag-active");
        tbody.getBoundingClientRect();     // commit the un-transformed layout before re-enabling slides
        tbody.classList.remove("tp-no-slide");
        const settle = shown - d.order.slice(0, d.order.indexOf(d.unit)).reduce((t, u) => t + u.h, d.base);
        if (settle && !reduceMotion) {
            // Glide on top of the other rows: .tp-settling keeps the row's z-index through the glide,
            // which after an upward drag ends over the row below it (later in the DOM).
            d.tr.classList.add("tp-settling");
            const anims = d.unit.els.map(el => el.animate([{ transform: `translateY(${settle}px)` }, { transform: "none" }],
                { duration: PICKER_SLIDE_MS, easing: "ease-out" }));
            anims[0]?.finished.then(() => d.tr.classList.remove("tp-settling"), () => d.tr.classList.remove("tp-settling"));
        }
        _pickerSuppressClickUntil = Date.now() + 300;   // the click that ends a drag isn't a logo click
        pickerSaveOrder(season, rows().map(r => r.dataset.team));
        onDrop?.();
    };
    tbody.addEventListener("pointerup", end);
    tbody.addEventListener("pointercancel", end);
    tbody.addEventListener("click", e => {
        if (Date.now() < _pickerSuppressClickUntil) { e.stopImmediatePropagation(); e.preventDefault(); }
    }, true);
}

// Voters tab of the Year window: one row per voter on official ballots this season.
// Uses the same distance-from-consensus measure as the homepage Consensus sort: each
// ballot is compared with that week's leave-one-out consensus (makeLooConsensus(), seeded
// with the rendered Official Overall order), via consensusTeamGaps() / consensusDistance().
//   Cons Δ   = mean over the voter's ballots of consensusDistance() (the "+N" on the
//              homepage sort: places the ballot's teams moved up vs. consensus); lower = closer.
//   #1 Pick  = team the voter ranked #1 most often (ties: most recent).
//   Favorite / Least Fav. = team with the largest positive / negative total signed gap
//              (consensus rank − voter rank, from consensusTeamGaps()), divided by the weeks
//              the voter voted, so season-long bias beats a one-week outlier.
// Voters below the participation minimum sort after the rest, in italics.
function buildSeasonVotersTableHtml(weekBallots, voterWeeksVoted, minWeeksVoted, totalWeeks, esc) {
    const voters = {};
    weekBallots.forEach(({ ballots, consensusOrder }) => {
        if (ballots.length === 0) return;
        const officialBallots = {};
        ballots.forEach(b => { if (b.teams.length) officialBallots[b.voter] = b.teams; });
        // Fallback when a week has no rendered aggregate row: points order (same as Python).
        let aggOrder = consensusOrder;
        if (!aggOrder?.length) {
            const pts = {};
            Object.values(officialBallots).forEach(teams =>
                teams.slice(0, 25).forEach((t, i) => { pts[t] = (pts[t] || 0) + (25 - i); }));
            aggOrder = Object.keys(pts).sort((a, b) => pts[b] - pts[a]).slice(0, 25);
        }
        const consensusFor = makeLooConsensus(officialBallots, aggOrder);
        ballots.forEach(b => {
            const v = voters[b.voter] || (voters[b.voter] = { name: b.voter, flair: null, deltaSum: 0, ballots: 0, ones: {}, teamDev: {} });
            if (b.flair) v.flair = b.flair;
            if (b.teams.length) {
                const cons = consensusFor(b.voter);
                v.deltaSum += consensusDistance(b.teams, cons);
                v.ballots++;
                consensusTeamGaps(b.teams, cons).forEach(({ team, gap }) => {
                    v.teamDev[team] = (v.teamDev[team] || 0) + gap;
                });
            }
            const one = Object.keys(b.ranks).find(t => b.ranks[t] === 1);
            if (one) {
                v.ones[one] = (v.ones[one] || 0) + 1;
                v.lastOne = one;
            }
        });
    });

    // Favorite / least favorite per voter from the season's signed gap sums
    Object.values(voters).forEach(v => {
        Object.entries(v.teamDev).forEach(([team, sum]) => {
            const d = sum / voterWeeksVoted[v.name];
            if (d > 0 && (!v.fav || d > v.fav.d)) v.fav = { team, d };
            if (d < 0 && (!v.hate || d < v.hate.d)) v.hate = { team, d };
        });
    });

    const rows = Object.values(voters).map(v => ({
        ...v,
        delta: v.ballots ? v.deltaSum / v.ballots : Infinity,
        qualified: voterWeeksVoted[v.name] >= minWeeksVoted,
    })).sort((a, b) => (b.qualified - a.qualified) || (a.delta - b.delta)
        || a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));

    const teamCell = (team, extra) => team
        ? `<img class="logo-sm" src="${logoSrc(team)}"> ${formatTeamName(team)} ${extra}`
        : "—";
    const devSpan = d => `<span class="fan-dev">${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)}</span>`;

    let html = `<colgroup>
        <col style="width:24px">
        <col style="width:26px">
        <col>
        <col style="width:52px">
        <col style="width:52px">
        <col>
        <col>
        <col>
    </colgroup><thead><tr>
        <th>#</th><th></th>
        <th class="team-col">Voter</th>
        <th>Weeks</th>
        <th title="Avg places off weekly consensus per ballot (lower = closer)">Cons Δ</th>
        <th class="fan-col">#1 Pick</th>
        <th class="fan-col">Favorite</th>
        <th class="fan-col">Least Fav.</th>
    </tr></thead><tbody>`;
    rows.forEach((v, i) => {
        let onePick = null, oneCount = 0;
        Object.entries(v.ones).forEach(([t, c]) => {
            if (c > oneCount || (c === oneCount && t === v.lastOne)) { onePick = t; oneCount = c; }
        });
        html += `<tr${v.qualified ? "" : ` class="fan-low-sample" title="Fewer than ${minWeeksVoted} ballots"`}>
            <td>${i + 1}</td>
            <td>${v.flair ? `<img class="logo-sm" src="${logoSrc(v.flair)}">` : ""}</td>
            <td class="team-col">${esc(v.name)}</td>
            <td>${voterWeeksVoted[v.name]}/${totalWeeks}</td>
            <td>${Number.isFinite(v.delta) ? v.delta.toFixed(1) : "—"}</td>
            <td class="fan-col">${teamCell(onePick, `<span class="fan-dev">×${oneCount}</span>`)}</td>
            <td class="fan-col">${v.fav ? teamCell(v.fav.team, devSpan(v.fav.d)) : "—"}</td>
            <td class="fan-col">${v.hate ? teamCell(v.hate.team, devSpan(v.hate.d)) : "—"}</td>
        </tr>`;
    });
    return html + `</tbody>`;
}

function showBumpChartModal() { showHeatmapModal('dots'); }

let _hmHighlightedTeam = null;
function hmHighlight(team) {
    const imgs = document.querySelectorAll('#heatmap-container .hm-logo');
    if (_hmHighlightedTeam === team) {
        imgs.forEach(img => img.style.opacity = '');
        _hmHighlightedTeam = null;
    } else {
        imgs.forEach(img => img.style.opacity = img.dataset.hmTeam === team ? '1' : '0.15');
        _hmHighlightedTeam = team;
    }
}

function showHeatmapModal(mode = 'grid') {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const isApMode = _apCurrentYear !== null;
    const currentYear = isApMode ? String(_apCurrentYear) : activeTab.dataset.year;
    const allTabs = isApMode ? getSortedApTabs() : getSortedTabs();
    const yearTabs = allTabs.filter(t => t.dataset.year === currentYear).reverse(); // oldest → newest
    if (yearTabs.length === 0) return;

    function getConsensusRanks(weekId) {
        const block = document.getElementById(weekId);
        if (!block) return null;
        const sections = block.querySelectorAll(".ballot-section");
        const aggSection = sections[2];
        if (aggSection) {
            const aggRow = aggSection.querySelector(".voter-row");
            if (aggRow) {
                const rankMap = {};
                Array.from(aggRow.querySelectorAll(".team-logo")).forEach((img, i) => {
                    if (i < 25) rankMap[img.dataset.team] = i + 1;
                });
                if (Object.keys(rankMap).length > 0) return rankMap;
            }
        }
        const officialSection = sections[0];
        if (!officialSection) return null;
        for (const row of officialSection.querySelectorAll(".voter-row")) {
            if (getVoterName(row) === "Official Overall") {
                const rankMap = {};
                Array.from(row.querySelectorAll(".team-logo")).forEach((img, i) => {
                    if (i < 25) rankMap[img.dataset.team] = i + 1;
                });
                return Object.keys(rankMap).length > 0 ? rankMap : null;
            }
        }
        return null;
    }

    // Top 25 from most recent loaded week
    let top25 = null;
    for (let i = yearTabs.length - 1; i >= 0; i--) {
        const ranks = getConsensusRanks(yearTabs[i].dataset.week);
        if (ranks) {
            top25 = Object.entries(ranks).sort((a, b) => a[1] - b[1]).map(([t]) => t);
            break;
        }
    }
    if (!top25 || top25.length === 0) return;

    // Only show weeks that have loaded consensus data
    const weekData = yearTabs
        .map(tab => ({ tab, ranks: getConsensusRanks(tab.dataset.week) }))
        .filter(d => d.ranks !== null);
    if (weekData.length === 0) return;

    // Ranks 1–26: deep green → pale green
    function rankColor(rank) {
        const t = (rank - 1) / 25;
        const r = Math.round(20  + t * 210); // 20  → 230
        const g = Math.round(110 + t * 130); // 110 → 240
        const b = Math.round(40  + t * 180); // 40  → 220
        return { bg: `rgb(${r},${g},${b})`, fg: '#fff' };
    }

    const escapedYear = CSS.escape(currentYear);
    const toggles = ``;

    let html;

    if (mode === 'dots') {
        // SVG bump chart: X = week, Y = rank, each team = unique color
        const W = 1150, H = 600;
        const mL = 44, mR = 16, mT = 20, mB = 44;
        const cW = W - mL - mR, cH = H - mT - mB;
        const n = weekData.length;
        const xPos = i => mL + (i + 0.5) * (cW / n);
        const yPos = r => mT + ((r - 1) / 24) * cH; // r=1 top, r=25 bottom
        const sz = 18;
        _hmHighlightedTeam = null;

        const { axisColor: hmAxis, gridColor: hmGrid, borderColor: hmBorder } = svgColors();
        let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" style="width:min(1120px,92vw);display:block;margin:0 auto;">`;

        // Gridlines + y-axis labels
        [1, 5, 10, 15, 20, 25].forEach(r => {
            const y = yPos(r).toFixed(1);
            s += `<line x1="${mL}" x2="${mL + cW}" y1="${y}" y2="${y}" stroke="${hmGrid}" stroke-width="1"/>`;
            s += `<text x="${mL - 6}" y="${(yPos(r) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="${hmAxis}">${r}</text>`;
        });

        // Chart border
        s += `<rect x="${mL}" y="${mT}" width="${cW}" height="${cH}" fill="none" stroke="${hmBorder}" stroke-width="1"/>`;

        // Y-axis label
        const yMid = (mT + cH / 2).toFixed(1);
        s += `<text x="10" y="${yMid}" text-anchor="middle" font-size="11" fill="${hmAxis}" transform="rotate(-90,10,${yMid})">Rank</text>`;

        // X-axis week labels
        weekData.forEach(({ tab }, wi) => {
            const wn = tab.dataset.weeknum;
            const label = wn === "0" ? "Pre" : `W${wn}`;
            s += `<text x="${xPos(wi).toFixed(1)}" y="${(mT + cH + 14).toFixed(1)}" text-anchor="middle" font-size="10" fill="${hmAxis}">${label}</text>`;
        });

        // Per-team rank arrays (ranked weeks only)
        const teamPoints = top25.map((team, ti) => ({
            team, ti,
            pts: weekData.map(({ ranks }, wi) => ({ wi, rank: ranks[team] || null }))
        }));

        // Logos — uniform size, clickable to highlight
        teamPoints.forEach(({ team, pts }) => {
            const name = formatTeamName(team);
            pts.forEach(({ wi, rank }) => {
                if (!rank) return;
                const cx = xPos(wi);
                const cy = yPos(rank);
                s += `<image class="hm-logo" data-hm-team="${team}" href="${logoSrc(team)}" x="${(cx - sz / 2).toFixed(1)}" y="${(cy - sz / 2).toFixed(1)}" width="${sz}" height="${sz}" style="cursor:pointer" onclick="hmHighlight('${team}')"><title>${name} — #${rank}</title></image>`;
            });
        });

        s += `</svg>`;
        html = toggles + s;
    } else {
        html = toggles + `<table class="heatmap-table"><thead><tr>
            <th class="heatmap-rank-col"></th>
            <th class="heatmap-team-col">Team</th>`;
        weekData.forEach(({ tab }) => {
            const wn = tab.dataset.weeknum;
            html += `<th class="heatmap-wk-th">${wn === "0" ? "Pre" : wn}</th>`;
        });
        html += `</tr></thead><tbody>`;
        top25.forEach((team, idx) => {
            html += `<tr><td class="heatmap-rank-col">${idx + 1}</td>
                <td class="heatmap-team-col"><img class="heatmap-logo" src="${logoSrc(team)}" width="16" height="16" onerror="this.style.display='none'"><span>${formatTeamName(team)}</span></td>`;
            weekData.forEach(({ ranks }) => {
                const rank = ranks[team] || null;
                const { bg, fg } = rankColor(rank ?? 26);
                const label = rank ?? 'x';
                html += `<td class="heatmap-cell" style="background:${bg};color:${fg}">${label}</td>`;
            });
            html += `</tr>`;
        });
        html += `</tbody></table>`;
    }

    const modal = document.getElementById("heatmap-modal");
    document.getElementById("heatmap-title").textContent = mode === 'dots'
        ? `${currentYear} Season Rank Trajectory`
        : `${currentYear} Season Consensus Rank Heatmap`;
    document.getElementById("heatmap-container").innerHTML = html;
    modal.dataset.mode = mode;
    modal.classList.add("open");
}

function showTenureModal() {
    const isApToggle = _apCurrentYear !== null;
    const isAp = ON_AP_PAGE || isApToggle;

    let currentYear, yearTabs;
    if (isApToggle) {
        currentYear = String(_apCurrentYear);
        yearTabs = getSortedApTabs().filter(t => t.dataset.year === currentYear).reverse();
    } else {
        const activeTab = document.querySelector(".week-tab.active");
        if (!activeTab) return;
        currentYear = activeTab.dataset.year;
        yearTabs = getSortedTabs().filter(t => t.dataset.year === currentYear).reverse();
    }
    if (yearTabs.length === 0) return;

    const ballotCount = isAp ? AP_TENURE_COUNTS : TENURE_COUNTS;
    const skipName = isAp ? "AP Overall" : "Official Overall";
    const lbData = buildLeaderboardData();

    // Collect all voters who appeared in any week this year
    const voterSet = new Set();
    yearTabs.forEach(tab => {
        const weekData = lbData[tab.dataset.week];
        if (!weekData) return;
        Object.keys(weekData).forEach(u => { if (u !== skipName && u !== "Recency") voterSet.add(u); });
    });

    const voters = Array.from(voterSet).sort((a, b) => (ballotCount[b] ?? 0) - (ballotCount[a] ?? 0));

    const modal = document.getElementById("tenure-modal");
    const title = document.getElementById("tenure-title");
    const table = document.getElementById("tenure-table");

    title.textContent = isAp ? `${currentYear} AP Tenure Leaderboard` : `${currentYear} Tenure Leaderboard`;

    let html = `<colgroup>
        <col style="width:28px">
        <col>
        <col style="width:80px">
    </colgroup><thead><tr>
        <th>#</th>
        <th class="name-col">Voter</th>
        <th title="All-time ballots">Ballots</th>
    </tr></thead><tbody>`;

    voters.forEach((username, i) => {
        const count = ballotCount[username] ?? 0;
        html += `<tr>
            <td>${i + 1}</td>
            <td class="name-col">${username}</td>
            <td>${count || '—'}</td>
        </tr>`;
    });

    html += `</tbody>`;
    table.innerHTML = html;
    modal.classList.add("open");
}

// ── Ballot submission times (Shift+S, PIN-locked) ───────────────────────────
// cbbpoll.net ballot ids are MongoDB ObjectIds, so the first 8 hex chars are the time the
// ballot was first created (later edits don't change it). Seasons from BALLOT_TIMES_FIRST_YEAR
// only. Week tab: every ballot of the active week by time (ET). Season tab: each week's
// cumulative share of ballots against hours before its deadline, plus a summary table.
// "Deadline" = the week's last ballot rounded up to the hour (no deadline is scraped).
const BALLOT_TIMES_FIRST_YEAR = 2027;
const BALLOT_TIMES_TZ = "America/New_York";
const BALLOT_TIMES_WINDOW_MS = 7 * 864e5;   // Week tab shows at most the last 7 days
const BALLOT_TIMES_SEASON_HOURS = 72;       // Season tab x-axis span
let _ballotTimesMode = "week";

const _btFmt = new Intl.DateTimeFormat("en-US", { timeZone: BALLOT_TIMES_TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const _btFmtSec = new Intl.DateTimeFormat("en-US", { timeZone: BALLOT_TIMES_TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
const _btTimeFmt =new Intl.DateTimeFormat("en-US", { timeZone: BALLOT_TIMES_TZ, hour: "numeric", minute: "2-digit" });
const _btDayFmt = new Intl.DateTimeFormat("en-US", { timeZone: BALLOT_TIMES_TZ, weekday: "short", month: "short", day: "numeric" });
const _btHourFmt = new Intl.DateTimeFormat("en-US", { timeZone: BALLOT_TIMES_TZ, hour: "numeric", hourCycle: "h23" });

// [{name, time (ms), official}] for a week block, sorted by time.
function weekBallotTimes(weekId) {
    const out = [];
    ["official", "provisional"].forEach(sec => {
        document.querySelectorAll(`#${weekId}-${sec} .voter-cell[data-ballot-url]`).forEach(el => {
            const m = /cbbpoll\.net\/ballots\/[^/]+\/([0-9a-f]{24})/.exec(el.dataset.ballotUrl);
            if (!m) return;
            out.push({
                name: el.querySelector(".voter-name")?.textContent || "?",
                time: parseInt(m[1].slice(0, 8), 16) * 1000,
                official: sec === "official",
            });
        });
    });
    return out.sort((a, b) => a.time - b.time);
}

function ballotTimesDeadline(ballots) {
    const last = ballots[ballots.length - 1].time;
    return Math.ceil(last / 36e5) * 36e5;
}

function ballotTimesWeekName(tab) {
    if (isPreseasonTab(tab)) return "Pre-Season";
    return weekTextLabel(tab) || `Week ${String(displayWeekNum(tab)).padStart(2, "0")}`;
}

function _btSvg(W, H) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.classList.add("ballot-times-svg");
    return svg;
}
function _btEl(svg, tag, attrs, text) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (text !== undefined) el.textContent = text;
    svg.appendChild(el);
    return el;
}

async function showBallotTimesChart(mode) {
    if (_apCurrentYear !== null || ON_AP_PAGE) return;
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const year = activeTab.dataset.year;
    if (Number(year) < BALLOT_TIMES_FIRST_YEAR) return;
    if (mode) _ballotTimesMode = mode;
    await loadYear(year);

    const modal = document.getElementById("voter-history-modal");
    const title = document.getElementById("voter-history-title");
    const table = document.getElementById("voter-history-table");
    table.classList.remove("week-stats-table");
    table.style.cssText = "display:block; white-space:normal; width:100%;";
    table.innerHTML = "";

    const tabsHtml = [{ key: "week", label: "Week" }, { key: "season", label: "Season" }].map(m =>
        `<span class="modal-mode-tab${_ballotTimesMode === m.key ? " active" : ""}" onclick="showBallotTimesChart('${m.key}')">${m.label}</span>`
    ).join("");
    const heading = _ballotTimesMode === "week" ? `${year} ${ballotTimesWeekName(activeTab)}` : `${year}`;
    title.innerHTML = `${_ballotTimesMode === "week" ? modalWeekArrowsHtml() : ""}${heading} Ballot Times — ${tabsHtml}`;

    const body = _ballotTimesMode === "week"
        ? buildBallotTimesWeek(activeTab.dataset.week)
        : buildBallotTimesSeason(year, activeTab.dataset.week);
    table.appendChild(body);
    modal.dataset.chartType = "ballottimes";
    modal.classList.add("open");
}

function _btEmpty(msg) {
    const d = document.createElement("div");
    d.className = "ballot-times-empty";
    d.textContent = msg;
    return d;
}

// Week tab: cumulative step line per section; one dot per ballot (hover = voter + time).
function buildBallotTimesWeek(weekId) {
    const ballots = weekBallotTimes(weekId);
    if (ballots.length === 0) return _btEmpty("No ballot times for this week.");
    const deadline = ballotTimesDeadline(ballots);
    const start = Math.max(ballots[0].time, deadline - BALLOT_TIMES_WINDOW_MS);
    const x0 = Math.floor(start / 36e5) * 36e5;
    const clipped = ballots.filter(b => b.time < x0).length;

    const W = 900, H = 440, mL = 44, mR = 24, mT = 36, mB = 46;
    const cW = W - mL - mR, cH = H - mT - mB;
    const nOff = ballots.filter(b => b.official).length;
    const nProv = ballots.length - nOff;
    const yMax = Math.max(5, Math.ceil(Math.max(nOff, nProv) / 10) * 10);
    const xs = t => mL + (Math.max(t, x0) - x0) / (deadline - x0) * cW;
    const ys = n => mT + cH - n / yMax * cH;
    const svg = _btSvg(W, H);

    // Horizontal gridlines + y labels
    const yStep = yMax > 50 ? 20 : 10;
    for (let n = 0; n <= yMax; n += yStep) {
        _btEl(svg, "line", { x1: mL, x2: mL + cW, y1: ys(n), y2: ys(n), class: "bt-grid" });
        _btEl(svg, "text", { x: mL - 8, y: ys(n) + 4, "text-anchor": "end", class: "bt-axis" }, n);
    }
    // Midnight (ET) gridlines; 6 AM / noon / 6 PM ticks; each day's label centered
    // on its visible stretch (skipped when too narrow to fit)
    const spanH = (deadline - x0) / 36e5;
    const dayStarts = [x0];
    for (let t = x0; t <= deadline; t += 36e5) {
        const hr = parseInt(_btHourFmt.format(t), 10) % 24;
        if (hr === 0 && t > x0) {
            dayStarts.push(t);
            _btEl(svg, "line", { x1: xs(t), x2: xs(t), y1: mT, y2: mT + cH, class: "bt-grid bt-grid-day" });
        }
        if (hr === 12 || (spanH <= 60 && (hr === 6 || hr === 18))) {
            _btEl(svg, "text", { x: xs(t), y: mT + cH + 16, "text-anchor": "middle", class: "bt-axis bt-axis-minor" },
                hr === 12 ? "noon" : (hr === 6 ? "6a" : "6p"));
        }
    }
    dayStarts.forEach((t, i) => {
        const end = dayStarts[i + 1] ?? deadline;
        if (xs(end) - xs(t) < 70) return;
        _btEl(svg, "text", { x: (xs(t) + xs(end)) / 2, y: mT + cH + 32, "text-anchor": "middle", class: "bt-axis" },
            _btDayFmt.format(t + 1));
    });
    _btEl(svg, "line", { x1: mL, x2: mL + cW, y1: mT + cH, y2: mT + cH, class: "bt-axis-line" });
    // Deadline marker
    _btEl(svg, "line", { x1: xs(deadline), x2: xs(deadline), y1: mT - 6, y2: mT + cH, class: "bt-deadline" });
    _btEl(svg, "text", { x: xs(deadline) - 4, y: mT - 10, "text-anchor": "end", class: "bt-axis" },
        `Deadline ≈ ${_btTimeFmt.format(deadline)} ET`);

    // Step lines + dots
    [[true, "bt-official"], [false, "bt-provisional"]].forEach(([official, cls]) => {
        const list = ballots.filter(b => b.official === official);
        if (list.length === 0) return;
        let n = list.filter(b => b.time < x0).length;
        let d = `M${xs(x0)},${ys(n)}`;
        const dots = [];
        list.forEach(b => {
            if (b.time < x0) return;
            d += `H${xs(b.time)}V${ys(n + 1)}`;
            n++;
            dots.push([b, xs(b.time), ys(n)]);
        });
        d += `H${xs(deadline)}`;
        _btEl(svg, "path", { d, class: `bt-line ${cls}` });
        dots.forEach(([b, x, y]) => {
            const c = _btEl(svg, "circle", { cx: x, cy: y, r: 3.2, class: `bt-dot ${cls}` });
            _btEl(c, "title", {}, `${b.name} — ${_btFmt.format(b.time)} ET (${official ? "official" : "provisional"})`);
        });
    });

    // Legend
    [[`Official (${nOff})`, "bt-official"], [`Provisional (${nProv})`, "bt-provisional"]].forEach(([label, cls], i) => {
        const lx = mL + 10 + i * 150;
        _btEl(svg, "circle", { cx: lx, cy: mT + 10, r: 4, class: `bt-dot ${cls}` });
        _btEl(svg, "text", { x: lx + 9, y: mT + 14, class: "bt-legend" }, label);
    });

    const wrap = document.createElement("div");
    wrap.appendChild(svg);
    const note = document.createElement("div");
    note.className = "ballot-times-note";
    const last3 = ballots.filter(b => b.time >= deadline - 3 * 36e5).length;
    note.textContent = `${ballots.length} ballots · first ${_btFmt.format(ballots[0].time)} ET · `
        + `last ${_btFmt.format(ballots[ballots.length - 1].time)} ET · ${last3} in the final 3 hours`
        + (clipped ? ` · ${clipped} earlier ballot${clipped === 1 ? "" : "s"} not shown` : "")
        + ". Times are when each ballot was first created.";
    wrap.appendChild(note);

    // Every ballot of the week (incl. any clipped from the chart), in submission order
    const fmtBefore = ms => {
        const m = Math.round(ms / 6e4), h = Math.floor(m / 60);
        return h >= 24 ? `${Math.floor(h / 24)}d ${h % 24}h` : (h ? `${h}h ${m % 60}m` : `${m}m`);
    };
    const tbl = document.createElement("table");
    tbl.className = "ballot-times-table bt-week-table";
    tbl.innerHTML = `<thead><tr><th>#</th><th class="name-col">Voter</th><th class="name-col">Type</th>`
        + `<th title="Ballot creation time">Submitted (ET)</th><th title="Before est. deadline">Before deadline</th></tr></thead><tbody></tbody>`;
    const tbody = tbl.querySelector("tbody");
    ballots.forEach((b, i) => {
        const tr = document.createElement("tr");
        const cls = b.official ? "bt-official" : "bt-provisional";
        [String(i + 1), b.name, b.official ? "Official" : "Provisional", _btFmtSec.format(b.time), fmtBefore(deadline - b.time)]
            .forEach((v, c) => {
                const td = document.createElement("td");
                if (c === 1 || c === 2) td.className = "name-col";
                if (c === 2) td.innerHTML = `<span class="bt-type-dot ${cls}"></span>`;
                td.appendChild(document.createTextNode(v));
                tr.appendChild(td);
            });
        tbody.appendChild(tr);
    });
    wrap.appendChild(tbl);
    return wrap;
}

// Season tab: one curve per week (cumulative % of ballots vs hours before deadline).
function buildBallotTimesSeason(year, activeWeekId) {
    const weeks = getSortedTabs().filter(t => t.dataset.year === year).reverse().map(tab => {
        const ballots = weekBallotTimes(tab.dataset.week);
        return ballots.length ? { tab, ballots, deadline: ballotTimesDeadline(ballots) } : null;
    }).filter(Boolean);
    if (weeks.length === 0) return _btEmpty("No ballot times for this season.");

    const W = 900, H = 420, mL = 48, mR = 24, mT = 24, mB = 40;
    const cW = W - mL - mR, cH = H - mT - mB;
    const span = BALLOT_TIMES_SEASON_HOURS;
    const xs = h => mL + (span - Math.min(h, span)) / span * cW;   // h = hours before deadline
    const ys = p => mT + cH - p * cH;
    const svg = _btSvg(W, H);

    for (let p = 0; p <= 1.0001; p += 0.25) {
        _btEl(svg, "line", { x1: mL, x2: mL + cW, y1: ys(p), y2: ys(p), class: "bt-grid" });
        _btEl(svg, "text", { x: mL - 8, y: ys(p) + 4, "text-anchor": "end", class: "bt-axis" }, `${Math.round(p * 100)}%`);
    }
    for (let h = 0; h <= span; h += 12) {
        _btEl(svg, "line", { x1: xs(h), x2: xs(h), y1: mT, y2: mT + cH, class: h % 24 === 0 ? "bt-grid bt-grid-day" : "bt-grid" });
        _btEl(svg, "text", { x: xs(h), y: mT + cH + 18, "text-anchor": "middle", class: "bt-axis" }, h === 0 ? "deadline" : `−${h}h`);
    }
    _btEl(svg, "line", { x1: mL, x2: mL + cW, y1: mT + cH, y2: mT + cH, class: "bt-axis-line" });
    _btEl(svg, "text", { x: mL + cW / 2, y: H - 4, "text-anchor": "middle", class: "bt-axis bt-axis-minor" }, "hours before deadline");

    // Inactive weeks first so the active one draws on top
    const labels = [];
    const ordered = weeks.filter(w => w.tab.dataset.week !== activeWeekId)
        .concat(weeks.filter(w => w.tab.dataset.week === activeWeekId));
    ordered.forEach(w => {
        const active = w.tab.dataset.week === activeWeekId;
        const total = w.ballots.length;
        const hrs = w.ballots.map(b => (w.deadline - b.time) / 36e5);
        let n = hrs.filter(h => h > span).length;
        let d = `M${xs(span)},${ys(n / total)}`;
        hrs.forEach(h => {
            if (h > span) return;
            d += `H${xs(h)}V${ys(++n / total)}`;
        });
        d += `H${xs(0)}`;
        const path = _btEl(svg, "path", { d, class: `bt-line bt-season-line${active ? " bt-season-active" : ""}` });
        _btEl(path, "title", {}, `${ballotTimesWeekName(w.tab)} — ${total} ballots`);
        labels.push({ y: ys(hrs.filter(h => h > span).length / total) - 4, text: ballotTimesWeekName(w.tab), active });
    });
    // Week labels at the left edge, nudged apart so they don't overlap
    labels.sort((a, b) => b.y - a.y);
    labels.forEach((l, i) => {
        if (i > 0) l.y = Math.min(l.y, labels[i - 1].y - 13);
        _btEl(svg, "text", { x: xs(span) + 4, y: l.y, class: `bt-legend${l.active ? " bt-season-label-active" : " bt-axis-minor"}` }, l.text);
    });

    // Summary table
    const median = arr => { const s = arr.slice().sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
    const fmtH = h => h >= 24 ? `${(h / 24).toFixed(1)}d` : `${h.toFixed(1)}h`;
    let rows = "";
    weeks.slice().reverse().forEach(w => {
        const hrs = w.ballots.map(b => (w.deadline - b.time) / 36e5);
        const pct = lim => `${Math.round(hrs.filter(h => h <= lim).length / hrs.length * 100)}%`;
        const off = w.ballots.filter(b => b.official).length;
        const active = w.tab.dataset.week === activeWeekId ? " class=\"bt-row-active\"" : "";
        rows += `<tr${active}><td class="name-col">${ballotTimesWeekName(w.tab)}</td><td>${w.ballots.length}</td><td>${off}</td>`
            + `<td>${_btFmt.format(w.deadline)}</td><td>${fmtH(median(hrs))}</td><td>${pct(24)}</td><td>${pct(12)}</td><td>${pct(3)}</td><td>${pct(1)}</td></tr>`;
    });
    const tbl = document.createElement("table");
    tbl.className = "ballot-times-table";
    tbl.innerHTML = `<thead><tr><th class="name-col">Week</th><th>Ballots</th><th>Official</th><th title="Last ballot rounded up to the hour (ET)">Deadline ≈</th>`
        + `<th title="Median time before deadline">Median</th><th title="Share in final 24 h">≤24h</th><th>≤12h</th><th>≤3h</th><th>≤1h</th></tr></thead><tbody>${rows}</tbody>`;

    const wrap = document.createElement("div");
    wrap.appendChild(svg);
    wrap.appendChild(tbl);
    return wrap;
}

// Conference table (Shift+K): every D1 school by conference for a season,
// from CONFERENCE_DATA (built from conferences.py). Used to check makeups.
function conferenceDisplayName(team) {
    const names = CONFERENCE_DATA.names;
    if (names[team]) return names[team];
    return team.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
}

// Shorter team name for tight spaces ("Michigan ST", "E. Kentucky", "FAU"), from
// SHORT_NAMES in conferences.py; falls back to the display name. Applies aliases.
function shortTeamName(team) {
    const key = CONFERENCE_DATA.aliases[team] || team;
    return CONFERENCE_DATA.short?.[key] ?? conferenceDisplayName(key);
}

function showConferenceModal(year) {
    const seasons = Object.keys(CONFERENCE_DATA.seasons).map(Number).sort((a, b) => a - b);
    if (seasons.length === 0) return;
    if (year === undefined) {
        const activeTab = document.querySelector(".week-tab.active");
        year = _apCurrentYear !== null ? Number(_apCurrentYear) : Number(activeTab?.dataset.year);
    }
    year = Number(year);
    if (!seasons.includes(year)) year = year < seasons[0] ? seasons[0] : seasons[seasons.length - 1];

    const table = CONFERENCE_DATA.seasons[year];
    const confs = Object.keys(table);
    const power = CONFERENCE_DATA.power;
    const powerConfs = power.filter(c => table[c]);
    const midConfs = confs.filter(c => !power.includes(c)).sort((a, b) => a.localeCompare(b));
    const count = list => list.reduce((n, c) => n + table[c].length, 0);

    document.getElementById("conference-title").textContent =
        `${year - 1}–${String(year).slice(-2)} Conferences`;
    document.getElementById("conference-years").innerHTML = seasons.map(y =>
        `<button class="conference-year${y === year ? " active" : ""}" data-year="${y}">${y}</button>`
    ).join("");

    const block = conf => {
        const teams = table[conf].slice().sort((a, b) =>
            conferenceDisplayName(a).localeCompare(conferenceDisplayName(b)));
        const cells = teams.map(t => {
            const name = conferenceDisplayName(t);
            return `<div class="conference-team" title="${t}">
                <img class="conference-logo" data-team="${t}" alt="">
                <span class="conference-team-name">${name}</span>
            </div>`;
        }).join("");
        return `<div class="conference-block">
            <h3>${conf} <span class="conference-count">${teams.length}</span></h3>
            <div class="conference-grid">${cells}</div>
        </div>`;
    };

    document.getElementById("conference-body").innerHTML =
        `<div class="conference-tier"><h2>Power <span class="conference-count">${powerConfs.length} conferences · ${count(powerConfs)} schools</span></h2>${powerConfs.map(block).join("")}</div>` +
        `<div class="conference-tier"><h2>Mid-Major <span class="conference-count">${midConfs.length} conferences · ${count(midConfs)} schools</span></h2>${midConfs.map(block).join("")}</div>`;

    document.querySelectorAll("#conference-body img.conference-logo").forEach(img => {
        img.addEventListener("error", () => {
            if (img.dataset.fallback) {
                // No logo file for this school: show a dashed placeholder instead.
                const ph = document.createElement("span");
                ph.className = "conference-logo missing";
                ph.title = "No logo file";
                img.replaceWith(ph);
                return;
            }
            img.dataset.fallback = "1";
            img.src = `cbb-logos/${img.dataset.team}.webp`;
        });
        setLogoSrc(img, img.dataset.team);
    });

    document.getElementById("conference-modal").classList.add("open");
}

document.getElementById("conference-years").addEventListener("click", e => {
    const btn = e.target.closest(".conference-year");
    if (btn) showConferenceModal(Number(btn.dataset.year));
});

// ── Report: MM + P12 (Mid-Major + Pac-12) ──────────────────────────────────
// Every team outside the five "big" conferences (CONFERENCE_DATA.power minus Pac-12), for the
// active week, in the Year window (#season-stats-modal, table class season-mmp12 on top of
// season-records so it shares the Records look, logos and click-to-expand game lists).
// 2025+ only (needs conferences.py). Columns, by group:
//   Poll    — Rk (points rank among every vote-getter), Pts, Δ (vs the previous week), Votes
//             (official ballots listing the team), Hi (best spot on a ballot), Avg (mean spot
//             on ballots that list it), AP (ESPN AP rank; Userpoll weeks only)
//   Résumé  — W-L, Conf (ESPN standings), vs P5 (record vs ACC/Big Ten/Big 12/SEC/Big East
//             teams, from quads-YEAR.json's played games)
//   Metrics — NET (once out), BPI rank (among all D1, by BPI score), BPI, SOR, SOS
// Rows: teams with votes this week or the previous poll. Default order: poll points, then
// previous poll's points, then BPI rank. Headers sort; click again to reverse.
let _mmSort = null;             // null = default order, else {key, dir: 1 | -1}
let _mmToken = 0;
const _mmApRanks = {};          // weekId → {espnId: AP rank} | null (no matching ESPN poll)

// Short labels for the long conference names, to keep the Conf column narrow (full name on hover).
const MM_CONF_SHORT = {
    "America East": "AE", "American": "AAC", "Atlantic 10": "A-10", "Conference USA": "CUSA",
    "Missouri Valley": "MVC", "Mountain West": "MWC",
};

function mmBig5() { return (CONFERENCE_DATA.power || []).filter(c => c !== "Pac-12"); }

function _mmRec(s) {
    const m = /^(\d+)-(\d+)/.exec(s || "");
    return m ? { w: +m[1], l: +m[2] } : null;
}

function showMmP12Report() {
    const modal = document.getElementById("season-stats-modal");
    const title = document.getElementById("season-stats-title");
    const table = document.getElementById("season-stats-table");
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const isApMode = _apCurrentYear !== null;
    const season = isApMode ? String(_apCurrentYear) : activeTab.dataset.year;
    const weekId = isApMode && _apCurrentWeekNum !== null ? `week-ap-${_apCurrentYear}-${_apCurrentWeekNum}` : activeTab.dataset.week;
    const tabs = isApMode ? getSortedApTabs() : getSortedTabs();
    const weekTab = tabs.find(t => t.dataset.week === weekId) || activeTab;
    const weekLabel = weekTextLabel(weekTab) || `Week ${displayWeekNum(weekTab)}`;
    // Previous poll in the same season (tabs are sorted newest first).
    const idx = tabs.indexOf(weekTab);
    const prevTab = idx >= 0 && tabs[idx + 1]?.dataset.year === weekTab.dataset.year ? tabs[idx + 1] : null;
    const showAp = !ON_AP_PAGE && !isApMode;

    _recordsRenderToken++;          // drop any Records render still in flight
    const token = ++_mmToken;
    table.className = "season-records season-mmp12";
    let last = [null, null];
    const render = (data, error) => {
        if (token !== _mmToken || !table.classList.contains("season-mmp12")) return;
        last = [data, error];
        // No "ESPN <time>" note here; only say so when ESPN couldn't be refreshed.
        const stale = data?.stale ? `couldn't refresh ESPN (${String(data.stale).replace(/[<>&]/g, "")})` : "";
        title.innerHTML = `<span class="records-title-main">${season}${isApMode ? " AP" : ""} ${weekLabel} — Mid-Major + Pac-12</span>`
            + (stale ? `<span class="records-note records-title-note">${stale}</span>` : "");
        table.innerHTML = buildMmP12TableHtml(season, weekId, prevTab?.dataset.week || null, showAp, data, error);
        table.querySelector(".records-retry")?.addEventListener("click", () => showMmP12Report());
        table.querySelectorAll("th[data-sort]").forEach(th => th.addEventListener("click", () => {
            const key = th.dataset.sort;
            const dir = +th.dataset.dir;
            _mmSort = _mmSort?.key === key ? (_mmSort.dir === dir ? { key, dir: -dir } : null) : { key, dir };
            render(...last);
        }));
        initRecordsLogos(table);
        if (!data) return;
        const tbody = table.querySelector("tbody");
        tbody.addEventListener("click", e => {
            const opp = e.target.closest("img.records-opp-logo[data-team]");
            if (opp) { toggleTeamHighlight(opp.dataset.team); return; }
            const tr = e.target.closest("tr.records-team-row");
            if (tr && tbody.contains(tr)) toggleTeamGames(tr, season, data);
        });
        tbody.querySelectorAll("tr.records-team-row").forEach(tr => {
            if (_recordsExpanded.has(`${season}:${tr.dataset.espn}`)) toggleTeamGames(tr, season, data, true);
        });
    };

    if (!conferenceTable(season)) {
        title.textContent = `${season} — Mid-Major + Pac-12`;
        table.innerHTML = `<tbody><tr><td class="records-msg">Conference data starts in 2025.</td></tr></tbody>`;
        modal.classList.add("open");
        return;
    }
    const cached = espnCachedData(`records:${season}`);
    render(cached, null);
    modal.classList.add("open");
    const again = () => render(...last);
    if (quadsAvailable(season) && (!_quadsData[season] || _quadsData[season].error)) fetchQuads(season).then(again, again);
    if (showAp && !(weekId in _mmApRanks)) {
        espnApPollForWeek(weekId).then(p => {
            const m = {};
            (p?.ranks || []).forEach(e => { if (e.rank <= 25) m[e.id] = e.rank; });
            _mmApRanks[weekId] = p ? m : null;
        }, () => {}).then(again);
    }
    if (!cached || Date.now() - cached.at >= ESPN_TTL_MS) {
        fetchSeasonRecords(season).then(d => render(d, null), err => render(null, err.message));
    }
}

function buildMmP12TableHtml(season, weekId, prevWeekId, showAp, data, error) {
    const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const alias = k => (CONFERENCE_DATA.aliases || {})[k] || k;
    const confs = conferenceTable(season);
    const big5 = new Set(mmBig5());
    const confOf = {};
    Object.entries(confs).forEach(([c, teams]) => teams.forEach(t => { confOf[t] = c; }));

    const quadSrc = quadsAvailable(season);
    const qd = _quadsData[season];
    const hasQuadsFile = !!QUAD_FILES?.[season]?.quads;
    const showNet = quadSrc === "net";
    const showResume = hasQuadsFile && Number(season) >= RESUME_FROM_SEASON;
    const apRanks = showAp ? _mmApRanks[weekId] : undefined;
    const blank = qd || !quadSrc ? "—" : "…";

    // Poll numbers from official ballots (same points as Official Overall).
    const ballotsOf = id => Object.entries(buildDeltaData(true)[id] || {})
        .filter(([u]) => u !== "Official Overall" && u !== "AP Overall").map(([, ts]) => ts.slice(0, 25));
    const ballots = ballotsOf(weekId);
    const pts = {}, spots = {};
    ballots.forEach(b => b.forEach((t, i) => {
        if (!t) return;
        pts[t] = (pts[t] || 0) + (25 - i);
        (spots[t] || (spots[t] = [])).push(i + 1);
    }));
    // Competition ranking (1, 2, 2, 4) by points among every vote-getter.
    const rankOf = p => {
        const r = {};
        Object.entries(p).sort((a, b) => b[1] - a[1]).forEach(([t, v], i, arr) => {
            r[t] = i && arr[i - 1][1] === v ? r[arr[i - 1][0]] : i + 1;
        });
        return r;
    };
    const pollRank = rankOf(pts);
    const prevPts = {};
    const prevBallots = prevWeekId ? ballotsOf(prevWeekId) : [];
    const prevVoters = {};
    prevBallots.forEach(b => b.forEach((t, i) => {
        if (!t) return;
        prevPts[t] = (prevPts[t] || 0) + (25 - i);
        prevVoters[t] = (prevVoters[t] || 0) + 1;
    }));
    // Share of the most points a team could get that week (25 from every official ballot).
    const share = (p, n) => n ? p / (25 * n) * 100 : null;
    const prevRank = rankOf(prevPts);

    // BPI rank among every D1 team in the quads file (competition ranking by score).
    const bpiRank = {};
    if (qd?.teams) {
        const s = Object.entries(qd.teams).filter(([, t]) => t.bpi != null).sort((a, b) => b[1].bpi - a[1].bpi);
        s.forEach(([k, t], i) => { bpiRank[k] = i && s[i - 1][1].bpi === t.bpi ? bpiRank[s[i - 1][0]] : i + 1; });
    }

    const rows = [];
    Object.entries(confs).forEach(([conf, teams]) => {
        if (big5.has(conf)) return;
        teams.forEach(team => {
            if (!pts[team] && !prevPts[team]) return;   // votes this week or last only
            const id = espnIdFor(team);
            const r = id && data ? data.byId[id] : null;
            const qk = alias(team);
            const t = qd?.teams?.[qk];
            const played = qd?.played?.[qk];
            let vsBig5 = null;
            if (played) {
                vsBig5 = { w: 0, l: 0 };
                played.forEach(g => {
                    if (!g.opp.key || !big5.has(confOf[g.opp.key])) return;
                    if (g.result === "W") vsBig5.w++; else if (g.result === "L") vsBig5.l++;
                });
            }
            const sp = spots[team] || [];
            const gp = r ? r.wins + r.losses : 0;
            rows.push({
                team, id, r, t, conf,
                pollRank: pollRank[team] ?? null,
                prevRank: prevRank[team] ?? null,
                // Rank change, positive = moved up; null unless ranked (received votes) in both polls.
                dRank: pollRank[team] && prevRank[team] ? prevRank[team] - pollRank[team] : null,
                prevPts: prevWeekId ? prevPts[team] || 0 : null,
                ptsPct: pts[team] ? share(pts[team], ballots.length) : null,
                prevPtsPct: prevPts[team] ? share(prevPts[team], prevBallots.length) : null,
                // Change in Pts % since the previous poll (percentage points; no votes counts as 0%).
                dPct: prevWeekId ? (share(pts[team] || 0, ballots.length) ?? 0) - (share(prevPts[team] || 0, prevBallots.length) ?? 0) : null,
                pts: pts[team] || 0,
                votes: sp.length,
                firsts: sp.filter(n => n === 1).length,
                prevVotes: prevWeekId ? prevVoters[team] || 0 : null,
                dVotes: prevWeekId ? sp.length - (prevVoters[team] || 0) : null,
                hi: sp.length ? Math.min(...sp) : null,
                // Worst spot; 26 (shown "NR") when any official voter left the team off.
                lo: sp.length ? (sp.length < ballots.length ? 26 : Math.max(...sp)) : null,
                avg: sp.length ? sp.reduce((a, b) => a + b, 0) / sp.length : null,
                ap: apRanks ? apRanks[id] ?? null : null,
                pct: gp ? r.wins / gp : null,
                confPct: (() => { const c = _mmRec(r?.confRecord); return c && c.w + c.l ? c.w / (c.w + c.l) : null; })(),
                vsBig5,
                net: showNet ? t?.rank ?? null : null,
                bpiRank: bpiRank[qk] ?? null,
                bpi: t?.bpi ?? null, sor: t?.sor ?? null, sos: t?.sos ?? null,
            });
        });
    });

    // Default order, then any header sort.
    const nullLast = (a, b, f) => (a == null) - (b == null) || (a == null ? 0 : f(a, b));
    rows.sort((a, b) => (b.pts - a.pts)
        || ((prevPts[b.team] || 0) - (prevPts[a.team] || 0))
        || nullLast(a.bpiRank, b.bpiRank, (x, y) => x - y)
        || nullLast(a.pct, b.pct, (x, y) => y - x)
        || conferenceDisplayName(a.team).localeCompare(conferenceDisplayName(b.team)));
    const shown = rows;
    const wlVal = x => x ? x.w - x.l * 0.001 : null;     // more wins first, then fewer losses
    const sortVal = {
        pollRank: x => x.pollRank, prevRank: x => x.prevRank, dRank: x => x.dRank,
        pts: x => x.pts, ptsPct: x => x.ptsPct, dPct: x => x.dPct, votes: x => x.votes, firsts: x => x.firsts, prevVotes: x => x.prevVotes, dVotes: x => x.dVotes, lo: x => x.lo,
        hi: x => x.hi, avg: x => x.avg, ap: x => x.ap, wl: x => x.pct, conf: x => x.confPct,
        vsBig5: x => wlVal(x.vsBig5),
        net: x => x.net, bpiRank: x => x.bpiRank, bpi: x => x.bpi, sor: x => x.sor, sos: x => x.sos,
        team: x => conferenceDisplayName(x.team), confName: x => x.conf,
    };
    if (_mmSort && sortVal[_mmSort.key]) {
        const f = sortVal[_mmSort.key], dir = _mmSort.dir;
        shown.sort((a, b) => nullLast(f(a), f(b), (x, y) => (typeof x === "string" ? x.localeCompare(y) : x - y) * dir));
    }

    // Columns: [key, label, tooltip, default sort dir (1 = ascending), group end?, show?, cell]
    const wl = x => x ? `${x.w}-${x.l}` : blank;
    const num1 = v => v == null ? blank : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1);
    const espnBlank = x => x.r ? null : "—";
    const cols = [
        ["confName", "Conf", "Conference", 1, true, true, x => MM_CONF_SHORT[x.conf] ? `<span class="mm-conf" title="${esc(x.conf)}">${MM_CONF_SHORT[x.conf]}</span>` : `<span class="mm-conf">${esc(x.conf)}</span>`],
        ["pollRank", "Rk", "Poll rank", 1, false, true, x => x.pollRank ?? "—"],
        ["prevRank", "P. Rk", "Previous poll rank", 1, false, !!prevWeekId, x => `<span class="mm-dim">${x.prevRank ?? "—"}</span>`],
        ["dRank", "ΔRk", "Rank change", -1, false, !!prevWeekId,
            x => x.dRank ? `<span class="${x.dRank > 0 ? "delta-up" : "delta-down"}">${x.dRank > 0 ? "+" : "−"}${Math.abs(x.dRank)}</span>` : x.dRank === 0 ? "0" : "—"],
        ["hi", "Hi", "Highest ballot rank", 1, false, true, x => x.hi ?? "—"],
        ["lo", "Lo", "Lowest ballot rank (NR = unranked)", 1, false, true, x => x.lo === 26 ? "NR" : x.lo ?? "—"],
        ["avg", "Avg", "Average ballot rank", 1, false, true, x => x.avg == null ? "—" : x.avg.toFixed(1)],
        ["ap", "AP", "AP rank", 1, false, showAp, x => apRanks === undefined ? "…" : x.ap ?? "—"],
        ["firsts", "#1", "First-place votes", -1, true, true, x => x.firsts || "—"],
        ["ptsPct", "Pts %", `% of max points (${25 * ballots.length})`, -1, false, true,
            x => x.ptsPct == null ? "—" : `<span title="${x.pts} pts">${x.ptsPct.toFixed(1)}%</span>`],
        ["dPct", "Pts Δ%", "Pts % change", -1, false, !!prevWeekId,
            x => x.dPct == null ? "—" : Math.abs(x.dPct) < 0.05 ? "0.0%"
                : `<span class="${x.dPct > 0 ? "delta-up" : "delta-down"}">${x.dPct > 0 ? "+" : "−"}${Math.abs(x.dPct).toFixed(1)}%</span>`],
        ["votes", "Voters", "Voters who ranked the team", -1, !prevWeekId, true, x => `${x.votes}<span class="mm-of">/${ballots.length}</span>`],
        ["prevVotes", "P. Voters", "Previous poll voters", -1, false, !!prevWeekId, x => `${x.prevVotes}<span class="mm-of">/${prevBallots.length}</span>`],
        ["dVotes", "ΔVoters", "Voter change", -1, true, !!prevWeekId,
            x => x.dVotes ? `${x.dVotes > 0 ? "+" : "−"}${Math.abs(x.dVotes)}` : "0"],
        ["wl", "W-L", "Record", -1, false, true, x => espnBlank(x) ?? `<b>${x.r.wins}-${x.r.losses}</b>`],
        ["conf", "Conf", "Conference record", -1, !hasQuadsFile, true, x => espnBlank(x) ?? esc(x.r.confRecord || "—")],
        ["vsBig5", "vs P5", "Record vs ACC, Big Ten, Big 12, SEC, Big East", -1, true, hasQuadsFile,
            x => x.vsBig5 ? (x.vsBig5.w + x.vsBig5.l ? wl(x.vsBig5) : "0-0") : blank],
        ["net", "NET", "NCAA NET rank", 1, false, showNet, x => x.net ?? blank],
        ["bpiRank", "BPI Rk", "BPI rank", 1, false, hasQuadsFile, x => x.bpiRank ?? blank],
        ["bpi", "BPI", "BPI rating", -1, false, hasQuadsFile, x => num1(x.bpi)],
        ["sor", "SOR", "Strength of Record rank", 1, false, showResume, x => x.sor ?? blank],
        ["sos", "SOS", "Strength of Schedule rank", 1, false, showResume, x => x.sos ?? blank],
    ].filter(c => c[5]);
    const COLS = 3 + cols.length;
    const arrow = key => _mmSort?.key === key ? (_mmSort.dir === 1 ? " ▲" : " ▼") : "";
    const th = (key, label, tip, dir, end, cls = "") =>
        `<th data-sort="${key}" data-dir="${dir}" class="mm-sortable${end ? " mm-sep" : ""}${_mmSort?.key === key ? " mm-sorted" : ""}${cls ? ` ${cls}` : ""}" title="${esc(tip)}">${label}${arrow(key)}</th>`;
    const head = `<thead><tr><th>#</th><th></th>${th("team", "Team", "Team", 1, false, "team-col")}`
        + cols.map(([k, l, tip, dir, end]) => th(k, l, tip, dir, end)).join("")
        + `</tr></thead>`;

    if (!data) {
        const msg = error ? `Couldn't load records from ESPN (${esc(error)}). <span class="records-retry">Retry</span>` : "Loading";
        return `${head}<tbody><tr><td colspan="${COLS}" class="records-msg">${msg}</td></tr></tbody>`;
    }
    const body = shown.map((x, i) => {
        const name = conferenceDisplayName(x.team);
        const logo = `<img class="logo-sm records-logo" data-team="${esc(x.team)}"${x.id ? ` data-espn="${x.id}"` : ""} alt="">`;
        const cells = cols.map(([k, , , , end, , cell]) => `<td class="mm-${k}${end ? " mm-sep" : ""}">${cell(x)}</td>`).join("");
        const ranked = x.pts && !(shown[i + 1]?.pts) && !_mmSort && i < shown.length - 1;
        const cls = [x.r ? "records-team-row" : "", ranked ? "records-t25-end" : ""].filter(Boolean).join(" ");
        return `<tr${cls ? ` class="${cls}"` : ""}${x.r ? ` data-espn="${x.id}"` : ""}><td>${i + 1}</td><td>${logo}</td>`
            + `<td class="team-col">${esc(name)}</td>${cells}</tr>`;
    }).join("");
    return `${head}<tbody>${body || `<tr><td colspan="${COLS}" class="records-msg">No Mid-Major or Pac-12 team received votes this week or the previous poll.</td></tr>`}</tbody>`;
}

// Reports menu (Shift+R): a list of report launchers. Add a handler to
// REPORT_ACTIONS keyed by the item's data-report (markup in build_full_html()).
const REPORT_ACTIONS = {
    "mm-p12": showMmP12Report,
};

function showReportsModal() {
    const modal = document.getElementById("reports-modal");
    modal.classList.add("open");
    modal.querySelector(".report-item")?.focus();
}

document.getElementById("reports-list").addEventListener("click", e => {
    const btn = e.target.closest(".report-item");
    const action = btn && REPORT_ACTIONS[btn.dataset.report];
    if (!action) return;
    document.getElementById("reports-modal").classList.remove("open");
    action();
});

// Plain ↑/↓ move between items while the menu is open (Enter/Space click the focused one).
document.getElementById("reports-list").addEventListener("keydown", e => {
    if (e.shiftKey || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
    const items = [...document.querySelectorAll("#reports-list .report-item")];
    const i = items.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
});

["tenure-modal", "conference-modal", "reports-modal", "settings-modal", "changes-modal"].forEach(id => {
    document.getElementById(id).addEventListener("click", e => {
        if (e.target === e.currentTarget) e.currentTarget.classList.remove("open");
    });
});

// Keyboard shortcuts

["keybind-legend-modal", "season-stats-modal", "heatmap-modal"].forEach(id => {
    document.getElementById(id).addEventListener("click", e => {
        if (e.target === e.currentTarget) e.currentTarget.classList.remove("open");
    });
});


(function() {
    let _resizeTimer;
    window.addEventListener("resize", () => {
        clearTimeout(_resizeTimer);
        _resizeTimer = setTimeout(updateAvgRankLines, 50);
    });
})();


// Prev/next week arrows floated into the Stats > Week modal
// titles. Same chevrons as the header's #week-arrows and shown under the same
// Settings toggle (body.show-week-arrows); navigateWeek() re-renders whichever
// of those modals is open.
function modalWeekArrowsHtml() {
    const chev = d => `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
    return `<span class="modal-week-arrows">`
        + `<button type="button" class="week-arrow" aria-label="Previous week" title="Previous week" onclick="navigateWeek(-1)">${chev("M15 5l-7 7 7 7")}</button>`
        + `<button type="button" class="week-arrow" aria-label="Next week" title="Next week" onclick="navigateWeek(1)">${chev("M9 5l7 7-7 7")}</button>`
        + `</span>`;
}

// Step one week forward (dir = 1) or back (dir = -1). Shared by Shift+←/→
// and the optional header arrows (#week-arrows).
// Re-render any open week-specific window for the week just navigated to (Shift+←/→ and the
// header week arrows). Add new week-specific windows here. Season-wide windows (team charts,
// heatmap, tenure, conferences, Year window Voters) aren't refreshed.
function refreshWeekWindows(weekId) {
    const vhm = document.getElementById("voter-history-modal");
    if (vhm.classList.contains("open")) {
        if (vhm.dataset.chartType === "highlow") showWeekHighLowChart(weekId, vhm.dataset.chartMode || "highlow");
        else if (vhm.dataset.chartType === "ballottimes" && !weekId.startsWith("week-ap-")) showBallotTimesChart();
    }
    const ssm = document.getElementById("season-stats-modal");
    if (ssm.classList.contains("open")) {
        const table = document.getElementById("season-stats-table");
        if (table.classList.contains("season-mmp12")) showMmP12Report();
        else if (table.classList.contains("season-records")) showSeasonStatsModal("records");
    }
}

function navigateWeek(dir) {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const currentWeekNum = parseInt(activeTab.dataset.weeknum);
    const currentYear = activeTab.dataset.year;
    if (_apCurrentYear !== null) {
        // AP mode: navigate AP weeks
        const sortedApAll = getSortedApTabs().filter(t => !isHiddenYear(t.dataset.year)).slice().reverse(); // ascending
        const idx = sortedApAll.findIndex(t => t.dataset.year === _apCurrentYear && t.dataset.weeknum === _apCurrentWeekNum);
        const target = dir > 0 ? sortedApAll[idx + 1] : sortedApAll[idx - 1];
        if (target) {
            loadApYear(target.dataset.year).then(async () => {
                await showApWeek(target.dataset.year, target.dataset.weeknum);
                if (weekPickerPinned) rebuildWeekPicker();
                refreshWeekWindows(`week-ap-${target.dataset.year}-${target.dataset.weeknum}`);
            }).catch(() => {});
        }
    } else {
        const sortedAll = getSortedTabs().filter(t => !isHiddenYear(t.dataset.year)).slice().reverse();
        const idx = sortedAll.findIndex(t => t.dataset.week === activeTab.dataset.week);
        const target = dir > 0 ? sortedAll[idx + 1] : sortedAll[idx - 1];
        if (target) {
            loadYear(target.dataset.year).then(async () => {
                await showWeek(target.dataset.week);
                if (weekPickerPinned) rebuildWeekPicker();
                refreshWeekWindows(target.dataset.week);
                backgroundLoad();
            }).catch(() => {});
        }
    }
}

// ── Header week arrows ──────────────────────────────────────────────────────
// Hidden by default; toggled in Settings and remembered in localStorage.
let _showWeekArrows = false;
try { _showWeekArrows = localStorage.getItem("showWeekArrows") === "1"; } catch (e) {}
function setWeekArrowsVisible(on) {
    _showWeekArrows = on;
    document.body.classList.toggle("show-week-arrows", on);
    refreshSettingsLabels();
    try { localStorage.setItem("showWeekArrows", on ? "1" : "0"); } catch (e) {}
}
setWeekArrowsVisible(_showWeekArrows);

// ── Highlight mode ──────────────────────────────────────────────────────────
// Glow (default): highlighted ballot cells get a glowing frame.
// Dim (body.highlight-dim): other ballot logos fade, highlighted cells get a plain
// frame. Outliers look the same in both (tag + bar). Toggled in Settings, remembered in localStorage.
let _highlightDim = false;
try { _highlightDim = localStorage.getItem("highlightMode") === "dim"; } catch (e) {}
function setHighlightDim(on) {
    _highlightDim = on;
    document.body.classList.toggle("highlight-dim", on);
    refreshSettingsLabels();
    try { localStorage.setItem("highlightMode", on ? "dim" : "glow"); } catch (e) {}
}
setHighlightDim(_highlightDim);

// ── Highlight average-rank lines ────────────────────────────────────────────
// The vertical line at a highlighted team's average ballot rank. Off by default;
// toggled in Settings, remembered in localStorage. Hidden via CSS (body.show-avg-lines),
// so updateAvgRankLines() still places them and still colors the consensus header.
let _showAvgLines = false;
try { _showAvgLines = localStorage.getItem("showAvgLines") === "1"; } catch (e) {}
function setAvgLinesVisible(on) {
    _showAvgLines = on;
    document.body.classList.toggle("show-avg-lines", on);
    refreshSettingsLabels();
    try { localStorage.setItem("showAvgLines", on ? "1" : "0"); } catch (e) {}
}
setAvgLinesVisible(_showAvgLines);

// ── Compact table ───────────────────────────────────────────────────────────
// Ballot tables at their natural width (like the outlier mockups) instead of stretched
// to the page. Toggled in Settings, remembered in localStorage.
let _compactTable = false;
try { _compactTable = localStorage.getItem("compactTable") === "1"; } catch (e) {}
function setCompactTable(on) {
    _compactTable = on;
    document.body.classList.toggle("compact-table", on);
    refreshSettingsLabels();
    try { localStorage.setItem("compactTable", on ? "1" : "0"); } catch (e) {}
    updateAvgRankLines();  // columns move, so the avg-rank lines must be re-placed
}
setCompactTable(_compactTable);
document.getElementById("week-arrow-prev").addEventListener("click", () => navigateWeek(-1));
document.getElementById("week-arrow-next").addEventListener("click", () => navigateWeek(1));

// ── PIN lock for the "Locked" keybinds (Shift+D/X/R/T/Y/G/U/W/H/K/P/?) and the Year
// window's Voters tab ──────────────────────────────────────────────────────────
// Client-side only — a deterrent, not real security. An unlock lasts for the rest of the
// viewer's local calendar day (localStorage `keybindsUnlockedDate`), checked each time a
// locked action runs, so a tab left open past midnight locks again. The PIN prompt opens
// only from Settings › Dev; locked actions do nothing (no prompt) until then.
const LOCKED_KEYS = new Set(["D", "X", "T", "Y", "G", "U", "W", "H", "K", "P", "S", "?"]);
// Only a salted PBKDF2-SHA256 hash of the PIN ships in the page, never the PIN itself.
// To change the PIN: python3 -c "import hashlib;print(hashlib.pbkdf2_hmac('sha256',b'NEWPIN',bytes.fromhex('<salt>'),300000).hex())"
const PIN_SALT = "3257a8d4b7c69c8ae5b2dd12961baa35";
const PIN_HASH = "20588ee36e7cdd384e92ceef66b5382d45fb006d4fea1d93059a20d679aa9a22";
const PIN_LENGTH = 9;
const PIN_ITERATIONS = 300000;
async function _pinMatches(pin) {
    try {
        const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(pin), "PBKDF2", false, ["deriveBits"]);
        const salt = new Uint8Array(PIN_SALT.match(/../g).map(h => parseInt(h, 16)));
        const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: PIN_ITERATIONS }, key, 256);
        const hex = Array.from(new Uint8Array(bits), b => b.toString(16).padStart(2, "0")).join("");
        return hex === PIN_HASH;
    } catch (e) { return false; }  // crypto.subtle needs https or localhost
}
const _localDateStr = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
let _keybindsUnlockedDate = null;
try {
    _keybindsUnlockedDate = localStorage.getItem("keybindsUnlockedDate");
    localStorage.removeItem("keybindsUnlocked");  // old never-expiring unlock flag
} catch (e) {}
// Keybind legend (Shift+? or Functions › Legend). The Locked section only shows while
// Dev is unlocked today; checked on every open so it follows unlocks and midnight re-locks.
function toggleKeybindLegend() {
    const modal = document.getElementById("keybind-legend-modal");
    const lockedSection = document.getElementById("keybind-locked-section");
    if (lockedSection) lockedSection.hidden = !isKeybindsUnlocked();
    modal.classList.toggle("open");
}

function isKeybindsUnlocked() { return _keybindsUnlockedDate === _localDateStr(); }
const _pinModal = document.getElementById("pin-modal");
const _pinInput = document.getElementById("pin-input");

// One wrong attempt closes the PIN window and makes Dev inert for 10 minutes
// (localStorage `pinLockedUntil`, epoch ms). Dev looks the same while locked out.
const PIN_LOCKOUT_MS = 10 * 60 * 1000;
// Function declaration (hoisted) that reads storage directly, so refreshSettingsLabels() can call it at load.
function _pinLockedOut() {
    try { return Date.now() < (Number(localStorage.getItem("pinLockedUntil")) || 0); } catch (e) { return false; }
}

function openPinModal() {
    if (_pinLockedOut()) return;
    _pinInput.value = "";
    _pinModal.classList.add("open");
    _pinInput.focus();
}
function closePinModal() {
    _pinModal.classList.remove("open");
    _pinInput.value = "";
}
_pinInput.addEventListener("input", async () => {
    _pinInput.value = _pinInput.value.replace(/\D/g, "").slice(0, PIN_LENGTH);
    if (_pinInput.value.length < PIN_LENGTH || _pinLockedOut()) return;
    const entered = _pinInput.value;
    const ok = await _pinMatches(entered);
    if (_pinInput.value !== entered || !_pinModal.classList.contains("open")) return;  // changed while hashing
    if (ok) {
        _keybindsUnlockedDate = _localDateStr();
        try { localStorage.setItem("keybindsUnlockedDate", _keybindsUnlockedDate); } catch (e) {}
        closePinModal();
        refreshSettingsLabels();  // un-dim Dev
    } else {
        _pinInput.value = "";
        try { localStorage.setItem("pinLockedUntil", String(Date.now() + PIN_LOCKOUT_MS)); } catch (e) {}
        closePinModal();
    }
});
_pinInput.addEventListener("keydown", e => {
    e.stopPropagation(); // keep digits/Shift combos out of the global handler
    if (e.key === "Escape") closePinModal();
});
_pinModal.addEventListener("click", e => { if (e.target === _pinModal) closePinModal(); });

document.addEventListener("keydown", e => {
    if (_pinModal.classList.contains("open")) {
        return;
    }
    const _isVetChord = _chordPending === "v" && (e.key === "x" || e.key === "X");
    if (e.shiftKey && !isKeybindsUnlocked() && !_isVetChord && LOCKED_KEYS.has(e.key.length === 1 ? e.key.toUpperCase() : e.key)) {
        e.preventDefault();
        return;  // locked: no prompt here — unlock via Settings › Dev
    }
    if (e.key === "Escape") {
        document.getElementById("voter-history-modal").classList.remove("open");
        document.getElementById("keybind-legend-modal").classList.remove("open");
        document.getElementById("season-stats-modal").classList.remove("open");
        document.getElementById("tenure-modal").classList.remove("open");
        document.getElementById("conference-modal").classList.remove("open");
        document.getElementById("heatmap-modal").classList.remove("open");
        document.getElementById("reports-modal").classList.remove("open");
        document.getElementById("settings-modal").classList.remove("open");
        document.getElementById("changes-modal").classList.remove("open");
    }
    // Chord: Shift+V then X → toggle veteran tags
    if (e.shiftKey && (e.key === "V" || e.key === "v")) {
        e.preventDefault();
        clearTimeout(_chordTimer);
        _chordPending = "v";
        _chordTimer = setTimeout(() => { _chordPending = null; }, 2000);
        return;
    }
    if ((e.key === "x" || e.key === "X") && _chordPending === "v") {
        e.preventDefault();
        _chordPending = null;
        clearTimeout(_chordTimer);
        _hideVeteranTagsOverride = !_hideVeteranTagsOverride;
        const isAlpha = currentSort === "alphabetic" || currentSort === "zetabetique";
        document.body.classList.toggle("hide-veteran-tags", !isAlpha || _hideVeteranTagsOverride);
        return;
    }

    if (!e.shiftKey) return;
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;

    const currentWeekNum = parseInt(activeTab.dataset.weeknum);
    const currentYear = activeTab.dataset.year;

    if (e.key === "A" || e.key === "a") {
        e.preventDefault();
        applyTableSort("alphabetic");
        return;
    }

    if (e.key === "Z" || e.key === "z") {
        e.preventDefault();
        applyTableSort("zetabetique");
        return;
    }

    if (e.key === "D" || e.key === "d") {
        e.preventDefault();
        showAggregateSection();
        return;
    }

    if (e.key === "E" || e.key === "e") {
        e.preventDefault();
        cycleDeltaMode();
        return;
    }

    if (e.key === "C" || e.key === "c") {
        e.preventDefault();
        applyTableSort("consensus");
        return;
    }

    if (e.key === "T" || e.key === "t") {
        e.preventDefault();
        showTenureModal();
        return;
    }

    if (e.key === "K" || e.key === "k") {
        e.preventDefault();
        showConferenceModal();
        return;
    }

    if (e.key === "R" || e.key === "r") {
        e.preventDefault();
        const reports = document.getElementById("reports-modal");
        if (reports.classList.contains("open")) reports.classList.remove("open");
        else showReportsModal();
        return;
    }

    if (e.key === "Y" || e.key === "y") {
        e.preventDefault();
        if (_apCurrentYear !== null) {
            showWeekHighLowChart(`week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`, "stats");
        } else {
            const activeTab = document.querySelector(".week-tab.active");
            if (activeTab) showWeekHighLowChart(activeTab.dataset.week, "stats");
        }
        return;
    }

    if (e.key === "G" || e.key === "g") {
        e.preventDefault();
        if (_apCurrentYear !== null) {
            showWeekHighLowChart(`week-ap-${_apCurrentYear}-${_apCurrentWeekNum}`, _weekChartKind);
        } else {
            const activeTab = document.querySelector(".week-tab.active");
            if (activeTab) showWeekHighLowChart(activeTab.dataset.week, _weekChartKind);
        }
        return;
    }

    if (e.key === "U" || e.key === "u") {
        e.preventDefault();
        showSeasonStatsModal();
        return;
    }

    // Hidden Voters tab of the Year window (PIN-locked)
    if (e.key === "W" || e.key === "w") {
        e.preventDefault();
        showSeasonStatsModal("voters");
        return;
    }

    if (e.key === "H" || e.key === "h") {
        e.preventDefault();
        showHeatmapModal();
        return;
    }
    // Ballot submission times (PIN-locked, 2027+)
    if (e.key === "S" || e.key === "s") {
        e.preventDefault();
        showBallotTimesChart();
        return;
    }
    if (e.key === "B" || e.key === "b") {
        e.preventDefault();
        showBumpChartModal();
        return;
    }
    if (e.key === "O" || e.key === "o") {
        e.preventDefault();
        toggleOutliers();
        return;
    }
    if (e.key === "L" || e.key === "l") {
        e.preventDefault();
        toggleOverallRow();
        return;
    }


    if (e.code >= "Digit1" && e.code <= "Digit9") {
        e.preventDefault();
        setDeltaWeeksBack(parseInt(e.code.replace("Digit", ""), 10));
        return;
    }

    if (e.key === "P" || e.key === "p") {
        e.preventDefault();
        saveTableAsPng();
        return;
    }

    if (e.key === "X" || e.key === "x") {
        e.preventDefault();
        if (_apCurrentYear !== null) {
            exitApBallots();
        } else {
            switchToApBallots();
        }
        return;
    }

    if (e.metaKey && e.code === "Digit0") {
        e.preventDefault();
        const preSeasonTab = document.querySelector(`.week-tab[data-year="${currentYear}"][data-weeknum="0"]`);
        if (preSeasonTab) {
            loadYear(currentYear).then(async () => {
                await showWeek(preSeasonTab.dataset.week);
                if (weekPickerPinned) rebuildWeekPicker();
            }).catch(() => {});
        }
        return;
    }

    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        navigateWeek(e.key === "ArrowRight" ? 1 : -1);
    }

    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        if (_apCurrentYear !== null) {
            // AP mode: navigate AP years
            const apTabs = getSortedApTabs();
            const years = [...new Set(apTabs.map(t => t.dataset.year))].filter(y => !isHiddenYear(y)).sort();
            const yearIdx = years.indexOf(_apCurrentYear);
            const targetYear = e.key === "ArrowUp" ? years[yearIdx + 1] : years[yearIdx - 1];
            if (!targetYear) return;
            loadApYear(targetYear).then(async () => {
                const yearApTabs = getSortedApTabs().filter(t => t.dataset.year === targetYear);
                const sameWeek = yearApTabs.find(t => t.dataset.weeknum === _apCurrentWeekNum);
                const target = sameWeek || yearApTabs[0]; // [0] = latest (sorted desc)
                if (target) {
                    await showApWeek(target.dataset.year, target.dataset.weeknum);
                    if (weekPickerPinned) rebuildWeekPicker();
                    const apWeekId = `week-ap-${target.dataset.year}-${target.dataset.weeknum}`;
                    const vhm2 = document.getElementById("voter-history-modal");
                    if (vhm2.classList.contains("open") && vhm2.dataset.chartType === "highlow")
                        showWeekHighLowChart(apWeekId, vhm2.dataset.chartMode || "highlow");
                }
            }).catch(() => {});
        } else {
            const tabs = getSortedTabs();
            const years = [...new Set(tabs.map(t => t.dataset.year))].filter(y => !isHiddenYear(y)).sort();
            const yearIdx = years.indexOf(currentYear);
            const targetYear = e.key === "ArrowUp" ? years[yearIdx + 1] : years[yearIdx - 1];
            if (!targetYear) return;
            loadYear(targetYear).then(async () => {
                const yearTabs = getSortedTabs().filter(t => t.dataset.year === targetYear);
                const sameWeek = yearTabs.find(t => parseInt(t.dataset.weeknum) === currentWeekNum);
                const target = sameWeek || yearTabs.sort((a, b) => parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum))[0];
                if (target) {
                    await showWeek(target.dataset.week);
                    if (weekPickerPinned) rebuildWeekPicker();
                    const vhm2 = document.getElementById("voter-history-modal");
                    if (vhm2.classList.contains("open") && vhm2.dataset.chartType === "highlow")
                        showWeekHighLowChart(target.dataset.week, vhm2.dataset.chartMode || "highlow");
                    if (vhm2.classList.contains("open") && vhm2.dataset.chartType === "ballottimes")
                        showBallotTimesChart();
                    backgroundLoad();
                }
            }).catch(() => {});
        }
    }

    if (e.key === "?") {
        e.preventDefault();
        toggleKeybindLegend();
    }
});

// Omission badge tooltip
const _omissionTip = document.createElement("div");
_omissionTip.id = "omission-tooltip";
document.body.appendChild(_omissionTip);

document.addEventListener("click", e => {
    const badge = e.target.closest(".voter-omission-badge");
    if (badge) {
        e.stopPropagation();
        if (_omissionTip.classList.contains("visible") && _omissionTip._source === badge) {
            _omissionTip.classList.remove("visible");
            return;
        }
        _omissionTip.textContent = badge.title;
        _omissionTip._source = badge;
        _omissionTip.classList.add("visible");
        const r = badge.getBoundingClientRect();
        const tipW = _omissionTip.offsetWidth;
        let left = r.left + r.width / 2 - tipW / 2;
        left = Math.max(6, Math.min(left, window.innerWidth - tipW - 6));
        const top = r.bottom + 5;
        _omissionTip.style.left = left + "px";
        _omissionTip.style.top = top + "px";
    } else {
        _omissionTip.classList.remove("visible");
    }
}, true);

// Init
rebuildYearPicker();
rebuildWeekPicker();
const allTabs = getSortedTabs();
if (allTabs.length > 0) {
    const inlineYear = allTabs[0]?.dataset.year;
    if (inlineYear) _loadedYears.add(inlineYear);
    injectVeteranTags(document);
    showWeek(allTabs[0].dataset.week);
    setTimeout(() => backgroundLoad(), 1000);
}

// ── "N/A" overlay for weeks with no ballots ────────────────────────────────
// Shows a viewport-sized diagonal "N/A" whenever the visible ballot section (Official,
// Provisional or aggregate; userpoll or AP) has no ballots. A MutationObserver on
// style changes catches every path that shows or hides a week or section.
const _noBallotsOverlay = (() => {
    const el = document.createElement("div");
    el.id = "no-ballots-overlay";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = "<span>N/A</span>";
    document.body.appendChild(el);
    return el;
})();

function sectionHasBallots(section) {
    return !!section.querySelector("tbody tr.voter-row:not(.row-weighted-ranking):not(.overall-row) .team-logo");
}

function sizeNoBallotsOverlay() {
    const span = _noBallotsOverlay.firstElementChild;
    const w = window.innerWidth, h = window.innerHeight;
    // Measure the text at 100px (layout size ignores transforms), then take the largest size
    // whose rotated box (width × cap height) still fits inside the viewport.
    span.style.transform = "none";
    span.style.fontSize = "100px";
    const r = span.offsetWidth / 100;          // text width per px of font-size
    const c = 0.72;                            // cap height per px of font-size (bold sans)
    const t = Math.atan2(h, w), cos = Math.cos(t), sin = Math.sin(t);
    const fs = 0.96 * Math.min(w / (r * cos + c * sin), h / (r * sin + c * cos));
    span.style.fontSize = fs + "px";
    span.style.transform = `rotate(${-t}rad)`;
}

let _noBallotsRaf = null;
function updateNoBallotsOverlay() {
    _noBallotsRaf = null;
    const visible = Array.from(document.querySelectorAll(".week-block .ballot-section"))
        .filter(s => s.offsetParent !== null);
    const empty = visible.length > 0 && visible.every(s => !sectionHasBallots(s));
    const wasVisible = _noBallotsOverlay.classList.contains("visible");
    _noBallotsOverlay.classList.toggle("visible", empty);
    if (empty && !wasVisible) sizeNoBallotsOverlay();
}

function scheduleNoBallotsUpdate() {
    if (_noBallotsRaf === null) _noBallotsRaf = requestAnimationFrame(updateNoBallotsOverlay);
}

new MutationObserver(muts => {
    if (muts.some(m => m.target.classList && (m.target.classList.contains("ballot-section")
            || m.target.classList.contains("week-block")))) scheduleNoBallotsUpdate();
}).observe(document.body, { subtree: true, attributes: true, attributeFilter: ["style"] });

window.addEventListener("resize", () => {
    if (_noBallotsOverlay.classList.contains("visible")) sizeNoBallotsOverlay();
});
scheduleNoBallotsUpdate();
