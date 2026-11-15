const state = { runs: [], selected: null, filter: "all", paused: false, lastGame: null };
const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatReward(value) {
  return typeof value === "number" ? value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "") : "—";
}

function renderRuns() {
  const list = $("run-list");
  list.replaceChildren();
  const filtered = state.runs.filter((run) => state.filter === "all"
    || (state.filter === "running" ? run.status === "running" : run.status !== "running"));
  $("run-count").textContent = String(filtered.length);
  if (!filtered.length) {
    list.append(el("div", "empty", state.runs.length ? "No runs in this filter." : "Waiting for snapshots…"));
    return;
  }
  for (const run of filtered) {
    const button = el("button", `run-item${state.selected === run.id ? " selected" : ""}`);
    button.type = "button";
    button.addEventListener("click", () => {
      state.selected = run.id;
      renderRuns();
      loadGame();
    });
    const main = el("div", "run-main");
    main.append(el("span", "run-name", run.title));
    const status = el("span", `status${run.status === "running" ? "" : " saved"}`,
      run.status === "running" ? "LIVE" : "SAVED");
    main.append(status);
    const meta = el("div", "run-meta");
    meta.append(el("span", run.source));
    if (run.effort) meta.append(el("span", `· ${run.effort} effort`));
    if (run.reward !== null && run.reward !== undefined) meta.append(el("span", `· ${formatReward(run.reward)}`));
    button.append(main, meta);
    list.append(button);
  }
}

function eventText(event) {
  const actor = event.by || event.actor || "Game";
  switch (event.type) {
    case "round_started": return [`Round ${event.round} began`, `${(event.alive || []).length} players · discussion opened`];
    case "message_sent": {
      const audience = event.channel === "public" ? "public" : `private to ${event.to}`;
      return [`${actor} sent a ${audience} message`, event.text || ""];
    }
    case "deal_proposed": return [`${actor} proposed a deal to ${event.to}`,
      `${event.offer_kind} ${event.offer_target} ↔ ${event.ask_kind} ${event.ask_target}${event.text ? ` · “${event.text}”` : ""}`];
    case "deal_accepted": return [`${actor} accepted ${event.frm}'s deal`, `${event.ask_kind} ${event.ask_target}`];
    case "deal_declined": return [`${actor} declined ${event.frm}'s deal`, `${event.ask_kind} ${event.ask_target}`];
    case "deal_expired": return ["A deal expired without an answer", `between ${event.frm} and ${event.to}`];
    case "deal_evaluated": return [`${actor} evaluated a deal`,
      `${event.accepted ? "Accepted" : "Rejected"} · ask ${Number(event.requested_utility || 0).toFixed(2)} · reservation ${Number(event.reservation_value || 0).toFixed(2)} · proposer trust ${Number(event.proposer_trust || 0).toFixed(2)}`];
    case "alliance_proposed": return [`${actor} proposed an alliance`, (event.members || []).join(", ")];
    case "alliance_formed": return ["Alliance formed", (event.members || []).join(" · ")];
    case "alliance_rejected": return ["Alliance proposal rejected", event.reason || "A member declined"];
    case "request_made": return [`${actor} asked ${event.to} for a promise`, `${event.kind} ${event.target}`];
    case "request_accepted": return [`${actor} accepted a promise request`, `${event.kind} ${event.target}`];
    case "request_declined": return [`${actor} declined a promise request`, `${event.kind} ${event.target}`];
    case "promise_made": return [`${actor} promised ${event.promisee}`, `${event.kind} ${event.target}`];
    case "promise_kept": return [`${actor} kept a promise to ${event.promisee}`, `${event.kind} ${event.target}`];
    case "promise_broken": return [`${actor} broke a promise to ${event.promisee}`, `${event.kind} ${event.target}`];
    case "voting_started": return ["Voting started", `${(event.eligible || []).length} ballots · choices are secret`];
    case "votes_tallied": return [event.revote ? "Revote tally" : "Vote tally",
      Object.entries(event.tally || {}).map(([name, n]) => `${name}: ${n}`).join(" · ")];
    case "revote_started": return ["Vote tied", `Revote among ${(event.tied || []).join(" and ")}`];
    case "eliminated": return [`${event.player} was eliminated`, `Round ${event.round}`];
    case "jury_voted": return [`${event.winner} won the jury vote`,
      Object.entries(event.count || {}).map(([name, n]) => `${name}: ${n}`).join(" · ")];
    case "controller_error": return [`${actor}'s agent command failed`, event.error || event.decision || "Fallback used"];
    case "controller_fallback": return [`${actor} used a safe fallback`, `Decision: ${event.decision}`];
    case "controller_action_rejected": return [`${actor}'s action was rejected`, event.error || "Safe fallback used"];
    default: return [event.type.replaceAll("_", " "), event.player || event.reason || ""];
  }
}

function badgeClass(type, event) {
  if (event.private || (Array.isArray(event.audience) && event.audience.length > 0)
      || ["deal_proposed", "deal_accepted", "deal_declined", "deal_evaluated"].includes(type))
    return "event-badge private";
  if (type.includes("vote") || type.includes("eliminated") || type === "jury_voted") return "event-badge vote";
  if (type.includes("deal")) return "event-badge deal";
  return "event-badge";
}

