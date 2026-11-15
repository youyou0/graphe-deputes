"""Construit site/data.json à partir de l'open data de l'Assemblée nationale.

Source : AMO10 « Députés actifs, mandats actifs et organes » (17e législature)
https://data.assemblee-nationale.fr/acteurs/deputes-en-exercice

Usage :
    python scripts/build_data.py            # télécharge puis construit
    python scripts/build_data.py --offline  # réutilise raw/amo.zip
"""
import io
import json
import sys
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(deputes)} députés, {len(orgs)} organes, {len(links)} liens -> {OUT}")


if __name__ == "__main__":
    main()
