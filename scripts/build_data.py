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
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.parse
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
    "SOCIETE IMMOBILIERE", "SOCIETE CIVILE IMMOBILIERE",
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


# ---------------------------------------------------------------------------
# SIREN : rapprochement avec l'API publique Recherche d'entreprises
# https://recherche-entreprises.api.gouv.fr (sans clé, 7 requêtes/s max)
# ---------------------------------------------------------------------------

SIREN_API = "https://recherche-entreprises.api.gouv.fr/search"
SIREN_CACHE = ROOT / "raw" / "siren_cache.json"

# Grands groupes dont la raison sociale officielle diffère du nom d'usage
# (« L'AIR LIQUIDE SOCIETE ANONYME POUR L'ETUDE… »). SIREN vérifiés via l'API.
# Banques mutualistes exclues : leurs « parts » désignent souvent une caisse locale.
KNOWN_SIREN = {
    "AIRLIQUIDE": "552096281", "TOTALENERGIES": "542051180", "LOREAL": "632012100",
    "LVMH": "775670417", "LVMHMOETHENNESSYLOUISVUITTON": "775670417", "BNPPARIBAS": "662042449",
    "ORANGE": "380129866", "AXA": "572093920", "ENGIE": "542107651", "SAFRAN": "562082909",
    "MICHELIN": "855200887", "SCHNEIDERELECTRIC": "542048574", "RENAULT": "441639465",
    "SOCIETEGENERALE": "552120222", "THALES": "552059024", "SAINTGOBAIN": "542039532",
    "DANONE": "552032534", "BOUYGUES": "572015246", "VEOLIA": "403210032",
    "VEOLIAENVIRONNEMENT": "403210032", "PERNODRICARD": "582041943", "ALSTOM": "389058447",
    "AIRFRANCE": "420495178", "ADP": "552016628", "AEROPORTSDEPARIS": "552016628",
    "SANOFI": "395030844", "VINCI": "552037806", "CAPGEMINI": "330703844", "KERING": "552075020",
    "HERMES": "572076396", "HERMESINTERNATIONAL": "572076396", "ESSILORLUXOTTICA": "712049618",
    "CARREFOUR": "652014051", "DASSAULTSYSTEMES": "322306440", "PUBLICIS": "542080601",
    "PUBLICISGROUPE": "542080601", "LEGRAND": "421259615", "ACCOR": "602036444",
    "EIFFAGE": "709802094", "EDF": "552081317", "ELECTRICITEDEFRANCE": "552081317",
    "SNCF": "552049447", "LAPOSTE": "356000000",
    # Noms d'un seul mot confirmés à la main (activité et siège cohérents).
    "AIRBUS": "383474814", "ATLANPOLE": "254401839", "CARBIOS": "531530228",
    "DEEZER": "898969852", "ENEDIS": "444608442", "ENERCOOP": "484223094",
    "EUROAPI": "890974413", "FRAMATOME": "379041395", "IPAG": "784280802",
    "KALRAY": "507620557", "LIDL": "343262622", "MACIF": "781452511",
    "MANUTAN": "334668852", "NICOX": "403942642", "RECONQUETE": "900676032",
    "SOITEC": "384711909", "VALLOUREC": "552142200", "VANTIVA": "333773174",
    "VIRIDIEN": "969202241",
}
# Formes juridiques qui signalent une petite structure patrimoniale ou agricole :
# « SCI ARDENNES DEVELOPPEMENT » n'est pas l'agence « Ardennes Développement ».
SMALL_FORMS = {"SCI", "EARL", "GAEC", "SCEA", "GFA", "SC"}
# « AIR LIQUIDE PRIME DE FIDELITE », « SANOFI ACTIONS » : même groupe.
KNOWN_SUFFIXES = ("PRIMEDEFIDELITE", "PRIMEFIDELITE", "PRIME", "ACTIONS", "ACTION", "GROUPE", "GROUP")


def company_tokens(s):
    s = re.sub(r"\([^)]*\)", " ", s or "")
    return re.sub(r"[^A-Z0-9 ]", " ", strip_accents(s).upper().replace(".", "")).split()


def company_words(s):
    return [w for w in company_tokens(s) if w not in LEGAL_FORMS]


def norm_company(s):
    """Nom comparable : sans accents, parenthèses, ponctuation ni forme juridique."""
    s = re.sub(r"\([^)]*\)", " ", s or "")
    s = re.sub(r"[^A-Z0-9 ]", " ", strip_accents(s).upper())
    return "".join(w for w in s.split() if w not in LEGAL_FORMS)


_rate_lock = threading.Lock()
_last_call = [0.0]


def _throttle(per_second=6):
    """Espace les appels à l'API, même depuis plusieurs threads."""
    with _rate_lock:
        wait = _last_call[0] + 1 / per_second - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def prefetch_sirens(labels, cache, workers=6):
    """Remplit le cache en parallèle (la latence réseau domine, pas le débit)."""
    todo = sorted({strip_accents(l) for l in labels} - set(cache))
    if not todo:
        return
    print(f"  SIREN : {len(todo)} recherches à faire")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(lambda q: search_siren(q, cache), todo):
            done += 1
            if done % 200 == 0:
                print(f"  SIREN : {done}/{len(todo)}")
                SIREN_CACHE.write_text(json.dumps(dict(cache), ensure_ascii=False), encoding="utf-8")


