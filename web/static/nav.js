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

  document.body.appendChild(nav);
})();
