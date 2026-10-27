# Audit préalable — programmation nominative de novembre 2026

Statut : **BLOQUÉ / NON VALIDÉ / AUCUN DÉPLOIEMENT**.

## Constats (lecture seule, 27 octobre 2026)
- L'état de production Supabase contient déjà des lignes d'historique pour les dix dates du 31 octobre au 29 novembre 2026.
- Plusieurs lignes concernent la même date, parfois avec des affectations distinctes. Il ne faut ni supprimer ni remplacer ces lignes automatiquement.
- Certains samedis ne contiennent que des lecteurs mooréphones, contrairement à la règle confirmée de célébration bilingue.
- L'historique contient des lignes avec annonces et des lignes sans annonces ; les futurs programmes n'en prévoient aucune.
- Les données actuelles sont plus riches que la liste historique initiale de lecteurs ; utiliser uniquement le roster actif réel et les règles d'éligibilité, jamais une liste figée.
- La CI de la branche échoue : tests d'intégration liés à la transformation runtime de `liturgie_app.py` et préservation de `liturgical_drafts`.

## Conditions avant proposition nominative
1. Identifier la signification des doublons et les lignes actives / annulées en utilisant les mécanismes existants de protection d'historique.
2. Conserver toutes les anciennes lignes comme historique ; ne pas effectuer d'UPDATE/DELETE sur Supabase.
3. Distinguer le programme déjà validé d'un nouveau projet non publié.
4. Calculer l'éligibilité réelle pour novembre et vérifier l'alternance Lecture ↔ Monition.
5. Produire dix célébrations avec quatre fonctions chacune : lecture FR, lecture MO, monition/P.U. FR, monition/P.U. MO ; aucune annonce.
6. Valider la disponibilité et l'absence de double affectation dans un même week-end.
7. Réparer la CI et tester le parcours adjoint → principal avant tout déploiement.

**Aucune attribution nominative supplémentaire n'est publiée par cet audit.**
