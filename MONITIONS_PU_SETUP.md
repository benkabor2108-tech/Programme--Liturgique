# Monitions introductives et prières universelles

## Objectif

Ajouter un espace privé, visible uniquement par l'administrateur principal, qui prépare une proposition de :

- monition introductive ;
- prière universelle complète ;
- document Word A4 prêt à relire et imprimer.

La proposition s'appuie sur les lectures liturgiques récupérées depuis l'API AELF. Le texte reste modifiable avant téléchargement.

## Disponibilité

- **Dimanche à venir** : à partir du mardi précédent à **18 h 00**, heure de Ouagadougou.
- **Grandes fêtes et événements** : à partir de **J-5 à 18 h 00**.
- Les repères automatiques suivent le calendrier romain ; si une célébration est transférée localement, l'administrateur peut choisir « Autre date liturgique ».

## Accès

L'onglet `📝 Monitions & P.U.` est injecté dans la barre d'onglets uniquement lorsque le rôle courant est `principal`.

Il n'est donc pas visible :

- en mode consultation ;
- pour un administrateur adjoint.

## Architecture

Pour ne pas réécrire le cœur historique de l'application :

- `liturgie_app_core.py` conserve exactement le cœur v3.9.6 validé ;
- `liturgie_app.py` devient une couche d'entrée très mince ;
- cette couche exécute le cœur à chaque rerun Streamlit et ajoute l'onglet privé uniquement au principal ;
- `liturgical_drafts.py` expose la façade du module ;
- les fonctions sont séparées en `liturgical_drafts_themes.py`, `liturgical_drafts_source.py`, `liturgical_drafts_schedule.py`, `liturgical_drafts_word.py` et `liturgical_drafts_ui.py`.

La couche d'entrée conserve aussi le nouveau champ `liturgical_drafts` lors de la normalisation de l'état afin que les brouillons restent persistants dans Supabase.

## Source liturgique

Le module interroge :

`https://api.aelf.org/v1/messes/{date}/{zone}`

Il extrait la première lecture, le psaume, la deuxième lecture lorsqu'elle existe et l'Évangile. La rédaction ne recopie pas les textes bibliques dans le Word ; elle les analyse pour repérer des thèmes et produire une proposition pastorale cohérente.

## Brouillons

Un brouillon peut être enregistré dans l'état Supabase sous `liturgical_drafts`. Il peut ensuite être repris et modifié.

## Export Word

Le document Word contient :

1. le titre de la célébration et la date ;
2. les références bibliques ;
3. la monition introductive ;
4. l'introduction de la prière universelle ;
5. six intentions éditables ;
6. la réponse de l'assemblée ;
7. la prière de conclusion ;
8. une mention discrète de la source AELF.

La mise en page est en A4 avec marges adaptées à l'impression.

## Dépendance ajoutée

`python-docx==1.2.0`
