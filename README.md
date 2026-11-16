# Graphe des députés

Site sur les députés de la 17e législature, en deux sections :

- **Liens entre députés** : graphe interactif, fiche complète de chaque député (votes, interventions, intérêts déclarés) ;
- **Sujets débattus** : carte des sujets qui occupent la séance publique, ceux qui reviennent, ceux qui émergent, et les groupes qui les portent.

Le graphe relie les députés :

- **à l'Assemblée** : groupes politiques, commissions, groupes d'études et d'amitié, missions d'information, délégations, organismes extérieurs, partis ;
- **en dehors** : les structures citées dans leurs déclarations d'intérêts à la HATVP (fonctions dirigeantes, participations financières, employeurs des 5 dernières années, activités de conseil, fonctions bénévoles).

Uniquement des données publiques, telles que déclarées, sans interprétation. Un lien n'indique ni conflit d'intérêts ni prise de position.

## Mise à jour automatique

Le workflow [`.github/workflows/update.yml`](.github/workflows/update.yml) s'exécute **tous les jours vers 5 h**, à chaque push sur `main`, et à la demande (onglet *Actions* puis *Run workflow*). Il :

1. télécharge les dernières données de l'Assemblée nationale (députés, organes, scrutins, comptes rendus) et de la HATVP ;
2. reconstruit tout avec `scripts/build_data.py`. Les caches SIREN, vidéo et photos sont conservés d'une exécution à l'autre : seules les nouveautés sont demandées ;
3. calcule la carte des sujets avec `scripts/sujets/run.py`, sur CPU : seuls les passages nouveaux sont encodés. Si le cache des embeddings a disparu, il est repris de la release `sujets-cache` du dépôt (calcul initial fait une fois sur GPU). Si cette étape échoue, le reste du site est publié quand même ;
4. vérifie le résultat (plus de 500 députés, sinon la publication est annulée et l'ancien site reste en ligne) ;
5. publie le dossier `site/` sur GitHub Pages.

Les données générées (`site/data.json`, `site/scrutins.json`, `site/videos.json`, `site/votes/`, `site/interventions/`, `site/photos/`, `site/sujets.json.gz`) ne sont **pas** versionnées : elles sont reconstruites à chaque exécution, pour que le dépôt ne grossisse pas.

## Lancer en local

```bash
python scripts/build_data.py
pip install -r scripts/sujets/requirements.txt   # une fois (torch, sentence-transformers…)
python scripts/sujets/run.py
python -m http.server 5173 --directory site
```

Puis ouvrir http://localhost:5173.

`build_data.py` télécharge toutes les sources dans `raw/` et génère les données du site. Options :
- `--offline` réutilise les fichiers déjà téléchargés dans `raw/` ;
- `--no-siren` saute le rattachement SIREN ;
- `--no-videos` saute la lecture des liens vidéo ;
- `--no-photos` saute le téléchargement des photos.

`scripts/sujets/run.py` utilise le GPU s'il y en a un. Sans cache, le premier calcul encode environ 11 500 passages : quelques minutes sur GPU, plusieurs heures sur CPU.

## Fonctionnalités

- Graphe biparti député ↔ organe (force-directed, rendu canvas).
- Filtres par type de lien et par groupe politique. Un premier clic sur un groupe l'isole.
- Fiche député : fonctions, organes, « députés les plus proches » (nombre d'organes partagés, hors groupe et parti).
- Fiche organe : composition par groupe, membres et fonctions.
- Recherche `Ctrl K` ou `/` (nom, département, organe, entreprise, SIREN).
- **Fiche complète par député** (`#fiche/PA1008`) :
  - identité, fonctions, organes et déclaration d'intérêts ;
  - participation aux scrutins publics et votes alignés sur son groupe, comparés à la médiane de l'Assemblée ;
  - répartition pour / contre / abstention ;
  - proximité de vote : les députés qui votent le plus comme lui, dans et hors de son groupe, et le plus différemment ;
  - tous ses votes, avec recherche et filtres (contre son groupe, votes solennels, motions de censure) et lien vers chaque scrutin ;
  - toutes ses interventions en séance publique, en texte intégral, avec recherche dans ses propos, filtre par texte de loi et lien vers le passage exact du compte rendu officiel.
- **Visages** : en zoomant sur le graphe, chaque député apparaît avec sa photo officielle, cerclée de la couleur de son groupe. En vue d'ensemble, des points, pour rester lisible.
- **Sujets débattus** (`#sujets`) :
  - **Carte** en bulles : chaque bulle est un sujet, placée selon le sens de ce qui s'y dit ; taille selon les mots prononcés sur la période ; couleur selon la famille ou le groupe qui en parle le plus ;
  - **Liste** triable par attention (mots), récurrence (séances), diversité des groupes ou date ;
  - **Émergents** : débats récents qu'aucun sujet n'accueille, y compris ceux absorbés par un sujet voisin ;
  - **Thème suivi** (hébergement d'urgence) et **textes de loi** ;
  - pour chaque sujet : frise mensuelle, répartition de la parole par groupe, extraits avec la question du député, la réponse du ministre et le lien vers le compte rendu.
- La fiche d'un député liste les sujets sur lesquels il intervient ; les extraits de la carte renvoient vers les fiches.
- Liens partageables : `#PA1008` ouvre l'aperçu dans le graphe, `#fiche/PA1008` la fiche complète, `#sujets/carte/S064` un sujet.

## Données

Sources :
- [open data de l'Assemblée nationale](https://data.assemblee-nationale.fr/acteurs/deputes-en-exercice), jeu AMO10 « Députés actifs, mandats actifs et organes » ;
- [open data de la HATVP](https://www.hatvp.fr/open-data/) : `declarations.xml` (toutes les déclarations publiées) et `liste.csv` (pages nominatives).
- photos officielles des députés, © Assemblée nationale, copiées dans `site/photos/` lors de la mise à jour.

### Traitement des déclarations HATVP

- Rattachement au député par nom et date de naissance, sinon par nom et prénom. 530 députés sur 574 ont une déclaration rattachée.
- On garde la dernière déclaration de député déposée.
- Rubriques **exclues volontairement** : l'activité du conjoint et les collaborateurs (personnes privées), ainsi que les mandats électifs (déjà couverts par l'Assemblée).
- Les noms sont saisis librement par les déclarants. Le script les nettoie : il retire les mentions « [Données non publiées] » et les formes juridiques (SA, SAS, SCI…), et ignore les libellés génériques (« Individuel », « Néant »…).
- Les variantes connues d'un même nom sont fusionnées (« TotalEnergies » et « TOTAL ENERGIES »).
- Les instances locales au nom ambigu (« SDIS », « CCAS », « Commission départementale… ») ne sont jamais fusionnées entre députés.
- Les structures non nommées (SCI privées, par exemple) sont comptées dans la fiche, mais pas reliées.
- **Rattachement au SIREN** via l'[API Recherche d'entreprises](https://recherche-entreprises.api.gouv.fr), avec une règle volontairement stricte :
  - pour une quarantaine de grands groupes cotés, dont la raison sociale officielle diffère du nom d'usage (« L'Air Liquide société anonyme pour l'étude… »), une table de SIREN vérifiés est utilisée ;
  - sinon, le SIREN n'est retenu que si **une seule** entreprise active porte exactement le nom déclaré (après normalisation). Les homonymes et les correspondances approximatives restent sans SIREN ;
  - un nom d'un seul mot n'est jamais rattaché automatiquement : « Gouvernement », « Hôpital » ou « MAIF » renvoyaient à des SCI homonymes. Les vrais groupes d'un seul mot (Airbus, Enedis, Framatome…) sont dans la table vérifiée ;
  - une « SCI X », une EARL ou un GAEC n'est jamais retenu pour un « X » déclaré sans cette forme juridique ;
  - les banques mutualistes (Crédit Agricole, Caisse d'épargne, Crédit Mutuel) ne sont pas rattachées : leurs « parts » désignent souvent une caisse locale ;
  - les structures qui partagent un SIREN sont fusionnées en un seul nœud ;
  - les réponses de l'API sont mises en cache dans `raw/siren_cache.json`. `--no-siren` désactive l'étape.
- Par défaut, le graphe ne montre que les structures citées par au moins deux députés. Une option affiche les autres.

### Votes

Source : [scrutins publics de la 17e législature](https://data.assemblee-nationale.fr/travaux-parlementaires/votes) (`Scrutins.json.zip`).

- `site/scrutins.json` liste les scrutins (date, titre, résultat, type). `site/votes/PAxxxx.json` contient, pour chaque député, sa position sur chaque scrutin et la position majoritaire de son groupe. Ces fichiers ne sont chargés qu'à l'ouverture d'une fiche.
- **Participation** : scrutins où le député a voté pour, contre ou abstention, rapportés aux scrutins tenus depuis son entrée en fonction. Un vote par délégation compte comme un vote.
- **Vote aligné** : même position que la position majoritaire de son groupe sur ce scrutin.
- **Proximité de vote** : part des scrutins où deux députés ont voté la même chose, parmi ceux où les deux ont voté. Il faut au moins 150 scrutins en commun.
- Les « mises au point » (« je voulais voter autrement ») ne sont pas prises en compte : seul le vote officiel compte.
- Seuls les scrutins publics sont nominatifs. Les votes à main levée, majoritaires sur les amendements, ne sont pas connus individuellement, et une absence n'est pas un vote contre.

### Interventions en séance

Source : [comptes rendus intégraux des séances publiques](https://data.assemblee-nationale.fr/travaux-parlementaires/debats) (format Syceron, `syseron.xml.zip`).

- Une intervention regroupe les paragraphes consécutifs d'un même député, sous un même point de l'ordre du jour. Chaque intervention est rattachée au texte débattu et à son contexte (article, « après l'article 8 »…), avec un lien vers son ancre dans le compte rendu officiel.
- La présidence de séance est exclue. Les didascalies (« Applaudissements sur les bancs… ») sont retirées du texte.
- Les **interjections**, lancées depuis les bancs sans avoir la parole, sont marquées à part et masquées par défaut. Les fragments de moins de 40 caractères (« Très bien ! ») sont ignorés.
- Le texte intégral est conservé dans `site/interventions/PAxxxx.json.gz`, un fichier compressé par député, décompressé par le navigateur à l'ouverture de l'onglet. Il servira à comparer les propos et les votes.
- Les comptes rendus couvrent la séance publique, pas les commissions.
- **Vidéo** : le lien vers la vidéo officielle de chaque séance est lu sur la page publique de son compte rendu, car il n'est pas dans les données ouvertes. L'horodatage de chaque intervention (`stime`, en secondes depuis le début de l'enregistrement) permet d'ouvrir la vidéo au bon moment, 3 secondes avant la prise de parole. Lecture avec [hls.js](https://github.com/video-dev/hls.js) 1.5.13, chargé seulement au premier clic.

Limites :
- Seuls les mandats en cours sont pris en compte.
- « Proche » veut seulement dire que deux députés siègent dans les mêmes organes de l'Assemblée. Ce n'est pas une affinité politique.
- Le nettoyage des noms est automatique. Il peut rester des doublons (« Air Liquide » et « Air Liquide prime de fidélité ») ou, plus rarement, des fusions abusives. La fiche renvoie toujours vers la déclaration d'origine sur hatvp.fr.

### Sujets débattus

Code : `scripts/sujets/`. Référentiel figé : `data/sujets/`.

- **Passages** : une question au gouvernement ou une question orale avec la réponse du ministre, ou un segment de débat entre deux mises aux voix. La présidence de séance est retirée.
- **Sujets automatiques** seulement pour les questions et les budgets (PLF, PLFSS) : leurs intitulés officiels ne disent pas le sujet (« Article 5 », un sous-titre par question). Les autres textes gardent leur intitulé officiel.
- **Référentiel figé** : sujets appris une fois sur octobre 2025 à février 2026 (embeddings `BAAI/bge-m3`, regroupement agglomératif déterministe), puis figés avec un identifiant stable (`S001`…) et une position sur la carte. Un nouveau passage rejoint le sujet le plus proche si sa similarité dépasse le 5ᵉ centile des membres du sujet.
- **Sujets émergents** : chaque mois, tous les passages sont regroupés ; un groupe dense (3 passages, 2 séances, 2 groupes politiques au moins) plus éloigné de tout sujet que 95 % des groupes de la période de référence est signalé.
- **Thèmes suivis** (`data/sujets/themes.json`) : un sujet transversal se suit par mots-clés, pas par une bulle.
- **Noms** : proposés automatiquement (sous-titre officiel le plus fréquent, sinon mots-clés). Les noms relus se mettent dans `data/sujets/noms.json`.
- **Test de faisabilité** (avant le développement) : sur deux mois tests, environ 70 % des nouveaux passages rattachés avec confiance, dont 85 à 90 % justes (relecture de 140 cas) ; les événements nouveaux connus (crise en Iran, intervention au Venezuela, lait infantile contaminé) ressortent comme émergents. Une recherche sémantique des sujets transversaux a été testée puis écartée : 3 résultats pertinents sur 10.
- **Limites** : groupes politiques actuels, pas ceux du jour de la séance ; questions orales, souvent locales, moins bien couvertes.

## Accessibilité

- Navigation au clavier : lien d'évitement, recherche `Ctrl K` avec flèches, bulles de la carte activables au clavier, `Échap` pour fermer.
- Contraste du texte conforme WCAG AA (4,5:1 au moins), mouvements réduits si le système le demande.
- Mobile : navigation en haut, filtres dans un panneau à ouvrir, fiches en feuille glissante.

## Stack

HTML, CSS et JS sans framework. [force-graph](https://github.com/vasturiano/force-graph) 1.43.5 et hls.js 1.5.13 sont inclus dans `site/vendor/`. Le script de données est en Python, sans dépendance ; la carte des sujets utilise `sentence-transformers` et `scikit-learn`.

## Pistes

- Rattacher davantage de structures au SIREN (correspondance approximative relue à la main).
- Ajouter un historique des législatures précédentes.
- Relire les noms des sujets (`data/sujets/noms.json`) et valider les sujets émergents pour les ajouter au référentiel.
- Groupes politiques à la date de chaque séance (historique des appartenances).
