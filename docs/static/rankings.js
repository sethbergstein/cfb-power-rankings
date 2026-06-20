(function () {
  const kind = document.body.dataset.rankingsKind;
  const seasonInput = document.getElementById("season");
  const postseasonInput = document.getElementById("postseason");
  const postseasonWrap = document.getElementById("postseason-wrap");
  const refreshBtn = document.getElementById("refresh-btn");
  const tableWrap = document.getElementById("rankings-table");
  const metaEl = document.getElementById("rankings-meta");
  const seasonBadge = document.getElementById("season-badge");

  let teamsBySchool = {};

  function season() {
    return Number(seasonInput?.value) || BCPI.defaultSeason;
  }

  function postseason() {
    return postseasonInput?.checked ? 1 : 0;
  }

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
      const w = row.wins != null ? row.wins : "—";
      const l = row.losses != null ? row.losses : "—";
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
          <h3 class="also-ran-title">Others in consideration</h3>
          <p class="also-ran-sub">Next ${alsoRan.length} out — not ranked, but closest to the top 25.</p>
          ${renderTableSection(alsoRan, { compact: true })}
        </div>`;
    }
    tableWrap.innerHTML = html;
  }

  async function loadRankings(refresh) {
    tableWrap.innerHTML = `<div class="loading-row">Loading ${kind} rankings…</div>`;
    BCPI.syncPostseasonControl(seasonInput, postseasonInput, postseasonWrap);
    if (refreshBtn) refreshBtn.hidden = BCPI.isStatic();
    try {
      const { bySchool } = await BCPI.fetchTeams(season());
      teamsBySchool = bySchool;
      const manifest = BCPI.isStatic() ? await BCPI.loadManifest() : null;
      if (seasonBadge) {
        seasonBadge.textContent = manifest ? manifest.label : `${season()} season`;
      }

      const data = await BCPI.fetchRankings(kind, {
        season: season(),
        postseason: postseason(),
        refresh,
      });

      renderRankings(data.rows || [], data.also_ran || []);

      if (metaEl) {
        const label = data.postseason ? "postseason" : `week ${data.week}`;
        const indexName =
          kind === "poll" ? "Bergstein Poll Index" : "Bergstein Power Index";
        const updated = BCPI.formatAsOf(data.as_of);
        metaEl.innerHTML = `
          <span>${indexName} · proprietary composite model</span>
          <span>${manifest?.label || `${season()} · ${label}`}</span>
          ${updated ? `<span>Updated ${updated}</span>` : ""}`;
      }
    } catch (err) {
      tableWrap.innerHTML = `<div class="loading-row">${BCPI.esc(err.message)}</div>`;
    }
  }

  seasonInput?.addEventListener("change", () => loadRankings(false));
  postseasonInput?.addEventListener("change", () => loadRankings(false));
  refreshBtn?.addEventListener("click", () => loadRankings(true));
  document.addEventListener("bcpi-theme-change", () => {
    if (tableWrap.querySelector(".ledger-table")) loadRankings(false);
  });

  BCPI.syncPostseasonControl(seasonInput, postseasonInput, postseasonWrap);
  loadRankings(false);
})();
