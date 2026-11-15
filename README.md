# Graphe des députés

Carte interactive des liens entre les députés de la 17e législature :

- **à l'Assemblée** : groupes politiques, commissions, groupes d'études et d'amitié, missions d'information, délégations, organismes extérieurs, partis ;
- **en dehors** : les structures citées dans leurs déclarations d'intérêts à la HATVP (fonctions dirigeantes, participations financières, employeurs des 5 dernières années, activités de conseil, fonctions bénévoles).

Uniquement des données publiques, telles que déclarées, sans interprétation. Un lien n'indique ni conflit d'intérêts ni prise de position.

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

Sources :
- [open data de l'Assemblée nationale](https://data.assemblee-nationale.fr/acteurs/deputes-en-exercice), jeu AMO10 « Députés actifs, mandats actifs et organes » ;
- [open data de la HATVP](https://www.hatvp.fr/open-data/) : `declarations.xml` (toutes les déclarations publiées) et `liste.csv` (pages nominatives).

### Traitement des déclarations HATVP

- Rattachement au député par nom et date de naissance, sinon par nom et prénom. 530 députés sur 574 ont une déclaration rattachée.
- On garde la dernière déclaration de député déposée.
- Rubriques **exclues volontairement** : l'activité du conjoint et les collaborateurs (personnes privées), ainsi que les mandats électifs (déjà couverts par l'Assemblée).
- Les noms sont saisis librement par les déclarants. Le script les nettoie : il retire les mentions « [Données non publiées] » et les formes juridiques (SA, SAS, SCI…), et ignore les libellés génériques (« Individuel », « Néant »…).
- Les variantes connues d'un même nom sont fusionnées (« TotalEnergies » et « TOTAL ENERGIES »).
- Les instances locales au nom ambigu (« SDIS », « CCAS », « Commission départementale… ») ne sont jamais fusionnées entre députés.
- Les structures non nommées (SCI privées, par exemple) sont comptées dans la fiche, mais pas reliées.
- Par défaut, le graphe ne montre que les structures citées par au moins deux députés. Une option affiche les autres.

Limites :
- Seuls les mandats en cours sont pris en compte.
- « Proche » veut seulement dire que deux députés siègent dans les mêmes organes de l'Assemblée. Ce n'est pas une affinité politique.
- Le nettoyage des noms est automatique. Il peut rester des doublons (« Air Liquide » et « Air Liquide prime de fidélité ») ou, plus rarement, des fusions abusives. La fiche renvoie toujours vers la déclaration d'origine sur hatvp.fr.

## Stack

HTML, CSS et JS sans framework. [force-graph](https://github.com/vasturiano/force-graph) 1.43.5 est inclus dans `site/vendor/`. Le script de données est en Python, sans dépendance.

## Pistes

- Relier les structures HATVP à leur SIREN (RNE) pour fiabiliser les fusions.
- Ajouter les votes (scrutins publics) pour mesurer la proximité de vote.
- Ajouter un historique des législatures précédentes.
