"""Construit site/data.json à partir de l'open data de l'Assemblée nationale.

Source : AMO10 « Députés actifs, mandats actifs et organes » (17e législature)
https://data.assemblee-nationale.fr/acteurs/deputes-en-exercice

Usage :
    python scripts/build_data.py            # télécharge puis construit
    python scripts/build_data.py --offline  # réutilise raw/amo.zip
"""
import csv
import io
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw" / "amo.zip"
OUT = ROOT / "site" / "data.json"
URL = (
    "https://data.assemblee-nationale.fr/static/openData/repository/17/amo/"
    "deputes_actifs_mandats_actifs_organes/"
    "AMO10_deputes_actifs_mandats_actifs_organes.json.zip"
)

# Types d'organes conservés dans le graphe, et leur libellé lisible.
KINDS = {
    "GP": "Groupe politique",
    "COMPER": "Commission permanente",
    "GE": "Groupe d'études",
    "GA": "Groupe d'amitié",
    "MISINFO": "Mission d'information",
    "PARPOL": "Parti politique",
    "ORGEXTPARL": "Organisme extérieur",
    "DELEG": "Délégation",
    "OFFPAR": "Office parlementaire",
    "API": "Assemblée internationale",
}


def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def load_zip():
    if "--offline" not in sys.argv:
        RAW.parent.mkdir(parents=True, exist_ok=True)
        print("Téléchargement…", URL)
        with urllib.request.urlopen(URL) as r:
            RAW.write_bytes(r.read())
    return zipfile.ZipFile(io.BytesIO(RAW.read_bytes()))


def main():
    z = load_zip()
    acteurs, organes = [], {}
    for name in z.namelist():
        if not name.endswith(".json"):
            continue
        doc = json.loads(z.read(name).decode("utf-8"))
        if "/acteur/" in name:
            acteurs.append(doc["acteur"])
        elif "/organe/" in name:
            o = doc["organe"]
            organes[o["uid"]] = o

    deputes, used_orgs, links = [], {}, []
    for a in acteurs:
        uid = a["uid"]["#text"] if isinstance(a["uid"], dict) else a["uid"]
        ident = a["etatCivil"]["ident"]
        naiss = a["etatCivil"].get("infoNaissance") or {}
        mandats = as_list(a["mandats"]["mandat"])

        mandat_an = next(
            (m for m in mandats if m["typeOrgane"] == "ASSEMBLEE" and not m.get("dateFin")),
            None,
        )
        if mandat_an is None:
            continue
        lieu = (mandat_an.get("election") or {}).get("lieu") or {}

        groupe = None
        roles = {}  # organeRef -> meilleure qualité
        for m in mandats:
            if m.get("dateFin") or m["typeOrgane"] not in KINDS:
                continue
            ref = m["organes"]["organeRef"]
            ref = ref[0] if isinstance(ref, list) else ref
            if ref not in organes:
                continue
            qual = (m.get("infosQualite") or {}).get("libQualiteSex") or "Membre"
            if m["typeOrgane"] == "GP":
                groupe = ref
            prev = roles.get(ref)
            # On garde la fonction la plus « haute » (tout sauf membre simple).
            if prev is None or prev.lower().startswith("membre"):
                roles[ref] = qual

        for ref, qual in roles.items():
            used_orgs[ref] = organes[ref]
            links.append({"source": uid, "target": ref, "role": qual})

        prof = a.get("profession") or {}
        deputes.append(
            {
                "id": uid,
                "civ": ident["civ"],
                "prenom": ident["prenom"],
                "nom": ident["nom"],
                "groupe": groupe,
                "dep": lieu.get("departement"),
                "numDep": lieu.get("numDepartement"),
                "circo": lieu.get("numCirco"),
                "region": lieu.get("region"),
                "naissance": naiss.get("dateNais"),
                "profession": prof.get("libelleCourant"),
                "debut": mandat_an.get("dateDebut"),
            }
        )

    orgs = []
    for ref, o in used_orgs.items():
        orgs.append(
            {
                "id": ref,
                "kind": o["codeType"],
                "libelle": o["libelle"],
                "abrev": o.get("libelleAbrev") or o.get("libelleAbrege"),
                "couleur": o.get("couleurAssociee"),
            }
        )

    data = {
        "generated": date.today().isoformat(),
        "source": URL,
        "kinds": KINDS,
        "deputes": sorted(deputes, key=lambda d: (d["nom"], d["prenom"])),
        "organes": sorted(orgs, key=lambda o: (o["kind"], o["libelle"])),
        "links": links,
    }
    add_hatvp(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(deputes)} députés, {len(orgs)} organes, {len(links)} liens -> {OUT}")


