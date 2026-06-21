(function () {
  const snapshotSelect = document.getElementById("snapshot-select");
  const predictBtn = document.getElementById("predict-btn");
  const venueCards = document.querySelectorAll(".venue-card");
  const board = document.getElementById("scoreboard");
  const seasonBadge = document.getElementById("season-badge");
  const pickerAEl = document.getElementById("team-a-picker");
  const pickerBEl = document.getElementById("team-b-picker");

  let teamsBySchool = {};
  let pickerA = null;
  let pickerB = null;

  function snapshot() {
    return BCPI.getSnapshot(snapshotSelect);
  }

  function selectedSiteValue() {
    const checked = document.querySelector('input[name="site"]:checked');
    return checked ? checked.value : "neutral";
  }

  function setVenueLogo(imgEl, team) {
    if (!imgEl) return;
    const logo = BCPI.logoForTeam(team, BCPI.getTheme());
    if (logo) {
      imgEl.src = logo;
      imgEl.hidden = false;
    } else {
      imgEl.hidden = true;
      imgEl.removeAttribute("src");
    }
  }

  function updateVenueCards() {
    const teamA = pickerA?.getTeam();
    const teamB = pickerB?.getTeam();

    const homeATeam = document.getElementById("venue-home-a-team");
    const homeAStadium = document.getElementById("venue-home-a-stadium");
    const homeASub = document.getElementById("venue-home-a-sub");
    const homeALogo = document.getElementById("venue-home-a-logo");

    const homeBTeam = document.getElementById("venue-home-b-team");
    const homeBStadium = document.getElementById("venue-home-b-stadium");
    const homeBSub = document.getElementById("venue-home-b-sub");
    const homeBLogo = document.getElementById("venue-home-b-logo");

    if (teamA && homeATeam && homeAStadium && homeASub) {
      setVenueLogo(homeALogo, teamA);
      homeATeam.textContent = teamA.school;
      homeATeam.style.color = BCPI.teamDisplayColor(teamA.color) || "";
      homeAStadium.textContent = teamA.venue_name || `${teamA.school} Stadium`;
      homeASub.textContent = teamA.venue_location || "Home field";
    } else if (homeATeam && homeAStadium && homeASub) {
      if (homeALogo) homeALogo.hidden = true;
      homeATeam.textContent = "Team A";
      homeATeam.style.color = "";
      homeAStadium.textContent = "Select a team";
      homeASub.textContent = "Pick Team A above";
    }

    if (teamB && homeBTeam && homeBStadium && homeBSub) {
      setVenueLogo(homeBLogo, teamB);
      homeBTeam.textContent = teamB.school;
      homeBTeam.style.color = BCPI.teamDisplayColor(teamB.color) || "";
      homeBStadium.textContent = teamB.venue_name || `${teamB.school} Stadium`;
      homeBSub.textContent = teamB.venue_location || "Home field";
    } else if (homeBTeam && homeBStadium && homeBSub) {
      if (homeBLogo) homeBLogo.hidden = true;
      homeBTeam.textContent = "Team B";
      homeBTeam.style.color = "";
      homeBStadium.textContent = "Select a team";
      homeBSub.textContent = "Pick Team B above";
    }
  }

  function initPickers(rows) {
    const onTeamChange = () => {
      updateVenueCards();
    };

    if (!pickerA) {
      pickerA = BCPI.createTeamPicker(pickerAEl, {
        teams: rows,
        value: "Indiana",
        onChange: onTeamChange,
      });
      pickerB = BCPI.createTeamPicker(pickerBEl, {
        teams: rows,
        value: "Miami",
        onChange: onTeamChange,
      });
    } else {
      pickerA.setTeams(rows);
      pickerB.setTeams(rows);
    }
    updateVenueCards();
  }

  async function loadTeams() {
    const snap = snapshot();
    if (!snap) return false;

    BCPI.showLoader("Loading teams…");
    try {
      const { rows, bySchool } = await BCPI.fetchTeams(snap);
      teamsBySchool = bySchool;
      initPickers(rows);
      if (seasonBadge) seasonBadge.textContent = snap.label;
      return true;
    } catch (err) {
      console.error(err);
      board.innerHTML = `<div class="board-placeholder"><div class="board-error">${BCPI.esc(err.message)}</div></div>`;
      return false;
    } finally {
      BCPI.hideLoader();
    }
  }

  function renderPlaceholder() {
    board.innerHTML = `<div class="board-placeholder">Choose two teams, then run the predictor.</div>`;
  }

  function teamBlock(side, school, profile, rank, rating, isHome) {
    const team = profile || teamsBySchool[school] || {};
    const logo = BCPI.logoForTeam(team, BCPI.getTheme());
    const logoHtml = logo
      ? `<img class="team-logo" src="${BCPI.esc(logo)}" alt="" />`
      : "";
    const colorStyle = team.color
      ? ` style="color:${BCPI.esc(BCPI.teamDisplayColor(team.color))}"`
      : "";
    const rankLine =
      rank != null && rating != null
        ? `#${rank} · power ${BCPI.formatNum(rating, 0)}`
        : "Unranked in power index";
    return `
      <div class="board-team${isHome ? " home" : ""}" id="board-${side}">
        <div class="team-logo-wrap">${logoHtml}</div>
        <h2 class="team-name"${colorStyle}>${BCPI.esc(school)}</h2>
        <p class="team-rank">${rankLine}</p>
      </div>`;
  }

  function renderResult(data, snap) {
    const pctA = Math.round((data.win_prob_a || 0) * 100);
    const pctB = Math.round((data.win_prob_b || 0) * 100);
    const site = selectedSiteValue();
    const homeA = site === "home_a";
    const homeB = site === "home_b";

    const teamsHtml = `
      ${teamBlock("a", data.team_a, data.team_a_profile, data.rank_a, data.power_rating_a, homeA)}
      <div class="board-at">AT</div>
      ${teamBlock("b", data.team_b, data.team_b_profile, data.rank_b, data.power_rating_b, homeB)}
    `;

    const venueHtml = `
      <div class="board-venue">
        <p class="board-venue-name">${BCPI.esc(data.venue_label || "Neutral site")}</p>
        <p class="board-venue-loc">${BCPI.esc(data.venue_location || "")}</p>
      </div>`;

    const marginVal = Number(data.predicted_margin_a);
    const margin = BCPI.formatNum(marginVal, 1);
    const favorite =
      !Number.isNaN(marginVal) && marginVal >= 0 ? data.team_a : data.team_b;

    const resultHtml = `
      <div class="board-result">
        <p class="result-line">
          ${BCPI.esc(favorite || "Even")} by <span class="mono">${margin}</span> points
        </p>
        <div class="win-bar">
          <div class="win-bar-a" style="width:${pctA}%"></div>
          <div class="win-bar-b" style="width:${pctB}%"></div>
        </div>
        <div class="win-pcts">
          <span>${BCPI.esc(data.team_a)} ${pctA}%</span>
          <span>${pctB}% ${BCPI.esc(data.team_b)}</span>
        </div>
      </div>`;

    const weekLabel =
      snap?.postseason ? "postseason" : snap?.week > 0 ? `week ${snap.week}` : "preseason";

    board.innerHTML = `
      <div class="board-meta">
        <span>BCPI matchup · power ratings</span>
        <span>${BCPI.esc(snap?.label || weekLabel)}</span>
      </div>
      <div class="board-teams">${teamsHtml}</div>
      ${venueHtml}
      ${resultHtml}`;
  }

  async function predict() {
    const snap = snapshot();
    const teamA = pickerA?.getValue();
    const teamB = pickerB?.getValue();
    if (!snap) {
      board.innerHTML = `<div class="board-placeholder">Select a season snapshot.</div>`;
      return;
    }
    if (!teamA || !teamB) {
      board.innerHTML = `<div class="board-placeholder">Select both teams.<div class="board-error">Team A and Team B are required.</div></div>`;
      return;
    }

    predictBtn.disabled = true;
    BCPI.showLoader("Running BCPI matchup model…");
    board.innerHTML = `<div class="board-placeholder">Running BCPI matchup model…</div>`;

    const site = selectedSiteValue();

    try {
      let data = await BCPI.predictMatchupClient({
        teamA,
        teamB,
        site,
        teamsBySchool,
        snapshot: snap,
      });

      if (site === "home_a") {
        const t = teamsBySchool[teamA] || {};
        data.venue_label = t.venue_name || `${teamA} home`;
        data.venue_location = t.venue_location || "";
      } else if (site === "home_b") {
        const t = teamsBySchool[teamB] || {};
        data.venue_label = t.venue_name || `${teamB} home`;
        data.venue_location = t.venue_location || "";
      } else {
        data.venue_label = "Neutral site";
        data.venue_location = "No home field advantage";
      }

      renderResult(data, snap);
    } catch (err) {
      board.innerHTML = `<div class="board-placeholder"><div class="board-error">${BCPI.esc(err.message)}</div></div>`;
    } finally {
      predictBtn.disabled = false;
      BCPI.hideLoader();
    }
  }

  venueCards.forEach((card) => {
    card.addEventListener("click", () => {
      venueCards.forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      const input = card.querySelector("input");
      if (input) input.checked = true;
      if (board.querySelector(".board-teams")) predict();
    });
  });

  document.querySelectorAll('input[name="site"]').forEach((input) => {
    input.addEventListener("change", () => {
      venueCards.forEach((card) => {
        card.classList.toggle("selected", card.querySelector("input") === input);
      });
    });
  });

  predictBtn?.addEventListener("click", predict);
  document.addEventListener("bcpi-theme-change", () => {
    updateVenueCards();
    if (board.querySelector(".board-teams")) predict();
  });

  renderPlaceholder();
  BCPI.initSnapshotSelect(snapshotSelect, async () => {
    const ok = await loadTeams();
    if (ok) predict();
  }).then(async () => {
    const ok = await loadTeams();
    if (ok) predict();
  });
})();
