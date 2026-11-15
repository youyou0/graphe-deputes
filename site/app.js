/* Graphe des députés : liens deputé ↔ organe, à partir de data.json. */
(() => {
  "use strict";

  const KIND_ORDER = ["GP", "COMPER", "GE", "GA", "MISINFO", "DELEG", "OFFPAR", "ORGEXTPARL", "API", "PARPOL"];
  const KIND_PLURAL = {
    GP: "Groupes politiques",
    COMPER: "Commissions permanentes",
    GE: "Groupes d'études",
    GA: "Groupes d'amitié",
    MISINFO: "Missions d'information",
    DELEG: "Délégations",
    OFFPAR: "Offices parlementaires",
    ORGEXTPARL: "Organismes extérieurs",
    API: "Assemblées internationales",
    PARPOL: "Partis politiques",
    HV_DIR: "Fonctions dirigeantes",
    HV_PART: "Participations financières",
    HV_EMP: "Employeurs (5 dernières années)",
    HV_CONS: "Activités de conseil",
    HV_BEN: "Fonctions bénévoles",
  };
  // Liens issus des déclarations d'intérêts HATVP.
  const HV_ORDER = ["HV_DIR", "HV_PART", "HV_EMP", "HV_CONS", "HV_BEN"];
  const HV_SINGULAR = {
    HV_DIR: "Fonction dirigeante",
    HV_PART: "Participation financière",
    HV_EMP: "Employeur",
    HV_CONS: "Activité de conseil",
    HV_BEN: "Fonction bénévole",
  };
  const DEFAULT_KINDS = new Set(["GP", "COMPER", "HV_DIR", "HV_PART", "HV_EMP"]);
  // Organes trop larges pour signifier une proximité entre deux députés.
  const NOT_PROXIMITY = new Set(["GP", "PARPOL"]);
  const NEUTRAL = "#8a8f98";
  const HV_COLOR = "#d9a441";
  const isHv = (n) => n.kind === "HATVP";

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const norm = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const plural = (n, one, many) => `${n.toLocaleString("fr-FR")} ${n > 1 ? many : one}`;

  const state = {
    kinds: new Set(DEFAULT_KINDS),
    groups: new Set(),
    selected: null,
    hover: null,
    // Structures HATVP citées par un seul député : masquées par défaut (bruit).
    singles: false,
  };

  let fitted = false;
  let graph, nodesById, deputes, organes, allLinks, groupsById, neighbors;

  fetch("data.json")
    .then((r) => r.json())
    .then(init)
    .catch(() => { $("#loading").textContent = "Impossible de charger data.json. Lancez le site via un serveur local."; });

  function init(data) {
    $("#genDate").textContent = new Date(data.generated).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });

    groupsById = new Map();
    organes = data.organes.map((o) => ({ ...o, type: "org", members: [] }));
    organes.filter((o) => o.kind === "GP").forEach((g) => groupsById.set(g.id, g));
    deputes = data.deputes.map((d) => ({ ...d, type: "dep", orgs: [] }));
    nodesById = new Map([...deputes, ...organes].map((n) => [n.id, n]));

    allLinks = [];
    for (const l of data.links) {
      const d = nodesById.get(l.source), o = nodesById.get(l.target);
      if (!d || !o) continue;
      // « Présidente du », « Membre de la » : on retire l'article final.
      const role = (l.role || "").replace(/\s+(du|de la|de l'|des|de)$/i, "");
      const link = { source: d, target: o, role, kind: l.kind || o.kind };
      d.orgs.push(link);
      o.members.push(link);
      allLinks.push(link);
    }
    for (const d of deputes) d.color = groupsById.get(d.groupe)?.couleur || NEUTRAL;
    // Nombre de députés distincts (un député peut citer une structure à deux titres).
    for (const o of organes) o.size = new Set(o.members.map((l) => l.source)).size;
    $("#hvCount").textContent = data.hatvp?.declarants ?? 0;
    groupsById.forEach((g) => state.groups.add(g.id));

    buildSidebar();
    buildGraph();
    bindPalette();
    $("#panelClose").addEventListener("click", () => select(null));
    $("#zoomFit").addEventListener("click", () => graph.zoomToFit(600, 60));
    window.addEventListener("hashchange", fromHash);
    $("#loading").remove();
    fromHash();
  }

  /* ---------- Sidebar ---------- */

  const CHECK = '<svg viewBox="0 0 12 12"><path d="m2.5 6.2 2.3 2.3 4.7-5"/></svg>';

  function buildSidebar() {
    const kindCounts = {};
    organes.forEach((o) => { kindCounts[o.kind] = (kindCounts[o.kind] || 0) + 1; });

    // Pour la HATVP, le compteur suit ce que montre le graphe (structures partagées ou toutes).
    HV_ORDER.forEach((k) => { kindCounts[k] = hvCount(k); });

    const toggle = (k) => `
      <button class="toggle" type="button" data-kind="${k}" aria-pressed="${state.kinds.has(k)}">
        <span class="t-check">${CHECK}</span>
        <span class="t-label">${esc(KIND_PLURAL[k])}</span>
        <span class="t-count">${kindCounts[k]}</span>
      </button>`;
    $("#kindList").innerHTML = KIND_ORDER.filter((k) => kindCounts[k]).map(toggle).join("");
    $("#hvList").innerHTML = HV_ORDER.filter((k) => kindCounts[k]).map(toggle).join("") + `
      <button class="toggle toggle-sub" type="button" id="singlesToggle" aria-pressed="${state.singles}">
        <span class="t-check">${CHECK}</span>
        <span class="t-label">Structures citées une seule fois</span>
      </button>`;
    const onKind = (e) => {
      if (e.target.closest("#singlesToggle")) {
        state.singles = !state.singles;
        syncHvCounts();
        refresh();
        return;
      }
      const b = e.target.closest("[data-kind]");
      if (!b) return;
      toggleSet(state.kinds, b.dataset.kind);
      b.setAttribute("aria-pressed", state.kinds.has(b.dataset.kind));
      refresh();
    };
    $("#kindList").addEventListener("click", onKind);
    $("#hvList").addEventListener("click", onKind);

    const groups = [...groupsById.values()]
      .map((g) => ({ g, n: deputes.filter((d) => d.groupe === g.id).length }))
      .sort((a, b) => b.n - a.n);
    $("#groupList").innerHTML = groups.map(({ g, n }) => `
      <button class="toggle" type="button" data-group="${g.id}" aria-pressed="true" title="${esc(g.libelle)}">
        <span class="t-swatch" style="background:${g.couleur || NEUTRAL}"></span>
        <span class="t-label">${esc(g.libelle)}</span>
        <span class="t-count">${n}</span>
      </button>`).join("");
    $("#groupList").addEventListener("click", (e) => {
      const b = e.target.closest("[data-group]");
      if (!b) return;
      // Premier clic quand tout est affiché : on isole ce groupe.
      if (state.groups.size === groupsById.size) state.groups = new Set([b.dataset.group]);
      else toggleSet(state.groups, b.dataset.group);
      if (state.groups.size === 0) groupsById.forEach((g) => state.groups.add(g.id));
      syncGroupButtons();
      refresh();
    });
    $("#groupsAll").addEventListener("click", () => {
      groupsById.forEach((g) => state.groups.add(g.id));
      syncGroupButtons();
      refresh();
    });
  }

  function hvCount(kind) {
    const targets = new Set(allLinks.filter((l) => l.kind === kind).map((l) => l.target));
    return [...targets].filter((o) => state.singles || o.size > 1).length;
  }

  function syncHvCounts() {
    $("#singlesToggle").setAttribute("aria-pressed", state.singles);
    HV_ORDER.forEach((k) => {
      const c = document.querySelector(`[data-kind="${k}"] .t-count`);
      if (c) c.textContent = hvCount(k);
    });
  }

  function syncGroupButtons() {
    document.querySelectorAll("[data-group]").forEach((b) => b.setAttribute("aria-pressed", state.groups.has(b.dataset.group)));
  }

  function toggleSet(set, v) { set.has(v) ? set.delete(v) : set.add(v); }

  /* ---------- Graphe ---------- */

  function visibleData() {
    const deps = deputes.filter((d) => state.groups.has(d.groupe) || (!d.groupe && state.groups.size === groupsById.size));
    const depSet = new Set(deps);
    const links = allLinks.filter((l) =>
      state.kinds.has(l.kind) && depSet.has(l.source) && (state.singles || !isHv(l.target) || l.target.size > 1));
    const orgSet = new Set(links.map((l) => l.target));
    return { nodes: [...deps, ...orgSet], links };
  }

  function computeNeighbors(links) {
    neighbors = new Map();
    const add = (a, b) => { if (!neighbors.has(a)) neighbors.set(a, new Set()); neighbors.get(a).add(b); };
    links.forEach((l) => { add(l.source, l.target); add(l.target, l.source); });
  }

  function orgRadius(o) { return 3 + Math.sqrt(o.size) * 1.15; }

  function buildGraph() {
    const el = $("#graph");
    const data = visibleData();
    computeNeighbors(data.links);

    graph = ForceGraph()(el)
      .backgroundColor("rgba(0,0,0,0)")
      .graphData(data)
      .nodeId("id")
      .nodeRelSize(1)
      .nodeVal((n) => (n.type === "org" ? orgRadius(n) ** 2 : 12))
      .nodeCanvasObject(drawNode)
      .nodePointerAreaPaint(paintArea)
      .linkColor(linkColor)
      .linkWidth((l) => (isFocusLink(l) ? 1.2 : 0.5))
      .linkDirectionalParticles(0)
      .cooldownTicks(220)
      .d3VelocityDecay(0.3)
      .onNodeHover(onHover)
      .onNodeClick((n) => select(n))
      .onBackgroundClick(() => select(null))
      .onEngineStop(() => {
        if (fitted) return;
        fitted = true;
        // Si un nœud est sélectionné (lien partagé, recherche), on reste centré dessus.
        if (state.selected) focusOn(state.selected);
        else graph.zoomToFit(500, 60);
      });

    graph.d3Force("charge").strength((n) => (n.type === "org" ? -60 - n.size * 1.5 : -14)).distanceMax(400);
    graph.d3Force("link").distance((l) => (l.kind === "GP" ? 26 : 60)).strength((l) => (l.kind === "GP" ? 0.5 : 0.04));

    window.__graph = graph; // pratique pour déboguer dans la console
    const ro = new ResizeObserver(() => graph.width(el.clientWidth).height(el.clientHeight));
    ro.observe(el);
    updateStats(data);
  }

  function refresh() {
    const data = visibleData();
    computeNeighbors(data.links);
    graph.graphData(data);
    fitted = false;
    graph.d3ReheatSimulation();
    updateStats(data);
    if (state.selected && !data.nodes.includes(state.selected)) select(null);
  }

  function updateStats(data) {
    const nd = data.nodes.filter((n) => n.type === "dep").length;
    const nh = data.nodes.filter((n) => n.type === "org" && isHv(n)).length;
    const no = data.nodes.length - nd - nh;
    $("#stats").innerHTML = `<span><b>${nd}</b> députés</span><span><b>${no}</b> organes</span>`
      + (nh ? `<span><b>${nh}</b> structures déclarées</span>` : "")
      + `<span><b>${data.links.length.toLocaleString("fr-FR")}</b> liens</span>`;
  }

  function focusNode() { return state.hover || state.selected; }
  function isFocusLink(l) { const f = focusNode(); return f && (l.source === f || l.target === f); }
  function isDimmed(n) {
    const f = focusNode();
    return f && n !== f && !neighbors.get(f)?.has(n);
  }

  function linkColor(l) {
    const f = focusNode();
    if (!f) return isHv(l.target) ? "rgba(217,164,65,0.13)" : "rgba(255,255,255,0.055)";
    return isFocusLink(l) ? "rgba(140,150,235,0.65)" : "rgba(255,255,255,0.02)";
  }

  function drawNode(n, ctx, scale) {
    const dim = isDimmed(n);
    const focus = n === focusNode();
    ctx.globalAlpha = dim ? 0.12 : 1;

    if (n.type === "dep") {
      const r = focus ? 5 : 3.2;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = n.color;
      ctx.fill();
      if (focus || n === state.selected) {
        ctx.lineWidth = 1.5 / scale;
        ctx.strokeStyle = "#f7f8f8";
        ctx.stroke();
      }
      if (!dim && (scale > 3.2 || focus || (focusNode() && focusNode().type === "org" && scale > 1.6))) {
        label(ctx, `${n.prenom} ${n.nom}`, n.x, n.y + r + 2, scale, focus ? "#f7f8f8" : "#b4b8bf", 10);
      }
    } else {
      const r = orgRadius(n);
      const color = n.kind === "GP" ? n.couleur || NEUTRAL : isHv(n) ? HV_COLOR : NEUTRAL;
      if (isHv(n)) diamond(ctx, n.x, n.y, r * 1.2);
      else roundRect(ctx, n.x - r, n.y - r, r * 2, r * 2, Math.min(r * 0.35, 4));
      ctx.fillStyle = "#0f1011";
      ctx.fill();
      ctx.lineWidth = (focus ? 2.4 : 1.5);
      ctx.strokeStyle = focus ? "#f7f8f8" : color;
      ctx.stroke();
      const show = !dim && (focus || n.kind === "GP" || scale > 1.3 || (focusNode() && neighbors.get(focusNode())?.has(n)));
      if (show) label(ctx, n.abrev && n.kind === "GP" ? n.abrev : shortOrg(n), n.x, n.y + r + 2.5, scale, focus ? "#f7f8f8" : "#d0d3d8", n.kind === "GP" ? 12 : 11);
    }
    ctx.globalAlpha = 1;
  }

  function label(ctx, text, x, y, scale, color, px) {
    const size = px / Math.max(scale, 0.6);
    ctx.font = `500 ${size}px Inter, system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.lineWidth = 3 / scale;
    ctx.strokeStyle = "rgba(15,16,17,0.9)";
    ctx.strokeText(text, x, y);
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
  }

  function diamond(ctx, x, y, r) {
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r, y);
    ctx.lineTo(x, y + r);
    ctx.lineTo(x - r, y);
    ctx.closePath();
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function paintArea(n, color, ctx) {
    const r = n.type === "org" ? orgRadius(n) + 1 : 5;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
    ctx.fill();
  }

  function shortOrg(o) {
    const s = o.libelle
      .replace(/^Commission (des |de la |de l'|du )?/i, "")
      .replace(/^Groupe d'études ?:? ?/i, "")
      .replace(/^Groupe d'amitié France-/i, "France-");
    return s.length > 38 ? s.slice(0, 36) + "…" : s;
  }

  /* ---------- Survol et sélection ---------- */

  const tooltip = $("#tooltip");
  function onHover(n) {
    state.hover = n || null;
    $("#graph").style.cursor = n ? "pointer" : "";
    if (!n) { tooltip.hidden = true; return; }
    const sub = n.type === "dep"
      ? `${groupsById.get(n.groupe)?.abrev || "Sans groupe"}, ${n.dep || ""}${n.circo ? ` (${n.circo}e circ.)` : ""}`
      : isHv(n)
        ? `Déclarations HATVP, ${plural(n.size, "député", "députés")}`
        : `${KIND_PLURAL[n.kind].replace(/s$/, "").replace(/s /, " ")}, ${plural(n.size, "membre", "membres")}`;
    tooltip.innerHTML = `<div>${esc(n.type === "dep" ? `${n.prenom} ${n.nom}` : n.libelle)}</div><div class="tt-sub">${esc(sub)}</div>`;
    tooltip.hidden = false;
  }
  $("#graph").addEventListener("pointermove", (e) => {
    if (tooltip.hidden) return;
    const box = $(".stage").getBoundingClientRect();
    const x = Math.min(e.clientX - box.left + 14, box.width - tooltip.offsetWidth - 8);
    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${e.clientY - box.top + 14}px`;
  });

  function select(n, { center = true } = {}) {
    state.selected = n || null;
    const panel = $("#panel");
    if (!n) {
      panel.hidden = true;
      if (location.hash) history.replaceState(null, "", location.pathname);
      return;
    }
    if (location.hash.slice(1) !== n.id) history.replaceState(null, "", `#${n.id}`);
    $("#panelBody").innerHTML = n.type === "dep" ? depPanel(n) : orgPanel(n);
    panel.hidden = false;
    panel.scrollTop = 0;
    // Sans position encore calculée, onEngineStop s'en chargera.
    if (center && n.x != null) focusOn(n);
  }

  function focusOn(n) {
    graph.centerAt(n.x, n.y, 600);
    if (graph.zoom() < 2) graph.zoom(n.type === "org" ? 2 : 2.6, 600);
  }

  function fromHash() {
    const id = decodeURIComponent(location.hash.slice(1));
    const n = id && nodesById.get(id);
    if (!n) return;
    ensureVisible(n);
    // Laisse la simulation placer le nœud avant de centrer.
    select(n);
  }

  function ensureVisible(n) {
    let changed = false;
    if (n.type === "org" && isHv(n)) {
      // Une structure HATVP est visible si au moins un de ses types de lien l'est.
      const kinds = new Set(n.members.map((l) => l.kind));
      if (![...kinds].some((k) => state.kinds.has(k))) {
        kinds.forEach((k) => {
          state.kinds.add(k);
          document.querySelector(`[data-kind="${k}"]`)?.setAttribute("aria-pressed", "true");
        });
        changed = true;
      }
      if (n.size < 2 && !state.singles) {
        state.singles = true;
        syncHvCounts();
        changed = true;
      }
    } else if (n.type === "org" && !state.kinds.has(n.kind)) {
      state.kinds.add(n.kind);
      document.querySelector(`[data-kind="${n.kind}"]`)?.setAttribute("aria-pressed", "true");
      changed = true;
    }
    if (n.type === "dep" && n.groupe && !state.groups.has(n.groupe)) {
      state.groups.add(n.groupe);
      syncGroupButtons();
      changed = true;
    }
    if (changed) refresh();
  }

  $("#panelBody").addEventListener("click", (e) => {
    const t = e.target.closest("[data-go]");
    if (t) {
      const n = nodesById.get(t.dataset.go);
      ensureVisible(n);
      select(n);
      return;
    }
    const more = e.target.closest("[data-more]");
    if (more) {
      more.previousElementSibling.querySelectorAll("[hidden]").forEach((li) => (li.hidden = false));
      more.remove();
    }
  });

  /* ---------- Fiches ---------- */

  const EXT = '<svg viewBox="0 0 12 12"><path d="M5 2H2v8h8V7M7 2h3v3M10 2 5.5 6.5"/></svg>';

  function initials(d) { return (d.prenom[0] || "") + (d.nom.replace(/^(de |d'|le |la )/i, "")[0] || ""); }
  function age(iso) {
    if (!iso) return null;
    const b = new Date(iso), now = new Date();
    return now.getFullYear() - b.getFullYear() - (now < new Date(now.getFullYear(), b.getMonth(), b.getDate()) ? 1 : 0);
  }
  function fmtDate(iso) { return iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "—"; }
  function isMemberRole(r) { return !r || /^membre/i.test(r); }

  function depPanel(d) {
    const g = groupsById.get(d.groupe);
    const num = d.id.replace(/^PA/, "");
    const a = age(d.naissance);
    const byKind = new Map();
    d.orgs.filter((l) => l.kind !== "GP").forEach((l) => {
      if (!byKind.has(l.kind)) byKind.set(l.kind, []);
      byKind.get(l.kind).push(l);
    });

    const roles = d.orgs.filter((l) => !isHv(l.target) && !isMemberRole(l.role));
    // Un seul organe en commun ne dit rien de particulier : on n'affiche que 2 et plus.
    const close = closest(d, 8).filter(({ c }) => c >= 2);

    let html = `
      <div class="p-head">
        <div class="p-id">
          <div class="avatar" style="border-color:${d.color}">
            <img src="https://www.assemblee-nationale.fr/dyn/static/tribun/17/photos/carre/${num}.jpg" alt="" loading="lazy" onerror="this.replaceWith(document.createTextNode('${esc(initials(d))}'))">
          </div>
          <div>
            <h2 class="p-title">${esc(d.prenom)} ${esc(d.nom)}</h2>
            <p class="p-kind">Député${d.civ === "Mme" ? "e" : ""} ${d.dep ? `de ${esc(d.dep)}` : ""}${d.circo ? `, ${d.circo}e circonscription` : ""}</p>
          </div>
        </div>
        ${g ? `<button class="chip" type="button" data-go="${g.id}"><i style="background:${g.couleur}"></i>${esc(g.libelle)}</button>` : `<span class="chip">Sans groupe</span>`}
        <dl class="facts">
          ${d.profession ? `<dt>Profession</dt><dd>${esc(d.profession)}</dd>` : ""}
          ${a ? `<dt>Âge</dt><dd>${a} ans</dd>` : ""}
          <dt>Mandat depuis le</dt><dd>${fmtDate(d.debut)}</dd>
          ${d.region ? `<dt>Région</dt><dd>${esc(d.region)}</dd>` : ""}
        </dl>
      </div>`;

    if (roles.length) {
      html += section("Fonctions", roles.length, `<ul class="rows">${roles.map((l) => orgRow(l.target, l.role)).join("")}</ul>`);
    }

    if (close.length) {
      html += section("Députés les plus proches", null,
        `<p class="p-note">Nombre d'organes partagés, hors groupe et parti.</p>
         <ul class="rows">${close.map(({ n, c }) => `
           <li><button class="row" type="button" data-go="${n.id}">
             <span class="r-dot" style="background:${n.color}"></span>
             <span class="r-main"><span class="r-name">${esc(n.prenom)} ${esc(n.nom)}</span></span>
             <span class="bar"><i style="width:${(c / close[0].c) * 100}%"></i></span>
             <span class="r-meta">${c}</span>
           </button></li>`).join("")}</ul>`);
    }

    for (const k of KIND_ORDER) {
      const ls = byKind.get(k);
      if (!ls) continue;
      html += section(KIND_PLURAL[k], ls.length, list(ls.map((l) => orgRow(l.target, isMemberRole(l.role) ? null : l.role)), 6));
    }

    html += hatvpSection(d);

    html += `<div class="p-section"><a class="ext-link" href="https://www.assemblee-nationale.fr/dyn/deputes/${d.id}" target="_blank" rel="noopener">Fiche officielle sur assemblee-nationale.fr ${EXT}</a></div>`;
    return html;
  }

  const MASKED_LABEL = {
    HV_DIR: ["fonction dirigeante non nommée", "fonctions dirigeantes non nommées"],
    HV_PART: ["participation non nommée", "participations non nommées"],
    HV_EMP: ["employeur non nommé", "employeurs non nommés"],
    HV_CONS: ["activité de conseil non nommée", "activités de conseil non nommées"],
    HV_BEN: ["fonction bénévole non nommée", "fonctions bénévoles non nommées"],
  };

  function hatvpSection(d) {
    const title = "Déclaration d'intérêts (HATVP)";
    if (!d.hatvp) {
      return section(title, null, `<p class="p-note">Aucune déclaration de député publiée n'a été rattachée à cette fiche.</p>`);
    }
    const links = d.orgs.filter((l) => isHv(l.target));
    let body = `<p class="p-note">Déposée le ${esc(d.hatvp.depot)}. Structures et fonctions telles que déclarées.</p>`;
    if (!links.length) body += `<p class="p-note">Aucune structure nommée dans les rubriques retenues.</p>`;
    for (const k of HV_ORDER) {
      const ls = links.filter((l) => l.kind === k);
      const masked = d.hatvp.masquees?.[k] || 0;
      if (!ls.length && !masked) continue;
      body += `<h4 class="p-sub">${esc(KIND_PLURAL[k])}<span>${ls.length + masked}</span></h4>`;
      if (ls.length) {
        body += list(ls.map((l) => `
          <li><button class="row" type="button" data-go="${l.target.id}">
            <span class="r-main"><span class="r-name">${esc(l.target.libelle)}</span>
            ${l.role ? `<span class="r-sub">${esc(l.role)}</span>` : ""}</span>
            ${l.target.size > 1 ? `<span class="r-meta">${plural(l.target.size, "député", "députés")}</span>` : ""}
          </button></li>`), 5);
      }
      if (masked) body += `<p class="p-note p-masked">+ ${masked} ${MASKED_LABEL[k][masked > 1 ? 1 : 0]} (nom non publié par la HATVP)</p>`;
    }
    if (d.hatvp.page) {
      body += `<a class="ext-link" href="${esc(d.hatvp.page)}" target="_blank" rel="noopener">Déclaration complète sur hatvp.fr ${EXT}</a>`;
    }
    return section(title, null, body);
  }

  function hvPanel(o) {
    // Un député peut citer la même structure à plusieurs titres : on regroupe.
    const byDep = new Map();
    o.members.forEach((l) => {
      if (!byDep.has(l.source)) byDep.set(l.source, []);
      byDep.get(l.source).push(l);
    });
    const deps = [...byDep.entries()].sort((a, b) => a[0].nom.localeCompare(b[0].nom, "fr"));
    const comp = new Map();
    deps.forEach(([d]) => comp.set(d.groupe, (comp.get(d.groupe) || 0) + 1));
    const compSorted = [...comp.entries()].sort((a, b) => b[1] - a[1]);

    let html = `
      <div class="p-head">
        <div class="p-id">
          <div class="org-mark hv-mark">
            <svg viewBox="0 0 16 16"><path d="M8 2.5 13.5 8 8 13.5 2.5 8Z"/></svg>
          </div>
          <div>
            <h2 class="p-title">${esc(o.libelle)}</h2>
            <p class="p-kind">Citée dans ${plural(deps.length, "déclaration", "déclarations")} d'intérêts</p>
          </div>
        </div>
        <p class="p-note p-disclaimer">Lien déclaré par le député à la HATVP. Il n'indique ni conflit d'intérêts ni prise de position.</p>
      </div>`;
    if (deps.length > 1) {
      html += section("Groupes politiques", null, `<div class="composition">${compSorted.map(([gid, n]) =>
        `<i style="flex:${n};background:${groupsById.get(gid)?.couleur || NEUTRAL}" title="${esc(groupsById.get(gid)?.abrev || "Sans groupe")} : ${n}"></i>`).join("")}</div>`);
    }
    html += section("Députés", deps.length, list(deps.map(([d, ls]) => `
      <li><button class="row" type="button" data-go="${d.id}">
        <span class="r-dot" style="background:${d.color}"></span>
        <span class="r-main"><span class="r-name">${esc(d.prenom)} ${esc(d.nom)}</span>
        <span class="r-sub">${esc(ls.map((l) => HV_SINGULAR[l.kind] + (l.role ? ` : ${l.role}` : "")).join(" ; "))}</span></span>
      </button></li>`), 25));
    return html;
  }

  function orgPanel(o) {
    if (isHv(o)) return hvPanel(o);
    const members = [...o.members].sort((a, b) =>
      (isMemberRole(a.role) - isMemberRole(b.role)) || a.source.nom.localeCompare(b.source.nom, "fr"));
    const comp = new Map();
    members.forEach((l) => comp.set(l.source.groupe, (comp.get(l.source.groupe) || 0) + 1));
    const compSorted = [...comp.entries()].sort((a, b) => b[1] - a[1]);
    const total = members.length;

    const compBar = `<div class="composition">${compSorted.map(([gid, n]) =>
      `<i style="flex:${n};background:${groupsById.get(gid)?.couleur || NEUTRAL}" title="${esc(groupsById.get(gid)?.abrev || "Sans groupe")} : ${n}"></i>`).join("")}</div>`;
    const compRows = compSorted.map(([gid, n]) => {
      const g = groupsById.get(gid);
      return `<li><button class="row" type="button" ${g ? `data-go="${g.id}"` : "disabled"}>
        <span class="r-dot" style="background:${g?.couleur || NEUTRAL}"></span>
        <span class="r-main"><span class="r-name">${esc(g?.libelle || "Sans groupe")}</span></span>
        <span class="r-meta">${n} (${Math.round((n / total) * 100)} %)</span>
      </button></li>`;
    });

    const singular = KIND_PLURAL[o.kind].replace(/^(\S+?)s\b/, "$1").replace(/ (\S+?)s$/, " $1");
    let html = `
      <div class="p-head">
        <div class="p-id">
          <div class="org-mark" style="border-color:${o.kind === "GP" ? o.couleur : "var(--border-strong)"}">
            <svg viewBox="0 0 16 16"><circle cx="5" cy="5" r="1.6"/><circle cx="11" cy="5" r="1.6"/><circle cx="5" cy="11" r="1.6"/><circle cx="11" cy="11" r="1.6"/></svg>
          </div>
          <div>
            <h2 class="p-title">${esc(o.libelle)}</h2>
            <p class="p-kind">${esc(singular)}, ${plural(total, "membre", "membres")}</p>
          </div>
        </div>
      </div>`;
    if (o.kind !== "GP") html += section("Composition", null, compBar + list(compRows, 6));
    html += section("Membres", total, list(members.map((l) => `
      <li><button class="row" type="button" data-go="${l.source.id}">
        <span class="r-dot" style="background:${l.source.color}"></span>
        <span class="r-main"><span class="r-name">${esc(l.source.prenom)} ${esc(l.source.nom)}</span>
        ${l.source.dep ? `<span class="r-sub">${esc(l.source.dep)}</span>` : ""}</span>
        ${isMemberRole(l.role) ? "" : `<span class="r-role">${esc(l.role)}</span>`}
      </button></li>`), 25));
    return html;
  }

  function orgRow(o, role) {
    return `<li><button class="row" type="button" data-go="${o.id}">
      <span class="r-main"><span class="r-name">${esc(o.libelle)}</span>
      ${role === undefined ? "" : ""}</span>
      ${role ? `<span class="r-role">${esc(role)}</span>` : `<span class="r-meta">${o.size}</span>`}
    </button></li>`;
  }

  function section(title, count, body) {
    return `<div class="p-section"><h3>${esc(title)}${count != null ? `<span>${count}</span>` : ""}</h3>${body}</div>`;
  }

  function list(items, max) {
    const lis = items.map((li, i) => (i >= max ? li.replace("<li>", "<li hidden>") : li)).join("");
    const more = items.length > max ? `<button class="link-btn more-btn" type="button" data-more>Afficher les ${items.length - max} autres</button>` : "";
    return `<ul class="rows">${lis}</ul>${more}`;
  }

  function closest(d, k) {
    const counts = new Map();
    for (const l of d.orgs) {
      // La proximité reste celle de l'Assemblée : les liens HATVP ont leur propre section.
      if (NOT_PROXIMITY.has(l.kind) || isHv(l.target)) continue;
      for (const m of l.target.members) {
        if (m.source !== d) counts.set(m.source, (counts.get(m.source) || 0) + 1);
      }
    }
    return [...counts.entries()]
      .map(([n, c]) => ({ n, c }))
      .sort((a, b) => b.c - a.c || a.n.nom.localeCompare(b.n.nom, "fr"))
      .slice(0, k);
  }

  /* ---------- Recherche (Ctrl K) ---------- */

  function bindPalette() {
    const back = $("#palette"), input = $("#paletteInput"), ul = $("#paletteResults");
    let results = [], idx = 0;

    const index = [
      ...deputes.map((d) => ({ n: d, key: norm(`${d.prenom} ${d.nom} ${d.dep || ""} ${d.numDep || ""}`) })),
      ...organes.map((o) => ({ n: o, key: norm(`${o.libelle} ${o.abrev || ""}`) })),
    ];

    const open = () => { back.hidden = false; input.value = ""; render(); input.focus(); };
    const close = () => { back.hidden = true; };

    function render() {
      const q = norm(input.value.trim());
      const terms = q.split(/\s+/).filter(Boolean);
      const hits = terms.length ? index.filter((e) => terms.every((t) => e.key.includes(t))) : [];
      const deps = hits.filter((e) => e.n.type === "dep").slice(0, 8).map((e) => e.n);
      const orgs = hits.filter((e) => e.n.type === "org").sort((a, b) => b.n.size - a.n.size).slice(0, 6).map((e) => e.n);
      results = [...deps, ...orgs];
      idx = 0;
      if (!terms.length) { ul.innerHTML = `<li class="palette-empty">Tapez un nom, un département ou un organe.</li>`; return; }
      if (!results.length) { ul.innerHTML = `<li class="palette-empty">Aucun résultat pour « ${esc(input.value)} ».</li>`; return; }
      let html = "", i = 0;
      if (deps.length) html += `<li class="pr-group">Députés</li>` + deps.map((d) => `
        <li role="option" data-i="${i++}"><span class="pr-dot" style="background:${d.color}"></span>
        <span class="pr-name">${esc(d.prenom)} ${esc(d.nom)}</span><span class="pr-sub">${esc(groupsById.get(d.groupe)?.abrev || "")}, ${esc(d.dep || "")}</span></li>`).join("");
      if (orgs.length) html += `<li class="pr-group">Organes et structures</li>` + orgs.map((o) => `
        <li role="option" data-i="${i++}"><span class="${isHv(o) ? "pr-dia" : "pr-sq"}"></span>
        <span class="pr-name">${esc(o.libelle)}</span><span class="pr-sub">${isHv(o) ? `HATVP, ${plural(o.size, "député", "députés")}` : plural(o.size, "membre", "membres")}</span></li>`).join("");
      ul.innerHTML = html;
      mark();
    }
    function mark() {
      ul.querySelectorAll("[data-i]").forEach((li) => li.setAttribute("aria-selected", +li.dataset.i === idx));
      ul.querySelector(`[data-i="${idx}"]`)?.scrollIntoView({ block: "nearest" });
    }
    function choose(i) {
      const n = results[i];
      if (!n) return;
      close();
      ensureVisible(n);
      select(n);
    }

    $("#searchTrigger").addEventListener("click", open);
    input.addEventListener("input", render);
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { idx = Math.min(idx + 1, results.length - 1); mark(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { idx = Math.max(idx - 1, 0); mark(); e.preventDefault(); }
      else if (e.key === "Enter") choose(idx);
      else if (e.key === "Escape") close();
    });
    ul.addEventListener("click", (e) => { const li = e.target.closest("[data-i]"); if (li) choose(+li.dataset.i); });
    ul.addEventListener("mousemove", (e) => { const li = e.target.closest("[data-i]"); if (li && +li.dataset.i !== idx) { idx = +li.dataset.i; mark(); } });
    back.addEventListener("click", (e) => { if (e.target === back) close(); });
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); back.hidden ? open() : close(); }
      else if (e.key === "/" && back.hidden && document.activeElement === document.body) { e.preventDefault(); open(); }
      else if (e.key === "Escape" && back.hidden && state.selected) select(null);
    });
  }
})();
