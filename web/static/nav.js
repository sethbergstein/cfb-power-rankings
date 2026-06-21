/** Mobile bottom tab bar — injected on all pages. */
(function () {
  if (document.querySelector(".mobile-tab-bar")) return;

  const staticSite = window.BCPI_CONFIG?.mode === "static";
  const path = window.location.pathname.replace(/\.html$/, "") || "/";
  const tabs = [
    { href: staticSite ? "./power.html" : "/power.html", label: "Power", match: "/power" },
    { href: staticSite ? "./poll.html" : "/poll.html", label: "Poll", match: "/poll" },
    { href: staticSite ? "./index.html" : "/", label: "Matchup", match: "/" },
  ];

  const spacer = document.createElement("div");
  spacer.className = "mobile-tab-bar-spacer";
  spacer.setAttribute("aria-hidden", "true");

  const nav = document.createElement("nav");
  nav.className = "mobile-tab-bar";
  nav.setAttribute("aria-label", "Primary");

  nav.innerHTML = tabs
    .map(({ href, label, match }) => {
      const active =
        match === "/"
          ? path === "/" || path.endsWith("/index")
          : path.endsWith(match);
      return `<a href="${href}" class="mobile-tab${active ? " active" : ""}">${label}</a>`;
    })
    .join("");

  document.body.appendChild(spacer);
  document.body.appendChild(nav);

  const mobileQuery = window.matchMedia("(max-width: 720px)");

  function updateMobileChromeInset() {
    if (!mobileQuery.matches || !window.visualViewport) {
      document.documentElement.style.setProperty("--mobile-chrome-bottom", "0px");
      return;
    }
    const vv = window.visualViewport;
    const inset = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop));
    document.documentElement.style.setProperty("--mobile-chrome-bottom", `${inset}px`);
  }

  function syncMobileTabStack() {
    if (!mobileQuery.matches) {
      document.documentElement.style.setProperty("--mobile-tab-stack-height", "0px");
      spacer.style.height = "0px";
      return;
    }

    updateMobileChromeInset();

    requestAnimationFrame(() => {
      const navHeight = Math.ceil(nav.getBoundingClientRect().height);
      const chrome =
        parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue("--mobile-chrome-bottom")
        ) || 0;
      const stackHeight = navHeight + chrome;
      document.documentElement.style.setProperty("--mobile-tab-stack-height", `${stackHeight}px`);
      spacer.style.height = `${stackHeight}px`;
    });
  }

  syncMobileTabStack();
  window.visualViewport?.addEventListener("resize", syncMobileTabStack);
  window.visualViewport?.addEventListener("scroll", syncMobileTabStack);
  mobileQuery.addEventListener("change", syncMobileTabStack);
  window.addEventListener("orientationchange", syncMobileTabStack);
  window.addEventListener("resize", syncMobileTabStack);

  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(syncMobileTabStack);
    observer.observe(nav);
  }
})();
