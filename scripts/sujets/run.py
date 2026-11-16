"""Carte des sujets débattus en séance. Écrit site/sujets.json.gz.

Usage (depuis la racine du projet, après scripts/build_data.py) :
    python scripts/sujets/run.py            mise à jour quotidienne
    python scripts/sujets/run.py --refit    réapprend le référentiel des sujets (GPU conseillé)

Dépendances : scripts/sujets/requirements.txt (torch, sentence-transformers, scikit-learn ;
umap-learn seulement pour --refit).

- Référentiel figé (data/sujets/) : les sujets sont appris une fois sur la période de
  référence, puis ne bougent plus. Chaque sujet a un identifiant stable (S001…) et une
  position sur la carte. Les nouveaux passages sont rattachés au sujet le plus proche.
- Embeddings en cache (raw/sujets_emb.npz) : seuls les passages nouveaux sont encodés.
- Noms à la main : data/sujets/noms.json ({"S064": "Énergie"}) remplace les libellés
  automatiques. Thèmes suivis : data/sujets/themes.json.
"""
import gzip
import json
import re
import sys
import time
import zlib
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from passages import build, key  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REFDIR = ROOT / "data/sujets"
CACHE = ROOT / "raw/sujets_emb.npz"
OUTFILE = ROOT / "site/sujets.json.gz"
MODEL = "BAAI/bge-m3"
FAMS = ("QAG", "QOSD", "PLF", "PLFSS")  # sujets automatiques ; les autres textes gardent leur intitulé
FIT = ("2025-10", "2026-02")  # période de référence du référentiel
PER_TOPIC = 25
MIN_TOPIC = 5
SEUIL_CENTILE = 5        # rattachement : 5e centile des membres de référence (réglé au test)
MIN_CHARS_DEPUTE = 150   # sans vraie parole de député (procédure pure), un passage n'est pas classé
REFIT = "--refit" in sys.argv

STOP = set("""avait avant avec avez avoir avons beaucoup cette chaque comme comment contre depuis entre encore était faire leurs madame mais même monsieur nous notre parce pour pourquoi quand quelle quelles quels sans sera sont toutes votre vous également ministre gouvernement collègues président présidente rapporteur rapporteure amendement amendements article texte commission défavorable favorable sagesse alinéa visant aujourd très aussi alors ainsi donc dans elles sommes faut cela celui celle ceux jamais toujours rien merci question questions millions milliards euros france français française françaises pays nôtre leur""".split())
GENERIC = re.compile(r"^(article|après l.article|avant l.article|discussion générale|motion|explications de vote|article liminaire|vote sur|seconde partie|première partie|présentation|discussion des articles|titre |état [a-z])", re.I)


def log(*a):
    print(*a, flush=True)


def chars_by_group(p):
    g = Counter()
    for x in p["paras"]:
        if x["r"] == "depute":
            g[x["g"]] += x["n"]
        elif x["r"] == "gouvernement":
            g["GOUV"] += x["n"]
    return g


def depute_chars(p):
    return sum(x["n"] for x in p["paras"] if x["r"] == "depute")


def clean_title(t):
    return re.sub(r"\s*\((suite|appelé par priorité)\)\s*$", "", t).strip()


def ptext(p):
    return " ".join(x["t"] for x in p["paras"])


def tfidf_words(docs, top=6):
    v = TfidfVectorizer(token_pattern=r"(?u)\b[^\W\d_]{4,}\b", max_df=0.3, sublinear_tf=True, stop_words=list(STOP))
    X = v.fit_transform(docs)
    voc = np.array(v.get_feature_names_out())
    return [voc[np.argsort(-X[r].toarray()[0])[:top]].tolist() for r in range(X.shape[0])]


PLACE = re.compile(r"\s+(?:dans (?:le|la|les|l['’])\s*|à |en |au |aux )[A-ZÉÈÀÂÎÔ][^,;]*$")


def generalize(t):
    """« Accès aux soins dans la Sarthe » -> « Accès aux soins » : le lieu d'une question ne nomme pas
    un sujet qui en regroupe beaucoup. On garde le titre si le reste serait trop court (« Situation à Gaza »)."""
    g = PLACE.sub("", t)
    return g if len(g.split()) >= 3 else t


