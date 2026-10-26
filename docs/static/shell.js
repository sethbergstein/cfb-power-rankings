/** Shared masthead / rail chrome for The Press Box. */
(function () {
  const staticSite = window.BCPI_CONFIG?.mode === "static";
  const path = (window.location.pathname.replace(/\.html$/, "") || "/").replace(/\/$/, "") || "/";

  function href(file) {
    if (file === "index.html" || file === "/") return staticSite ? "./index.html" : "/";
    return staticSite ? `./${file}` : `/${file}`;
  }

  function isActive(matchers) {
    return matchers.some((match) => {
      if (match === "/") return path === "/" || path.endsWith("/index");
      return path.endsWith(match);
    });
  }

  function tab(file, label, matchers) {
    const active = isActive(matchers);
    return `<a href="${href(file)}" class="${active ? "active" : ""}"${
      active ? ' aria-current="page"' : ""
    }>${label}</a>`;
  }

  window.BCPI_SHELL = {
    paperName: "The Allegheny Herald",
    paperSide: "College & Pro",
    kicker: "Your Only Resource for Fall Weekends",
    siteTitle: "The Press Box | The Allegheny Herald",
    railHtml() {
      return `
        <div class="rail-sport">
          <span class="rail-sport-name">College</span>
          <div class="rail-tabs">
            ${tab("power.html", "Power", ["/power"])}
            ${tab("poll.html", "Poll", ["/poll"])}
            ${tab("index.html", "Matchup", ["/"])}
          </div>
        </div>
        <div class="rail-sport">
          <span class="rail-sport-name">NFL</span>
          <div class="rail-tabs">
            ${tab("nfl-power.html", "Power", ["/nfl-power"])}
            ${tab("nfl-matchup.html", "Matchup", ["/nfl-matchup"])}
          </div>
        </div>`;
    },
    paintChrome() {
      const bannerName = document.querySelector(".banner-name");
      const bannerSide = document.querySelector(".banner-side");
      const kicker = document.querySelector(".mast-kicker");
      const rail = document.querySelector("nav.rail");
      if (bannerName) bannerName.textContent = this.paperName;
      if (bannerSide && !bannerSide.classList.contains("banner-date")) {
        bannerSide.textContent = this.paperSide;
      }
      if (kicker) kicker.textContent = this.kicker;
      if (rail) rail.innerHTML = this.railHtml();
    },
    refreshStamp: null,
  };

  function parseStamp(iso) {
    if (!iso) return null;
    const text = String(iso).trim();
    const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatMastDate(date, narrow) {
    const zone = "America/Los_Angeles";
    if (narrow) {
      const weekday = new Intl.DateTimeFormat("en-US", { timeZone: zone, weekday: "short" }).format(date);
      const month = new Intl.DateTimeFormat("en-US", { timeZone: zone, month: "short" }).format(date);
      const day = new Intl.DateTimeFormat("en-US", { timeZone: zone, day: "numeric" }).format(date);
      const year = new Intl.DateTimeFormat("en-US", { timeZone: zone, year: "numeric" }).format(date);
      return `${weekday}., ${month}. ${day}, ${year}`;
    }
    return new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    }).format(date);
  }

  function paintRefreshDate() {
    const when = window.BCPI_SHELL.refreshStamp;
    const el = document.querySelector(".banner-side");
    if (!when || !el) return;
    const narrow = window.matchMedia("(max-width: 720px)").matches;
    el.textContent = formatMastDate(when, narrow);
    el.classList.add("banner-date");
  }

  async function readStamp(path, pick) {
    if (typeof BCPI === "undefined") return null;
    try {
      const data = await BCPI.fetchJsonCached(path);
      return parseStamp(pick(data));
    } catch {
      return null;
    }
  }

  async function collegeStamps() {
    const stamps = [];
    const staticSite = typeof BCPI !== "undefined" && BCPI.isStatic();
    if (staticSite) {
      stamps.push(await readStamp("power.json", (data) => data && data.as_of));
      stamps.push(await readStamp("poll.json", (data) => data && data.as_of));
      return stamps;
    }
    let fromApi = false;
    for (const kind of ["power", "poll"]) {
      try {
        const res = await fetch(`/api/rankings/${kind}`);
        if (!res.ok) continue;
        fromApi = true;
        const data = await res.json();
        stamps.push(parseStamp(data && data.as_of));
      } catch {
        /* one feed missing should not blank the date */
      }
    }
    if (!fromApi && typeof BCPI !== "undefined") {
      stamps.push(await readStamp("power.json", (data) => data && data.as_of));
      stamps.push(await readStamp("poll.json", (data) => data && data.as_of));
    }
    return stamps;
  }

  async function newestRefresh() {
    const stamps = await collegeStamps();
    let nflStamp = await readStamp(
      "nfl/nfl_power.json",
      (data) => data && data.meta && data.meta.generated_utc
    );
    if (!nflStamp) {
      nflStamp = await readStamp(
        "nfl/power.json",
        (data) => data && data.meta && data.meta.generated_utc
      );
    }
    stamps.push(nflStamp);
    return stamps.filter(Boolean).sort((a, b) => b - a)[0] || null;
  }

  document.addEventListener("DOMContentLoaded", () => {
    window.BCPI_SHELL.paintChrome();
    const narrowQuery = window.matchMedia("(max-width: 720px)");
    if (narrowQuery.addEventListener) {
      narrowQuery.addEventListener("change", paintRefreshDate);
    }
    newestRefresh()
      .then((stamp) => {
        window.BCPI_SHELL.refreshStamp = stamp;
        paintRefreshDate();
      })
      .catch((error) => {
        window.BCPI_SHELL.refreshError = String((error && error.stack) || error);
      });
  });
})();
