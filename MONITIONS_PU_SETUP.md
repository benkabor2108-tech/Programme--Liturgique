# Monitions introductives et prières universelles

## Objectif

Ajouter un espace privé, visible uniquement par l'administrateur principal, qui prépare une proposition de :

- monition introductive ;
- prière universelle complète ;
- document Word A4 prêt à relire et imprimer.

La proposition s'appuie sur les lectures liturgiques récupérées depuis l'API AELF. Le texte reste modifiable avant téléchargement.

## Structure rédactionnelle obligatoire

### Monition introductive

La génération suit toujours l'ordre :

**Accueil → temps liturgique → dimanche/fête célébrée → thème central des textes → courte expression biblique → invitation intérieure.**

Le temps liturgique est toujours mentionné explicitement : Temps de l'Avent, Temps de Noël, Temps du Carême, Triduum pascal, Temps pascal ou Temps ordinaire.

Une seule courte expression biblique est insérée naturellement dans le paragraphe, de préférence à partir de l'Évangile. Elle sert le thème central sans transformer la monition en résumé détaillé des lectures.

### Prière universelle

La génération automatique comprend quatre intentions, toujours dans cet ordre :

1. **L'Église et ses responsables** : pape, évêques, prêtres, diacres, consacrés, catéchistes et serviteurs de l'Évangile.
2. **Les responsables des nations**, avec une mention particulière des responsables du Burkina Faso.
3. **Le monde souffrant** : malades, prisonniers, pauvres, personnes déplacées, personnes isolées, veuves, veufs, orphelins et victimes de violence ou d'injustice.
4. **L'assemblée en prière** : familles, communauté chrétienne et personnes qui auraient voulu participer mais n'ont pas pu venir.

Chaque intention peut reprendre une courte expression biblique appropriée tirée de la première lecture, du psaume, de la deuxième lecture ou de l'Évangile. La citation reste brève et cohérente avec la catégorie de l'intention. Si aucun extrait n'est vraiment adapté, la rédaction utilise uniquement une reformulation fidèle au thème des textes.

L'introduction et la conclusion de la prière universelle sont préparées séparément afin de pouvoir être relues ou proclamées par le célébrant selon l'usage de la paroisse.

## Disponibilité et préparation automatique

- **Dimanche à venir** : la proposition est préparée automatiquement à partir du mardi précédent à **18 h 00**, heure de Ouagadougou.
- **Grandes fêtes et événements** : la proposition est préparée automatiquement à **J-5 à partir de 18 h 00**.
- Le workflow GitHub Actions passe à 18 h 00, 18 h 15 et 18 h 45 pour rattraper un éventuel retard ponctuel du scheduler ou une indisponibilité temporaire de la source AELF.
- Un brouillon déjà présent n'est jamais écrasé automatiquement : toute correction pastorale faite par l'administrateur principal est préservée.
- Les repères automatiques suivent le calendrier romain ; si une célébration est transférée localement, l'administrateur peut choisir « Autre date liturgique » et utiliser la préparation manuelle de l'onglet.

Quand l'administrateur principal ouvre l'onglet après la préparation automatique, la monition et la prière universelle sont déjà présentes. Le bouton de préparation manuelle reste disponible comme solution de secours ou pour une autre date liturgique.

## Accès

L'onglet `📝 Monitions & P.U.` est injecté dans la barre d'onglets uniquement lorsque le rôle courant est `principal`.

Il n'est donc pas visible :

- en mode consultation ;
- pour un administrateur adjoint.

## Architecture

Pour ne pas réécrire le cœur historique de l'application :

- `liturgie_app_core.py` conserve exactement le cœur validé ;
- `liturgie_app.py` reste une couche d'entrée très mince ;
- cette couche exécute le cœur à chaque rerun Streamlit et ajoute l'onglet privé uniquement au principal ;
- `liturgical_drafts.py` expose la façade du module ;
- les fonctions sont séparées en `liturgical_drafts_themes.py`, `liturgical_drafts_source.py`, `liturgical_drafts_schedule.py`, `liturgical_drafts_word.py` et `liturgical_drafts_ui.py` ;
- `scripts/liturgical_drafts_automation.py` exécute la préparation automatique hors de Streamlit ;
- `.github/workflows/liturgical-drafts.yml` lance ce moteur de façon planifiée.

La couche d'entrée conserve aussi le champ `liturgical_drafts` lors de la normalisation de l'état afin que les brouillons restent persistants dans Supabase.

## Secrets utilisés par l'automatisation

Le workflow réutilise les mêmes secrets Supabase que le moteur WhatsApp :

- `SUPABASE_URL`
- `SUPABASE_API_KEY`
- `SUPABASE_STATE_KEY`

Aucun secret AELF n'est requis et aucun secret n'est stocké dans le dépôt.

## Source liturgique

Le module interroge :

`https://api.aelf.org/v1/messes/{date}/{zone}`

Il extrait la première lecture, le psaume, la deuxième lecture lorsqu'elle existe et l'Évangile. Le moteur :

- repère le temps liturgique et la célébration ;
- analyse les lectures pour identifier les thèmes dominants ;
- sélectionne de très courts extraits bibliques utiles à la rédaction ;
- construit une monition et quatre intentions cohérentes entre elles.

La rédaction ne recopie jamais un long passage biblique dans le Word.

## Brouillons

Les propositions automatiques et les brouillons modifiés sont enregistrés dans l'état Supabase sous `liturgical_drafts`. Ils peuvent ensuite être repris et modifiés.

Les anciens brouillons comportant six intentions restent lisibles afin de ne pas perdre une correction pastorale déjà effectuée. Les nouvelles générations utilisent quatre intentions.

## Export Word

Le document Word contient :

1. le titre de la célébration, le temps liturgique et la date ;
2. les références bibliques ;
3. la monition introductive ;
4. l'introduction de la prière universelle ;
5. quatre intentions éditables pour les nouvelles générations ;
6. la réponse de l'assemblée ;
7. la prière de conclusion ;
8. une mention discrète de la source AELF.

La mise en page est en A4 avec marges adaptées à l'impression.

## Dépendance ajoutée

`python-docx==1.2.0`