# ---------------------------------------------------------------------------
# HATVP : déclarations d'intérêts et d'activités des députés
# https://www.hatvp.fr/open-data/
# ---------------------------------------------------------------------------

HATVP_XML_URL = "https://www.hatvp.fr/livraison/merge/declarations.xml"
HATVP_CSV_URL = "https://www.hatvp.fr/livraison/opendata/liste.csv"
HATVP_XML = ROOT / "raw" / "hatvp_declarations.xml"
HATVP_CSV = ROOT / "raw" / "hatvp_liste.csv"

# Rubriques retenues. Volontairement exclues : activité du conjoint et
# collaborateurs parlementaires (personnes privées), mandats électifs (déjà
# couverts par l'Assemblée).
HV_SECTIONS = {
    "HV_DIR": ("participationDirigeantDto", "nomSociete"),
    "HV_PART": ("participationFinanciereDto", "nomSociete"),
    "HV_EMP": ("activProfCinqDerniereDto", "employeur"),
    "HV_CONS": ("activConsultantDto", "nomEmployeur"),
    "HV_BEN": ("fonctionBenevoleDto", "nomStructure"),
}
HV_KINDS = {
    "HV_DIR": "Fonction dirigeante",
    "HV_PART": "Participation financière",
    "HV_EMP": "Employeur (5 dernières années)",
    "HV_CONS": "Activité de conseil",
    "HV_BEN": "Fonction bénévole",
}

MASKED = re.compile(r"\[\s*donn[ée]es non publi[ée]es\s*\]", re.I)
LEGAL_FORMS = {
    "SA", "SAS", "SASU", "SARL", "EURL", "SCI", "SCEA", "GAEC", "GFA", "EARL",
    "SNC", "SC", "SCP", "SELARL", "SELAS", "SCM", "SEL", "GIE", "SCOP", "SPFPL",
}
# Libellés qui ne désignent pas une structure identifiable.
GENERIC = {
    "NEANT", "AUCUN", "AUCUNE", "SANS OBJET", "NON", "INDIVIDUEL", "INDEPENDANT",
    "INDEPENDANTE", "ACTIVITE LIBERALE", "LIBERAL", "LIBERALE", "PROFESSION LIBERALE",
    "AUTO ENTREPRENEUR", "AUTOENTREPRENEUR", "MICRO ENTREPRENEUR", "MICRO ENTREPRISE",
    "MICROENTREPRISE", "ENTREPRISE INDIVIDUELLE", "EI", "PARTICULIER", "PARTICULIERS",
    "DIVERS", "NC", "NA", "ND", "X", "SANS", "RETRAITE", "CHOMAGE", "AUTRE",
}
# Libellés qui désignent une structure différente selon le territoire
# (le SDIS de l'Ain n'est pas celui du Var) : jamais fusionnés entre députés.
AMBIGUOUS = {
    "SDIS", "CCAS", "CIAS", "ADIL", "CDG", "CAUE", "SIVOM", "SIVU", "SDE", "SEM", "SPL", "OPH",
    "GFR", "GROUPEMENT FORESTIER", "MAIRIE", "COMMUNE", "VILLE", "CONSEIL MUNICIPAL",
    "CONSEIL DEPARTEMENTAL", "CONSEIL REGIONAL", "DEPARTEMENT", "REGION",
    "COMMUNAUTE DE COMMUNES", "COMMUNAUTE D AGGLOMERATION", "OFFICE DE TOURISME",
    "CENTRE HOSPITALIER", "EHPAD", "ASSOCIATION", "LYCEE", "COLLEGE", "ECOLE",
    "SYNDICAT DES EAUX", "SYNDICAT INTERCOMMUNAL", "MISSION LOCALE", "CAF", "CPAM",
    "CHAMBRE D AGRICULTURE", "CCI", "CHAMBRE DES METIERS", "PARC NATUREL REGIONAL", "PNR",
}
# « Commission départementale de… », « Conseil communal de… » : instances locales
# dont le nom ne dit pas le territoire.
LOCAL_WORDS = re.compile(r"\b(DEPARTEMENTAL|DEPARTEMENTALE|COMMUNAL|COMMUNALE|INTERCOMMUNAL|INTERCOMMUNALE)\b")
# Variantes d'écriture connues d'une même structure (clé sans espaces).
ALIASES = {
    "TOTALENERGIE": "TOTALENERGIES",
    "TOTALENERGIESSE": "TOTALENERGIES",
    "TOTAL": "TOTALENERGIES",
    "PARTIRENAISSANCE": "RENAISSANCE",
    "LAREPUBLIQUEENMARCHE": "ENMARCHE",
    "LAREM": "ENMARCHE",
    "LREM": "ENMARCHE",
    "EUROPEECOLOGIELESVERTS": "EELV",
    "LESECOLOGISTES": "EELV",
    "LESREPUBLICAINS": "LR",
    "PS": "PARTISOCIALISTE",
    "LFI": "LAFRANCEINSOUMISE",
    "RN": "RASSEMBLEMENTNATIONAL",
    "POLEEMPLOI": "FRANCETRAVAIL",
}
GENERIC_KEYS = {"AUTOENTREPRISE", "AUTOENTREPRENEUR", "MICROENTREPRISE", "MICROENTREPRENEUR", "FREELANCE"}


