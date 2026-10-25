(function () {
  const view = document.getElementById("view");
  const slotA = document.getElementById("slot-a");
  const slotB = document.getElementById("slot-b");
  const venue = document.getElementById("venue");
  const venueDetail = document.getElementById("venue-detail");
  const projection = document.getElementById("projection");
  const ratings = document.getElementById("ratings-asof");
  const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

  const COMPONENT_LABELS = {
    results_margin: "Results & margin",
    offense: "Offense",
    quarterback: "Quarterback",
    injuries: "Injuries",
  };

  let catalog = null;
  let pack = null;
  let teams = [];
  let teamsBySchool = {};
  let powerByTeam = {};
  let schoolA = "Kansas City Chiefs";
  let schoolB = "Buffalo Bills";
  let site = "home_a";

  function esc(value) {
    return BCPI.esc(value == null ? "" : String(value));
  }

  function editionDate(iso) {
    if (!iso) return "";
    const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
    if (Number.isNaN(date.getTime())) return "";
    return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}, ${date.getUTCFullYear()}`;
  }

  function erf(x) {
    const s = Math.sign(x);
    x = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * x);
    const y =
      1 -
      (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
        t *
        Math.exp(-x * x));
    return s * y;
  }

  function normalCDF(z) {
    return 0.5 * (1 + erf(z / Math.SQRT2));
  }

  function predict(homeAbbr, awayAbbr, neutral) {
    const h = powerByTeam[homeAbbr];
    const a = powerByTeam[awayAbbr];
    if (!h || !a) throw new Error("Missing power ratings for one of these teams.");
    const hf = neutral ? 0 : Number(pack.meta.home_field);
    const margin = hf + Number(h.power) - Number(a.power);
    const pHome = normalCDF(margin / Number(pack.meta.win_prob_sigma));
    const why = {};
    Object.keys(h.components || {}).forEach((key) => {
      why[key] = Number(h.components[key]) - Number(a.components[key]);
    });
    return { margin, pHome, why, homeField: hf, home: h, away: a };
  }

  function logo(team) {
    const src = team && (team.logo || team.logo_dark);
    if (!src) return `<span class="logo-md"></span>`;
    return `<img class="logo-md" src="${esc(src)}" alt="" />`;
  }

  function powerLine(school) {
    const team = teamsBySchool[school];
    const row = team && powerByTeam[team.team || team.abbreviation];
    if (!row || row.power == null) return "Power —";
    return `Power ${Number(row.power).toFixed(2)}`;
  }

  function paintSlot(el, school) {
    const team = teamsBySchool[school];
    el.innerHTML = `
      ${logo(team)}
      <p class="name">${esc(school || "Select")}</p>
      <p class="pwr">${esc(powerLine(school))}</p>
      <button type="button" class="change">Change</button>`;
    el.querySelector(".change").addEventListener("click", async () => {
      const picked = await BCPI.pickTeam({ teams, title: "NFL teams" });
      if (!picked || picked === school) return;
      if (el === slotA) schoolA = picked;
      else schoolB = picked;
      paint();
      runPredict();
    });
  }

  function venueInfo(school) {
    const team = teamsBySchool[school] || {};
    let stadium = team.venue_name || (school ? `${school} Stadium` : "");
    const location =
      team.venue_location || [team.venue_city, team.venue_state].filter(Boolean).join(", ");
    if (location && stadium.includes(`(${location})`)) {
      stadium = stadium.replace(` (${location})`, "").trim();
    }
    return { stadium, location };
  }

  function paintVenue() {
    const options = [
      { id: "neutral", label: "Neutral" },
      { id: "home_a", label: schoolA ? `At ${shortName(schoolA)}` : "At team A" },
      { id: "home_b", label: schoolB ? `At ${shortName(schoolB)}` : "At team B" },
    ];
    venue.innerHTML = options
      .map(
        (option) =>
          `<button type="button" data-site="${option.id}" aria-pressed="${
            option.id === site ? "true" : "false"
          }">${esc(option.label)}</button>`
      )
      .join("");
    venue.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.site === site) return;
        site = button.dataset.site;
        paintVenue();
        runPredict();
      });
    });
    paintVenueDetail();
  }

  function shortName(school) {
    const team = teamsBySchool[school];
    if (!team) return school;
    const parts = String(school).split(" ");
    return team.abbreviation || parts[parts.length - 1];
  }

  function paintVenueDetail() {
    if (!venueDetail) return;
    if (site === "neutral") {
      venueDetail.innerHTML = `Neutral site<span class="venue-city">No home field</span>`;
      return;
    }
    const school = site === "home_a" ? schoolA : schoolB;
    const info = venueInfo(school);
    const meta = info.location || "";
    venueDetail.innerHTML = `${esc(info.stadium || `${school} home`)}${
      meta ? `<span class="venue-city">${esc(meta)}</span>` : ""
    }`;
  }

  function paint() {
    paintSlot(slotA, schoolA);
    paintSlot(slotB, schoolB);
    paintVenue();
  }

  function venueName() {
    if (site === "neutral") return "Neutral";
    const school = site === "home_a" ? schoolA : schoolB;
    const info = venueInfo(school);
    return info.stadium || `At ${school}`;
  }

  function signedPoints(value) {
    const number = Number(value) || 0;
    if (Math.abs(number) < 0.05) return "0.0";
    return `${number > 0 ? "+" : "−"}${Math.abs(number).toFixed(1)}`;
  }

  function qbNotes(rows) {
    return rows
      .filter((row) => Number(row.starter_prob) < 1)
      .map(
        (row) =>
          `${row.team}: ${row.starter} (${Math.round(Number(row.starter_prob) * 100)}% to start)`
      );
  }

  function renderProjection(result, homeName, awayName) {
    const margin = result.margin;
    const pctHome = Math.round(result.pHome * 100);
    const pctAway = 100 - pctHome;
    const favorite = margin >= 0 ? homeName : awayName;
    const headline =
      Math.abs(margin) < 0.05 ? "Even" : `${favorite} by ${Math.abs(margin).toFixed(1)}`;
    const aIsHome = site !== "home_b";
    const pctA = aIsHome ? pctHome : pctAway;
    const pctB = aIsHome ? pctAway : pctHome;
    const aLeads = pctA >= pctB;
    const powerGap = Number(result.home.power) - Number(result.away.power);
    const whyRows = Object.entries(result.why)
      .map(([key, value]) => {
        const fromA = aIsHome ? value : -value;
        return `<div class="proj-line"><dt>${esc(COMPONENT_LABELS[key] || key)}</dt><dd>${esc(
          signedPoints(fromA)
        )}</dd></div>`;
      })
      .join("");
    const flags = qbNotes([result.home, result.away]);
    projection.hidden = false;
    projection.innerHTML = `
      <p class="proj-kicker">Projection · ${esc(venueName())}</p>
      <h2 class="proj-headline">${esc(headline)}</h2>
      <div class="winbar">
        <div class="${aLeads ? "solid" : "hatch"}" style="width:${pctA}%"></div>
        <div class="${aLeads ? "hatch" : "solid"}" style="width:${pctB}%"></div>
      </div>
      <div class="pct-row">
        <span>${esc(schoolA)} ${pctA}%</span>
        <span>${pctB}% ${esc(schoolB)}</span>
      </div>
      <dl class="proj-lines">
        <div class="proj-line"><dt>Power gap</dt><dd>${esc(
          Math.abs(powerGap) < 0.05
            ? "None"
            : `${powerGap >= 0 === aIsHome ? schoolA : schoolB} by ${Math.abs(powerGap).toFixed(1)}`
        )}</dd></div>
        <div class="proj-line"><dt>Home field</dt><dd>${esc(
          Math.abs(result.homeField) < 0.05
            ? "None"
            : `${Math.abs(result.homeField).toFixed(1)} points to ${
                site === "home_a" ? schoolA : site === "home_b" ? schoolB : "neither"
              }`
        )}</dd></div>
        ${whyRows}
      </dl>
      <p class="note">Expected margin, not a betting line. A typical miss is about ${esc(
        Number(pack.meta.win_prob_sigma).toFixed(1)
      )} points.</p>
      ${
        flags.length
          ? `<p class="note">${esc(flags.join(". "))}.</p>`
          : ""
      }`;
  }

  function runPredict() {
    if (!schoolA || !schoolB) {
      projection.hidden = true;
      return;
    }
    if (schoolA === schoolB) {
      projection.hidden = false;
      projection.innerHTML = `<p class="note">Pick two different teams.</p>`;
      return;
    }
    const teamA = teamsBySchool[schoolA];
    const teamB = teamsBySchool[schoolB];
    if (!teamA || !teamB) {
      projection.hidden = false;
      projection.innerHTML = `<p class="note">Could not resolve teams.</p>`;
      return;
    }
    const home = site === "home_b" ? teamB : teamA;
    const away = site === "home_b" ? teamA : teamB;
    const neutral = site === "neutral";
    try {
      const result = predict(home.team || home.abbreviation, away.team || away.abbreviation, neutral);
      renderProjection(result, home.school || home.name, away.school || away.name);
    } catch (error) {
      projection.hidden = false;
      projection.innerHTML = `<p class="note">${esc(error.message || "Could not run this matchup.")}</p>`;
    }
  }

  function snapsForSeason(season) {
    return (catalog.snapshots || [])
      .filter((snap) => snap.season === season)
      .sort((a, b) => a.week - b.week);
  }

  function seasonsInCatalog() {
    return [...new Set((catalog.snapshots || []).map((snap) => snap.season))].sort((a, b) => b - a);
  }

  function snapFromQuery() {
    const params = new URLSearchParams(location.search);
    const defaultSnap =
      (catalog.snapshots || []).find((snap) => snap.id === catalog.default) || catalog.snapshots[0];
    const season = params.get("season") ? Number(params.get("season")) : defaultSnap.season;
    const weekParam = params.get("week");
    const snaps = snapsForSeason(season);
    if (weekParam != null && weekParam !== "") {
      const match = snaps.find((snap) => String(snap.week) === weekParam);
      if (match) return match;
    }
    if (season === defaultSnap.season) return defaultSnap;
    return snaps[snaps.length - 1] || defaultSnap;
  }

  function pickerHtml(snap) {
    const seasons = seasonsInCatalog();
    const weeks = snapsForSeason(snap.season);
    return `
      <div class="edition-pickers">
        <label class="edition-pick">
          <span>Season</span>
          <select id="nfl-season">${seasons
            .map(
              (year) =>
                `<option value="${year}"${year === snap.season ? " selected" : ""}>${year}</option>`
            )
            .join("")}</select>
        </label>
        <label class="edition-pick">
          <span>Week</span>
          <select id="nfl-week">${weeks
            .map(
              (item) =>
                `<option value="${item.week}"${item.week === snap.week ? " selected" : ""}>Week ${
                  item.week
                }</option>`
            )
            .join("")}</select>
        </label>
      </div>`;
  }

  function bindPickers(snap) {
    const seasonEl = document.getElementById("nfl-season");
    const weekEl = document.getElementById("nfl-week");
    const host = document.getElementById("edition-host");
    if (!seasonEl || !weekEl) return;
    seasonEl.addEventListener("change", () => {
      const snaps = snapsForSeason(Number(seasonEl.value));
      const next = snaps[snaps.length - 1] || snap;
      location.assign(BCPI.pageUrl("nfl-matchup", { season: next.season, week: next.week }));
    });
    weekEl.addEventListener("change", () => {
      location.assign(BCPI.pageUrl("nfl-matchup", { season: snap.season, week: weekEl.value }));
    });
    if (host) host.hidden = false;
  }

  async function loadPower(snap) {
    if (snap.id === catalog.default) return BCPI.fetchJsonCached("nfl/power.json");
    return BCPI.fetchJsonCached(`nfl/snapshots/${snap.id}/power.json`);
  }

  async function boot() {
    catalog = await BCPI.fetchJsonCached("nfl/catalog.json");
    const snap = snapFromQuery();
    const [teamRows, powerPack] = await Promise.all([
      BCPI.fetchJsonCached("nfl/teams.json"),
      loadPower(snap),
    ]);
    pack = powerPack;
    teams = teamRows || [];
    teamsBySchool = {};
    teams.forEach((row) => {
      teamsBySchool[row.school || row.name] = row;
    });
    powerByTeam = {};
    (pack.teams || []).forEach((row) => {
      powerByTeam[row.team] = row;
    });

    const season = document.getElementById("dateline-season");
    const edition = document.getElementById("dateline-edition");
    const date = document.getElementById("dateline-date");
    if (season) season.textContent = `${snap.season} SEASON`;
    if (edition) edition.textContent = `Week ${snap.week} Edition`;
    if (date) date.textContent = editionDate(pack.meta?.generated_utc);
    if (ratings) ratings.textContent = `Ratings through week ${snap.week}`;

    const host = document.getElementById("edition-host");
    if (host) {
      host.innerHTML = pickerHtml(snap);
      bindPickers(snap);
    }

    if (!teamsBySchool[schoolA] && teams[0]) schoolA = teams[0].school || teams[0].name;
    if (!teamsBySchool[schoolB] && teams[1]) schoolB = teams[1].school || teams[1].name;
    paint();
    runPredict();
  }

  boot().catch((error) => {
    view.insertAdjacentHTML(
      "beforeend",
      `<p class="note">${esc(error.message || "Could not load NFL matchup.")}</p>`
    );
  });
})();
