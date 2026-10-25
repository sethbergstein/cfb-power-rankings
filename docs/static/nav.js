/** Mobile bottom tab bar — injected on all pages. */
(function () {
  if (document.querySelector(".mobile-tab-bar")) return;

  const staticSite = window.BCPI_CONFIG?.mode === "static";
  const path = (window.location.pathname.replace(/\.html$/, "") || "/").replace(/\/$/, "") || "/";

  function href(file) {
    if (file === "index.html") return staticSite ? "./index.html" : "/";
    return staticSite ? `./${file}` : `/${file}`;
  }

  function active(matchers) {
    return matchers.some((match) => {
      if (match === "/") return path === "/" || path.endsWith("/index");
      return path.endsWith(match);
    });
  }

  const tabs = [
    { file: "power.html", label: "Power", match: ["/power"] },
    { file: "poll.html", label: "Poll", match: ["/poll"] },
    { file: "index.html", label: "Match", match: ["/"] },
    { file: "nfl-power.html", label: "NFL", match: ["/nfl-power"] },
    { file: "nfl-matchup.html", label: "NFL·M", match: ["/nfl-matchup"] },
  ];

  const nav = document.createElement("nav");
  nav.className = "mobile-tab-bar";
  nav.setAttribute("aria-label", "Primary");
  nav.innerHTML = tabs
    .map(({ file, label, match }) => {
      const on = active(match);
      return `<a href="${href(file)}" class="mobile-tab${on ? " active" : ""}">${label}</a>`;
    })
    .join("");
  document.body.appendChild(nav);

  const mobileQuery = window.matchMedia("(max-width: 720px)");

  function syncMobileShell() {
    if (!mobileQuery.matches) {
      document.documentElement.style.removeProperty("--app-height");
      document.documentElement.style.removeProperty("--app-offset-top");
      return;
    }
    const vv = window.visualViewport;
    if (!vv) return;
    document.documentElement.style.setProperty("--app-height", `${Math.round(vv.height)}px`);
    document.documentElement.style.setProperty("--app-offset-top", `${Math.round(vv.offsetTop)}px`);
  }

  syncMobileShell();
  window.visualViewport?.addEventListener("resize", syncMobileShell);
  window.visualViewport?.addEventListener("scroll", syncMobileShell);
  mobileQuery.addEventListener("change", syncMobileShell);
  window.addEventListener("orientationchange", syncMobileShell);
  window.addEventListener("resize", syncMobileShell);
})();