def strip_accents(s):
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


def name_key(s):
    return re.sub(r"[^a-z]", "", strip_accents(s or "").lower())


def clean_label(raw):
    """Nettoie un nom de structure saisi librement. Renvoie (libellé, clé) ou None."""
    s = MASKED.sub(" ", raw or "")
    s = re.split(r"\s:\s|\n", s.strip())[0]  # « Nom : adresse », retours à la ligne
    s = re.sub(r"\s+", " ", s).strip(" -,.;/")
    if not s:
        return None
    key = re.sub(r"[^A-Z0-9 ]", " ", strip_accents(s).upper())
    words = [w for w in key.split() if w not in LEGAL_FORMS]
    spaced = " ".join(words)
    if len(spaced) < 2 or spaced in GENERIC:
        return None
    # Sans espaces : « TOTAL ENERGIES » et « TotalEnergies » donnent la même clé.
    key = "".join(words)
    key = ALIASES.get(key, key)
    if key in GENERIC_KEYS:
        return None
    if spaced in AMBIGUOUS or LOCAL_WORDS.search(spaced):
        key += "#"  # rendu unique par député dans add_hatvp
    return s, key


def year(s):
    m = re.search(r"(\d{4})", s or "")
    return m.group(1) if m else None


def period(it):
    a, b = year(it.findtext("dateDebut")), year(it.findtext("dateFin"))
    if a and b:
        return a if a == b else f"{a}–{b}"
    if a:
        return f"depuis {a}"
    return None


def short(s, n=90):
    s = re.sub(r"\s+", " ", MASKED.sub("", s or "")).strip(" -,.;")
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(kind, it):
    """Texte court décrivant le lien, tel que déclaré."""
    if kind == "HV_PART":
        parts = []
        ev = (it.findtext("evaluation") or "").strip()
        if re.fullmatch(r"\d+([.,]\d+)?", ev):
            parts.append(f"{int(float(ev.replace(',', '.'))):,} €".replace(",", " "))
        nb = (it.findtext("nombreParts") or "").strip()
        if nb.isdigit():
            parts.append(f"{nb} parts")
        return ", ".join(parts) or None
    text = {
        "HV_DIR": it.findtext("activite"),
        "HV_EMP": it.findtext("description"),
        "HV_CONS": it.findtext("description"),
        "HV_BEN": it.findtext("descriptionActivite"),
    }[kind]
    return ", ".join(x for x in (short(text, 70), period(it)) if x) or None


