(function () {
  const view = document.getElementById("view");
  const slotA = document.getElementById("slot-a");
  const slotB = document.getElementById("slot-b");
  const venue = document.getElementById("venue");
  const venueDetail = document.getElementById("venue-detail");
  const projection = document.getElementById("projection");
  const ratings = document.getElementById("ratings-asof");

  let catalog = null;
  let snap = null;
  let teams = [];
  let teamsBySchool = {};
  let schoolA = "Indiana";
  let schoolB = "Miami";
  let site = "neutral";
  let powerBySchool = {};

  function esc(value) {
    return BCPI.esc(value == null ? "" : String(value));
  }

  function editionDate(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
    return `${months[date.getUTCMonth()]} ${date.getUTCDate()}, ${date.getUTCFullYear()}`;
  }

  function logo(team) {
    const src = team && (team.logo || team.logo_dark);
    if (!src) return `<span class="logo-md"></span>`;
    return `<img class="logo-md" src="${esc(src)}" alt="" />`;
  }

  function powerLine(school) {
    const row = powerBySchool[school];
    if (!row || row.power_score == null) return "Power —";
    return `Power ${Number(row.power_score).toFixed(2)}`;
  }

  function paintSlot(el, school) {
    const team = teamsBySchool[school];
    el.innerHTML = `
      ${logo(team)}
      <p class="name">${esc(school || "Select")}</p>
      <p class="pwr">${esc(powerLine(school))}</p>
      <button type="button" class="change">Change</button>`;
    el.querySelector(".change").addEventListener("click", async () => {
      const picked = await BCPI.pickTeam({ teams, title: "Teams" });
      if (!picked || picked === school) return;
      if (el === slotA) schoolA = picked;
      else schoolB = picked;
      paint();
      predict();
    });
  }

  function venueInfo(school) {
    const team = teamsBySchool[school] || {};
    let stadium = team.venue_name || (school ? `${school} Stadium` : "");
    const location =
      team.venue_location ||
      [team.venue_city, team.venue_state].filter(Boolean).join(", ");
    if (location && stadium.includes(`(${location})`)) {
      stadium = stadium.replace(` (${location})`, "").trim();
    }
    return { stadium, location };
  }

  function paintVenue() {
    const options = [
      { id: "neutral", label: "Neutral" },
      { id: "home_a", label: schoolA ? `At ${schoolA}` : "At team A" },
      { id: "home_b", label: schoolB ? `At ${schoolB}` : "At team B" },
    ];
    venue.innerHTML = options
      .map(
        (option) =>
          `<button type="button" data-site="${option.id}" aria-pressed="${option.id === site ? "true" : "false"}">${esc(option.label)}</button>`
      )
      .join("");
    venue.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.site === site) return;
        site = button.dataset.site;
        paintVenue();
        predict();
      });
    });
    paintVenueDetail();
  }

  function formatCapacity(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return "";
    return n.toLocaleString("en-US");
  }

  function paintVenueDetail() {
    if (!venueDetail) return;
    if (site === "neutral") {
      venueDetail.innerHTML = `Neutral site<span class="venue-city">No home field</span>`;
      return;
    }
    const school = site === "home_a" ? schoolA : schoolB;
    const team = teamsBySchool[school] || {};
    const info = venueInfo(school);
    if (!info.stadium && !info.location) {
      venueDetail.innerHTML = `${esc(school)} home`;
      return;
    }
    const capacity = formatCapacity(team.venue_capacity);
    const meta = [info.location, capacity ? `Seats ${capacity}` : ""]
      .filter(Boolean)
      .join(" · ");
    venueDetail.innerHTML = `${esc(info.stadium || `${school} Stadium`)}${
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

  function pointsLabel(value, homeName) {
    const number = Number(value);
    if (!Number.isFinite(number) || Math.abs(number) < 0.05) return "None";
    const favorite = number >= 0 ? schoolA : schoolB;
    if (homeName) {
      const side = number >= 0 ? schoolA : schoolB;
      return `${Math.abs(number).toFixed(1)} points to ${side}`;
    }
    return `${favorite} by ${Math.abs(number).toFixed(1)}`;
  }

  function availabilityLine(notes) {
    if (!notes || !notes.length) return "";
    const text = notes
      .map((note) => {
        const status = note.status === "doubtful" ? "doubtful" : "out";
        return `${note.player} (${note.position}) is ${status}, ${Number(note.points).toFixed(1)} points off ${note.team}`;
      })
      .join(". ");
    return `<p class="note">${esc(text)}.</p>`;
  }

  function renderProjection(data) {
    const margin = Number(data.predicted_margin_a);
    const pctA = Math.round((data.win_prob_a || 0) * 100);
    const pctB = Math.round((data.win_prob_b || 0) * 100);
    const favorite = margin >= 0 ? data.team_a : data.team_b;
    const headline =
      Math.abs(margin) < 0.05 ? "Even" : `${favorite} by ${Math.abs(margin).toFixed(1)}`;
    const aLeads = pctA >= pctB;
    const powerGap = data.power_gap_a != null ? data.power_gap_a : null;
    const homeField = data.home_field_a != null ? data.home_field_a : null;
    projection.hidden = false;
    projection.innerHTML = `
      <p class="proj-kicker">Projection · ${esc(venueName())}</p>
      <h2 class="proj-headline">${esc(headline)}</h2>
      <div class="winbar">
        <div class="${aLeads ? "solid" : "hatch"}" style="width:${pctA}%"></div>
        <div class="${aLeads ? "hatch" : "solid"}" style="width:${pctB}%"></div>
      </div>
      <div class="pct-row">
        <span>${esc(data.team_a)} ${pctA}%</span>
        <span>${pctB}% ${esc(data.team_b)}</span>
      </div>
      <dl class="proj-lines">
        <div class="proj-line"><dt>Power gap</dt><dd>${esc(powerGap == null ? "—" : pointsLabel(powerGap))}</dd></div>
        <div class="proj-line"><dt>Home field</dt><dd>${esc(homeField == null ? "—" : pointsLabel(homeField, true))}</dd></div>
      </dl>
      ${availabilityLine(data.availability)}`;
  }

  async function predict() {
    if (!snap || !schoolA || !schoolB) {
      projection.hidden = true;
      return;
    }
    if (schoolA === schoolB) {
      projection.hidden = false;
      projection.innerHTML = `<p class="note">Pick two different teams.</p>`;
      return;
    }
    try {
      let data = await BCPI.predictMatchupClient({
        teamA: schoolA,
        teamB: schoolB,
        site,
        teamsBySchool,
        snapshot: snap,
      });
      if (data.power_gap_a == null && site !== "neutral") {
        const neutral = await BCPI.predictMatchupClient({
          teamA: schoolA,
          teamB: schoolB,
          site: "neutral",
          teamsBySchool,
          snapshot: snap,
        });
        data = {
          ...data,
          power_gap_a: neutral.predicted_margin_a,
          home_field_a: Number(data.predicted_margin_a) - Number(neutral.predicted_margin_a),
        };
      } else if (data.power_gap_a == null) {
        data = { ...data, power_gap_a: data.predicted_margin_a, home_field_a: 0 };
      }
      renderProjection(data);
    } catch (error) {
      projection.hidden = false;
      projection.innerHTML = `<p class="note">${esc(error.message || "Could not run this matchup.")}</p>`;
    }
  }

  async function boot() {
    catalog = await BCPI.loadCatalog();
    snap = catalog.snapshots.find((item) => item.id === catalog.default) || catalog.snapshots[0];
    if (!snap) return;
    const [teamPack, powerPack] = await Promise.all([
      BCPI.fetchTeams(snap),
      BCPI.fetchRankings("power", { snapshot: snap }),
    ]);
    teams = teamPack.rows;
    teamsBySchool = teamPack.bySchool;
    powerBySchool = {};
    (powerPack.rows || []).forEach((row) => {
      powerBySchool[row.school] = row;
    });
    const season = document.getElementById("dateline-season");
    const edition = document.getElementById("dateline-edition");
    const date = document.getElementById("dateline-date");
    if (season) season.textContent = `${snap.season} SEASON`;
    if (edition) {
      edition.textContent = snap.postseason
        ? "Postseason Edition"
        : snap.week
          ? `Week ${snap.week} Edition`
          : "Preseason Edition";
    }
    if (date) date.textContent = editionDate(powerPack.as_of);
    if (ratings) {
      const when = snap.postseason ? "the postseason" : snap.week ? `week ${snap.week}` : "the preseason";
      ratings.textContent = `Ratings as of ${when}`;
    }
    if (!teamsBySchool[schoolA] && teams[0]) schoolA = teams[0].school;
    if (!teamsBySchool[schoolB] && teams[1]) schoolB = teams[1].school;
    paint();
    predict();
  }

  boot().catch((error) => {
    view.insertAdjacentHTML(
      "beforeend",
      `<p class="note">${esc(error.message || "Could not load teams.")}</p>`
    );
  });
})();
