(function () {
  const kind = document.body.dataset.page === "poll" ? "poll" : "power";
  const view = document.getElementById("view");
  const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

  let catalog = null;
  let weights = null;

  function esc(value) {
    return BCPI.esc(value == null ? "" : String(value));
  }

  function ordinal(n) {
    const v = n % 100;
    if (v >= 11 && v <= 13) return `${n}th`;
    const tail = { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th";
    return `${n}${tail}`;
  }

  function signed(value) {
    const number = Number(value) || 0;
    if (Math.abs(number) < 0.005) return "0.00";
    const body = Math.abs(number).toFixed(2);
    return `${number > 0 ? "+" : "−"}${body}`;
  }

  function points(value) {
    return (Number(value) || 0).toFixed(2);
  }

  function record(row) {
    const wins = row.wins != null ? row.wins : 0;
    const losses = row.losses != null ? row.losses : 0;
    const note = row.result_note
      ? `<abbr class="result-note" title="${esc(row.result_note)}">*</abbr>`
      : "";
    return `${wins}-${losses}${note}`;
  }

  function editionDate(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}, ${date.getUTCFullYear()}`;
  }

  function editionLabel(snap) {
    if (!snap) return "";
    if (snap.postseason) return "Postseason Edition";
    if (!snap.week) return "Preseason Edition";
    return `Week ${snap.week} Edition`;
  }

  function weekQuery(snap) {
    if (!snap) return "";
    if (snap.postseason) return "post";
    return String(snap.week);
  }

  function seasonSnaps() {
    const season = Number(catalog.default && catalog.snapshots.find((snap) => snap.id === catalog.default)?.season) || catalog.snapshots[0].season;
    return catalog.snapshots
      .filter((snap) => snap.season === season)
      .sort((a, b) => a.week - b.week || Number(a.postseason) - Number(b.postseason));
  }

  function snapFromQuery() {
    const snaps = seasonSnaps();
    const params = new URLSearchParams(location.search);
    const week = params.get("week");
    if (week === "post") return snaps.find((snap) => snap.postseason) || snaps[snaps.length - 1];
    if (week != null && week !== "") {
      const match = snaps.find((snap) => !snap.postseason && String(snap.week) === week);
      if (match) return match;
    }
    return snaps.find((snap) => snap.id === catalog.default) || snaps[snaps.length - 1];
  }

  function listUrl(snap) {
    return BCPI.pageUrl(kind, { week: weekQuery(snap) });
  }

  function teamUrl(snap, school) {
    return BCPI.pageUrl(kind, { team: BCPI.slugify(school), week: weekQuery(snap) });
  }

  function paintDateline(snap, asOf) {
    const season = document.getElementById("dateline-season");
    const edition = document.getElementById("dateline-edition");
    const date = document.getElementById("dateline-date");
    if (season) season.textContent = `${snap.season} SEASON`;
    if (edition) edition.textContent = editionLabel(snap);
    if (date) date.textContent = editionDate(asOf);
  }

  function showFrame(on) {
    document.querySelectorAll(".banner, .masthead, .dateline, .rail").forEach((el) => {
      el.hidden = !on;
    });
  }

  function scrollKey(snap) {
    return `bcpi-list-scroll:${kind}:${snap.id}`;
  }

  function rememberScroll(snap) {
    sessionStorage.setItem(scrollKey(snap), String(window.scrollY));
  }

  function restoreScroll(snap) {
    const raw = sessionStorage.getItem(scrollKey(snap));
    if (raw == null) return;
    sessionStorage.removeItem(scrollKey(snap));
    const y = Number(raw);
    requestAnimationFrame(() => window.scrollTo(0, y));
  }

  async function loadWeights() {
    if (weights) return weights;
    const params = await BCPI.loadModelParams();
    const stored = params.power_weights || {};
    weights = {
      solver: Number(stored.solver),
      quality: Number(stored.quality),
      market: Number(stored.market) || 0,
      sample: Number(params.power_sample_games) || 6,
    };
    if (!Number.isFinite(weights.solver) || !Number.isFinite(weights.quality)) {
      throw new Error("Power weights are missing from the published parameters.");
    }
    return weights;
  }

  function piecesFor(row, model) {
    if (row.solver_z == null || row.prior_z == null) return null;
    const games = Number(row.fbs_games) || 0;
    const c = row.credibility == null ? Math.min(games / model.sample, 1) : Number(row.credibility);
    const qualityZ = row.quality_z == null ? Number(row.prior_z) : Number(row.quality_z);
    const marketZ = Number(row.market_z) || 0;
    const scoreboard = model.solver * Number(row.solver_z);
    const play = c * model.quality * qualityZ + c * model.market * marketZ;
    const hype = (1 - c) * (model.quality + model.market) * Number(row.prior_z);
    const h2h = Number(row.h2h_adjustment) || 0;
    const total = scoreboard + play + hype + h2h;
    const score = Number(row.power_score);
    if (Math.abs(total - score) > 0.01) {
      console.warn(
        `[power] ${row.school} week ${row.week}: pieces ${total.toFixed(4)} vs score ${score.toFixed(4)}`
      );
    }
    return {
      c,
      games,
      scoreboard,
      play,
      hype,
      h2h,
      total,
      boardShare: model.solver,
      playShare: c * (model.quality + model.market),
      hypeShare: (1 - c) * (model.quality + model.market),
      sample: model.sample,
    };
  }

  function competitionRank(rows, valueOf) {
    const ranked = rows
      .map((row) => ({ school: row.school, value: valueOf(row) }))
      .filter((row) => row.value != null && !Number.isNaN(row.value))
      .sort((a, b) => b.value - a.value);
    const map = {};
    ranked.forEach((row, index) => {
      if (index > 0 && row.value === ranked[index - 1].value) map[row.school] = map[ranked[index - 1].school];
      else map[row.school] = index + 1;
    });
    return map;
  }

  function powerLines(rows, model) {
    const solverRank = competitionRank(rows, (row) => Number(row.solver_z));
    const qualityRank = competitionRank(rows, (row) =>
      row.quality_z == null ? null : Number(row.quality_z)
    );
    const used = new Set();
    const lines = {};
    rows
      .filter((row) => Number(row.rank) <= 25)
      .sort((a, b) => a.rank - b.rank)
      .forEach((row) => {
        const parts = piecesFor(row, model);
        if (!parts) {
          lines[row.school] = `No. ${row.rank} in the preseason list.`;
          return;
        }
        const candidates = [];
        const hypeShare = Math.abs(parts.total) > 0.05 ? Math.abs(parts.hype) / Math.abs(parts.total) : 0;
        if (parts.c < 1 && hypeShare > 0.2) {
          candidates.push("Still leaning on preseason hype. A few more games will settle it.");
          candidates.push(`${row.school} still carries last year's reputation in this score.`);
          candidates.push("Preseason opinion is still a real part of this score.");
        }
        const solver = solverRank[row.school];
        const quality = qualityRank[row.school];
        if (solver <= 5 && quality <= 5) {
          candidates.push("Top-five on the scoreboard and top-five snap for snap.");
          candidates.push("The results and the downs both land in the top five.");
        }
        if (solver && quality && solver + 10 <= quality) {
          candidates.push("Wins on the scoreboard more than the film says it should.");
          candidates.push(`No. ${solver} on the scoreboard, No. ${quality} in the downs.`);
        }
        if (solver && quality && quality + 10 <= solver) {
          candidates.push("Plays better than the results show. The scoreboard may catch up.");
          candidates.push(`No. ${quality} moving the chains, No. ${solver} on the scoreboard.`);
        }
        if (parts.h2h >= 0.05) candidates.push("A win against a team just ahead moved this score up.");
        if (parts.h2h <= -0.05) candidates.push("A loss to a team just behind moved this score down.");
        if (Number(row.losses) === 0 && Number(row.wins) > 0) {
          candidates.push(`${row.wins}-0, No. ${row.rank} on a neutral field.`);
        }
        if (solver && quality && Math.abs(solver - quality) <= 3) {
          candidates.push("The scoreboard and the downs are telling the same story.");
        }
        candidates.push(`No. ${row.rank} on a neutral field. Record ${row.wins}-${row.losses}.`);
        const line = candidates.find((item) => !used.has(item)) || candidates[candidates.length - 1];
        used.add(line);
        lines[row.school] = line;
      });
    return { lines, solverRank, qualityRank };
  }

  function deckLine(leaders, snaps, index) {
    const team = leaders[index];
    if (!team) return "";
    let held = 1;
    for (let i = index - 1; i >= 0; i -= 1) {
      if (snaps[i + 1].week - snaps[i].week !== 1) break;
      if (leaders[i] !== team) break;
      held += 1;
    }
    if (held >= 2) return `${team} holds the top spot for a ${ordinal(held)} straight week.`;
    const previous = index > 0 ? leaders[index - 1] : "";
    if (previous && previous !== team) return `${team} takes over the top spot from ${previous}.`;
    return `${team} is No. 1.`;
  }

  async function leadersThrough(snaps, index) {
    const slice = snaps.slice(0, index + 1);
    const packs = await Promise.all(slice.map((snap) => BCPI.fetchRankings(kind, { snapshot: snap })));
    return packs.map((pack) => {
      const top = (pack.rows || []).find((row) => Number(row.rank) === 1) || pack.rows?.[0];
      return top ? top.school : "";
    });
  }

  function logoHtml(team, sizeClass) {
    const src = team && (team.logo || team.logo_dark);
    if (!src) return `<span class="${sizeClass}"></span>`;
    return `<img class="${sizeClass}" src="${esc(src)}" alt="" />`;
  }

  function priorSnap(snaps, index) {
    const prev = snaps[index - 1];
    const curr = snaps[index];
    if (!prev || !curr) return null;
    if (curr.postseason || prev.postseason) return prev;
    if (curr.week - prev.week === 1) return prev;
    return null;
  }

  function movement(current, previous) {
    if (previous == null) return "—";
    const delta = previous - current;
    if (delta === 0) return "—";
    return `${delta > 0 ? "▲" : "▼"}${Math.abs(delta)}`;
  }

  function stepper(snaps, index) {
    const prev = snaps[index - 1];
    const next = snaps[index + 1];
    const label = (snap, arrow) => {
      if (!snap) return arrow === "prev" ? "‹ Week" : "Week ›";
      if (snap.postseason) return arrow === "prev" ? "‹ Postseason" : "Postseason ›";
      if (!snap.week) return arrow === "prev" ? "‹ Preseason" : "Preseason ›";
      return arrow === "prev" ? `‹ Week ${snap.week}` : `Week ${snap.week} ›`;
    };
    return `
      <div class="stepper">
        <button type="button" data-week="${prev ? esc(weekQuery(prev)) : ""}" ${prev ? "" : "disabled"}>${esc(label(prev, "prev"))}</button>
        <button type="button" data-week="${next ? esc(weekQuery(next)) : ""}" ${next ? "" : "disabled"}>${esc(label(next, "next"))}</button>
      </div>`;
  }

  function teamCell(row, team) {
    return `
      <span class="team-bits">
        ${logoHtml(team, "logo")}
        <span>
          <span class="team-name">${esc(row.school)}</span>
          <span class="conf">${esc(row.conference || "")}</span>
        </span>
      </span>`;
  }

  function renderPowerList(pack, snaps, index, deck, teamsBySchool) {
    const top = (pack.rows || []).filter((row) => Number(row.rank) <= 25);
    const rows = top
      .map((row) => {
        const team = teamsBySchool[row.school] || {};
        return `<a class="board-row cols-power" href="${esc(teamUrl(snaps[index], row.school))}">
          <span class="num">${esc(row.rank)}</span>
          ${teamCell(row, team)}
          <span class="rec">${record(row)}</span>
          <span class="score">${esc(points(row.power_score))}</span>
        </a>`;
      })
      .join("");
    view.innerHTML = `
      <p class="sec-label"><span>Power rankings</span><i></i></p>
      <h2 class="headline">Who wins on a neutral field</h2>
      <p class="deck">${esc(deck)}</p>
      ${stepper(snaps, index)}
      <div class="board">
        <div class="board-head cols-power"><span>No.</span><span>Team</span><span class="rec">Rec</span><span class="score">Score</span></div>
        ${rows}
      </div>
      <p class="caption">Tap any team to see what's behind its score.</p>`;
  }

  function renderPollList(pack, snaps, index, deck, teamsBySchool, priorRanks) {
    const top = (pack.rows || []).filter((row) => Number(row.rank) <= 25);
    const rows = top
      .map((row) => {
        const team = teamsBySchool[row.school] || {};
        return `<a class="board-row cols-poll" href="${esc(teamUrl(snaps[index], row.school))}">
          <span class="num">${esc(row.rank)}</span>
          ${teamCell(row, team)}
          <span class="rec">${record(row)}</span>
          <span class="move">${esc(movement(Number(row.rank), priorRanks[row.school]))}</span>
          <span class="score">${esc(points(row.poll_score))}</span>
        </a>`;
      })
      .join("");
    view.innerHTML = `
      <p class="sec-label"><span>The poll</span><i></i></p>
      <h2 class="headline">Who has earned it so far</h2>
      <p class="deck">${esc(deck)}</p>
      ${stepper(snaps, index)}
      <div class="board">
        <div class="board-head cols-poll"><span>No.</span><span>Team</span><span class="rec">Rec</span><span class="move">±</span><span class="score">Score</span></div>
        ${rows}
      </div>
      <p class="caption">Tap any team to see the résumé.</p>`;
  }

  function splitBar(parts) {
    const shown = parts.filter((part) => part.always || Math.abs(part.value) >= 0.05);
    const total = shown.reduce((sum, part) => sum + Math.abs(part.value), 0);
    if (total <= 0) return "";
    const legend = [];
    const segs = shown
      .map((part) => {
        const negative = part.value < -0.005;
        const klass = negative ? "neg" : part.tone;
        const width = (Math.abs(part.value) / total) * 100;
        const shownValue = part.value < -0.005 ? signed(part.value) : Math.abs(part.value).toFixed(2);
        const label = `${part.name} ${shownValue}`;
        const inside = width >= 28 && !negative;
        if (!inside) legend.push(label);
        const inner = inside ? `<b class="${part.tone === "hatch" ? "chip" : ""}">${esc(label)}</b>` : "";
        return `<span class="${klass}" style="flex:${width} 1 0">${inner}</span>`;
      })
      .join("");
    const legendHtml = legend.length ? `<div class="split-legend">${legend.map((label) => `<span>${esc(label)}</span>`).join("")}</div>` : "";
    return `<div class="split">${segs}</div>${legendHtml}`;
  }

  function pieceBlock({ title, verdict, copy, meta, zero }) {
    return `
      <section class="piece${zero ? " is-zero" : ""}">
        <div class="piece-top">
          <h3>${esc(title)}</h3>
          <p class="verdict">${esc(verdict)}</p>
        </div>
        <p>${esc(copy)}</p>
        <p class="meta">${esc(meta)}</p>
      </section>`;
  }

  function pct(share) {
    return `${Math.round(share * 100)}%`;
  }

  function renderPowerTeam(row, team, snap, context) {
    const prior = context.priorRanks[row.school];
    const lastWeek = context.hasPrior ? prior || "New" : "—";
    const leader = context.rows.find((item) => Number(item.rank) === 1);
    const runner = context.rows.find((item) => Number(item.rank) === 2);
    const gapLabel = Number(row.rank) === 1 ? "Ahead of No. 2" : "Behind No. 1";
    let gapValue = "—";
    if (Number(row.rank) === 1 && runner) gapValue = points(Number(row.power_score) - Number(runner.power_score));
    else if (leader) gapValue = signed(Number(row.power_score) - Number(leader.power_score));
    const parts = piecesFor(row, context.model);
    const line = context.lines[row.school] || `No. ${row.rank} on a neutral field. Record ${row.wins}-${row.losses}.`;
    let breakdown = `<p class="note">This edition is the preseason list. The breakdown starts after games are played.</p>`;
    if (parts) {
      const solverNo = context.solverRank[row.school];
      const qualityNo = context.qualityRank[row.school];
      const hypeTail =
        parts.c < 1
          ? `${row.school} has played ${parts.games} of ${parts.sample}.`
          : `${row.school} has played ${parts.games}.`;
      const hypeVerdict = parts.c >= 1 ? "Gone" : `${pct(parts.hypeShare)} left`;
      breakdown = `
        <p class="sec-label"><span>What's behind the ${esc(points(row.power_score))}</span><i></i></p>
        ${splitBar([
          { name: "Scoreboard", value: parts.scoreboard, tone: "solid", always: true },
          { name: "How they play", value: parts.play, tone: "hatch", always: true },
          { name: "Hype", value: parts.hype, tone: "plain", always: false },
          { name: "H2H", value: parts.h2h, tone: "plain", always: false },
        ])}
        ${pieceBlock({
          title: "The Scoreboard",
          verdict: solverNo ? `No. ${solverNo}` : "—",
          copy: "Who they beat, by how much, and how good those teams were. Recent games count more. Running up the score past a point does nothing.",
          meta: `Counts for ${pct(parts.boardShare)} · Adds ${signed(parts.scoreboard)}`,
          zero: Math.abs(parts.scoreboard) < 0.005,
        })}
        ${pieceBlock({
          title: "How They Play",
          verdict: qualityNo ? `No. ${qualityNo}` : "—",
          copy: "Winning the down: staying on schedule and moving the chains, plus a little credit for big plays and recent scoring.",
          meta: `Counts for ${pct(parts.playShare)} · Adds ${signed(parts.play)}`,
          zero: Math.abs(parts.play) < 0.005,
        })}
        ${pieceBlock({
          title: "Preseason Hype",
          verdict: hypeVerdict,
          copy: `Last year, recruiting, and the preseason polls. It shrinks every game and is out after ${parts.sample === 6 ? "six" : parts.sample}. ${hypeTail}`,
          meta: `Counts for ${pct(parts.hypeShare)} now · Adds ${signed(parts.hype)}`,
          zero: Math.abs(parts.hype) < 0.005,
        })}
        ${pieceBlock({
          title: "Head-to-Head",
          verdict: Math.abs(parts.h2h) < 0.005 ? "No change" : signed(parts.h2h),
          copy: "Beat a team just ahead of you and you jump them. It only kicks in when two teams are close.",
          meta: `Adds ${signed(parts.h2h)}`,
          zero: Math.abs(parts.h2h) < 0.005,
        })}`;
    }
    view.innerHTML = `
      <div class="inside-bar">
        <a class="back" href="${esc(listUrl(snap))}">‹ Power rankings</a>
        <a class="mini-mark" href="${esc(listUrl(snap))}">Bergstein</a>
      </div>
      <p class="sec-label"><span>No. ${esc(row.rank)} · ${esc(row.conference || "")} · ${record(row)}</span><i></i></p>
      <div class="team-lockup">
        ${logoHtml(team, "logo-lg")}
        <h2>${esc(row.school)}</h2>
      </div>
      <p class="one-liner">${esc(line)}</p>
      <div class="statbox" data-sum-ok="${parts ? (Math.abs(parts.total - Number(row.power_score)) <= 0.01 ? "1" : "0") : ""}">
        <div class="stat"><div class="lbl">Power score</div><div class="val">${esc(points(row.power_score))}</div></div>
        <div class="stat"><div class="lbl">Last week</div><div class="val${lastWeek === "New" || lastWeek === "—" ? " word" : ""}">${esc(lastWeek)}</div></div>
        <div class="stat"><div class="lbl">${esc(gapLabel)}</div><div class="val">${esc(gapValue)}</div></div>
      </div>
      ${breakdown}`;
  }

  function pollParts(row) {
    if (row.resume_z == null || row.preseason_share == null) return null;
    const share = Number(row.preseason_share) || 0;
    const pre = share * (Number(row.preseason_z) || 0);
    const resume = (1 - share) * (Number(row.resume_z) || 0);
    const h2h = Number(row.h2h_adjustment) || 0;
    const total = pre + resume + h2h;
    const score = Number(row.poll_score);
    if (Math.abs(total - score) > 0.01) {
      console.warn(
        `[poll] ${row.school} week ${row.week}: pieces ${total.toFixed(4)} vs score ${score.toFixed(4)}`
      );
    }
    return { share, pre, resume, h2h, total };
  }

  function opponentRank(name, rows) {
    if (!name) return null;
    const found = rows.find((row) => row.school === name);
    if (!found || Number(found.rank) > 25) return null;
    return Number(found.rank);
  }

  function renderPollTeam(row, team, snap, context) {
    const prior = context.priorRanks[row.school];
    const lastWeek = context.hasPrior ? prior || "New" : "—";
    const preseasonRank = context.preseasonRank[row.school];
    const resumeRank = context.resumeRank[row.school];
    const parts = pollParts(row);
    const bestRank = opponentRank(row.best_win, context.rows);
    const worstRank = opponentRank(row.worst_loss, context.rows);
    const gamesPlayed = Number(row.fbs_games) || 0;
    let resume = "";
    if (!parts) {
      resume = `<p class="note">This edition is the preseason poll. The résumé starts after games are played.</p>`;
    } else {
      const hypeVerdict = parts.share <= 0 ? "Gone" : `${pct(parts.share)} left`;
      const played =
        Number(row.fcs_games) > 0
          ? `${row.school} has played ${gamesPlayed} against FBS and ${row.fcs_games} against FCS.`
          : `${row.school} has played ${gamesPlayed}.`;
      resume = `
        <p class="sec-label"><span>The résumé</span><i></i></p>
        ${splitBar([
          { name: "Results", value: parts.resume, tone: "solid", always: true },
          { name: "Preseason", value: parts.pre, tone: "hatch", always: Math.abs(parts.pre) >= 0.05 },
          { name: "H2H", value: parts.h2h, tone: "plain", always: false },
        ])}
        ${pieceBlock({
          title: "The Results",
          verdict: resumeRank ? `No. ${resumeRank}` : "—",
          copy: "Wins and losses measured against a top-25 team with the same opponent, home or away. Margins count for a smaller share, and a blowout stops adding past a point.",
          meta: `Counts for ${pct(1 - parts.share)} · Adds ${signed(parts.resume)}`,
          zero: Math.abs(parts.resume) < 0.005,
        })}
        ${pieceBlock({
          title: "Preseason",
          verdict: hypeVerdict,
          copy: `Last year's final poll, the roster, and the preseason polls. The share shrinks as the games pile up. ${played}`,
          meta: `Counts for ${pct(parts.share)} now · Adds ${signed(parts.pre)}`,
          zero: Math.abs(parts.pre) < 0.005,
        })}
        ${pieceBlock({
          title: "Head-to-Head",
          verdict: Math.abs(parts.h2h) < 0.005 ? "No change" : signed(parts.h2h),
          copy: "Beat a team just ahead of you and you jump them. It only kicks in when two teams are close.",
          meta: `Adds ${signed(parts.h2h)}`,
          zero: Math.abs(parts.h2h) < 0.005,
        })}
        ${pieceBlock({
          title: "Best Win",
          verdict: row.best_win || "None",
          copy: row.best_win
            ? bestRank
              ? `${row.school} beat ${row.best_win}, No. ${bestRank} in this poll.`
              : `${row.school} beat ${row.best_win}.`
            : "No win on the schedule yet.",
          meta: "This season",
          zero: !row.best_win,
        })}
        ${pieceBlock({
          title: "Worst Loss",
          verdict: row.worst_loss || "None",
          copy: row.worst_loss
            ? worstRank
              ? `${row.school} lost to ${row.worst_loss}, No. ${worstRank} in this poll.`
              : `${row.school} lost to ${row.worst_loss}.`
            : "No loss on the schedule.",
          meta: "This season",
          zero: !row.worst_loss,
        })}
        ${context.rankedWinsHtml || ""}`;
    }
    const preseasonCell =
      preseasonRank && parts && parts.share > 0 ? String(preseasonRank) : "—";
    view.innerHTML = `
      <div class="inside-bar">
        <a class="back" href="${esc(listUrl(snap))}">‹ The poll</a>
        <a class="mini-mark" href="${esc(listUrl(snap))}">Bergstein</a>
      </div>
      <p class="sec-label"><span>No. ${esc(row.rank)} in the poll · ${esc(row.conference || "")} · ${record(row)}</span><i></i></p>
      <div class="team-lockup">
        ${logoHtml(team, "logo-lg")}
        <h2>${esc(row.school)}</h2>
      </div>
      <div class="statbox">
        <div class="stat"><div class="lbl">Poll rank</div><div class="val">${esc(row.rank)}</div></div>
        <div class="stat"><div class="lbl">Last week</div><div class="val${lastWeek === "New" || lastWeek === "—" ? " word" : ""}">${esc(lastWeek)}</div></div>
        <div class="stat"><div class="lbl">Preseason</div><div class="val${preseasonCell === "—" ? " word" : ""}">${esc(preseasonCell)}</div></div>
      </div>
      ${resume}
      ${context.gameLog || ""}`;
  }

  function kickoffLabel(game) {
    if (game.tbd || !game.date) return "Time TBA";
    const date = new Date(game.date);
    if (Number.isNaN(date.getTime())) return "Time TBA";
    const day = date.toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
      timeZone: "America/New_York",
    });
    const time = date
      .toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        timeZone: "America/New_York",
      })
      .replace(" AM", " a.m.")
      .replace(" PM", " p.m.");
    return `${day}, ${time} ET`;
  }

  function rankEntering(maps, gameWeek, opponent) {
    const weeks = Object.keys(maps)
      .map(Number)
      .filter((week) => week < gameWeek)
      .sort((a, b) => b - a);
    if (!weeks.length || weeks[0] !== gameWeek - 1) return null;
    const rank = maps[weeks[0]][opponent];
    return rank && rank <= 25 ? rank : null;
  }

  async function scheduleContext(snap, school, rows) {
    let schedule = { games: [] };
    try {
      if (BCPI.isStatic()) schedule = await BCPI.fetchJsonCached(`schedules/${snap.season}.json`);
      else {
        const res = await fetch(`/api/schedule?season=${snap.season}`);
        if (res.ok) schedule = await res.json();
      }
    } catch {
      schedule = { games: [] };
    }
    const games = (schedule.games || [])
      .filter((game) => game.home === school || game.away === school)
      .filter((game) => (snap.postseason ? Boolean(game.post) : !game.post))
      .sort((a, b) => a.week - b.week || String(a.date).localeCompare(String(b.date)));
    const snaps = seasonSnaps().filter((item) => !item.postseason && item.week < (snap.week || 0));
    const maps = {};
    await Promise.all(
      snaps.map(async (item) => {
        const pack = await BCPI.fetchRankings("poll", { snapshot: item });
        const bySchool = {};
        (pack.rows || []).forEach((row) => {
          bySchool[row.school] = Number(row.rank);
        });
        maps[item.week] = bySchool;
      })
    );
    const rankedWins = [];
    const played = [];
    const upcoming = [];
    games.forEach((game) => {
      const home = game.home === school;
      const opponent = home ? game.away : game.home;
      const done = game.done && game.homeScore != null && game.awayScore != null;
      const mine = home ? game.homeScore : game.awayScore;
      const theirs = home ? game.awayScore : game.homeScore;
      const site = game.neutral || home ? "vs" : "at";
      if (!done || game.week > snap.week) {
        if (game.week >= snap.week) upcoming.push({ game, opponent, site });
        return;
      }
      const win = mine > theirs;
      const atTime = rankEntering(maps, game.week, opponent);
      played.push({ game, opponent, site, mine, theirs, win, atTime });
      if (win && atTime) rankedWins.push(`${opponent} (No. ${atTime} at the time)`);
    });
    const nextGames = upcoming;
    const logRows = played
      .concat(nextGames.map((item) => ({ ...item, upcoming: true })))
      .map((item) => {
        if (item.upcoming) {
          return `<div class="log-row cols-log">
            <span class="wk">${esc(item.game.week)}</span>
            <span class="team-name">${esc(item.site)} ${esc(item.opponent)}</span>
            <span class="move">—</span>
            <span class="kick">${esc(kickoffLabel(item.game))}</span>
          </div>`;
        }
        const ranked = item.atTime ? ` <span class="opp-rank">No. ${esc(item.atTime)}</span>` : "";
        return `<div class="log-row cols-log">
          <span class="wk">${esc(item.game.week)}</span>
          <span><span class="team-name">${esc(item.site)} ${esc(item.opponent)}</span>${ranked}</span>
          <span class="wl ${item.win ? "win" : "loss"}">${item.win ? "W" : "L"}</span>
          <span class="score">${esc(item.mine)}–${esc(item.theirs)}</span>
        </div>`;
      })
      .join("");
    const gameLog = logRows
      ? `<p class="sec-label"><span>Game log</span><i></i></p>
        <div class="board">
          <div class="log-head cols-log"><span>Wk</span><span>Opponent</span><span></span><span class="score">Score</span></div>
          ${logRows}
        </div>`
      : `<p class="sec-label"><span>Game log</span><i></i></p><p class="note">No games are published for this edition.</p>`;
    const rankedList =
      rankedWins.length <= 1
        ? rankedWins.join("")
        : `${rankedWins.slice(0, -1).join(", ")} and ${rankedWins[rankedWins.length - 1]}`;
    const rankedWinsHtml = pieceBlock({
      title: "Ranked Wins",
      verdict: rankedWins.length ? String(rankedWins.length) : "None",
      copy: rankedWins.length
        ? `Beat ${rankedList}.`
        : "No win against a team that was ranked in the previous edition.",
      meta: "Rank entering that week",
      zero: rankedWins.length === 0,
    });
    return { gameLog, rankedWinsHtml: games.length ? rankedWinsHtml : "" };
  }

  function bindList(snaps, index) {
    view.querySelectorAll(".stepper button").forEach((button) => {
      button.addEventListener("click", () => {
        if (!button.dataset.week) return;
        const params = new URLSearchParams(location.search);
        params.delete("team");
        params.set("week", button.dataset.week);
        location.href = `${location.pathname}?${params.toString()}`;
      });
    });
    view.querySelectorAll(".board-row").forEach((link) => {
      link.addEventListener("click", () => rememberScroll(snaps[index]));
    });
  }

  async function showList(snap) {
    showFrame(true);
    const snaps = seasonSnaps();
    const index = Math.max(0, snaps.findIndex((item) => item.id === snap.id));
    const prev = priorSnap(snaps, index);
    const [teams, pack, leaders, priorPack] = await Promise.all([
      BCPI.fetchTeams(snap),
      BCPI.fetchRankings(kind, { snapshot: snap }),
      leadersThrough(snaps, index),
      prev ? BCPI.fetchRankings(kind, { snapshot: prev }) : Promise.resolve(null),
    ]);
    paintDateline(snap, pack.as_of);
    const deck = deckLine(leaders, snaps, index);
    const priorRanks = {};
    (priorPack?.rows || []).forEach((row) => {
      priorRanks[row.school] = Number(row.rank);
    });
    if (kind === "power") renderPowerList(pack, snaps, index, deck, teams.bySchool);
    else renderPollList(pack, snaps, index, deck, teams.bySchool, priorRanks);
    bindList(snaps, index);
    restoreScroll(snap);
    document.title = kind === "poll" ? "Bergstein · Poll" : "Bergstein · Power";
  }

  async function showTeam(snap, slug) {
    showFrame(false);
    const [teams, pack, model] = await Promise.all([
      BCPI.fetchTeams(snap),
      BCPI.fetchRankings(kind, { snapshot: snap }),
      kind === "power" ? loadWeights() : Promise.resolve(null),
    ]);
    const row = (pack.rows || []).find((item) => BCPI.slugify(item.school) === slug);
    if (!row) {
      view.innerHTML = `
        <div class="inside-bar">
          <a class="back" href="${esc(listUrl(snap))}">‹ ${kind === "poll" ? "The poll" : "Power rankings"}</a>
          <a class="mini-mark" href="${esc(listUrl(snap))}">Bergstein</a>
        </div>
        <p class="status">That team is not in this edition.</p>`;
      return;
    }
    const snaps = seasonSnaps();
    const index = snaps.findIndex((item) => item.id === snap.id);
    const prev = priorSnap(snaps, index);
    const priorPack = prev ? await BCPI.fetchRankings(kind, { snapshot: prev }) : null;
    const priorRanks = {};
    (priorPack?.rows || []).forEach((item) => {
      priorRanks[item.school] = Number(item.rank);
    });
    const team = teams.bySchool[row.school] || {};
    if (kind === "power") {
      const ranked = powerLines(pack.rows || [], model);
      renderPowerTeam(row, team, snap, {
        rows: pack.rows || [],
        priorRanks,
        model,
        hasPrior: Boolean(prev),
        lines: ranked.lines,
        solverRank: ranked.solverRank,
        qualityRank: ranked.qualityRank,
      });
    } else {
      const resumeRank = competitionRank(pack.rows || [], (item) =>
        item.resume_z == null ? null : Number(item.resume_z)
      );
      const preseasonRank = competitionRank(pack.rows || [], (item) =>
        item.preseason_z == null ? null : Number(item.preseason_z)
      );
      const extra = await scheduleContext(snap, row.school, pack.rows || []);
      renderPollTeam(row, team, snap, {
        rows: pack.rows || [],
        priorRanks,
        hasPrior: Boolean(prev),
        resumeRank,
        preseasonRank,
        ...extra,
      });
    }
    const indexName = kind === "poll" ? "Bergstein Poll" : "Bergstein Power Index";
    const shareTitle = `${row.school}: No. ${row.rank} in the ${indexName}`;
    document.title = `Bergstein · ${row.school}`;
    const ogTitle = document.querySelector('meta[property="og:title"]');
    if (ogTitle) ogTitle.setAttribute("content", shareTitle);
    const twTitle = document.querySelector('meta[name="twitter:title"]');
    if (twTitle) twTitle.setAttribute("content", shareTitle);
    window.scrollTo(0, 0);
  }

  async function render() {
    try {
      if (!catalog) catalog = await BCPI.loadCatalog();
      const snap = snapFromQuery();
      if (!snap) {
        view.innerHTML = `<p class="status">No edition is published yet.</p>`;
        return;
      }
      const slug = new URLSearchParams(location.search).get("team");
      if (slug) await showTeam(snap, slug);
      else await showList(snap);
    } catch (error) {
      view.innerHTML = `<p class="status">${esc(error.message || "Could not load this edition.")}</p>`;
    }
  }

  render();
})();
