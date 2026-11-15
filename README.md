# Graphe des députés

Carte interactive des liens entre les députés de la 17e législature et les organes dont ils sont membres : groupes politiques, commissions, groupes d'études et d'amitié, missions d'information, délégations, organismes extérieurs, partis.

Uniquement des données publiques, sans interprétation.

## Lancer en local

```bash
python scripts/build_data.py
python -m http.server 5173 --directory site
```

Puis ouvrir http://localhost:5173.

`build_data.py` télécharge l'export officiel et produit `site/data.json`. Avec `--offline`, il réutilise `raw/amo.zip` déjà téléchargé.

## Fonctionnalités

- Graphe biparti député ↔ organe (force-directed, rendu canvas).
- Filtres par type de lien et par groupe politique. Un premier clic sur un groupe l'isole.
- Fiche député : fonctions, organes, « députés les plus proches » (nombre d'organes partagés, hors groupe et parti).
- Fiche organe : composition par groupe, membres et fonctions.
- Recherche `Ctrl K` ou `/` (nom, département, organe).
- Liens partageables : `#PA1008` ouvre directement une fiche.

## Données

Source : [open data de l'Assemblée nationale](https://data.assemblee-nationale.fr/acteurs/deputes-en-exercice), jeu AMO10 « Députés actifs, mandats actifs et organes ».

Limites :
- Seuls les mandats en cours sont pris en compte.
- « Proche » veut seulement dire que deux députés siègent dans les mêmes organes. Ce n'est pas une affinité politique.

## Stack

HTML, CSS et JS sans framework. [force-graph](https://github.com/vasturiano/force-graph) 1.43.5 est inclus dans `site/vendor/`. Le script de données est en Python, sans dépendance.

## Pistes

- Ajouter les déclarations d'intérêts (HATVP) et les entreprises (RNE).
- Ajouter les votes (scrutins publics) pour mesurer la proximité de vote.
- Ajouter un historique des législatures précédentes.