function renderEvents(game) {
  const feed = $("events");
  feed.replaceChildren();
  const relevant = (game.events || []).filter((event) => event.type !== "passed");
  const entries = relevant.slice(-80).reverse();
  if (!entries.length) {
    feed.append(el("div", "empty", "No events yet."));
    return;
  }
  for (const event of entries) {
    const row = el("div", "event");
    row.append(el("span", "event-time", `R${event.round || "—"} · ${String(event.seq || "").padStart(3, "0")}`));
    const body = el("div", "event-body");
    const [title, detail] = eventText(event);
    const titleNode = el("div", "event-title");
    titleNode.append(el("span", badgeClass(event.type, event), event.private ? "private" : event.type.split("_")[0]));
    titleNode.append(document.createTextNode(title));
    body.append(titleNode);
    if (detail) body.append(el("div", "event-detail", detail));
    row.append(body);
    feed.append(row);
  }
}

function renderPlayers(game) {
  const container = $("players");
  container.replaceChildren();
  const names = Object.keys(game.personalities || {});
  if (game.evaluated && !names.includes(game.evaluated)) names.unshift(game.evaluated);
  const alive = game.alive || names.filter((name) => !(game.eliminated_in_order || []).includes(name));
  const alliances = (game.alliances || []).filter((a) => a.status === "active");
  for (const name of names) {
    const card = el("div", `player-card${name === game.evaluated ? " me" : ""}${name === game.current_actor ? " turn" : ""}${alive.includes(name) ? "" : " out"}`);
    const top = el("div", "player-top");
    top.append(el("span", "player-name", name));
    top.append(el("span", `player-tag${alive.includes(name) ? "" : " out"}`, alive.includes(name) ? (name === game.evaluated ? "AGENT" : "ALIVE") : "OUT"));
    card.append(top);
    let detail = game.personalities?.[name] || (name === game.evaluated ? "evaluated seat" : "player");
    if (!alive.includes(name)) {
      const index = (game.eliminated_in_order || []).indexOf(name);
      detail += ` · eliminated ${index >= 0 ? `#${index + 1}` : ""}`;
    }
    card.append(el("div", "player-detail", detail));
    const traits = el("div", "player-traits");
    for (const alliance of alliances.filter((a) => a.members.includes(name))) traits.append(el("span", "trait", `alliance ${alliance.id}`));
    const goal = game.npc_private_state?.[name]?.goal;
    if (goal) traits.append(el("span", "trait", `private goal: ${goal.kind} ${goal.target}`));
    card.append(traits);
    container.append(card);
  }
}

function renderNpcState(game) {
  const container = $("npc-state");
  container.replaceChildren();
  for (const [name, info] of Object.entries(game.npc_private_state || {})) {
    const card = el("div", "npc-card");
    const heading = info.goal ? `${info.goal.kind} ${info.goal.target}` : "—";
    card.append(el("strong", "", `${name} · ${heading}`));
    const trust = info.trust || {};
    const trustLine = Object.entries(trust).map(([person, value]) => `${person} ${Number(value).toFixed(2)}`).join(" · ");
    card.append(el("div", "", `Reservation slack: ${Number(info.reservation_slack || 0).toFixed(2)}\nTrust: ${trustLine}`));
    container.append(card);
  }
  if (!container.children.length) container.append(el("div", "empty", "No NPC private-state telemetry in this snapshot."));
}

function renderGame(game, run) {
  state.lastGame = game;
  $("empty-state").classList.add("hidden");
  $("game-view").classList.remove("hidden");
  $("game-source").textContent = `${run.source.toUpperCase()} GAME${run.status === "running" ? " · LIVE" : " · SAVED"}`;
  $("game-name").textContent = run.model || run.title;
  const actor = game.current_actor ? ` · acting: ${game.current_actor}` : "";
  $("game-subline").textContent = `Seed ${game.seed ?? run.seed ?? "—"}${actor} · ${run.title}`;
  $("phase-label").textContent = game.phase || (game.terminal ? "finished" : "unknown");
  $("round-label").textContent = `ROUND ${game.round ?? "—"}`;
  $("alive-stat").textContent = String((game.alive || []).length || 0);
  const deals = game.deals || [];
  const accepted = deals.filter((deal) => deal.status === "accepted").length;
  $("deal-stat").textContent = `${accepted} / ${deals.length}`;
  $("reward-stat").textContent = game.terminal ? formatReward(game.reward) : "—";
  $("winner-stat").textContent = game.winner || "—";
  renderPlayers(game);
  renderEvents(game);
  renderNpcState(game);
}

async function loadGame() {
  const run = state.runs.find((item) => item.id === state.selected);
  if (!run) return;
  try {
    const response = await fetch(`/api/game?id=${encodeURIComponent(run.id)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("snapshot not found");
    renderGame(await response.json(), run);
  } catch {
    $("empty-state").classList.remove("hidden");
    $("game-view").classList.add("hidden");
  }
}

async function refresh() {
  if (state.paused) return;
  try {
    const response = await fetch("/api/runs", { cache: "no-store" });
    if (!response.ok) throw new Error("dashboard API unavailable");
    state.runs = await response.json();
    $("connection-label").textContent = "Connected";
    $("connection-label").previousElementSibling.classList.remove("off");
    $("updated-label").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    if (!state.runs.some((run) => run.id === state.selected)) {
      state.selected = (state.runs.find((run) => run.status === "running") || state.runs[0] || {}).id || null;
    }
    renderRuns();
    await loadGame();
  } catch {
    $("connection-label").textContent = "Offline";
    $("connection-label").previousElementSibling.classList.add("off");
  }
}

document.querySelectorAll(".filter").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".filter").forEach((other) => other.classList.remove("active"));
  button.classList.add("active");
  state.filter = button.dataset.filter;
  renderRuns();
}));
$("pause-button").addEventListener("click", () => {
  state.paused = !state.paused;
  $("pause-button").textContent = state.paused ? "Resume updates" : "Pause updates";
  if (!state.paused) refresh();
});
$("scroll-latest").addEventListener("click", () => { $("events").scrollTop = 0; });
refresh();
setInterval(refresh, 1000);