def fetch(url, path):
    if "--offline" in sys.argv and path.exists():
        return
    print("Téléchargement…", url)
    with urllib.request.urlopen(url) as r:
        path.write_bytes(r.read())


def add_hatvp(data):
    fetch(HATVP_XML_URL, HATVP_XML)
    fetch(HATVP_CSV_URL, HATVP_CSV)

    by_birth = {(name_key(d["nom"]), d["naissance"]): d for d in data["deputes"]}
    by_name = {(name_key(d["nom"]), name_key(d["prenom"])): d for d in data["deputes"]}

    def find(nom, prenom, naissance):
        return by_birth.get((name_key(nom), naissance)) or by_name.get((name_key(nom), name_key(prenom)))

    # Page nominative HATVP de chaque député.
    pages = {}
    with open(HATVP_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["type_mandat"] == "depute" and row["url_dossier"]:
                d = find(row["nom"], row["prenom"], None)
                if d:
                    pages[d["id"]] = "https://www.hatvp.fr" + row["url_dossier"]

    # Dernière déclaration de député déposée par chaque député en exercice.
    latest = {}
    for decl in ET.parse(HATVP_XML).getroot().iter("declaration"):
        g = decl.find("general")
        if g is None or g.findtext("qualiteMandat/codTypeMandatFichier") != "depute":
            continue
        dc = g.find("declarant")
        dn = dc.findtext("dateNaissance") or ""
        iso = "-".join(reversed(dn.split("/"))) if dn.count("/") == 2 else None
        d = find(dc.findtext("nom"), dc.findtext("prenom"), iso)
        if not d:
            continue
        dd = decl.findtext("dateDepot") or ""  # « 29/11/2024 18:54:22 »
        sort_key = dd[6:10] + dd[3:5] + dd[0:2] + dd[11:]
        if d["id"] not in latest or sort_key > latest[d["id"]][0]:
            latest[d["id"]] = (sort_key, decl, dd[:10])

    entities = {}  # clé -> {libellés, députés}
    links, unnamed = [], {}
    for dep_id, (_, decl, depot) in latest.items():
        dep = next(d for d in data["deputes"] if d["id"] == dep_id)
        dep["hatvp"] = {"depot": depot, "page": pages.get(dep_id)}
        seen = set()
        for kind, (section, field) in HV_SECTIONS.items():
            for it in decl.findall(f"{section}/items/items"):
                raw = it.findtext(field)
                cleaned = clean_label(raw)
                if cleaned is None:
                    # Structure non nommée (SCI privée, etc.) : on la compte sans la relier.
                    if raw and MASKED.search(raw):
                        unnamed.setdefault(dep_id, {}).setdefault(kind, 0)
                        unnamed[dep_id][kind] += 1
                    continue
                label, key = cleaned
                if key.endswith("#"):
                    key += dep_id
                desc = describe(kind, it)
                if (kind, key) in seen:
                    continue  # même structure déclarée plusieurs années
                seen.add((kind, key))
                e = entities.setdefault(key, {"labels": {}, "deps": set()})
                e["labels"][label] = e["labels"].get(label, 0) + 1
                e["deps"].add(dep_id)
                links.append({"source": dep_id, "target": "HV:" + key, "kind": kind, "role": desc})

    for dep_id, counts in unnamed.items():
        dep = next(d for d in data["deputes"] if d["id"] == dep_id)
        dep["hatvp"]["masquees"] = counts

    for key, e in entities.items():
        label = max(e["labels"].items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        data["organes"].append({"id": "HV:" + key, "kind": "HATVP", "libelle": label, "abrev": None, "couleur": None})

    data["links"].extend(links)
    data["kinds"].update(HV_KINDS)
    data["kinds"]["HATVP"] = "Structure déclarée (HATVP)"
    data["hatvp"] = {"source": HATVP_XML_URL, "declarants": len(latest)}
    shared = sum(1 for e in entities.values() if len(e["deps"]) > 1)
    print(f"HATVP : {len(latest)} déclarations rattachées, {len(entities)} structures "
          f"({shared} citées par plusieurs députés), {len(links)} liens")


if __name__ == "__main__":
    main()
