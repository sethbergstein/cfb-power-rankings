/** Shared helpers for BCPI web UI. */

const BCPI = {
  defaultSeason: 2025,
  futureSeason: 2026,
  _manifest: null,
  _params: null,
  _powerRows: null,

  isStatic() {
    return window.BCPI_CONFIG?.mode === "static";
  },

  dataUrl(path) {
    const base = window.BCPI_CONFIG?.dataUrl || "./data";
    return `${base}/${path}`;
  },

  async loadManifest() {
    if (BCPI._manifest) return BCPI._manifest;
    const res = await fetch(BCPI.dataUrl("manifest.json"));
    if (!res.ok) throw new Error("Failed to load site data");
    BCPI._manifest = await res.json();
    return BCPI._manifest;
  },

  async loadParams() {
    if (BCPI._params) return BCPI._params;
    const res = await fetch(BCPI.dataUrl("params.json"));
    if (!res.ok) throw new Error("Failed to load model params");
    BCPI._params = await res.json();
    return BCPI._params;
  },

  async loadPowerRows() {
    if (BCPI._powerRows) return BCPI._powerRows;
    const res = await fetch(BCPI.dataUrl("power.json"));
    if (!res.ok) throw new Error("Failed to load power ratings");
    const data = await res.json();
    BCPI._powerRows = data.rows || [];
    return BCPI._powerRows;
  },

  async fetchTeams(season) {
    if (BCPI.isStatic()) {
      const res = await fetch(BCPI.dataUrl("teams.json"));
      if (!res.ok) throw new Error("Failed to load teams");
      const rows = await res.json();
      const bySchool = {};
      rows.forEach((t) => {
        bySchool[t.school] = t;
      });
      return { rows, bySchool };
    }
    const res = await fetch(`/api/teams?season=${season}`);
    if (!res.ok) {
      throw new Error(
        "Cannot load teams. Start the app with: python run_bcpi.py serve"
      );
    }
    const rows = await res.json();
    const bySchool = {};
    rows.forEach((t) => {
      bySchool[t.school] = t;
    });
    return { rows, bySchool };
  },

  async fetchRankings(kind, { season, postseason, refresh } = {}) {
    if (BCPI.isStatic()) {
      const file = kind === "poll" ? "poll.json" : "power.json";
      const res = await fetch(BCPI.dataUrl(file));
      if (!res.ok) throw new Error(`Failed to load ${kind} rankings`);
      const data = await res.json();
      const rows = data.rows || [];
      return {
        kind,
        season: data.season,
        postseason: data.postseason,
        week: data.week,
        as_of: data.as_of,
        rows: rows.slice(0, 25),
        also_ran: rows.slice(25, 35),
      };
    }
    const params = new URLSearchParams({
      season: String(season),
      postseason: postseason ? "1" : "0",
    });
    if (refresh) params.set("refresh", "1");
    const res = await fetch(`/api/rankings/${kind}?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load rankings");
    return data;
  },

  async predictMatchupClient({ teamA, teamB, site, teamsBySchool, season, postseason }) {
    if (!BCPI.isStatic()) {
      const params = new URLSearchParams({
        team_a: teamA,
        team_b: teamB,
        site,
        season: String(season),
        postseason: String(postseason),
      });
      const res = await fetch(`/api/matchup?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Prediction failed");
      return BCPI.attachProfiles(BCPI.normalizeMatchup(data, teamA, teamB), teamsBySchool);
    }

    const [params, powerRows] = await Promise.all([
      BCPI.loadParams(),
      BCPI.loadPowerRows(),
    ]);
    const bySchool = {};
    powerRows.forEach((r) => {
      bySchool[r.school] = r;
    });
    const a = bySchool[teamA];
    const b = bySchool[teamB];
    if (!a || !b) throw new Error("Team not found in published ratings");

    let home = teamA;
    let away = teamB;
    let neutral = true;
    if (site === "home_a") neutral = false;
    else if (site === "home_b") {
      home = teamB;
      away = teamA;
      neutral = false;
    }

    const homeRow = bySchool[home];
    const awayRow = bySchool[away];
    let marginHome =
      (Number(homeRow.power_rating) - Number(awayRow.power_rating)) / params.margin_scale;
    if (!neutral) marginHome += params.hfa;

    const winHome = 1 / (1 + Math.exp(-marginHome / params.win_prob_scale));
    const manifest = await BCPI.loadManifest();
    const payload = {
      team_a: teamA,
      team_b: teamB,
      week: manifest.week,
    };

    if (home === teamA) {
      payload.predicted_margin_a = marginHome;
      payload.win_prob_a = winHome;
      payload.win_prob_b = 1 - winHome;
      payload.rank_a = a.rank;
      payload.rank_b = b.rank;
      payload.power_rating_a = a.power_rating;
      payload.power_rating_b = b.power_rating;
    } else {
      payload.predicted_margin_a = -marginHome;
      payload.win_prob_a = 1 - winHome;
      payload.win_prob_b = winHome;
      payload.rank_a = a.rank;
      payload.rank_b = b.rank;
      payload.power_rating_a = a.power_rating;
      payload.power_rating_b = b.power_rating;
    }
    return BCPI.attachProfiles(payload, teamsBySchool);
  },

  getTheme() {
    return document.documentElement.getAttribute("data-theme") || "light";
  },

  logoForTeam(team, theme) {
    if (!team) return null;
    if (theme === "dark" && team.logo_dark) return team.logo_dark;
    return team.logo || team.logo_dark;
  },

  normalizeMatchup(data, schoolA, schoolB) {
    if (!data || data.error) return data;
    if (data.team_a != null && data.predicted_margin_a != null) return data;

    const aIsHome = data.home_team === schoolA;
    const normalized = { ...data, team_a: schoolA, team_b: schoolB };
    if (aIsHome) {
      normalized.predicted_margin_a = data.predicted_margin_home;
      normalized.win_prob_a = data.home_win_probability;
      normalized.win_prob_b = data.away_win_probability;
      normalized.rank_a = data.home_bcpi_rank;
      normalized.rank_b = data.away_bcpi_rank;
      normalized.power_rating_a = data.home_power_rating;
      normalized.power_rating_b = data.away_power_rating;
    } else {
      normalized.predicted_margin_a = -Number(data.predicted_margin_home);
      normalized.win_prob_a = data.away_win_probability;
      normalized.win_prob_b = data.home_win_probability;
      normalized.rank_a = data.away_bcpi_rank;
      normalized.rank_b = data.home_bcpi_rank;
      normalized.power_rating_a = data.away_power_rating;
      normalized.power_rating_b = data.home_power_rating;
    }
    return normalized;
  },

  attachProfiles(data, teamsBySchool) {
    if (!data.team_a_profile) {
      data.team_a_profile = teamsBySchool[data.team_a] || null;
    }
    if (!data.team_b_profile) {
      data.team_b_profile = teamsBySchool[data.team_b] || null;
    }
    return data;
  },

  formatNum(value, digits = 2) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    return Number(value).toFixed(digits);
  },

  _parseHex(hex) {
    if (!hex) return null;
    let h = String(hex).replace("#", "").trim();
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    if (h.length !== 6) return null;
    return [
      parseInt(h.slice(0, 2), 16),
      parseInt(h.slice(2, 4), 16),
      parseInt(h.slice(4, 6), 16),
    ];
  },

  _mixRgb(a, b, t) {
    return a.map((v, i) => Math.round(v + (b[i] - v) * t));
  },

  _toHex(rgb) {
    return `#${rgb.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
  },

  _luminance(hex) {
    const rgb = BCPI._parseHex(hex);
    if (!rgb) return 0;
    const [r, g, b] = rgb.map((c) => {
      c /= 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  },

  /** Team brand color adjusted for readable contrast on current theme. */
  teamDisplayColor(color) {
    if (!color) return "";
    const theme = BCPI.getTheme();
    const lum = BCPI._luminance(color);
    if (theme === "dark") {
      if (lum < 0.45) {
        return BCPI._toHex(BCPI._mixRgb(BCPI._parseHex(color), [243, 237, 228], 0.55));
      }
      return color;
    }
    if (lum > 0.72) {
      return BCPI._toHex(BCPI._mixRgb(BCPI._parseHex(color), [20, 18, 16], 0.4));
    }
    return color;
  },

  formatAsOf(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  },

  isPostseasonAvailable(season) {
    return Number(season) < BCPI.futureSeason;
  },

  syncPostseasonControl(seasonInput, postseasonInput, postseasonWrap) {
    if (BCPI.isStatic()) {
      if (postseasonWrap) postseasonWrap.hidden = true;
      if (postseasonInput) postseasonInput.checked = false;
      if (seasonInput) {
        seasonInput.disabled = true;
        BCPI.loadManifest().then((m) => {
          seasonInput.value = m.season;
        });
      }
      return;
    }
    if (!postseasonInput) return;
    const available = BCPI.isPostseasonAvailable(
      Number(seasonInput?.value) || BCPI.defaultSeason
    );
    postseasonInput.disabled = !available;
    if (postseasonWrap) {
      postseasonWrap.hidden = !available;
    }
    if (!available) {
      postseasonInput.checked = false;
    }
  },

  esc(text) {
    const el = document.createElement("span");
    el.textContent = text ?? "";
    return el.innerHTML;
  },

  createTeamPicker(container, { teams = [], value = "", onChange } = {}) {
    container.innerHTML = `
      <div class="team-picker">
        <button type="button" class="team-picker-trigger" aria-haspopup="listbox">
          <span class="team-picker-logo-wrap"></span>
          <span class="team-picker-label">
            <span class="team-picker-name">Select team</span>
            <span class="team-picker-abbr"></span>
          </span>
          <span class="team-picker-chevron" aria-hidden="true">▾</span>
        </button>
        <div class="team-picker-menu" hidden>
          <input type="search" class="team-picker-search" placeholder="Search teams…" autocomplete="off" />
          <ul class="team-picker-list" role="listbox"></ul>
        </div>
      </div>`;

    const root = container.querySelector(".team-picker");
    const trigger = root.querySelector(".team-picker-trigger");
    const menu = root.querySelector(".team-picker-menu");
    const search = root.querySelector(".team-picker-search");
    const list = root.querySelector(".team-picker-list");
    const logoWrap = root.querySelector(".team-picker-logo-wrap");
    const nameEl = root.querySelector(".team-picker-name");
    const abbrEl = root.querySelector(".team-picker-abbr");

    let selected = value || "";
    let allTeams = [...teams].sort((a, b) => a.school.localeCompare(b.school));

    function renderTrigger(team) {
      logoWrap.innerHTML = "";
      if (team) {
        const logo = BCPI.logoForTeam(team, BCPI.getTheme());
        if (logo) {
          const img = document.createElement("img");
          img.src = logo;
          img.alt = "";
          img.className = "team-picker-logo";
          logoWrap.appendChild(img);
        }
        nameEl.textContent = team.school;
        nameEl.style.color = BCPI.teamDisplayColor(team.color) || "";
        abbrEl.textContent = team.abbreviation || "";
      } else {
        nameEl.textContent = "Select team";
        nameEl.style.color = "";
        abbrEl.textContent = "";
      }
    }

    function renderList(filter = "") {
      const q = filter.trim().toLowerCase();
      const filtered = q
        ? allTeams.filter(
            (t) =>
              t.school.toLowerCase().includes(q) ||
              (t.abbreviation || "").toLowerCase().includes(q)
          )
        : allTeams;

      list.innerHTML = filtered
        .map((t) => {
          const logo = BCPI.logoForTeam(t, BCPI.getTheme()) || "";
          const active = t.school === selected ? " active" : "";
          return `<li class="team-picker-option${active}" data-school="${BCPI.esc(t.school)}" role="option">
            ${logo ? `<img class="team-picker-option-logo" src="${BCPI.esc(logo)}" alt="" />` : ""}
            <span class="team-picker-option-name" style="color:${BCPI.esc(BCPI.teamDisplayColor(t.color) || "inherit")}">${BCPI.esc(t.school)}</span>
            <span class="team-picker-option-abbr">${BCPI.esc(t.abbreviation || "")}</span>
          </li>`;
        })
        .join("");

      if (!filtered.length) {
        list.innerHTML = `<li class="team-picker-empty">No teams match</li>`;
      }
    }

    function openMenu() {
      document.dispatchEvent(new CustomEvent("bcpi-picker-open", { detail: root }));
      root.classList.add("is-open");
      menu.hidden = false;
      search.value = "";
      renderList();
      search.focus();
    }

    function closeMenu() {
      menu.hidden = true;
      root.classList.remove("is-open");
    }

    document.addEventListener("bcpi-picker-open", (event) => {
      if (event.detail !== root) closeMenu();
    });

    window.addEventListener(
      "scroll",
      () => {
        if (!menu.hidden) closeMenu();
      },
      true
    );

    function setValue(school, fireChange = true) {
      selected = school || "";
      const team = allTeams.find((t) => t.school === selected);
      renderTrigger(team);
      if (fireChange && onChange) onChange(selected, team);
    }

    trigger.addEventListener("click", () => {
      if (menu.hidden) openMenu();
      else closeMenu();
    });

    search.addEventListener("input", () => renderList(search.value));

    list.addEventListener("click", (event) => {
      const option = event.target.closest(".team-picker-option");
      if (!option) return;
      setValue(option.dataset.school);
      closeMenu();
    });

    document.addEventListener("click", (event) => {
      if (!root.contains(event.target)) closeMenu();
    });

    document.addEventListener("bcpi-theme-change", () => {
      renderTrigger(allTeams.find((t) => t.school === selected));
      if (!menu.hidden) renderList(search.value);
    });

    return {
      setTeams(rows) {
        allTeams = [...rows].sort((a, b) => a.school.localeCompare(b.school));
        if (selected && !allTeams.some((t) => t.school === selected)) {
          selected = "";
        }
        setValue(selected, false);
      },
      setValue(school, fireChange = true) {
        setValue(school, fireChange);
      },
      getValue() {
        return selected;
      },
      getTeam() {
        return allTeams.find((t) => t.school === selected) || null;
      },
      closeMenu,
    };
  },
};

document.addEventListener("DOMContentLoaded", () => {
  const path = window.location.pathname.replace(/\.html$/, "");
  document.querySelectorAll(".site-nav a").forEach((link) => {
    const href = link.getAttribute("href") || "";
    const normalized = href === "/" ? "/" : href.replace(/\.html$/, "");
    if (normalized === "/" && (path === "/" || path.endsWith("/index"))) {
      link.classList.add("active");
    } else if (normalized !== "/" && path.endsWith(normalized)) {
      link.classList.add("active");
    }
  });
});
