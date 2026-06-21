(function () {
  const kind = document.body.dataset.rankingsKind;
  const snapshotSelect = document.getElementById("snapshot-select");
  const refreshBtn = document.getElementById("refresh-btn");
  const tableWrap = document.getElementById("rankings-table");
  const metaEl = document.getElementById("rankings-meta");
  const seasonBadge = document.getElementById("season-badge");

  let teamsBySchool = {};

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

  const columns = kind === "poll" ? pollColumns : powerColumns;

  function cellValue(row, col) {
    if (col.key === "record") {
      const w = row.wins != null ? row.wins : "-";
      const l = row.losses != null ? row.losses : "-";
      return `${w}-${l}`;
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

  function renderTableSection(rows, { compact = false } = {}) {
    const head = columns
      .map((c) => {
        const align = c.align === "left" ? " col-left" : " col-center";
        return `<th class="${c.cls}${align}">${BCPI.esc(c.label)}</th>`;
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

  function renderRankings(top25, alsoRan) {
    let html = renderTableSection(top25);
    if (alsoRan.length) {
      html += `
        <div class="also-ran-section">
          <h3 class="also-ran-title">Just outside the top 25</h3>
          <p class="also-ran-sub">Ranks 26 through ${25 + alsoRan.length}.</p>
          ${renderTableSection(alsoRan, { compact: true })}
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

  async function loadRankings(refresh) {
    const snapshot = BCPI.getSnapshot(snapshotSelect);
    if (!snapshot) {
      tableWrap.innerHTML = `<div class="loading-row">No season snapshots published yet.</div>`;
      return;
    }

    const loaderMessage = refresh
      ? "Recalculating from CFBD data…"
      : `Loading ${kind} rankings…`;
    BCPI.showLoader(loaderMessage);
    tableWrap.innerHTML = `<div class="loading-row">${BCPI.esc(loaderMessage)}</div>`;
    if (refreshBtn) refreshBtn.hidden = BCPI.isStatic();

    try {
      const { bySchool } = await BCPI.fetchTeams(snapshot);
      teamsBySchool = bySchool;
      if (seasonBadge) seasonBadge.textContent = snapshot.label;

      const data = await BCPI.fetchRankings(kind, { snapshot, refresh });
      renderRankings(data.rows || [], data.also_ran || []);

      if (metaEl) {
        const label = data.label || snapshot.label;
        const indexName =
          kind === "poll" ? "Bergstein Poll Index" : "Bergstein Power Index";
        const updated = BCPI.formatAsOf(data.as_of);
        metaEl.innerHTML = `
          <span>${indexName}</span>
          <span>${BCPI.esc(label)}</span>
          ${updated ? `<span>Updated ${updated}</span>` : ""}`;
      }
    } catch (err) {
      tableWrap.innerHTML = `<div class="loading-row">${BCPI.esc(err.message)}</div>`;
    } finally {
      BCPI.hideLoader();
    }
  }

  refreshBtn?.addEventListener("click", () => loadRankings(true));
  document.addEventListener("bcpi-theme-change", () => {
    if (tableWrap.querySelector(".ledger-table")) loadRankings(false);
  });

  BCPI.initSnapshotSelect(snapshotSelect, () => loadRankings(false)).then(() =>
    loadRankings(false)
  );
  window.addEventListener("resize", updateTableScrollState);
})();
