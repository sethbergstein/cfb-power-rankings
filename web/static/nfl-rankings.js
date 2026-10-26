(function () {
  const view = document.getElementById("view");
  const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

  const COMPONENT_COPY = {
    results_margin: {
      title: "Results & Margin",
      copy: "How the team has scored and allowed points, adjusted for opponent strength. Defense lives here. Early weeks still lean on a preseason expectation that fades as games pile up.",
    },
    offense: {
      title: "Offense",
      copy: "How efficient the offense is on a per-play basis, opponent-adjusted.",
    },
    quarterback: {
      title: "Quarterback",
      copy: "Who is expected to play QB this week compared with the QB the team's results so far were built on.",
    },
    injuries: {
      title: "Injuries",
      copy: "Starters newly ruled out or questionable this week, compared with the league average. A normal injury week lands near zero.",
    },
  };

  let catalog = null;
  let teamsByAbbr = {};

  function esc(value) {
    return BCPI.esc(value == null ? "" : String(value));
  }

  function signed(value) {
    const number = Number(value) || 0;
    if (Math.abs(number) < 0.005) return "0.00";
    const body = Math.abs(number).toFixed(2);
    return `${number > 0 ? "+" : "−"}${body}`;
  }

  function points(value) {
    return (Number(value) || 0).toFixed(2);
  }

  function editionDate(iso) {
    if (!iso) return "";
    const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
    if (Number.isNaN(date.getTime())) return "";
    return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}, ${date.getUTCFullYear()}`;
  }

  async function loadCatalog() {
    if (catalog) return catalog;
    catalog = await BCPI.fetchJsonCached("nfl/catalog.json");
    return catalog;
  }

  async function loadTeams() {
    const rows = await BCPI.fetchJsonCached("nfl/teams.json");
    teamsByAbbr = {};
    (rows || []).forEach((row) => {
      teamsByAbbr[row.team || row.abbreviation] = row;
    });
    return rows;
  }

  async function loadPower(snap) {
    if (!snap) {
      return BCPI.fetchJsonCached("nfl/power.json");
    }
    if (snap.id === catalog.default) {
      return BCPI.fetchJsonCached("nfl/power.json");
    }
    return BCPI.fetchJsonCached(`nfl/snapshots/${snap.id}/power.json`);
  }

  function seasonsInCatalog() {
    const set = new Set((catalog.snapshots || []).map((snap) => snap.season));
    return [...set].sort((a, b) => b - a);
  }

  function snapsForSeason(season) {
    return (catalog.snapshots || [])
      .filter((snap) => snap.season === season)
      .sort((a, b) => a.week - b.week);
  }

  function snapFromQuery() {
    const params = new URLSearchParams(location.search);
    const seasonParam = params.get("season");
    const weekParam = params.get("week");
    const defaultSnap =
      (catalog.snapshots || []).find((snap) => snap.id === catalog.default) || catalog.snapshots[0];
    const season = seasonParam ? Number(seasonParam) : defaultSnap.season;
    const snaps = snapsForSeason(season);
    if (weekParam != null && weekParam !== "") {
      const match = snaps.find((snap) => String(snap.week) === weekParam);
      if (match) return match;
    }
    if (season === defaultSnap.season) return defaultSnap;
    return snaps[snaps.length - 1] || defaultSnap;
  }

  function listUrl(snap) {
    return BCPI.pageUrl("nfl-power", { season: snap.season, week: snap.week });
  }

  function teamUrl(snap, team) {
    return BCPI.pageUrl("nfl-power", {
      season: snap.season,
      week: snap.week,
      team: String(team).toLowerCase(),
    });
  }

  function paintDateline(snap, asOf) {
    const season = document.getElementById("dateline-season");
    const edition = document.getElementById("dateline-edition");
    const date = document.getElementById("dateline-date");
    if (season) season.textContent = `${snap.season} SEASON`;
    if (edition) edition.textContent = `Week ${snap.week} Edition`;
    if (date) date.textContent = editionDate(asOf);
  }

  function logoHtml(team, klass) {
    const src = team && (team.logo || team.logo_dark);
    if (!src) return `<span class="${klass}"></span>`;
    return `<img class="${klass}" src="${esc(src)}" alt="" />`;
  }

  function qbFlag(row) {
    if (row.starter_prob == null || Number(row.starter_prob) >= 1) return "";
    const pct = Math.round(Number(row.starter_prob) * 100);
    const alt = row.alt_qb && row.alt_qb !== row.starter ? ` / ${row.alt_qb}` : "";
    return `<span class="qb-flag" title="${esc(row.qb_note || "QB situation unsettled")}">QB ${esc(
      row.starter || "?"
    )}${esc(alt)} · ${pct}%</span>`;
  }

  function earlyNote(week) {
    if (week > 5) return "";
    return `<p class="note">Through week ${week}: early rankings still lean on last year and roster change. The engine is least sharp here.</p>`;
  }

  function editorFootnote(pack) {
    const applied = Number(pack && pack.meta && pack.meta.overrides_applied);
    if (!Number.isFinite(applied) || applied <= 0) return "";
    return `<p class="caption editor-note">Some quarterback statuses are set by the editor.</p>`;
  }

  function pickerHtml(snap) {
    const seasons = seasonsInCatalog();
    const weeks = snapsForSeason(snap.season);
    const seasonOpts = seasons
      .map(
        (year) =>
          `<option value="${year}"${year === snap.season ? " selected" : ""}>${year}</option>`
      )
      .join("");
    const weekOpts = weeks
      .map(
        (item) =>
          `<option value="${item.week}"${item.week === snap.week ? " selected" : ""}>Week ${
            item.week
          }</option>`
      )
      .join("");
    return `
      <div class="edition-pickers">
        <label class="edition-pick">
          <span>Season</span>
          <select id="nfl-season">${seasonOpts}</select>
        </label>
        <label class="edition-pick">
          <span>Week</span>
          <select id="nfl-week">${weekOpts}</select>
        </label>
      </div>`;
  }

  function bindPickers(snap) {
    const seasonEl = document.getElementById("nfl-season");
    const weekEl = document.getElementById("nfl-week");
    if (!seasonEl || !weekEl) return;
    seasonEl.addEventListener("change", () => {
      const season = Number(seasonEl.value);
      const snaps = snapsForSeason(season);
      const next = snaps[snaps.length - 1] || snap;
      location.assign(listUrl(next));
    });
    weekEl.addEventListener("change", () => {
      location.assign(
        BCPI.pageUrl("nfl-power", { season: snap.season, week: weekEl.value })
      );
    });
  }

  function renderList(pack, snap) {
    const rows = (pack.teams || [])
      .map((row) => {
        const team = teamsByAbbr[row.team] || {};
        return `<a class="board-row cols-power" href="${esc(teamUrl(snap, row.team))}">
          <span class="num">${esc(row.rank)}</span>
          <span class="team-bits">
            ${logoHtml(team, "logo")}
            <span>
              <span class="team-name">${esc(row.name)}</span>
              <span class="conf">${esc(team.conference || row.team)}</span>
              ${qbFlag(row)}
            </span>
          </span>
          <span class="rec">${esc(row.record || "—")}</span>
          <span class="score">${esc(points(row.power))}</span>
        </a>`;
      })
      .join("");
    view.innerHTML = `
      <p class="sec-label"><span>NFL power rankings</span><i></i></p>
      <h2 class="headline">Who wins on a neutral field</h2>
      <p class="deck">Points better than an average team, right now. No betting lines in the score.</p>
      ${pickerHtml(snap)}
      ${earlyNote(snap.week)}
      <div class="board">
        <div class="board-head cols-power"><span>No.</span><span>Team</span><span class="rec">Rec</span><span class="score">Score</span></div>
        ${rows}
      </div>
      <p class="caption">Tap any team to see what's behind its score. Record and point differential are display-only.</p>
      ${editorFootnote(pack)}`;
    bindPickers(snap);
  }

  function pieceBlock({ title, verdict, copy, meta, zero }) {
    return `
      <section class="piece${zero ? " is-zero" : ""}">
        <div class="piece-top">
          <h3>${esc(title)}</h3>
          <p class="verdict">${esc(verdict)}</p>
        </div>
        <p>${esc(copy)}</p>
        <p class="meta">${esc(meta)}</p>
      </section>`;
  }

  function splitBar(parts) {
    const shown = parts.filter((part) => part.always || Math.abs(part.value) >= 0.05);
    const total = shown.reduce((sum, part) => sum + Math.abs(part.value), 0);
    if (total <= 0) return "";
    const legend = [];
    const segs = shown
      .map((part) => {
        const negative = part.value < -0.005;
        const klass = negative ? "neg" : part.tone;
        const width = (Math.abs(part.value) / total) * 100;
        const shownValue = part.value < -0.005 ? signed(part.value) : Math.abs(part.value).toFixed(2);
        const label = `${part.name} ${shownValue}`;
        const inside = width >= 28 && !negative;
        if (!inside) legend.push(label);
        const inner = inside ? `<b>${esc(label)}</b>` : "";
        return `<span class="${klass}" style="flex:${width} 1 0">${inner}</span>`;
      })
      .join("");
    const legendHtml = legend.length
      ? `<div class="split-legend">${legend.map((label) => `<span>${esc(label)}</span>`).join("")}</div>`
      : "";
    return `<div class="split">${segs}</div>${legendHtml}`;
  }

  function renderTeam(row, snap, pack) {
    const team = teamsByAbbr[row.team] || {};
    const leader = (pack.teams || []).find((item) => Number(item.rank) === 1);
    const runner = (pack.teams || []).find((item) => Number(item.rank) === 2);
    const gapLabel = Number(row.rank) === 1 ? "Ahead of No. 2" : "Behind No. 1";
    let gapValue = "—";
    if (Number(row.rank) === 1 && runner) gapValue = points(Number(row.power) - Number(runner.power));
    else if (leader) gapValue = signed(Number(row.power) - Number(leader.power));

    const components = row.components || {};
    const order = ["results_margin", "offense", "quarterback", "injuries"];
    const tones = { results_margin: "solid", offense: "hatch", quarterback: "plain", injuries: "plain" };
    const splitParts = order.map((key) => ({
      name: COMPONENT_COPY[key].title.split(" ")[0],
      value: Number(components[key]) || 0,
      tone: tones[key],
      always: true,
    }));

    const qbLine =
      Number(row.starter_prob) < 1
        ? `${row.starter} is ${Math.round(Number(row.starter_prob) * 100)}% to start${
            row.alt_qb && row.alt_qb !== row.starter ? `; ${row.alt_qb} is the alternate` : ""
          }.`
        : `${row.starter || "The starter"} is locked in.`;

    const breakdown = `
      <p class="sec-label"><span>What's behind the ${esc(points(row.power))}</span><i></i></p>
      ${splitBar(splitParts)}
      ${order
        .map((key) => {
          const info = COMPONENT_COPY[key];
          const value = Number(components[key]) || 0;
          let extra = "";
          if (key === "quarterback") extra = ` ${qbLine}`;
          if (key === "injuries" && row.injury_starters_newly_lost != null) {
            extra = ` Raw starter-equivalents newly lost: ${Number(row.injury_starters_newly_lost).toFixed(2)}.`;
          }
          return pieceBlock({
            title: info.title,
            verdict: signed(value),
            copy: info.copy + extra,
            meta: `Adds ${signed(value)}`,
            zero: Math.abs(value) < 0.005,
          });
        })
        .join("")}`;

    view.innerHTML = `
      <div class="inside-bar">
        <a class="back" href="${esc(listUrl(snap))}">‹ NFL power rankings</a>
        <a class="mini-mark" href="${esc(listUrl(snap))}">The Press Box</a>
      </div>
      <p class="sec-label"><span>No. ${esc(row.rank)} · ${esc(team.conference || "")} · ${esc(
      row.record || "—"
    )}</span><i></i></p>
      <div class="team-lockup">
        ${logoHtml(team, "logo-lg")}
        <h2>${esc(row.name)}</h2>
      </div>
      <p class="one-liner">${esc(row.name)} is ${esc(signed(row.power))} points vs average on a neutral field. Point differential ${esc(
      row.point_diff > 0 ? `+${row.point_diff}` : String(row.point_diff)
    )}.</p>
      ${qbFlag(row)}
      <div class="statbox">
        <div class="stat"><div class="lbl">Power score</div><div class="val">${esc(points(row.power))}</div></div>
        <div class="stat"><div class="lbl">Point diff</div><div class="val">${esc(
          row.point_diff > 0 ? `+${row.point_diff}` : String(row.point_diff)
        )}</div></div>
        <div class="stat"><div class="lbl">${esc(gapLabel)}</div><div class="val">${esc(gapValue)}</div></div>
      </div>
      ${breakdown}
      ${editorFootnote(pack)}`;
  }

  async function boot() {
    await loadCatalog();
    await loadTeams();
    const snap = snapFromQuery();
    const pack = await loadPower(snap);
    paintDateline(snap, pack.meta?.generated_utc);
    const params = new URLSearchParams(location.search);
    const teamKey = (params.get("team") || "").toUpperCase();
    if (teamKey) {
      const row = (pack.teams || []).find((item) => item.team === teamKey);
      if (row) {
        document.querySelectorAll(".banner, .masthead, .dateline, .rail").forEach((el) => {
          el.hidden = true;
        });
        renderTeam(row, snap, pack);
        return;
      }
    }
    renderList(pack, snap);
  }

  boot().catch((error) => {
    view.innerHTML = `<p class="note">${esc(error.message || "Could not load NFL rankings.")}</p>`;
  });
})();
