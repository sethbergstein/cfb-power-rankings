/** Shared helpers for BCPI web UI. */

const BCPI = {
  defaultSeason: 2025,
  futureSeason: 2026,
  _manifest: null,
  _params: null,
  _powerRows: null,
  _catalog: null,
  _memCache: {},
  _loaderCount: 0,
  _loaderTimer: null,
  _loaderVisible: false,
  _loaderDelayMs: 480,
  CACHE_PREFIX: "bcpi-cache:",
  SNAPSHOT_STORAGE_KEY: "bcpi-snapshot-id",

  getSavedSnapshotId() {
    try {
      return localStorage.getItem(BCPI.SNAPSHOT_STORAGE_KEY);
    } catch {
      return null;
    }
  },

  saveSnapshotId(id) {
    try {
      if (id) localStorage.setItem(BCPI.SNAPSHOT_STORAGE_KEY, id);
    } catch {
      /* ignore private mode */
    }
  },

  isStatic() {
    return window.BCPI_CONFIG?.mode === "static";
  },

  dataUrl(path) {
    const base = window.BCPI_CONFIG?.dataUrl || "./data";
    return `${base}/${path}`;
  },

  _sessionGet(key) {
    try {
      const raw = sessionStorage.getItem(BCPI.CACHE_PREFIX + key);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  },

  _sessionSet(key, data) {
    try {
      sessionStorage.setItem(BCPI.CACHE_PREFIX + key, JSON.stringify(data));
    } catch {
      /* quota or private mode */
    }
  },

  hasSessionCache(path) {
    return BCPI._memCache[path] != null || BCPI._sessionGet(path) != null;
  },

  async fetchJsonCached(path, { force = false } = {}) {
    if (!force && BCPI._memCache[path] != null) {
      return BCPI._memCache[path];
    }

    if (!force && BCPI.isStatic()) {
      const cached = BCPI._sessionGet(path);
      if (cached != null) {
        BCPI._memCache[path] = cached;
        BCPI._fetchJsonFresh(path).catch(() => {});
        return cached;
      }
    }

    return BCPI._fetchJsonFresh(path);
  },

  async _fetchJsonFresh(path) {
    const res = await fetch(BCPI.dataUrl(path));
    if (!res.ok) throw new Error(`Failed to load ${path}`);
    const data = await res.json();
    BCPI._memCache[path] = data;
    if (BCPI.isStatic()) BCPI._sessionSet(path, data);
    return data;
  },

  prefetchSnapshotData(snapshot) {
    if (!BCPI.isStatic() || !snapshot?.id) return;
    const snapId = snapshot.id;
    [
      `snapshots/${snapId}/teams.json`,
      `snapshots/${snapId}/power.json`,
      `snapshots/${snapId}/poll.json`,
    ].forEach((path) => {
      if (BCPI.hasSessionCache(path)) return;
      BCPI._fetchJsonFresh(path).catch(() => {});
    });
  },

  async loadCatalog() {
    if (BCPI._catalog) return BCPI._catalog;
    const path = BCPI.isStatic() ? "catalog.json" : null;
    if (path) {
      BCPI._catalog = await BCPI.fetchJsonCached(path);
      return BCPI._catalog;
    }
    const res = await fetch("/api/catalog");
    if (!res.ok) throw new Error("Failed to load season catalog");
    BCPI._catalog = await res.json();
    return BCPI._catalog;
  },

  getSnapshot(selectEl) {
    const id = selectEl?.value;
    if (!id || !BCPI._catalog?.snapshots) return null;
    return BCPI._catalog.snapshots.find((snap) => snap.id === id) || null;
  },

  async initSnapshotSelect(selectEl, onChange) {
    if (!selectEl) return null;
    const catalog = await BCPI.loadCatalog();
    selectEl.innerHTML = (catalog.snapshots || [])
      .map(
        (snap) =>
          `<option value="${BCPI.esc(snap.id)}">${BCPI.esc(snap.label)}</option>`
      )
      .join("");
    if (catalog.default) selectEl.value = catalog.default;
    else if (catalog.snapshots?.length) selectEl.value = catalog.snapshots[0].id;
    const saved = BCPI.getSavedSnapshotId();
    if (saved && catalog.snapshots.some((snap) => snap.id === saved)) {
      selectEl.value = saved;
    }
    selectEl.disabled = !catalog.snapshots?.length;
    selectEl.addEventListener("change", () => {
      BCPI.saveSnapshotId(selectEl.value);
      BCPI.prefetchSnapshotData(BCPI.getSnapshot(selectEl));
      if (onChange) onChange();
    });
    BCPI.prefetchSnapshotData(BCPI.getSnapshot(selectEl));
    return catalog;
  },

  showLoader(message = "Loading…", { immediate = false } = {}) {
    BCPI._loaderCount += 1;
    clearTimeout(BCPI._loaderTimer);
    const delay = immediate ? 0 : BCPI._loaderDelayMs;
    BCPI._loaderTimer = setTimeout(() => {
      if (BCPI._loaderCount <= 0) return;
      let root = document.getElementById("bcpi-loader");
      if (!root) {
        root = document.createElement("div");
        root.id = "bcpi-loader";
        root.className = "bcpi-loader";
        root.innerHTML = `
          <div class="bcpi-loader-stage" aria-hidden="true">
            <svg class="bcpi-loader-trophy" viewBox="0 0 64 96" role="img" aria-label="">
              <path d="M18 8h28v10c0 8-4 14-10 17 6 3 10 9 10 17v6H18v-6c0-8 4-14 10-17-6-3-10-9-10-17V8z" fill="currentColor"/>
              <rect x="24" y="58" width="16" height="8" rx="1" fill="currentColor"/>
              <rect x="20" y="66" width="24" height="6" rx="1" fill="currentColor"/>
              <rect x="16" y="72" width="32" height="8" rx="1" fill="currentColor"/>
              <path d="M8 12h8c2 8 2 16 0 22h-8V12zm48 0h8v22h-8c-2-6-2-14 0-22z" fill="currentColor" opacity="0.85"/>
            </svg>
          </div>
          <p class="bcpi-loader-text"></p>`;
        document.body.appendChild(root);
      }
      const text = root.querySelector(".bcpi-loader-text");
      if (text) text.textContent = message;
      root.hidden = false;
      BCPI._loaderVisible = true;
    }, delay);
  },

  hideLoader() {
    BCPI._loaderCount = Math.max(0, BCPI._loaderCount - 1);
    if (BCPI._loaderCount > 0) return;
    clearTimeout(BCPI._loaderTimer);
    const root = document.getElementById("bcpi-loader");
    if (root) root.hidden = true;
    BCPI._loaderVisible = false;
  },

  async loadManifest() {
    if (BCPI._manifest) return BCPI._manifest;
    BCPI._manifest = await BCPI.fetchJsonCached("manifest.json");
    return BCPI._manifest;
  },

  async loadParams() {
    if (BCPI._params) return BCPI._params;
    BCPI._params = await BCPI.fetchJsonCached("params.json");
    return BCPI._params;
  },

  async loadPowerRows(snapshot) {
    if (BCPI.isStatic() && snapshot?.id) {
      const data = await BCPI.fetchJsonCached(`snapshots/${snapshot.id}/power.json`);
      return data.rows || [];
    }
    if (BCPI._powerRows) return BCPI._powerRows;
    const data = await BCPI.fetchJsonCached("power.json");
    BCPI._powerRows = data.rows || [];
    return BCPI._powerRows;
  },

  async fetchTeams(snapshot) {
    if (BCPI.isStatic()) {
      const path = snapshot?.id
        ? `snapshots/${snapshot.id}/teams.json`
        : "teams.json";
      const rows = await BCPI.fetchJsonCached(path);
      const bySchool = {};
      rows.forEach((t) => {
        bySchool[t.school] = t;
      });
      return { rows, bySchool };
    }
    const season = snapshot?.season || BCPI.defaultSeason;
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

  async fetchRankings(kind, { snapshot, refresh } = {}) {
    if (BCPI.isStatic()) {
      const snapId = snapshot?.id;
      const file = kind === "poll" ? "poll.json" : "power.json";
      const path = snapId ? `snapshots/${snapId}/${file}` : file;
      const data = await BCPI.fetchJsonCached(path, { force: refresh });
      const rows = data.rows || [];
      return {
        kind,
        season: data.season,
        postseason: data.postseason,
        week: data.week,
        label: data.label,
        as_of: data.as_of,
        rows: rows.slice(0, 25),
        also_ran: rows.slice(25, 35),
      };
    }
    if (!snapshot) throw new Error("Select a season snapshot");
    const params = new URLSearchParams({
      season: String(snapshot.season),
      postseason: snapshot.postseason ? "1" : "0",
    });
    if (snapshot.week > 0 && !snapshot.postseason) {
      params.set("week", String(snapshot.week));
    }
    if (refresh) params.set("refresh", "1");
    const res = await fetch(`/api/rankings/${kind}?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load rankings");
    return data;
  },

  async predictMatchupClient({ teamA, teamB, site, teamsBySchool, snapshot }) {
    if (!BCPI.isStatic()) {
      const params = new URLSearchParams({
        team_a: teamA,
        team_b: teamB,
        site,
        season: String(snapshot?.season || BCPI.defaultSeason),
        postseason: snapshot?.postseason ? "1" : "0",
      });
      if (snapshot?.week > 0 && !snapshot?.postseason) {
        params.set("week", String(snapshot.week));
      }
      const res = await fetch(`/api/matchup?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Prediction failed");
      return BCPI.attachProfiles(BCPI.normalizeMatchup(data, teamA, teamB), teamsBySchool);
    }

    const [params, powerRows] = await Promise.all([
      BCPI.loadParams(),
      BCPI.loadPowerRows(snapshot),
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
    if (!neutral) {
      const teamHfa = params.team_hfa?.[home];
      marginHome += teamHfa != null ? Number(teamHfa) : params.hfa;
    }

    const winHome = 1 / (1 + Math.exp(-marginHome / params.win_prob_scale));
    const manifest = snapshot?.label
      ? { week: snapshot.week, label: snapshot.label }
      : await BCPI.loadManifest();
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
    if (value == null || Number.isNaN(Number(value))) return "-";
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

    function positionMenu() {
      const rect = trigger.getBoundingClientRect();
      const maxHeight = Math.max(160, window.innerHeight - rect.bottom - 12);
      menu.style.position = "fixed";
      menu.style.left = `${Math.max(8, rect.left)}px`;
      menu.style.top = `${rect.bottom + 4}px`;
      menu.style.width = `${rect.width}px`;
      menu.style.right = "auto";
      menu.style.zIndex = "10001";
      menu.style.maxHeight = `${Math.min(320, maxHeight)}px`;
    }

    function resetMenuStyle() {
      menu.style.position = "";
      menu.style.left = "";
      menu.style.top = "";
      menu.style.width = "";
      menu.style.right = "";
      menu.style.zIndex = "";
      menu.style.maxHeight = "";
    }

    function openMenu() {
      document.dispatchEvent(new CustomEvent("bcpi-picker-open", { detail: root }));
      root.classList.add("is-open");
      menu.hidden = false;
      search.value = "";
      renderList();
      positionMenu();
      search.focus({ preventScroll: true });
    }

    function closeMenu() {
      menu.hidden = true;
      root.classList.remove("is-open");
      resetMenuStyle();
    }

    document.addEventListener("bcpi-picker-open", (event) => {
      if (event.detail !== root) closeMenu();
    });

    const scrollRoot = document.querySelector("main.page");
    scrollRoot?.addEventListener(
      "scroll",
      (event) => {
        if (menu.hidden) return;
        if (menu.contains(event.target) || root.contains(event.target)) return;
        closeMenu();
      },
      { passive: true }
    );

    window.addEventListener("resize", () => {
      if (!menu.hidden) positionMenu();
    });
    window.visualViewport?.addEventListener("resize", () => {
      if (!menu.hidden) positionMenu();
    });
    window.visualViewport?.addEventListener("scroll", () => {
      if (!menu.hidden) positionMenu();
    });

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
      if (!menu.hidden) {
        renderList(search.value);
        positionMenu();
      }
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