def auto_name(titres, mots):
    """Libellé provisoire : le sous-titre officiel le plus fréquent (variantes de lieu additionnées)
    s'il est parlant, sinon les mots clés."""
    c = Counter()
    for t, n in titres:
        if not GENERIC.match(t):
            c[generalize(t)] += n
    for t, n in c.most_common():
        if n >= 2:
            return t
    return " · ".join(w.capitalize() if i == 0 else w for i, w in enumerate(mots[:3]))


# ---------- 1. Passages ----------
t0 = time.time()
data = json.loads((ROOT / "site/data.json").read_text(encoding="utf-8"))
deputes = {d["id"]: d for d in data["deputes"]}
gp = {o["id"]: o["abrev"] for o in data["organes"] if o["kind"] == "GP"}
GROUPES = {o["abrev"]: {"nom": o["libelle"], "couleur": o["couleur"]} for o in data["organes"] if o["kind"] == "GP"}
P, stats = build(ROOT / "raw/debats.zip", deputes, gp)
byid = {p["id"]: p for p in P}
log(f"passages : {len(P)} ({dict(Counter(p['fam'] for p in P))})")

# ---------- 2. Embeddings (cache) ----------
todo = [p for p in P if p["fam"] in FAMS]
cache = {}
if CACHE.exists():
    z = np.load(CACHE, allow_pickle=False)
    cache = dict(zip(z["keys"].tolist(), z["emb"]))
missing = [p for p in todo if key(p) not in cache]
log(f"embeddings : {len(todo) - len(missing)} en cache, {len(missing)} à calculer")
if missing:
    import torch
    from sentence_transformers import SentenceTransformer

    cuda = torch.cuda.is_available()
    model = SentenceTransformer(MODEL, device="cuda" if cuda else "cpu")
    if cuda:
        model.half()
    model.max_seq_length = 1024
    texts = [ptext(p) for p in missing]
    order = np.argsort([len(t) for t in texts])
    emb = model.encode([texts[i] for i in order], batch_size=16 if cuda else 8, normalize_embeddings=True,
                       show_progress_bar=sys.stdout.isatty())
    for j, i in enumerate(order):
        cache[key(missing[i])] = emb[j].astype(np.float16)
    CACHE.parent.mkdir(exist_ok=True)
    keys = sorted(cache)
    np.savez(CACHE, keys=np.array(keys), emb=np.stack([cache[k] for k in keys]))
    log(f"  encodés en {time.time() - t0:.0f} s ({'GPU' if cuda else 'CPU'})")
EIDS = [p["id"] for p in todo]
row = {pid: r for r, pid in enumerate(EIDS)}
E = np.stack([cache[key(byid[pid])] for pid in EIDS]).astype(np.float32)
eligible = [pid for pid in EIDS if depute_chars(byid[pid]) >= MIN_CHARS_DEPUTE]

