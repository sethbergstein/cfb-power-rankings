/** Shared masthead / rail chrome for The Football Journal. */
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
    paperName: "The Football Journal",
    paperSide: "College & Pro",
    kicker: "College · NFL · Rankings",
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
      if (bannerSide) bannerSide.textContent = this.paperSide;
      if (kicker) kicker.textContent = this.kicker;
      if (rail) rail.innerHTML = this.railHtml();
    },
  };

  document.addEventListener("DOMContentLoaded", () => {
    window.BCPI_SHELL.paintChrome();
  });
})();
