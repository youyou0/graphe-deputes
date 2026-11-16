"""Découpe les comptes rendus de séance (Syceron) en passages : l'unité de la carte des sujets.

Un passage est :
- une question au gouvernement ou une question orale, avec la réponse du ministre ;
- ou un segment de débat entre deux mises aux voix, coupé au-delà de 4 000 caractères
  entre deux orateurs.

On garde les députés, les ministres et les autres orateurs (rapporteurs, anciens députés).
La présidence de séance est retirée, y compris ses « La parole est à… » qui n'ont pas
toujours le rôle `president` dans les XML.
"""
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter

NS = "{http://schemas.assemblee-nationale.fr/referentiel}"
MAX_CHARS = 4000
VOTE_RE = re.compile(r"^Je mets aux voix")
GOUV_RE = re.compile(r"ministre|secrétaire d’État|secrétaire d'État|garde des sceaux", re.I)


def txt(el):
    """Texte d'un élément, sans les didascalies en italique."""
    if el is None:
        return ""
    out = []

    def walk(e, skip=False):
        skip = skip or e.tag == NS + "italique"
        if e.text and not skip:
            out.append(e.text)
        for c in e:
            walk(c, skip)
            if c.tail:
                out.append(c.tail)

    walk(el)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def famille(titres):
    t = (titres[0] if titres else "").lower()
    if t.startswith("questions au gouvernement"):
        return "QAG"
    if t.startswith("questions orales sans débat"):
        return "QOSD"
    if "loi de finances" in t:
        return "PLF"
    if "financement de la sécurité sociale" in t:
        return "PLFSS"
    return "texte"


def key(p):
    """Clé stable d'un passage (cache des embeddings) : séance, premier et dernier paragraphe."""
    return f"{p['s']}|{p['paras'][0]['x']}|{p['paras'][-1]['x']}"


def build(debats_zip, deputes, groupes):
    """deputes : {id: député de data.json} ; groupes : {id d'organe: abréviation}."""
    passages = []
    stats = Counter()
    z = zipfile.ZipFile(debats_zip)
    for name in sorted(z.namelist()):
        if not name.endswith(".xml"):
            continue
        root = ET.fromstring(z.read(name))
        raw = root.findtext(f"{NS}metadonnees/{NS}dateSeance") or ""
        day = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        uid = root.findtext(f"{NS}uid")
        contenu = root.find(f"{NS}contenu")
        if contenu is None:
            continue
        presidents = {p.get("id_acteur") for p in contenu.iter(NS + "paragraphe") if p.get("roledebat") == "president"}
        stack, cur = [], None

        def close():
            if cur and cur["paras"]:
                passages.append(cur)

        for el in contenu.iter():
            if el.tag == NS + "point":
                lvl = int(el.get("nivpoint") or 1)
                title = txt(el.find(NS + "texte"))
                if title:
                    stack = stack[: lvl - 1] + [""] * max(0, lvl - 1 - len(stack)) + [title]
                close()
                cur = {"s": uid, "d": day, "titres": [t for t in stack if t], "paras": [], "suite": 0}
                continue
            if el.tag != NS + "paragraphe" or cur is None:
                continue
            a = el.get("id_acteur")
            t = txt(el.find(NS + "texte"))
            code = el.get("code_grammaire") or ""
            if a in presidents or el.get("roledebat") == "president":
                stats["presidence"] += 1
                if VOTE_RE.match(t):
                    close()
                    cur = {"s": uid, "d": day, "titres": cur["titres"], "paras": [], "suite": 0}
                continue
            if not a or not t or code.startswith("INTERRUPTION"):
                continue
            nom = (el.findtext(f"{NS}orateurs/{NS}orateur/{NS}nom") or "").strip()
            qual = (el.findtext(f"{NS}orateurs/{NS}orateur/{NS}qualite") or "").strip()
            if a in deputes and not GOUV_RE.search(qual):
                role, grp = "depute", groupes.get(deputes[a]["groupe"], "?")
            elif GOUV_RE.search(qual):
                role, grp = "gouvernement", "GOUV"
            else:
                role, grp = "autre", "?"
            stats[role] += 1
            if (famille(cur["titres"]) not in ("QAG", "QOSD") and cur["paras"] and cur["paras"][-1]["a"] != a
                    and sum(p["n"] for p in cur["paras"]) + len(t) > MAX_CHARS):
                close()
                cur = {"s": uid, "d": day, "titres": cur["titres"], "paras": [], "suite": cur["suite"] + 1}
            cur["paras"].append({"a": a, "x": el.get("id_syceron"), "nm": nom[:60], "r": role, "g": grp,
                                 "q": qual[:60], "t": t, "n": len(t)})
        close()

    out = []
    for p in passages:
        p["fam"] = famille(p["titres"])
        p["n"] = sum(x["n"] for x in p["paras"])
        if p["n"] >= 200:
            p["id"] = len(out)
            out.append(p)
    return out, stats
