let _sortedTabsCache = null;
let _leaderboardDataCache = null;
let _deltaDataCache = null;
let _deltaDataCacheIsProvisional = null;

const _loadedYears = new Set();
const _loadingYears = {};
const HIDDEN_YEARS = new Set(["2024"]);

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
    if (typeof FRAGMENT_YEARS === 'undefined' || !FRAGMENT_YEARS.includes(year)) {
        _loadedYears.add(year);
        return;
    }
    _loadingYears[year] = (async () => {
        try {
            document.body.classList.add('year-loading');
            const resp = await fetch(`data-${year}.html`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const html = await resp.text();
            const container = document.getElementById('year-data-container');
            container.insertAdjacentHTML('beforeend', html);
            injectVeteranTags(container);
            _loadedYears.add(year);
            _sortedTabsCache = null;
            _leaderboardDataCache = null;
            _deltaDataCache = null;
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

const highlightClasses = [
    "team-highlight-1","team-highlight-2","team-highlight-3",
    "team-highlight-4","team-highlight-5"
];
const highlightColors = {
    "team-highlight-1": "#ffcc00",
    "team-highlight-2": "#0077cc",
    "team-highlight-3": "#ff6666",
    "team-highlight-4": "#33cc33",
    "team-highlight-5": "#cc66ff"
};

const highlightedTeams = {}; // "team-highlight-1" → team name, etc.

function applyHighlightStyles() {
    let el = document.getElementById("team-highlight-styles");
    if (!el) {
        el = document.createElement("style");
        el.id = "team-highlight-styles";
        document.head.appendChild(el);
    }
    const rules = [];
    highlightClasses.forEach(cls => {
        const team = highlightedTeams[cls];
        if (!team) return;
        const color = highlightColors[cls];
        rules.push(`.team-logo[data-team="${team}"] { outline: 2px solid ${color}; border-radius: 4px; box-shadow: 0 0 20px 6px ${color}; }`);
        rules.push(`.row-delta .team-logo[data-team="${team}"] { box-shadow: none; }`);
    });
    el.textContent = rules.join(" ");
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
    const block = document.getElementById(activeTab.dataset.week);
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
        const color = highlightColors[cls];
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
    block.querySelectorAll("img[data-src]").forEach(img => {
        img.src = "cbb-logos/" + img.dataset.src + ".webp";
        img.removeAttribute("data-src");
    });
}

function getSortedTabs() {
    if (_sortedTabsCache) return _sortedTabsCache;
    _sortedTabsCache = Array.from(document.querySelectorAll(".week-tab"))
        .sort((a, b) => parseInt(b.dataset.year) - parseInt(a.dataset.year) || parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum));
    return _sortedTabsCache;
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
    if (isPinned) {
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

function expandAllDeltas() {
    const allRows = Array.from(document.querySelectorAll(".voter-row"));
    const deltaData = buildDeltaData();
    const sortedTabs = getSortedTabs();
    allRows.forEach(r => {
        if (!r.classList.contains("row-delta")) {
            r.classList.add("row-delta");
            if (r.classList.contains("row-weighted-ranking")) return;
            const weekId = r.closest(".week-block")?.id;
            if (weekId) applyDeltaToRow(r, weekId, deltaData, sortedTabs);
        }
    });
}

function hideRankHeaders(block) {
    if (!block) return;
    block.querySelectorAll("table thead th:not(:first-child)").forEach(th => { th.style.color = "transparent"; th.style.borderRight = "none"; });
}

function showRankHeaders(block) {
    if (!block) return;
    block.querySelectorAll("table thead th:not(:first-child)").forEach(th => { th.style.color = th.dataset.consensusColor || ""; th.style.borderRight = ""; });
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
    const sort = opt.dataset.sort;
    // Check if locked and prevent interaction with locked tabs
    if (sortTabsLocked && (sort === "ranking" || sort === "tenure")) {
        return;
    }
    document.querySelectorAll(".consensus-dist").forEach(el => el.remove());
    document.querySelectorAll(".rank-score-label").forEach(el => el.remove());
    rankingSortActive = false;
    const picker = opt.closest(".sort-picker");
    // Show the toggle again
    if (picker._toggle) picker._toggle.style.display = "";
    picker.classList.remove("open");
    // Restore rank headers when picker closes
    const block = picker._sourceBlock || picker.closest(".week-block");
    showRankHeaders(block);
    applyTableSort(sort);
}, true);

let currentSort = "alphabetic";

const SORT_LABELS = { alphabetic: "Alphabetic", zetabetique: "Zétabétique", consensus: "Consensus", ranking: "Précision", tenure: "Tenure" };

function setGlobalSort(sort) {
    currentSort = sort;
    const label = SORT_LABELS[sort] || (sort.charAt(0).toUpperCase() + sort.slice(1));
    document.querySelectorAll(".voters-toggle").forEach(t => {
        if (t.style.display !== "none") t.textContent = label;
    });
    document.querySelectorAll(".sort-option").forEach(o => {
        o.classList.toggle("active", o.dataset.sort === sort);
    });
    document.body.classList.toggle("hide-veteran-tags", sort !== "alphabetic" && sort !== "zetabetique");
}

function resetRankingSort() {
    setGlobalSort("alphabetic");
    document.querySelectorAll(".voters-toggle").forEach(t => { if (t.style.display === "none") t.style.display = ""; });
}

function applyTableSort(sort) {
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

    if (sort === "zetabetique") {
        rows.sort((a, b) => getVoterName(b).localeCompare(getVoterName(a)));
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
        // Sort by total ballots submitted across all years (pre-computed at build time)
        const ballotCount = (typeof TENURE_COUNTS !== 'undefined') ? TENURE_COUNTS : {};
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

// Compute the 5-Week Weighted top-25 teams for a given week.
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
// Works for regular voters, "Official Overall" (aggregate row), and "5-Week Weighted" (computed).
function buildSeasonDataForUser(username) {
    const result = {};
    const allTabsSorted = getSortedTabs();
    if (username === "5-Week Weighted") {
        const deltaData = buildDeltaData();
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
        weekTd.textContent = tab.dataset.weeklabel || ("Week " + tab.dataset.weeknum);
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
    container.appendChild(tbody);
}


function showVoterHistory(username) {
    const allTabsSorted = getSortedTabs();

    // Build ballot data for all weeks
    const mergedData = buildSeasonDataForUser(username);

    // Use the active week's year
    const activeTab = document.querySelector(".week-tab.active");
    const currentYear = activeTab?.dataset.year || allTabsSorted[0]?.dataset.year;
    const yearTabs = allTabsSorted
        .filter(t => t.dataset.year === currentYear)
        .reverse();

    const modal = document.getElementById("voter-history-modal");
    const title = document.getElementById("voter-history-title");
    const table = document.getElementById("voter-history-table");

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
            if (e.shiftKey) {
                e.stopPropagation();
                const team = logo.dataset.team;
                const row = logo.closest(".voter-row");
                const username = row ? getVoterName(row) : null;
                showTeamRankChart(team, username);
                return;
            }
            const team = logo.dataset.team;
            const isHighlighted = highlightClasses.some(c => highlightedTeams[c] === team);
            if (isHighlighted) {
                highlightClasses.forEach(c => { if (highlightedTeams[c] === team) delete highlightedTeams[c]; });
            } else {
                const availableColor = highlightClasses.find(c => !highlightedTeams[c]);
                if (availableColor) highlightedTeams[availableColor] = team;
            }
            applyHighlightStyles();
            updateAvgRankLines();
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
            const isHighlighted = highlightClasses.some(c => highlightedTeams[c] === team);
            if (isHighlighted) {
                highlightClasses.forEach(c => { if (highlightedTeams[c] === team) delete highlightedTeams[c]; });
            } else {
                const availableColor = highlightClasses.find(c => !highlightedTeams[c]);
                if (availableColor) highlightedTeams[availableColor] = team;
            }
            applyHighlightStyles();
            updateAvgRankLines();
        });
    });
}

function showTeamRankChart(team, username) {
    const allTabsSorted = getSortedTabs();

    // Build ballot data for all weeks (works for all row types)
    const mergedData = username ? buildSeasonDataForUser(username) : {};

    // Current year's weeks in chronological order
    const activeTab = document.querySelector(".week-tab.active");
    const currentYear = activeTab?.dataset.year || allTabsSorted[0]?.dataset.year;
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

    title.innerHTML = `<img class="logo" src="cbb-logos/${team}.webp" style="height:22px;vertical-align:middle;margin-right:6px;">${team} — ${username || "Unknown"}`;
    table.innerHTML = "";
    table.style.cssText = "display:block; white-space:normal; width:100%;";

    // SVG chart
    const svgNS = "http://www.w3.org/2000/svg";
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

    const axisColor = "#999", gridColor = "#e8e8e8";

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
    border.setAttribute("fill", "none"); border.setAttribute("stroke", "#ddd");
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
        nrLine.setAttribute("stroke", "#eee"); nrLine.setAttribute("stroke-width", "1");
        nrLine.setAttribute("stroke-dasharray", "3,3");
        svg.appendChild(nrLine);
        const nrTxt = document.createElementNS(svgNS, "text");
        nrTxt.setAttribute("x", x); nrTxt.setAttribute("y", mT + cH - 5);
        nrTxt.setAttribute("text-anchor", "middle"); nrTxt.setAttribute("font-size", "9");
        nrTxt.setAttribute("fill", "#ccc");
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
        circle.setAttribute("stroke", "#fff"); circle.setAttribute("stroke-width", "2");
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
        msg.textContent = `${team} not ranked by ${username || "this voter"} this season`;
        svg.appendChild(msg);
    }

    table.appendChild(svg);
    modal.classList.add("open");
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

    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;

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
    const tabs = Array.from(document.querySelectorAll(".week-tab"));
    const byYear = {};
    tabs.forEach(t => {
        const y = t.dataset.year;
        if (!byYear[y]) byYear[y] = [];
        byYear[y].push(t);
    });
    const years = Object.keys(byYear).filter(y => !HIDDEN_YEARS.has(y)).sort();

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
        btn.addEventListener("click", async e => {
            e.stopPropagation();
            try { await loadYear(y); } catch { return; }
            const activeTab = document.querySelector(".week-tab.active");
            const currentWeekNum = activeTab ? parseInt(activeTab.dataset.weeknum) : null;
            const sameWeek = currentWeekNum
                ? byYear[y].find(t => parseInt(t.dataset.weeknum) === currentWeekNum)
                : null;
            const target = sameWeek || byYear[y][byYear[y].length - 1];
            showWeek(target.dataset.week);
            backgroundLoad();
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
        .filter(t => parseInt(t.dataset.weeknum) !== 0)
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
        lazyLoadWeek(block);
        if (isAggregate) {
            const newActiveTab = document.querySelector(".week-tab.active");
            if (newActiveTab) injectWeightedRankingRow(newActiveTab, block);
        }
    }

    bindTeamLogos();
    bindRankHeaders();
    bindVoterCells();
    bindVotersToggle();
    updateRankingOptionVisibility();
    if (currentSort && currentSort !== "ranking") {
        applyTableSort(currentSort);
    }
    updateAvgRankLines();
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
    _deltaDataCache = null;
    updateRankingOptionVisibility();
    if (currentSort === "ranking") resetRankingSort();
    applyTableSort(currentSort);
    updateAvgRankLines();
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
    const deltaData = buildDeltaData();

    const result = compute5WeekWeighted(weekId, deltaData, allTabsSorted);
    if (!result) return;
    const { ranked, teamAvgRankSum, totalVoters } = result;

    // Display avg = sum / totalVoters (includes rank-26 penalty for non-rankers)
    const teamDisplayAvg = {};
    ranked.forEach(team => {
        teamDisplayAvg[team] = teamAvgRankSum[team] / totalVoters;
    });

    // Compute previous week's weighted ranking for delta comparison
    const currIdx = allTabsSorted.findIndex(t => t.dataset.week === weekId);
    const prevWeekId = currIdx + 1 < allTabsSorted.length ? allTabsSorted[currIdx + 1].dataset.week : null;
    const prevResult = prevWeekId ? compute5WeekWeighted(prevWeekId, deltaData, allTabsSorted) : null;
    const prevRankOf = {};
    if (prevResult) prevResult.ranked.forEach((team, i) => { prevRankOf[team] = i + 1; });

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
        td.appendChild(deltaLabel);

        const img = document.createElement("img");
        img.className = "logo team-logo";
        img.dataset.team = team;
        img.src = "cbb-logos/" + team + ".webp";
        td.appendChild(img);

        const avgLabel = document.createElement("span");
        avgLabel.className = "avg-label";
        avgLabel.textContent = teamDisplayAvg[team].toFixed(1);
        td.appendChild(avgLabel);

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

function showAvgRankModal(weekId) {
    const block = document.getElementById(weekId);
    if (!block) return;
    const sections = block.querySelectorAll(".ballot-section");
    const officialSection = sections[0];
    if (!officialSection) return;

    // Collect all voter rows (exclude Official Overall)
    const voterRows = Array.from(officialSection.querySelectorAll(".voter-row"))
        .filter(r => getVoterName(r) !== "Official Overall");
    const totalVoters = voterRows.length;
    if (totalVoters === 0) return;

    // Compute rank sums, voter counts, points, and rank lists per team
    const teamRankSum = {};
    const teamVoterCount = {};
    const teamPoints = {};
    const teamRanks = {};
    voterRows.forEach(row => {
        const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
        teams.slice(0, 25).forEach((team, i) => {
            const rank = i + 1;
            teamRankSum[team] = (teamRankSum[team] || 0) + rank;
            teamVoterCount[team] = (teamVoterCount[team] || 0) + 1;
            teamPoints[team] = (teamPoints[team] || 0) + (26 - rank);
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
    const allTabsSorted = getSortedTabs();
    const currTabIdx = allTabsSorted.findIndex(t => t.dataset.week === weekId);
    const currYear = allTabsSorted[currTabIdx]?.dataset.year;
    const prevTab = allTabsSorted[currTabIdx + 1];
    const prevTeamRank = {};
    if (prevTab && prevTab.dataset.year === currYear) {
        const prevTeams = buildDeltaData()[prevTab.dataset.week]?.["Official Overall"];
        if (prevTeams) prevTeams.forEach((t, i) => { prevTeamRank[t] = i + 1; });
    }
    const hasPrevWeek = Object.keys(prevTeamRank).length > 0;

    const activeTab = document.querySelector(".week-tab.active");
    const weekNum = activeTab?.dataset.weeknum || "";
    const year = activeTab?.dataset.year || "";

    const modal = document.getElementById("avg-rank-modal");
    const title = document.getElementById("avg-rank-title");
    const table = document.getElementById("avg-rank-table");

    const weekPad = String(weekNum).padStart(2, "0");
    const weekLabel = activeTab?.dataset.weeklabel;
    title.textContent = weekLabel ? `${year} ${weekLabel} Statistics` : `${year} #${weekPad} Statistics`;

    const buildRow = (team, rank) => {
        const avg = teamRankSum[team] / teamVoterCount[team];
        const median = computeMedian(teamRanks[team]);
        const count = teamVoterCount[team];
        const pts = teamPoints[team];
        const hi = Math.min(...teamRanks[team]);
        const lo = Math.max(...teamRanks[team]);
        let deltaCell = '<td></td>';
        if (hasPrevWeek) {
            const prevRank = prevTeamRank[team];
            if (!prevRank) {
                deltaCell = '<td><span class="delta-new">NEW</span></td>';
            } else {
                const diff = prevRank - rank;
                if (diff > 0) {
                    deltaCell = `<td><span class="delta-up">${diff}</span></td>`;
                } else if (diff < 0) {
                    deltaCell = `<td><span class="delta-down">${Math.abs(diff)}</span></td>`;
                } else {
                    deltaCell = '<td><span class="delta-same">—</span></td>';
                }
            }
        }
        return `<tr>
            <td>${rank}</td>
            <td style="padding:2px 4px;"><img class="logo-sm" src="cbb-logos/${team}.webp"></td>
            <td class="team-col">${team}</td>
            ${deltaCell}
            <td>${hi}</td>
            <td>${Number.isInteger(median) ? median : median.toFixed(1)}</td>
            <td style="border-right:1px solid #bbb">${lo}</td>
            <td>${count}/${totalVoters}</td>
            <td>${pts}</td>
            <td>${avg.toFixed(2)}</td>
        </tr>`;
    };

    let html = `<colgroup>
        <col style="width:28px">
        <col style="width:28px">
        <col>
        <col style="width:40px">
        <col style="width:36px">
        <col style="width:52px">
        <col style="width:36px">
        <col style="width:56px">
        <col style="width:36px">
        <col style="width:64px">
    </colgroup><thead><tr>
        <th>#</th><th></th>
        <th class="team-col">Team</th>
        <th title="Change from previous week">Δ</th>
        <th title="Highest rank given by any voter this week">Hi</th>
        <th>Median</th>
        <th title="Lowest rank given by any voter this week" style="border-right:1px solid #bbb">Lo</th>
        <th>Voters</th>
        <th>Pts</th>
        <th>Avg Rank</th>
    </tr></thead><tbody>`;
    top25.forEach((team, i) => { html += buildRow(team, i + 1); });
    if (receivingVotes.length > 0) {
        html += `<tr class="rv-divider"><td colspan="10">Receiving Votes</td></tr>`;
        receivingVotes.forEach((team, i) => { html += buildRow(team, 26 + i); });
    }
    html += "</tbody>";
    table.innerHTML = html;
    modal.classList.add("open");
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
    document.getElementById("toggle-text").innerText = "Data Ballots";
    _deltaDataCache = null;
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

// Close sort pickers on scroll
document.addEventListener("scroll", () => {
    document.querySelectorAll(".sort-picker.open").forEach(p => {
        p.classList.remove("open");
        if (p._toggle) p._toggle.style.display = "";
        showRankHeaders(p._sourceBlock || p.closest(".week-block"));
    });
}, { passive: true });

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
                img.src = "cbb-logos/" + img.dataset.src + ".webp";
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
        const week = activeTab.dataset.weeklabel || activeTab.dataset.weeknum;
        const year = activeTab.dataset.year;
        const label = document.getElementById("toggle-text").innerText.includes("Provisional") ? "provisional" : "official";
        link.download = `cbb-poll-${year}-week${week}-${label}.png`;
        link.href = canvas.toDataURL("image/png");
        link.click();
    });
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

function buildDeltaData() {
    const isProvisional = document.getElementById("toggle-text")?.innerText === "Provisional Ballots";
    if (_deltaDataCache !== null && _deltaDataCacheIsProvisional === isProvisional) return _deltaDataCache;
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
    _deltaDataCache = data;
    _deltaDataCacheIsProvisional = isProvisional;
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


function showSeasonStatsModal() {
    const activeTab = document.querySelector(".week-tab.active");
    if (!activeTab) return;
    const currentYear = activeTab.dataset.year;

    const allTabs = getSortedTabs();
    const yearTabs = allTabs.filter(t => t.dataset.year === currentYear).reverse();
    if (yearTabs.length === 0) return;

    const totalWeeks = yearTabs.length;

    // Accumulate per-team stats from official ballot sections only
    const teamTotalPts = {};
    const teamRankSum = {};
    const teamVoterWeeks = {};  // total voter-ballot appearances (for avg rank)
    const teamWeeksRanked = {}; // distinct weeks the team appeared in any ballot
    const teamFirstPlaceVotes = {};
    const teamBestRank = {};
    const teamBestConsensusRank = {};  // best (lowest #) consensus rank across weeks
    const teamWorstConsensusRank = {}; // worst (highest #) consensus rank across weeks

    yearTabs.forEach(tab => {
        const weekId = tab.dataset.week;
        const block = document.getElementById(weekId);
        if (!block) return;
        const officialSection = block.querySelectorAll(".ballot-section")[0];
        if (!officialSection) return;

        const seenThisWeek = new Set();
        officialSection.querySelectorAll(".voter-row").forEach(row => {
            const voterName = getVoterName(row);
            const teams = Array.from(row.querySelectorAll(".team-logo")).map(img => img.dataset.team);
            if (voterName === "Official Overall") {
                // Track best/worst consensus rank from the weekly aggregate
                teams.slice(0, 25).forEach((team, i) => {
                    const rank = i + 1;
                    if (!teamBestConsensusRank[team] || rank < teamBestConsensusRank[team]) teamBestConsensusRank[team] = rank;
                    if (!teamWorstConsensusRank[team] || rank > teamWorstConsensusRank[team]) teamWorstConsensusRank[team] = rank;
                });
                return;
            }
            teams.slice(0, 25).forEach((team, i) => {
                const rank = i + 1;
                teamTotalPts[team] = (teamTotalPts[team] || 0) + (25 - i);
                teamRankSum[team] = (teamRankSum[team] || 0) + rank;
                teamVoterWeeks[team] = (teamVoterWeeks[team] || 0) + 1;
                seenThisWeek.add(team);
                if (rank === 1) teamFirstPlaceVotes[team] = (teamFirstPlaceVotes[team] || 0) + 1;
                if (!teamBestRank[team] || rank < teamBestRank[team]) teamBestRank[team] = rank;
            });
        });
        seenThisWeek.forEach(team => {
            teamWeeksRanked[team] = (teamWeeksRanked[team] || 0) + 1;
        });
    });

    // Sort by total season points descending
    const allTeams = Object.keys(teamTotalPts).sort((a, b) => teamTotalPts[b] - teamTotalPts[a]);

    const modal = document.getElementById("season-stats-modal");
    const title = document.getElementById("season-stats-title");
    const table = document.getElementById("season-stats-table");

    title.textContent = `${currentYear} Season Statistics`;

    let html = `<colgroup>
        <col style="width:24px">
        <col style="width:26px">
        <col>
        <col style="width:52px">
        <col style="width:44px">
        <col style="width:60px">
        <col style="width:52px">
        <col style="width:36px">
        <col style="width:36px">
        <col style="width:36px">
    </colgroup><thead><tr>
        <th>#</th><th></th>
        <th class="team-col">Team</th>
        <th>Weeks</th>
        <th>Pts</th>
        <th>Avg Rank</th>
        <th>#1 Votes</th>
        <th>Best</th>
        <th title="Best consensus rank of the week">Hi</th>
        <th title="Worst consensus rank of the week">Lo</th>
    </tr></thead><tbody>`;

    allTeams.forEach((team, i) => {
        const avgRank = (teamRankSum[team] / teamVoterWeeks[team]).toFixed(2);
        const firstPlace = teamFirstPlaceVotes[team] || 0;
        const hiRank = teamBestConsensusRank[team] || "—";
        const loRank = teamWorstConsensusRank[team] || "—";
        html += `<tr>
            <td>${i + 1}</td>
            <td><img class="logo-sm" src="cbb-logos/${team}.webp"></td>
            <td class="team-col">${team}</td>
            <td>${teamWeeksRanked[team]}/${totalWeeks}</td>
            <td>${teamTotalPts[team]}</td>
            <td>${avgRank}</td>
            <td>${firstPlace || "—"}</td>
            <td>${teamBestRank[team]}</td>
            <td>${hiRank}</td>
            <td>${loRank}</td>
        </tr>`;
    });

    html += `</tbody>`;
    table.innerHTML = html;
    modal.classList.add("open");
}

// Keyboard shortcuts
let rankingSortActive = false;
let sortTabsLocked = true;
let lastKeyWasU = false;

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

document.getElementById("keybind-legend-modal").addEventListener("click", e => {
    if (e.target === document.getElementById("keybind-legend-modal"))
        document.getElementById("keybind-legend-modal").classList.remove("open");
});

document.getElementById("avg-rank-modal").addEventListener("click", e => {
    if (e.target === document.getElementById("avg-rank-modal"))
        document.getElementById("avg-rank-modal").classList.remove("open");
});

document.getElementById("season-stats-modal").addEventListener("click", e => {
    if (e.target === document.getElementById("season-stats-modal"))
        document.getElementById("season-stats-modal").classList.remove("open");
});

document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
        document.getElementById("voter-history-modal").classList.remove("open");
        document.getElementById("keybind-legend-modal").classList.remove("open");
        document.getElementById("avg-rank-modal").classList.remove("open");
        document.getElementById("season-stats-modal").classList.remove("open");
    }
    // Check for unlock combo: Shift+U then !
    if (e.shiftKey && (e.key === "!" || e.key === "Shift")) {
        if (e.key === "!" && lastKeyWasU) {
            e.preventDefault();
            sortTabsLocked = false;
            lastKeyWasU = false;
            // Update UI to remove locked class from tabs
            document.querySelectorAll(".sort-option[data-sort='ranking'], .sort-option[data-sort='tenure']").forEach(opt => {
                opt.classList.remove("locked");
            });
            return;
        }
    }
    if (!e.shiftKey) {
        lastKeyWasU = false;
        return;
    }
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
        toggleAllDeltas();
        return;
    }

    if (e.key === "C" || e.key === "c") {
        e.preventDefault();
        applyTableSort("consensus");
        return;
    }

    if (e.key === "R" || e.key === "r") {
        e.preventDefault();
        if (!sortTabsLocked) {
            applyTableSort("ranking");
        }
        return;
    }

    if (e.key === "T" || e.key === "t") {
        e.preventDefault();
        if (!sortTabsLocked) {
            applyTableSort("tenure");
        }
        return;
    }

    if (e.key === "Y" || e.key === "y") {
        e.preventDefault();
        const activeTab = document.querySelector(".week-tab.active");
        if (activeTab) showAvgRankModal(activeTab.dataset.week);
        return;
    }

    if (e.key === "U" || e.key === "u") {
        e.preventDefault();
        lastKeyWasU = true;
        // Reset flag after 1 second if no ! is pressed
        setTimeout(() => { lastKeyWasU = false; }, 1000);
        showSeasonStatsModal();
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

    if (e.metaKey && e.code === "Digit0") {
        e.preventDefault();
        const preSeasonTab = document.querySelector(`.week-tab[data-year="${currentYear}"][data-weeknum="0"]`);
        if (preSeasonTab) {
            loadYear(currentYear).then(() => {
                showWeek(preSeasonTab.dataset.week);
                if (weekPickerPinned) rebuildWeekPicker();
            }).catch(() => {});
        }
        return;
    }

    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const sortedAll = getSortedTabs().filter(t => parseInt(t.dataset.weeknum) !== 0).slice().reverse();
        let idx = sortedAll.findIndex(t => t.dataset.week === activeTab.dataset.week);
        if (idx === -1 && currentWeekNum === 0) {
            // Currently on pre-season; treat as just before week 1 of this year
            const firstOfYear = sortedAll.findIndex(t => t.dataset.year === currentYear);
            idx = firstOfYear - 1;
        }
        const target = e.key === "ArrowRight"
            ? sortedAll[idx + 1]
            : sortedAll[idx - 1];
        if (target) {
            loadYear(target.dataset.year).then(() => {
                showWeek(target.dataset.week);
                if (weekPickerPinned) rebuildWeekPicker();
                backgroundLoad();
            }).catch(() => {});
        }
    }

    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        const tabs = getSortedTabs();
        const years = [...new Set(tabs.map(t => t.dataset.year))].filter(y => !HIDDEN_YEARS.has(y)).sort();
        const yearIdx = years.indexOf(currentYear);
        const targetYear = e.key === "ArrowUp"
            ? years[yearIdx + 1]
            : years[yearIdx - 1];
        if (!targetYear) return;
        loadYear(targetYear).then(() => {
            const yearTabs = getSortedTabs().filter(t => t.dataset.year === targetYear);
            const sameWeek = yearTabs.find(t => parseInt(t.dataset.weeknum) === currentWeekNum);
            const target = sameWeek || yearTabs.sort((a, b) => parseInt(b.dataset.weeknum) - parseInt(a.dataset.weeknum))[0];
            if (target) {
                showWeek(target.dataset.week);
                if (weekPickerPinned) rebuildWeekPicker();
                backgroundLoad();
            }
        }).catch(() => {});
    }

    if (e.key === "?") {
        e.preventDefault();
        document.getElementById("keybind-legend-modal").classList.toggle("open");
    }
});

// Update locked state UI
function updateLockedUI() {
    document.querySelectorAll(".sort-option[data-sort='ranking'], .sort-option[data-sort='tenure']").forEach(opt => {
        if (sortTabsLocked) {
            opt.classList.add("locked");
        } else {
            opt.classList.remove("locked");
        }
    });
}

// Init
updateLockedUI();
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
