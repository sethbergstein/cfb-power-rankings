(function () {
  const kind = document.body.dataset.rankingsKind;
  const snapshotSelect = document.getElementById("snapshot-select");
  const refreshBtn = document.getElementById("refresh-btn");
  const tableWrap = document.getElementById("rankings-table");
  const metaEl = document.getElementById("rankings-meta");
  const seasonBadge = document.getElementById("season-badge");

  let teamsBySchool = {};
  let lastTop25 = [];
  let lastAlsoRan = [];
  let lastPolls = null;

  const powerColumns = [
    { key: "rank", label: "Rank", cls: "col-rank" },
    { key: "school", label: "Team", cls: "col-team", align: "left" },
    { key: "conference", label: "Conf", cls: "col-conf", align: "center" },
    { key: "record", label: "W-L", cls: "col-num", align: "center" },
    { key: "power_score", label: "Power score", cls: "col-num", fmt: 2, align: "center" },
    { key: "power_rating", label: "Rating", cls: "col-num", fmt: 0, align: "center" },
    { key: "poll_rank", label: "Poll #", cls: "col-num", fmt: 0, align: "center" },
  ];

  const pollColumns = [
    { key: "rank", label: "Rank", cls: "col-rank" },
    { key: "school", label: "Team", cls: "col-team", align: "left" },
    { key: "conference", label: "Conf", cls: "col-conf", align: "center" },
    { key: "record", label: "W-L", cls: "col-num", align: "center" },
    { key: "poll_score", label: "Poll score", cls: "col-num", fmt: 2, align: "center" },
    { key: "poll_rating", label: "Rating", cls: "col-num", fmt: 0, align: "center" },
    { key: "power_rank", label: "Power #", cls: "col-num", fmt: 0, align: "center" },
  ];

  function activeColumns(polls) {
    const cols = (kind === "poll" ? pollColumns : powerColumns).slice();
    if (polls?.fpi) {
      cols.push({
        key: "fpi_rank",
        label: "FPI",
        title: "ESPN Football Power Index",
        cls: "col-num",
        align: "center",
        external: true,
      });
    }
    if (polls?.ap) {
      cols.push({
        key: "ap_rank",
        label: "AP",
        title: "AP Top 25",
        cls: "col-num",
        align: "center",
        external: true,
      });
    }
    if (polls?.cfp) {
      cols.push({
        key: "cfp_rank",
        label: "CFP",
        title: "CFP committee ranking",
        cls: "col-num",
        align: "center",
        external: true,
      });
    }
    return cols;
  }

  function applyExternalPolls(rows, polls) {
    const ap = polls?.ap || null;
    const cfp = polls?.cfp || null;
    const fpi = polls?.fpi || null;
    if (!ap && !cfp && !fpi) return rows;
    return rows.map((row) => {
      const next = { ...row };
      if (ap) next.ap_rank = ap[row.school] ?? null;
      if (cfp) next.cfp_rank = cfp[row.school] ?? null;
      if (fpi) next.fpi_rank = fpi[row.school] ?? null;
      return next;
    });
  }

  function cellValue(row, col) {
    if (col.key === "record") {
      const w = row.wins != null ? row.wins : "-";
      const l = row.losses != null ? row.losses : "-";
      const note = row.result_note
        ? `<abbr class="result-note" title="${BCPI.esc(row.result_note)}">*</abbr>`
        : "";
      return `${w}-${l}${note}`;
    }
    if (col.external) {
      const value = row[col.key];
      if (value == null || value === "") {
        return `<span class="external-blank" title="Unranked">—</span>`;
      }
      return BCPI.esc(String(value));
    }
    if (col.fmt != null) return BCPI.formatNum(row[col.key], col.fmt);
    return BCPI.esc(row[col.key]);
  }

  function teamCell(row) {
    const team = teamsBySchool[row.school] || {};
    const theme = BCPI.getTheme();
    const logo = BCPI.logoForTeam(team, theme);
    const logoHtml = logo
      ? `<img class="team-cell-logo" src="${BCPI.esc(logo)}" alt="" />`
      : `<span class="team-cell-logo"></span>`;
    const abbr = row.abbreviation || team.abbreviation || "";
    const colorStyle = team.color
      ? ` style="color:${BCPI.esc(BCPI.teamDisplayColor(team.color))}"`
      : "";
    return `
      <div class="team-cell">
        ${logoHtml}
        <div>
          <div class="team-cell-name"${colorStyle}>${BCPI.esc(row.school)}</div>
          <div class="team-cell-abbr">${BCPI.esc(abbr)}</div>
        </div>
      </div>`;
  }

  function renderTableSection(rows, { compact = false, columns } = {}) {
    const head = columns
      .map((c) => {
        const align = c.align === "left" ? " col-left" : " col-center";
        const title = c.title ? ` title="${BCPI.esc(c.title)}"` : "";
        return `<th class="${c.cls}${align}"${title}>${BCPI.esc(c.label)}</th>`;
      })
      .join("");

    const body = rows
      .map((row) => {
        const top = !compact && Number(row.rank) <= 5 ? " rank-top" : "";
        const cells = columns
          .map((c) => {
            const align = c.align === "left" ? " col-left" : " col-center";
            if (c.key === "school") {
              return `<td class="${c.cls}${align}">${teamCell(row)}</td>`;
            }
            return `<td class="${c.cls}${align}">${cellValue(row, c)}</td>`;
          })
          .join("");
        return `<tr class="${top}${compact ? " also-ran-row" : ""}">${cells}</tr>`;
      })
      .join("");

    return `
      <table class="ledger-table${compact ? " ledger-table-compact" : ""}">
        <thead class="${compact ? "also-ran-head" : ""}"><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>`;
  }

  function renderRankings(top25, alsoRan, polls) {
    lastPolls = polls || null;
    const columns = activeColumns(lastPolls);
    lastTop25 = applyExternalPolls(top25, lastPolls);
    lastAlsoRan = applyExternalPolls(alsoRan, lastPolls);
    let html = renderTableSection(lastTop25, { columns });
    if (lastAlsoRan.length) {
      html += `
        <div class="also-ran-section">
          <h3 class="also-ran-title">Just outside the top 25</h3>
          <p class="also-ran-sub">Ranks 26 through ${25 + lastAlsoRan.length}.</p>
          ${renderTableSection(lastAlsoRan, { compact: true, columns })}
        </div>`;
    }
    tableWrap.innerHTML = html;
    updateTableScrollState();
  }

  function updateTableScrollState() {
    if (!window.matchMedia("(max-width: 720px)").matches) {
      tableWrap.classList.remove("has-horizontal-scroll");
      return;
    }
    tableWrap.classList.toggle(
      "has-horizontal-scroll",
      tableWrap.scrollWidth > tableWrap.clientWidth + 2
    );
  }

  function renderMeta(data, snapshot) {
    if (!metaEl) return;
    const label = data.label || snapshot.label;
    const indexName =
      kind === "poll" ? "Bergstein Poll Index" : "Bergstein Power Index";
    const updated = BCPI.formatAsOf(data.as_of);
    metaEl.innerHTML = `
      <span>${indexName}</span>
      <span>${BCPI.esc(label)}</span>
      ${updated ? `<span>Updated ${updated}</span>` : ""}`;
  }

  function rankingsCacheReady(snapshot) {
    if (!BCPI.isStatic() || !snapshot?.id) return false;
    const rankFile = kind === "poll" ? "poll.json" : "power.json";
    return (
      BCPI.hasSessionCache(`snapshots/${snapshot.id}/teams.json`) &&
      BCPI.hasSessionCache(`snapshots/${snapshot.id}/${rankFile}`)
    );
  }

  async function loadRankings(refresh) {
    const snapshot = BCPI.getSnapshot(snapshotSelect);
    if (!snapshot) {
      tableWrap.innerHTML = `<div class="loading-row">No season snapshots published yet.</div>`;
      return;
    }

    const loaderMessage = refresh
      ? "Recalculating from CFBD data…"
      : `Loading ${kind} rankings…`;
    const cacheReady = !refresh && rankingsCacheReady(snapshot);
    if (!cacheReady) {
      BCPI.showLoader(loaderMessage, { immediate: refresh });
      tableWrap.innerHTML = `<div class="loading-row">${BCPI.esc(loaderMessage)}</div>`;
    }
    if (refreshBtn) refreshBtn.hidden = BCPI.isStatic();

    try {
      const externalPromise = BCPI.isStatic()
        ? fetchExternalPolls(snapshot)
        : Promise.resolve(null);
      const [{ bySchool }, data, staticPolls] = await Promise.all([
        BCPI.fetchTeams(snapshot),
        BCPI.fetchRankings(kind, { snapshot, refresh }),
        externalPromise,
      ]);
      teamsBySchool = bySchool;
      if (seasonBadge) seasonBadge.textContent = snapshot.label;
      renderRankings(
        data.rows || [],
        data.also_ran || [],
        data.external_polls || staticPolls
      );
      renderMeta(data, snapshot);
    } catch (err) {
      tableWrap.innerHTML = `<div class="loading-row">${BCPI.esc(err.message)}</div>`;
    } finally {
      BCPI.hideLoader();
    }
  }

  async function fetchExternalPolls(snapshot) {
    if (!snapshot?.id) return null;
    const path = `snapshots/${snapshot.id}/external_polls.json`;
    try {
      return await BCPI.fetchJsonCached(path);
    } catch {
      return null;
    }
  }

  refreshBtn?.addEventListener("click", () => loadRankings(true));
  document.addEventListener("bcpi-theme-change", () => {
    if (lastTop25.length) renderRankings(lastTop25, lastAlsoRan, lastPolls);
  });

  BCPI.initSnapshotSelect(snapshotSelect, () => loadRankings(false)).then(() =>
    loadRankings(false)
  );
  window.addEventListener("resize", updateTableScrollState);
})();