def search_siren(label, cache):
    q = strip_accents(label)
    if q in cache:
        return cache[q]
    _throttle()
    url = SIREN_API + "?" + urllib.parse.urlencode({"q": q, "per_page": 10})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                res = json.loads(r.read().decode("utf-8")).get("results", [])
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + attempt * 2)
                _throttle()
                continue
            res = []
            break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2)
    else:
        return None  # échec réseau : non mis en cache, retenté au prochain lancement
    cache[q] = [
        {
            "siren": x["siren"],
            "nom": x.get("nom_raison_sociale") or x.get("nom_complet"),
            "complet": x.get("nom_complet"),
            "actif": x.get("etat_administratif") == "A",
            "naf": x.get("activite_principale"),
            "commune": (x.get("siege") or {}).get("libelle_commune"),
        }
        for x in res
    ]
    return cache[q]


def resolve_siren(key, label, cache):
    """SIREN si la correspondance est sûre, sinon None.

    Règle : table des grands groupes, sinon une seule entreprise active dont la
    raison sociale normalisée est exactement le nom déclaré. Plusieurs homonymes
    actifs = ambigu = pas de rattachement.
    """
    if key in KNOWN_SIREN:
        return KNOWN_SIREN[key], None
    for k, siren in KNOWN_SIREN.items():
        rest = key[len(k):]
        if key.startswith(k) and rest in KNOWN_SUFFIXES:
            return siren, None
    if "#" in key or len(key) < 3:
        return None, None
    # Un nom d'un seul mot (« Gouvernement », « Hôpital », « MAIF ») a presque
    # toujours un homonyme sans rapport : seule la table ci-dessus fait foi.
    if len(company_words(label)) < 2:
        return None, None
    declared_forms = set(company_tokens(label)) & SMALL_FORMS
    cands = search_siren(label, cache) or []
    exact = {
        c["siren"]: c for c in cands
        if c["actif"] and norm_company(c["nom"]) == key
        and (set(company_tokens(c["nom"])) & SMALL_FORMS) <= declared_forms
    }
    if len(exact) == 1:
        c = next(iter(exact.values()))
        return c["siren"], c
    return None, None


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

    # Rattachement au SIREN, puis fusion des structures qui partagent le même.
    cache = json.loads(SIREN_CACHE.read_text(encoding="utf-8")) if SIREN_CACHE.exists() else {}
    target_of, merged = {}, {}  # clé -> id du nœud ; id -> structure fusionnée
    use_api = "--no-siren" not in sys.argv
    if use_api:
        prefetch_sirens(
            [max(e["labels"], key=e["labels"].get) for k, e in entities.items()
             if "#" not in k and len(k) >= 3 and k not in KNOWN_SIREN],
            cache,
        )
    for i, (key, e) in enumerate(sorted(entities.items())):
        label = max(e["labels"].items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        siren, cand = resolve_siren(key, label, cache) if use_api else (None, None)
        node_id = f"HV:S{siren}" if siren else f"HV:{key}"
        target_of[key] = node_id
        m = merged.setdefault(node_id, {"labels": {}, "siren": siren, "cand": cand})
        for lab, n in e["labels"].items():
            m["labels"][lab] = m["labels"].get(lab, 0) + n
        if use_api and i % 100 == 0:
            print(f"  SIREN : {i}/{len(entities)}")
            SIREN_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    for node_id, m in merged.items():
        if m["siren"] and not m["cand"]:
            # Groupe de la table KNOWN_SIREN : on récupère sa fiche officielle.
            m["cand"] = next((c for c in (search_siren(m["siren"], cache) or []) if c["siren"] == m["siren"]), None)
        label = max(m["labels"].items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        org = {"id": node_id, "kind": "HATVP", "libelle": label, "abrev": None, "couleur": None}
        if m["siren"]:
            c = m["cand"] or {}
            org.update({"siren": m["siren"], "nomOfficiel": c.get("complet"), "naf": c.get("naf"), "commune": c.get("commune")})
        data["organes"].append(org)
    if use_api:
        SIREN_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    # Après fusion, un député peut citer deux fois la même structure au même titre.
    final, seen_links = [], set()
    for l in links:
        l["target"] = target_of[l["target"][3:]]
        k = (l["source"], l["target"], l["kind"])
        if k not in seen_links:
            seen_links.add(k)
            final.append(l)

    data["links"].extend(final)
    data["kinds"].update(HV_KINDS)
    data["kinds"]["HATVP"] = "Structure déclarée (HATVP)"
    data["hatvp"] = {"source": HATVP_XML_URL, "declarants": len(latest)}
    deps_of = {}
    for l in final:
        deps_of.setdefault(l["target"], set()).add(l["source"])
    shared = sum(1 for s in deps_of.values() if len(s) > 1)
    with_siren = sum(1 for m in merged.values() if m["siren"])
    print(f"HATVP : {len(latest)} déclarations rattachées, {len(merged)} structures "
          f"({shared} citées par plusieurs députés, {with_siren} avec SIREN), {len(final)} liens")


if __name__ == "__main__":
    main()
