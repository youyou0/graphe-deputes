/* Sujets débattus en séance : carte en bulles, liste, sujets émergents, thèmes suivis, textes.
   Données : sujets.json.gz (scripts/sujets/run.py). Chargées à la première visite de la section.
   Interface pour app.js : window.Sujets = { load, show, hide, search, forDepute }. */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const norm = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  const fmtM = (m) => `${MOIS[+m.slice(5) - 1]} ${m.slice(0, 4)}`;
  const fmtMs = (m) => `${MOIS[+m.slice(5) - 1]} ${m.slice(2, 4)}`;
  const fmtD = (d) => new Date(d).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
  const nf = (n) => n.toLocaleString("fr-FR");
  const words = (c) => Math.round(c / 6); // ~6 caractères par mot en français, espace compris
  const CR = (s, a) => `https://www.assemblee-nationale.fr/dyn/17/comptes-rendus/seance/${s}#${a}`;
  const EXT = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M5 2H2v8h8V7M7 2h3v3M10 2 5.5 6.5"/></svg>';
  const TABS = [["carte", "Carte"], ["liste", "Liste"], ["emergents", "Émergents"], ["themes", "Thème suivi"], ["textes", "Textes de loi"]];
  const FAMS = [["QAG", "Questions au gouv."], ["QOSD", "Questions orales"], ["BUDGET", "Budgets"]];
  const FAMC = { Questions: "#5e6ad2", Budgets: "#d9a441", Mixte: "#8a8f98" };

  let D = null, loading = null, root = null;
  let G, GOUV, AUTRE, bySujet, byTexte;
  const st = { tab: "carte", sel: null, m0: 0, m1: 0, fams: new Set(["QAG", "QOSD", "BUDGET"]), sort: "volume", q: "", color: "famille", showEm: true, zoom: null, emf: "Questions" };

  async function fetchGz(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(r.status);
    const buf = new Uint8Array(await r.arrayBuffer());
    if (buf[0] === 0x1f && buf[1] === 0x8b) {
      const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
      return JSON.parse(await new Response(stream).text());
    }
    return JSON.parse(new TextDecoder().decode(buf));
  }

  function load() {
    loading ??= fetchGz("sujets.json.gz").then((data) => {
      D = data;
      G = D.groupes;
      GOUV = G.findIndex((g) => g.id === "GOUV");
      AUTRE = G.findIndex((g) => g.id === "?");
      bySujet = D.sujets.map(() => []);
      byTexte = D.textes.map(() => []);
      for (const r of D.passages) (r[0] === 4 ? byTexte : bySujet)[r[1]].push(r);
      st.m0 = 0;
      st.m1 = D.mois.length - 1;
      D.sujets.forEach((s) => { s._k = norm(`${s.nom} ${s.titres.join(" ")} ${s.mots.join(" ")}`); });
      return D;
    });
    return loading;
  }

  const famOf = (f) => (f === 2 || f === 3 ? "BUDGET" : D.familles[f]);
  const inP = (m) => m >= st.m0 && m <= st.m1;
  const isSuj = () => st.tab === "carte" || st.tab === "liste";

  function measure(rows) {
    let vol = 0;
    const se = new Set(), mo = new Set(), byM = new Array(D.mois.length).fill(0), byG = new Array(G.length).fill(0);
    for (const r of rows) {
      let c = 0;
      for (const k in r[4]) c += r[4][k];
      byM[r[2]] += c;
      if (inP(r[2])) {
        vol += c; se.add(r[3]); mo.add(r[2]);
        for (const k in r[4]) byG[k] += r[4][k];
      }
    }
    return { vol, seances: se.size, mois: mo.size, byM, byG, div: diversity(byG), last: byM.reduce((l, v, k) => (v && k <= st.m1 ? k : l), -1) };
  }
  function diversity(byG) {
    // Entropie normalisée de la parole des députés entre groupes : 0 = un seul groupe, 1 = tous à parts égales.
    const dep = byG.map((v, i) => (i === GOUV || i === AUTRE ? 0 : v));
    const tot = dep.reduce((a, b) => a + b, 0);
    if (tot < 3000) return null;
    let h = 0;
    for (const v of dep) if (v > 0) { const p = v / tot; h -= p * Math.log(p); }
    return h / Math.log(G.length - 2);
  }
  const rowsOf = (i) => bySujet[i].filter((r) => st.fams.has(famOf(r[0])));

  /* ---------- rendu général ---------- */

  function render() {
    if (!root) return;
    if (!D) { root.innerHTML = `<div class="loading"><span class="spinner" aria-hidden="true"></span>Chargement des sujets…</div>`; return; }
    root.innerHTML = `
      <h1 class="sr-only">Sujets débattus en séance</h1>
      <div class="sj-bar">
        <div class="seg sj-tabs" role="tablist" aria-label="Vues">${TABS.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${k === st.tab}">${l}</button>`).join("")}</div>
        <div class="sj-ctrls">
          <label class="sj-period">Du <select class="f-select" id="sjM0" aria-label="Début de la période">${monthOpts(st.m0)}</select></label>
          <label class="sj-period">au <select class="f-select" id="sjM1" aria-label="Fin de la période">${monthOpts(st.m1)}</select></label>
          ${isSuj() ? `<span class="sj-fams" role="group" aria-label="Familles de débats">${FAMS.map(([k, l]) => `<button class="chip" type="button" data-fam="${k}" aria-pressed="${st.fams.has(k)}">${l}</button>`).join("")}</span>` : ""}
        </div>
      </div>
      <div class="sj-body ${st.tab === "carte" ? "is-map" : ""}">
        <section class="sj-main" id="sjMain"></section>
        <aside class="sj-detail" id="sjDetail" aria-live="polite"></aside>
      </div>`;
    bindBar();
    ({ carte: renderMap, liste: renderList, emergents: renderEmergents, themes: renderThemes, textes: renderTextes })[st.tab]();
  }
  function monthOpts(sel) { return D.mois.map((m, k) => `<option value="${k}" ${k === sel ? "selected" : ""}>${fmtMs(m)}</option>`).join(""); }

  function bindBar() {
    root.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => go(b.dataset.tab, null));
    $("#sjM0", root).onchange = (e) => { st.m0 = Math.min(+e.target.value, st.m1); render(); };
    $("#sjM1", root).onchange = (e) => { st.m1 = Math.max(+e.target.value, st.m0); render(); };
    root.querySelectorAll("[data-fam]").forEach((b) => b.onclick = () => {
      const k = b.dataset.fam;
      st.fams.has(k) ? st.fams.delete(k) : st.fams.add(k);
      if (!st.fams.size) st.fams.add(k);
      render();
    });
  }

  // Navigation : l'onglet change l'adresse (historique) ; la sélection la remplace (pas d'historique).
  function go(tab, sel) {
    const h = `#sujets/${tab}${sel != null ? `/${sel}` : ""}`;
    if (location.hash !== h) location.hash = h;
    else route(tab, sel);
  }
  function setSel(sel) {
    st.sel = sel;
    const h = `#sujets/${st.tab}${sel != null ? `/${sel}` : ""}`;
    if (location.hash !== h) history.replaceState(null, "", h);
  }

  /* ---------- carte en bulles ---------- */

  const W = 1000, H = 700, PAD = 56;
  function famLabel(rows) {
    let q = 0, b = 0;
    for (const r of rows) if (inP(r[2])) { let c = 0; for (const k in r[4]) c += r[4][k]; famOf(r[0]) === "BUDGET" ? (b += c) : (q += c); }
    return q > 2 * b ? "Questions" : b > 2 * q ? "Budgets" : "Mixte";
  }
  function domGroup(byG) {
    let best = -1, v = 0;
    byG.forEach((c, i) => { if (i !== GOUV && i !== AUTRE && c > v) { v = c; best = i; } });
    return best;
  }
  function separate(nodes) {
    // Chaque bulle garde sa place « de sens » mais ne chevauche pas ses voisines.
    for (let it = 0; it < 140; it++) {
      for (let a = 0; a < nodes.length; a++) for (let b = a + 1; b < nodes.length; b++) {
        const A = nodes[a], B = nodes[b], dx = B.x - A.x, dy = B.y - A.y, d = Math.hypot(dx, dy) || 0.01, min = A.r + B.r + 2;
        if (d < min) { const k = (min - d) / d / 2; A.x -= dx * k; A.y -= dy * k; B.x += dx * k; B.y += dy * k; }
      }
      for (const n of nodes) { n.x += (n.hx - n.x) * 0.02; n.y += (n.hy - n.y) * 0.02; }
    }
  }

  function renderMap() {
    const its = D.sujets.map((s, i) => ({ i, s, rows: rowsOf(i) })).map((it) => ({ ...it, m: measure(it.rows) })).filter((it) => it.m.vol > 0);
    const max = Math.max(1, ...its.map((it) => it.m.vol));
    const nodes = its.map((it) => {
      const hx = PAD + it.s.x * (W - 2 * PAD), hy = PAD + it.s.y * (H - 2 * PAD), g = domGroup(it.m.byG);
      return { ...it, hx, hy, x: hx, y: hy, r: 3 + 36 * Math.sqrt(it.m.vol / max), g,
        fill: st.color === "famille" ? FAMC[famLabel(it.rows)] : G[g]?.couleur || "#555" };
    });
    separate(nodes);
    const em = st.showEm ? D.emergents.map((e, i) => ({ e, i })).filter(({ e }) => inP(D.mois.indexOf(e.mois)) && (st.fams.has("BUDGET") || e.famille === "Questions")) : [];
    if (st.sel == null || !nodes.some((n) => n.s.id === st.sel)) {
      // Par défaut, le plus gros sujet qui porte un vrai intitulé (pas une liste de mots-clés).
      const big = nodes.slice().sort((a, b) => b.r - a.r);
      setSel((big.find((n) => n.s.nomme || !n.s.nom.includes(" · ")) || big[0])?.s.id ?? null);
    }
    const q = norm(st.q.trim());
    const hit = (n) => !q || n.s._k.includes(q);
    const labelled = new Set(nodes.slice().sort((a, b) => b.r - a.r).slice(0, 26).map((n) => n.i));
    const vb = st.zoom || [0, 0, W, H];
    const legend = st.color === "famille"
      ? Object.entries(FAMC).map(([k, c]) => `<span style="--c:${c}">${k}</span>`).join("")
      : [...new Set(nodes.map((n) => n.g))].filter((g) => g >= 0).map((g) => `<span style="--c:${G[g].couleur}">${esc(G[g].id)}</span>`).join("");
    $("#sjMain", root).innerHTML = `
      <div class="sj-tools">
        <label class="vote-search"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3"/></svg>
          <input type="search" id="sjQ" placeholder="Chercher un sujet…" value="${esc(st.q)}" autocomplete="off"></label>
        <label class="sj-lab">Couleur <select class="f-select" id="sjCol"><option value="famille" ${st.color === "famille" ? "selected" : ""}>Famille</option><option value="groupe" ${st.color === "groupe" ? "selected" : ""}>Groupe qui en parle le plus</option></select></label>
        <label class="f-check"><input type="checkbox" id="sjEm" ${st.showEm ? "checked" : ""}> Émergents</label>
        <span class="sj-zoom">
          <button class="icon-btn" type="button" data-z="in" aria-label="Zoomer"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3.5v9M3.5 8h9"/></svg></button>
          <button class="icon-btn" type="button" data-z="out" aria-label="Dézoomer"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8h9"/></svg></button>
          <button class="icon-btn" type="button" data-z="fit" aria-label="Recentrer"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4"/></svg></button>
        </span>
      </div>
      <svg id="sjMap" viewBox="${vb.join(" ")}" role="group" aria-label="Carte des sujets : bulles proportionnelles au volume de parole. Chaque bulle est un bouton.">
        ${em.map(({ e, i }) => `<g class="em" data-e="${i}" transform="translate(${(PAD + e.x * (W - 2 * PAD)).toFixed(1)},${(PAD + e.y * (H - 2 * PAD)).toFixed(1)})" tabindex="0" role="button" aria-label="Sujet émergent : ${esc(e.nom)}"><circle r="${(4 + 3 * Math.sqrt(e.n)).toFixed(1)}"/><title>Émergent · ${esc(e.nom)} (${e.n} passages)</title></g>`).join("")}
        ${nodes.map((n) => `<g class="b${n.s.id === st.sel ? " sel" : ""}${hit(n) ? "" : " dim"}" data-i="${n.i}" transform="translate(${n.x.toFixed(1)},${n.y.toFixed(1)})" tabindex="0" role="button" aria-label="${esc(n.s.nom)}, ${nf(words(n.m.vol))} mots">
          <circle r="${n.r.toFixed(1)}" fill="${n.fill}"/>
          ${labelled.has(n.i) || (q && hit(n)) ? `<text y="${(n.r + 12).toFixed(1)}">${esc(n.s.nom.length > 26 ? n.s.nom.slice(0, 25) + "…" : n.s.nom)}</text>` : ""}
          <title>${esc(n.s.nom)} · ${nf(words(n.m.vol))} mots · ${n.m.seances} séances</title></g>`).join("")}
      </svg>
      <div class="sj-legend">${legend}${st.showEm ? `<span class="emk">Sujet émergent</span>` : ""}<span class="sj-note">Taille : mots prononcés sur la période · deux bulles proches parlent de choses proches</span></div>`;
    const svg = $("#sjMap", root);
    const pick = (el, e) => { if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return; e.preventDefault(); setSel(D.sujets[+el.dataset.i].id); renderMap(); $(`#sjMap g.b[data-i="${el.dataset.i}"]`, root)?.focus(); };
    svg.querySelectorAll("g.b").forEach((el) => { el.onclick = (e) => pick(el, e); el.onkeydown = (e) => pick(el, e); });
    svg.querySelectorAll("g.em").forEach((el) => { const f = (e) => { if (e.type === "keydown" && e.key !== "Enter") return; go("emergents", +el.dataset.e); }; el.onclick = f; el.onkeydown = f; });
    const qi = $("#sjQ", root);
    qi.oninput = () => { st.q = qi.value; renderMap(); const i = $("#sjQ", root); i.focus(); i.setSelectionRange(i.value.length, i.value.length); };
    $("#sjCol", root).onchange = (e) => { st.color = e.target.value; renderMap(); };
    $("#sjEm", root).onchange = (e) => { st.showEm = e.target.checked; renderMap(); };
    const zoomBy = (k, fx = 0.5, fy = 0.5) => {
      const [x, y, w, h] = st.zoom || [0, 0, W, H];
      const nw = Math.min(W * 1.2, Math.max(W / 8, w * k)), nh = (nw * H) / W;
      st.zoom = [x + (w - nw) * fx, y + (h - nh) * fy, nw, nh];
      svg.setAttribute("viewBox", st.zoom.join(" "));
    };
    root.querySelectorAll("[data-z]").forEach((b) => b.onclick = () => {
      if (b.dataset.z === "fit") { st.zoom = null; svg.setAttribute("viewBox", `0 0 ${W} ${H}`); } else zoomBy(b.dataset.z === "in" ? 1 / 1.3 : 1.3);
    });
    svg.ondblclick = () => { st.zoom = null; svg.setAttribute("viewBox", `0 0 ${W} ${H}`); };
    svg.onwheel = (e) => {
      e.preventDefault();
      const b = svg.getBoundingClientRect();
      zoomBy(e.deltaY > 0 ? 1.15 : 1 / 1.15, (e.clientX - b.left) / b.width, (e.clientY - b.top) / b.height);
    };
    let drag = null;
    svg.onpointerdown = (e) => { if (e.target.closest("g")) return; drag = { x: e.clientX, y: e.clientY, z: st.zoom || [0, 0, W, H] }; svg.setPointerCapture(e.pointerId); };
    svg.onpointermove = (e) => {
      if (!drag) return;
      const b = svg.getBoundingClientRect(), [x, y, w, h] = drag.z;
      st.zoom = [x - ((e.clientX - drag.x) * w) / b.width, y - ((e.clientY - drag.y) * h) / b.height, w, h];
      svg.setAttribute("viewBox", st.zoom.join(" "));
    };
    svg.onpointerup = () => { drag = null; };
    detailSujet();
  }

  /* ---------- liste des sujets ---------- */

  const SORTS = {
    volume: ["Attention (mots)", (m) => m.vol, (m) => `${nf(words(m.vol))} mots`],
    seances: ["Récurrence (séances)", (m) => m.seances * 100 + m.mois, (m) => `${m.seances} séances`],
    diversite: ["Transpartisan", (m) => m.div ?? -1, (m) => (m.div == null ? "—" : `${Math.round(m.div * 100)} %`)],
    recent: ["Le plus récent", (m) => m.last * 1e9 + m.vol, (m) => (m.last < 0 ? "" : fmtMs(D.mois[m.last]))],
  };
  function spark(byM) {
    const w = 72, h = 20, n = st.m1 - st.m0 + 1, max = Math.max(1, ...byM.slice(st.m0, st.m1 + 1));
    let d = "";
    for (let k = 0; k < n; k++) d += `${k ? "L" : "M"}${(n === 1 ? w / 2 : (k * w) / (n - 1)).toFixed(1)},${(h - 2 - (byM[st.m0 + k] / max) * (h - 4)).toFixed(1)}`;
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="${d}"/></svg>`;
  }
  function listShell(head, items, empty) {
    $("#sjMain", root).innerHTML = `<div class="sj-tools">${head}</div><ul class="sj-list" role="listbox" aria-label="Résultats">${items || `<li class="sj-empty">${empty}</li>`}</ul>`;
  }
  function bindList(onPick) {
    root.querySelectorAll(".sj-item").forEach((el) => {
      const f = (e) => { if (e.type === "keydown" && e.key !== "Enter") return; onPick(el.dataset.k); };
      el.onclick = f; el.onkeydown = f;
    });
  }

  function renderList() {
    const q = norm(st.q.trim());
    let its = D.sujets.map((s, i) => ({ s, i, m: measure(rowsOf(i)) })).filter((it) => it.m.vol > 0 && (!q || it.s._k.includes(q)));
    const [, key, lab] = SORTS[st.sort];
    its.sort((a, b) => key(b.m) - key(a.m));
    if (st.sel == null || !its.some((it) => it.s.id === st.sel)) setSel(its[0]?.s.id ?? null);
    listShell(`<label class="vote-search"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3"/></svg>
        <input type="search" id="sjQ" placeholder="Filtrer les sujets…" value="${esc(st.q)}" autocomplete="off"></label>
      <label class="sj-lab">Trier par <select class="f-select" id="sjSort">${Object.entries(SORTS).map(([k, v]) => `<option value="${k}" ${k === st.sort ? "selected" : ""}>${v[0]}</option>`).join("")}</select></label>`,
    its.map((it) => `<li class="sj-item" role="option" tabindex="0" data-k="${it.s.id}" aria-selected="${it.s.id === st.sel}">
        <span class="sj-name"><span>${esc(it.s.nom)}</span><small>${esc(it.s.mots.slice(0, 4).join(" · "))}</small></span>
        ${spark(it.m.byM)}<span class="sj-val">${lab(it.m)}</span></li>`).join(""), "Aucun sujet sur cette période.");
    const qi = $("#sjQ", root);
    qi.oninput = () => { st.q = qi.value; renderList(); const i = $("#sjQ", root); i.focus(); i.setSelectionRange(i.value.length, i.value.length); };
    $("#sjSort", root).onchange = (e) => { st.sort = e.target.value; renderList(); };
    bindList((k) => { setSel(k); renderList(); $(`.sj-item[data-k="${k}"]`, root)?.focus(); });
    detailSujet();
  }

  /* ---------- détail d'un sujet ou d'un texte ---------- */

  function monthBars(byM, label) {
    const max = Math.max(1, ...byM);
    return `<div class="sj-bars" role="img" aria-label="${esc(label)}">${byM.map((v, k) => `<i class="${inP(k) ? "in" : ""}" style="height:${((v / max) * 100).toFixed(1)}%" title="${fmtM(D.mois[k])} : ${nf(words(v))} mots"></i>`).join("")}</div>
      <div class="sj-axis"><span>${fmtMs(D.mois[0])}</span><span>${fmtMs(D.mois[D.mois.length - 1])}</span></div>`;
  }
  function groupStack(byG, unit = "mots") {
    const tot = byG.reduce((a, b) => a + b, 0) || 1;
    const order = byG.map((v, i) => [v, i]).filter((x) => x[0] > 0).sort((a, b) => b[0] - a[0]);
    return `<div class="composition">${order.map(([v, i]) => `<i style="flex:${v};background:${G[i].couleur || "#555"}" title="${esc(G[i].nom)} : ${Math.round((v / tot) * 100)} %"></i>`).join("")}</div>
      <ul class="sj-groups">${order.slice(0, 12).map(([v, i]) => `<li><span class="r-dot" style="background:${G[i].couleur || "#555"}"></span>${esc(G[i].id === "GOUV" ? "Gouvernement" : G[i].id === "?" ? "Autres" : G[i].id)}<b>${Math.round((v / tot) * 100)} %</b></li>`).join("")}</ul>`;
  }
  function spk(o) {
    const g = G.find((x) => x.id === o.g);
    const name = o.id ? `<a href="#fiche/${esc(o.id)}">${esc(o.n)}</a>` : `<b>${esc(o.n || "Orateur")}</b>`;
    const sub = o.g === "GOUV" ? esc(o.q || "gouvernement") : o.g && o.g !== "?" ? esc(o.g) : esc(o.q || "");
    return `<span class="r-dot" style="background:${g?.couleur || "#555"}"></span>${name}${sub ? `<span>${sub}</span>` : ""}`;
  }
  function exHtml(e) {
    return `<article class="sj-ex">
      <div class="sj-ex-h">${spk(e.o)}<time datetime="${e.d}">${fmtD(e.d)}</time></div>
      <p class="sj-ex-ctx">${esc(e.ti.join(" › "))}</p>
      <p>${esc(e.t)}${e.t.length >= 420 ? "…" : ""}</p>
      ${e.r ? `<div class="sj-rep"><div class="sj-ex-h">${spk(e.r.o)}</div><p>${esc(e.r.t)}${e.r.t.length >= 300 ? "…" : ""}</p></div>` : ""}
      <a class="ext-link" href="${CR(e.s, e.a)}" target="_blank" rel="noopener">Compte rendu officiel ${EXT}</a>
    </article>`;
  }
  const inPeriod = (e) => inP(D.mois.indexOf(e.d.slice(0, 7)));
  const kpi = (v, l) => `<div class="kpi"><div class="kpi-value">${v}</div><div class="kpi-label">${l}</div></div>`;

  function detailSujet() {
    const el = $("#sjDetail", root);
    const i = D.sujets.findIndex((s) => s.id === st.sel);
    if (i < 0) { el.innerHTML = `<p class="sj-empty">Choisissez un sujet.</p>`; return; }
    const s = D.sujets[i], m = measure(rowsOf(i)), ex = s.extraits.filter(inPeriod).reverse();
    const tot = m.byG.reduce((a, b) => a + b, 0) || 1;
    el.innerHTML = `
      <header class="sj-dh">
        <p class="sj-eyebrow"><span class="tag">${s.id}</span>${s.nomme ? "" : `<span class="tag" title="Libellé proposé automatiquement, à relire">nom automatique</span>`}</p>
        <h2>${esc(s.nom)}</h2>
        <p class="sj-words">${esc(s.mots.join(" · "))}</p>
      </header>
      <div class="kpis sj-kpis">
        ${kpi(nf(words(m.vol)), "mots prononcés")}${kpi(m.seances, "séances")}${kpi(`${m.mois}<small>/${st.m1 - st.m0 + 1}</small>`, "mois actifs")}${kpi(m.div == null ? "—" : `${Math.round(m.div * 100)} %`, "diversité des groupes")}
      </div>
      <section><h3>Attention mois par mois</h3>${monthBars(m.byM, "Volume de parole par mois")}</section>
      <section><h3>Qui en parle</h3>${groupStack(m.byG)}<p class="p-note">Part de la parole sur la période, gouvernement compris (${Math.round((m.byG[GOUV] / tot) * 100)} %). Groupes actuels des députés.</p></section>
      <section><h3>Sous-titres officiels regroupés</h3><p class="sj-words">${esc(s.titres.join(" · "))}</p></section>
      <section><h3>Extraits <span>${ex.length}</span></h3>${ex.length ? ex.map(exHtml).join("") : `<p class="sj-empty">Pas d'extrait sur cette période.</p>`}</section>`;
    el.scrollTop = 0;
  }

  /* ---------- émergents ---------- */

  function renderEmergents() {
    const c = D.emergents.map((e, i) => ({ e, i })).filter(({ e }) => inP(D.mois.indexOf(e.mois)) && (st.emf === "tous" || e.famille === st.emf)).reverse();
    if (st.sel == null || !c.some((x) => x.i === +st.sel)) setSel(c[0]?.i ?? null);
    const per = (e) => (e.fin && e.fin !== e.mois ? `${fmtMs(e.mois)} – ${fmtMs(e.fin)}` : fmtMs(e.mois));
    listShell(`<p class="sj-intro">Des débats récents, denses (au moins 2 séances et 2 groupes), qu'aucun sujet existant n'accueille vraiment. À valider avant d'en faire de nouveaux sujets.</p>
      <span class="seg" role="tablist" aria-label="Famille">${[["Questions", "Questions"], ["Budgets", "Budgets"], ["tous", "Tous"]].map(([k, l]) => `<button type="button" role="tab" data-f="${k}" aria-selected="${st.emf === k}">${l}</button>`).join("")}</span>`,
    c.map(({ e, i }) => `<li class="sj-item" role="option" tabindex="0" data-k="${i}" aria-selected="${i === +st.sel}">
        <span class="sj-name"><span>${esc(e.nom)}</span><small>${esc(e.mots.slice(0, 4).join(" · "))}</small></span>
        <span class="sj-val">${per(e)}</span><span class="sj-val">${e.n}</span></li>`).join(""), "Aucun sujet émergent sur cette période.");
    root.querySelectorAll("[data-f]").forEach((b) => b.onclick = () => { st.emf = b.dataset.f; setSel(null); renderEmergents(); });
    bindList((k) => { setSel(+k); renderEmergents(); $(`.sj-item[data-k="${k}"]`, root)?.focus(); });
    const e = D.emergents[st.sel];
    const abs = e?.absorbe ? D.sujets.find((s) => s.id === e.absorbe) : null;
    $("#sjDetail", root).innerHTML = e ? `
      <header class="sj-dh"><p class="sj-eyebrow"><span class="tag tag-warn">émergent</span><span class="tag">${esc(e.famille)}</span></p>
        <h2>${esc(e.nom)}</h2>
        <p class="sj-words">${per(e)} · ${e.n} passages · ${e.seances} séances · ${esc(e.groupes.join(", "))}</p></header>
      <section>${abs ? `<p class="sj-callout">${Math.round(e.part_absorbee * 100)} % de ces passages sont aujourd'hui rangés dans <button class="link-btn" type="button" data-goto="${abs.id}">${esc(abs.nom)}</button>. S'il est validé, ce sujet rejoindrait la carte.</p>` : `<p class="sj-callout">Aucun de ces passages n'a trouvé de sujet existant.</p>`}</section>
      <section><h3>Sous-titres officiels</h3><p class="sj-words">${esc(e.titres.join(" · "))}</p></section>
      <section><h3>Extraits</h3>${e.extraits.map(exHtml).join("")}</section>` : `<p class="sj-empty">Aucun sujet émergent sur cette période.</p>`;
    root.querySelector("[data-goto]")?.addEventListener("click", (ev) => go("carte", ev.currentTarget.dataset.goto));
  }

  /* ---------- thème suivi ---------- */

  function renderThemes() {
    const ths = D.themes;
    if (st.sel == null || !ths[+st.sel]) setSel(0);
    listShell(`<p class="sj-intro">Un sujet transversal, présent dans des débats très différents, se suit mieux par mots-clés qu'avec une bulle de la carte.</p>`,
      ths.map((t, i) => `<li class="sj-item" role="option" tabindex="0" data-k="${i}" aria-selected="${i === +st.sel}"><span class="sj-name"><span>${esc(t.nom)}</span><small>${t.mentions.length} paragraphes</small></span></li>`).join(""), "Aucun thème défini.");
    bindList((k) => { setSel(+k); renderThemes(); });
    const t = ths[+st.sel];
    if (!t) return;
    const byM = new Array(D.mois.length).fill(0), byG = new Array(G.length).fill(0), se = new Set();
    let n = 0, strong = 0;
    for (const [m, s, g, k] of t.mentions) { byM[m] += 6; if (inP(m)) { byG[g]++; se.add(s); n++; if (k >= 2) strong++; } }
    $("#sjDetail", root).innerHTML = `
      <header class="sj-dh"><p class="sj-eyebrow"><span class="tag">thème suivi</span></p><h2>${esc(t.nom)}</h2>
        <p class="sj-words">Mots-clés : hébergement d'urgence, « le 115 », sans-abri, SIAO, sans domicile, dormir à la rue, mise à l'abri</p></header>
      <div class="kpis sj-kpis">${kpi(n, "paragraphes qui le mentionnent")}${kpi(strong, "qui en parlent vraiment")}${kpi(se.size, "séances")}</div>
      <section><h3>Mentions mois par mois</h3>${monthBars(byM, "Mentions par mois")}</section>
      <section><h3>Qui le mentionne</h3>${groupStack(byG)}</section>
      <section><h3>Passages qui en parlent vraiment <span>2 mentions ou plus</span></h3>${t.extraits.filter(inPeriod).map(exHtml).join("") || `<p class="sj-empty">Aucun sur cette période.</p>`}</section>`;
  }

  /* ---------- textes de loi ---------- */

  function renderTextes() {
    const q = norm(st.q.trim());
    let its = D.textes.map((s, i) => ({ s, i, m: measure(byTexte[i]) })).filter((it) => it.m.vol > 0 && (!q || norm(it.s.nom).includes(q)));
    its.sort((a, b) => b.m.vol - a.m.vol);
    if (st.sel == null || !its.some((it) => it.i === +st.sel)) setSel(its[0]?.i ?? null);
    listShell(`<label class="vote-search"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3"/></svg>
        <input type="search" id="sjQ" placeholder="Filtrer les textes…" value="${esc(st.q)}" autocomplete="off"></label>`,
    its.map((it) => `<li class="sj-item" role="option" tabindex="0" data-k="${it.i}" aria-selected="${it.i === +st.sel}">
        <span class="sj-name"><span>${esc(it.s.nom)}</span><small>${it.m.seances} séances</small></span>${spark(it.m.byM)}<span class="sj-val">${nf(words(it.m.vol))} mots</span></li>`).join(""), "Aucun texte sur cette période.");
    const qi = $("#sjQ", root);
    qi.oninput = () => { st.q = qi.value; renderTextes(); const i = $("#sjQ", root); i.focus(); i.setSelectionRange(i.value.length, i.value.length); };
    bindList((k) => { setSel(+k); renderTextes(); $(`.sj-item[data-k="${k}"]`, root)?.focus(); });
    const t = D.textes[+st.sel];
    if (!t) { $("#sjDetail", root).innerHTML = `<p class="sj-empty">Aucun texte sur cette période.</p>`; return; }
    const m = measure(byTexte[+st.sel]), ex = t.extraits.filter(inPeriod);
    $("#sjDetail", root).innerHTML = `
      <header class="sj-dh"><p class="sj-eyebrow"><span class="tag">texte de loi</span></p><h2>${esc(t.nom)}</h2></header>
      <div class="kpis sj-kpis">${kpi(nf(words(m.vol)), "mots prononcés")}${kpi(m.seances, "séances")}${kpi(m.div == null ? "—" : `${Math.round(m.div * 100)} %`, "diversité des groupes")}</div>
      <section><h3>Attention mois par mois</h3>${monthBars(m.byM, "Volume de parole par mois")}</section>
      <section><h3>Qui en parle</h3>${groupStack(m.byG)}</section>
      <section><h3>Extraits <span>${ex.length}</span></h3>${ex.map(exHtml).join("") || `<p class="sj-empty">Pas d'extrait sur cette période.</p>`}</section>`;
  }

  /* ---------- interface ---------- */

  function route(tab, sel) {
    const t = TABS.some(([k]) => k === tab) ? tab : "carte";
    if (t !== st.tab) { st.q = ""; st.zoom = null; }
    st.tab = t;
    st.sel = sel ?? null;
    render();
  }

  window.Sujets = {
    load,
    /** Affiche la section dans `el` ; `path` est la suite de l'adresse après #sujets/. */
    show(el, path) {
      root = el;
      const [tab, sel] = (path || "").split("/");
      st.tab = TABS.some(([k]) => k === tab) ? tab : "carte";
      st.sel = sel ? decodeURIComponent(sel) : null;
      render();
      load().then(() => { if (root === el) render(); }).catch(() => {
        el.innerHTML = `<div class="loading">Impossible de charger les sujets (sujets.json.gz).</div>`;
      });
    },
    hide() { root = null; },
    /** Recherche pour la palette : [{id, nom, sub}] */
    search(q) {
      if (!D) return [];
      const t = norm(q).split(/\s+/).filter(Boolean);
      return D.sujets.filter((s) => t.every((w) => s._k.includes(w))).slice(0, 6).map((s) => ({ id: s.id, nom: s.nom, sub: s.mots.slice(0, 3).join(" · ") }));
    },
    /** Sujets sur lesquels un député intervient le plus : [{id, nom, mots}] */
    forDepute(pid) {
      return (D?.deputes?.[pid] || []).map(([t, n]) => ({ id: D.sujets[t].id, nom: D.sujets[t].nom, mots: words(n) }));
    },
  };
})();