# ---------- 3. Référentiel figé ----------
if REFIT or not (REFDIR / "referentiel.json").exists():
    import umap

    fit = [pid for pid in eligible if FIT[0] <= byid[pid]["d"][:7] <= FIT[1]]
    X = E[[row[pid] for pid in fit]]
    lab = AgglomerativeClustering(n_clusters=len(fit) // PER_TOPIC, metric="cosine", linkage="complete").fit_predict(X)
    keep = sorted([k for k, n in Counter(lab).items() if n >= MIN_TOPIC], key=lambda k: -(lab == k).sum())
    C = np.stack([X[lab == k].mean(0) for k in keep])
    C /= np.linalg.norm(C, axis=1, keepdims=True)
    own = np.concatenate([X[lab == k] @ C[i] for i, k in enumerate(keep)])
    members = [[fit[j] for j in np.where(lab == k)[0]] for k in keep]
    words = tfidf_words([" ".join(ptext(byid[pid]) for pid in m) for m in members])
    # Position sur la carte : projection 2D des centres (figée avec le référentiel).
    XY = umap.UMAP(n_neighbors=10, n_components=2, metric="cosine", min_dist=0.35, spread=1.2, random_state=42).fit_transform(C)
    XY = (XY - XY.min(0)) / (XY.max(0) - XY.min(0))
    sujets = [{"id": f"S{i + 1:03d}", "mots": words[i], "titres": Counter(clean_title(byid[pid]["titres"][-1]) for pid in m).most_common(5),
               "familles": dict(Counter(byid[pid]["fam"] for pid in m)), "n_ref": len(m),
               "x": round(float(XY[i, 0]), 4), "y": round(float(XY[i, 1]), 4)} for i, m in enumerate(members)]
    REF = {"periode": FIT, "modele": MODEL, "seuil": float(np.percentile(own, SEUIL_CENTILE)), "sujets": sujets}
    REFDIR.mkdir(parents=True, exist_ok=True)
    (REFDIR / "referentiel.json").write_text(json.dumps(REF, ensure_ascii=False, indent=1), encoding="utf-8")
    np.save(REFDIR / "centres.npy", C.astype(np.float16))
    log(f"référentiel créé : {len(sujets)} sujets, seuil {REF['seuil']:.3f}")
else:
    REF = json.loads((REFDIR / "referentiel.json").read_text(encoding="utf-8"))
    C = np.load(REFDIR / "centres.npy").astype(np.float32)
    C /= np.linalg.norm(C, axis=1, keepdims=True)
NOMS = json.loads((REFDIR / "noms.json").read_text(encoding="utf-8")) if (REFDIR / "noms.json").exists() else {}
SEUIL = REF["seuil"]

# ---------- 4. Rattachement ----------
S = E[[row[pid] for pid in eligible]] @ C.T
best, score = S.argmax(1), S.max(1)
assigned = {pid: int(b) for pid, b, sc in zip(eligible, best, score) if sc >= SEUIL}
log(f"rattachés : {len(assigned)}/{len(eligible)} ({len(assigned) / max(1, len(eligible)):.0%})")

# ---------- 5. Sujets émergents ----------
# Chaque mois, TOUS les passages sont regroupés (liaison complète : toutes les paires d'un groupe
# sont aussi proches qu'un passage de son sujet). Un groupe dense trop loin de tout sujet existant
# est un candidat, même si ses passages ont été rangés ailleurs (absorbés par un sujet voisin).
by_month = defaultdict(list)
for pid in eligible:
    by_month[byid[pid]["d"][:7]].append(pid)
groups = []
for month, ids in sorted(by_month.items()):
    if len(ids) < 3:
        continue
    X = E[[row[pid] for pid in ids]]
    lab = AgglomerativeClustering(n_clusters=None, distance_threshold=1 - SEUIL, metric="cosine", linkage="complete").fit_predict(X)
    for k, n in Counter(lab).items():
        comp = [ids[j] for j in np.where(lab == k)[0]]
        seances = {byid[pid]["s"] for pid in comp}
        grp = {g for pid in comp for g in chars_by_group(byid[pid]) if g not in ("GOUV", "?")}
        if n >= 3 and len(seances) >= 2 and len(grp) >= 2:
            c = X[lab == k].mean(0)
            c /= np.linalg.norm(c)
            sims = C @ c
            groups.append((month, comp, float(sims.max()), sorted(grp)))
ref_sims = [g[2] for g in groups if FIT[0] <= g[0] <= FIT[1]]
NOUVEAUTE = float(np.percentile(ref_sims, 5)) if ref_sims else 0.85
cands = [g for g in groups if not FIT[0] <= g[0] <= FIT[1] and g[2] < NOUVEAUTE]


def mnum(m):
    return int(m[:4]) * 12 + int(m[5:7])


cent = [E[[row[pid] for pid in g[1]]].mean(0) for g in cands]
cent = [v / np.linalg.norm(v) for v in cent]
par = list(range(len(cands)))


def root(a):
    while par[a] != a:
        a = par[a]
    return a


for a in range(len(cands)):
    for b in range(a + 1, len(cands)):
        if abs(mnum(cands[a][0]) - mnum(cands[b][0])) <= 2 and cent[a] @ cent[b] >= SEUIL:
            par[root(b)] = root(a)
merged = defaultdict(list)
for a in range(len(cands)):
    merged[root(a)].append(cands[a])
candidats = []
for parts in merged.values():
    ids = list(dict.fromkeys(pid for g in parts for pid in g[1]))
    mois = sorted({g[0] for g in parts})
    v = E[[row[pid] for pid in ids]].mean(0)
    v /= np.linalg.norm(v)
    absorbe = Counter(assigned[pid] for pid in ids if pid in assigned).most_common(1)
    candidats.append({"mois": mois[0], "fin": mois[-1], "ids": ids, "voisin": int((C @ v).argmax()),
                      "titres": Counter(clean_title(byid[pid]["titres"][-1]) for pid in ids).most_common(4),
                      "groupes": sorted({g for p_ in parts for g in p_[3]}),
                      "seances": len({byid[pid]["s"] for pid in ids}),
                      "absorbe": REF["sujets"][absorbe[0][0]]["id"] if absorbe else None,
                      "part_absorbee": round(sum(1 for pid in ids if pid in assigned) / len(ids), 2),
                      "famille": Counter("Budgets" if byid[pid]["fam"] in ("PLF", "PLFSS") else "Questions" for pid in ids).most_common(1)[0][0]})
candidats.sort(key=lambda c: c["mois"])
if candidats:
    for c, w in zip(candidats, tfidf_words([" ".join(ptext(byid[pid]) for pid in c["ids"]) for c in candidats])):
        c["mots"] = w
log(f"sujets émergents : {len(candidats)} (seuil de nouveauté {NOUVEAUTE:.3f})")

# ---------- 6. Thèmes suivis (mots-clés) ----------
THEMES = json.loads((REFDIR / "themes.json").read_text(encoding="utf-8")) if (REFDIR / "themes.json").exists() else []
themes_raw = []
for th in THEMES:
    rx = re.compile(th["mots_cles"], re.I)
    mentions = [(p["id"], k, len(rx.findall(x["t"]))) for p in P for k, x in enumerate(p["paras"])
                if x["r"] in ("depute", "gouvernement") and rx.search(x["t"])]
    themes_raw.append((th, mentions))
    log(f"thème « {th['nom']} » : {len(mentions)} mentions")

# ---------- 7. Export compact ----------
months = sorted({p["d"][:7] for p in P})
mi = {m: i for i, m in enumerate(months)}
seances = sorted({(p["d"], p["s"]) for p in P})
si = {s[1]: i for i, s in enumerate(seances)}
groups_order = sorted(GROUPES) + ["GOUV", "?"]
gi = {g: i for i, g in enumerate(groups_order)}


def gvec(p):
    return {gi[g]: n for g, n in chars_by_group(p).items() if g in gi}


def speaker(x):
    if x["r"] == "depute":
        d = deputes.get(x["a"])
        return {"n": f"{d['prenom']} {d['nom']}" if d else x["nm"], "g": x["g"], "id": x["a"]}
    return {"n": x["nm"], "g": "GOUV" if x["r"] == "gouvernement" else "?", "q": x["q"]}


def extract(pid, k=None):
    """La prise de parole du député (ou le paragraphe k) et, s'il y en a une, la réponse du gouvernement."""
    p = byid[pid]
    paras = p["paras"]
    first = paras[k] if k is not None else next((x for x in paras if x["r"] == "depute" and x["n"] >= 120), paras[0])
    rep = None if k is not None else next((x for x in paras if x["r"] == "gouvernement" and x["n"] >= 120), None)
    e = {"d": p["d"], "s": p["s"], "a": first["x"], "ti": [clean_title(t) for t in p["titres"]][-3:],
         "o": speaker(first), "t": first["t"][:420]}
    if rep:
        e["r"] = {"o": speaker(rep), "t": rep["t"][:300]}
    return e


FAM = ["QAG", "QOSD", "PLF", "PLFSS", "texte"]
textes = Counter(clean_title(p["titres"][0]) for p in P if p["fam"] == "texte" and p["titres"])
texte_list = [t for t, n in textes.most_common() if n >= 5]
ti = {t: i for i, t in enumerate(texte_list)}
rows = []  # [famille, sujet ou texte, mois, séance, {groupe: caractères}]
for p in P:
    if p["fam"] == "texte":
        t = ti.get(clean_title(p["titres"][0])) if p["titres"] else None
        if t is not None:
            rows.append([4, t, mi[p["d"][:7]], si[p["s"]], gvec(p)])
    elif p["id"] in assigned:
        rows.append([FAM.index(p["fam"]), assigned[p["id"]], mi[p["d"][:7]], si[p["s"]], gvec(p)])

by_topic = defaultdict(list)
for pid, t in assigned.items():
    by_topic[t].append(pid)
sujets_out = []
for i, s in enumerate(REF["sujets"]):
    ids = by_topic[i]
    sims = E[[row[pid] for pid in ids]] @ C[i] if ids else np.array([])
    picked, seen = [], set()
    for pid in [ids[j] for j in np.argsort(-sims)] + sorted(ids, key=lambda x: byid[x]["d"], reverse=True):
        if byid[pid]["s"] not in seen:
            picked.append(pid)
            seen.add(byid[pid]["s"])
        if len(picked) >= 24:
            break
    titres = [tuple(t) for t in s["titres"]]
    sujets_out.append({"id": s["id"], "nom": NOMS.get(s["id"], auto_name(titres, s["mots"])), "nomme": s["id"] in NOMS,
                       "mots": s["mots"], "titres": [t for t, _ in titres], "x": s["x"], "y": s["y"],
                       "extraits": [extract(pid) for pid in sorted(picked, key=lambda x: byid[x]["d"])]})

textes_out = []
for t in texte_list:
    ids = [p["id"] for p in P if p["fam"] == "texte" and p["titres"] and clean_title(p["titres"][0]) == t]
    step = max(1, len(ids) // 8)
    textes_out.append({"nom": t, "extraits": [extract(pid) for pid in ids[::step][:8]]})

cand_out = []
for c in candidats:
    near = REF["sujets"][c["voisin"]]
    ang = (zlib.crc32(c["titres"][0][0].encode()) % 360) / 57.3  # décalage stable autour du sujet voisin
    cand_out.append({"nom": auto_name(c["titres"], c["mots"]), "mois": c["mois"], "fin": c["fin"], "famille": c["famille"],
                     "titres": [t for t, _ in c["titres"]], "mots": c["mots"], "groupes": c["groupes"],
                     "seances": c["seances"], "n": len(c["ids"]), "absorbe": c["absorbe"], "part_absorbee": c["part_absorbee"],
                     "x": round(near["x"] + 0.035 * np.cos(ang), 4), "y": round(near["y"] + 0.035 * np.sin(ang), 4),
                     "extraits": [extract(pid) for pid in c["ids"][:6]]})

themes_out = []
for th, mentions in themes_raw:
    trows = []
    for pid, k, n in mentions:
        p = byid[pid]
        x = p["paras"][k]
        trows.append([mi[p["d"][:7]], si[p["s"]], gi.get("GOUV" if x["r"] == "gouvernement" else x["g"], gi["?"]), n])
    appuyees = sorted([m for m in mentions if m[2] >= 2], key=lambda m: byid[m[0]]["d"], reverse=True)
    themes_out.append({"nom": th["nom"], "mots_cles": th["mots_cles"], "mentions": trows,
                       "extraits": [extract(pid, k) for pid, k, _ in appuyees[:30]]})

# Pour la fiche de chaque député : les sujets sur lesquels il parle le plus (caractères prononcés).
dep_topics = defaultdict(Counter)
for pid, t in assigned.items():
    for x in byid[pid]["paras"]:
        if x["r"] == "depute":
            dep_topics[x["a"]][t] += x["n"]
deputes_out = {a: [[t, n] for t, n in c.most_common(8)] for a, c in dep_topics.items()}

out = {
    "deputes": deputes_out,
    "genere": data["generated"], "reference": FIT, "mois": months, "seances": [s[0] for s in seances], "familles": FAM,
    "groupes": [{"id": g, **GROUPES.get(g, {"nom": "Gouvernement" if g == "GOUV" else "Autres orateurs",
                                            "couleur": "#8a8f98" if g == "GOUV" else "#555"})} for g in groups_order],
    "passages": rows, "sujets": sujets_out, "textes": textes_out, "emergents": cand_out, "themes": themes_out,
    "stats": {"eligibles": len(eligible), "rattaches": len(assigned)},
}
raw = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
OUTFILE.write_bytes(gzip.compress(raw, 9))
log(f"{OUTFILE.relative_to(ROOT)} : {len(raw) / 1e6:.1f} Mo ({OUTFILE.stat().st_size / 1e6:.1f} Mo compressé), {time.time() - t0:.0f} s")
