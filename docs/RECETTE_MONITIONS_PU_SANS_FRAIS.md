# Recette avant mise en service — Atelier Monitions et prières universelles

Statut : **en attente de recette fonctionnelle et de sauvegarde vérifiée**. Ne pas fusionner cette branche dans `main` ni déployer avant accord explicite de l'administrateur principal.

## Vérifications confirmées le 14 octobre 2026
- GitHub Actions : CI générale #156 et Reader liturgical workshop checks #50 réussis au commit `da4370e98ad91c1125a1e41ad82036a181bc2bc4`.
- Supabase « PROGRAMME -LITURGIQUE » : la table `public.liturgie_state` contient **une ligne** pour la clé `programme-liturgique-principal`, révision 29 au moment de la vérification. La table est protégée par RLS et possède une clé primaire `app_key`.
- `state_json` contient 20 rubriques ; les rubriques historiques `people`, `names`, `roster`, `attendance`, `history`, `liturgical_drafts`, `whatsapp_templates` et `audit_log` sont présentes.
- `reader_liturgical_texts` n'est pas encore présente dans l'état de production, ce qui est attendu avant déploiement.
- Aucune écriture de test n'a été faite sur Supabase. Aucune branche Supabase payante n'a été créée.

## Procédure sans frais supplémentaires
1. **Sauvegarder avant tout déploiement** : exporter la ligne `liturgie_state` (avec `app_key`, `state_json`, `revision`, `updated_at`) dans un fichier privé, non commité dans GitHub ; vérifier que l'export est complet, lisible et restaurable. Ne jamais publier ce fichier ni ses données personnelles dans une PR.
2. **Recette hors production** : exécuter les tests Python et les contrôles d'exports Word/PDF avec des données synthétiques ; vérifier que les quatre intentions sont numérotées et que « Prions le Seigneur. » apparaît une fois à la fin de chacune.
3. **Recette Streamlit** : tester l'atelier libre et l'atelier daté avec le rôle administrateur principal ; confirmer qu'un adjoint ou lecteur n'y accède pas ; vérifier le chargement AELF, la génération, la correction manuelle, l'affichage sur téléphone et ordinateur.
4. **Persistance** : uniquement après sauvegarde et avec accord, créer un document de test clairement identifié ; sauvegarder, recharger, modifier, vérifier l'historique et supprimer/archiver le document de test selon les fonctions réellement disponibles. Vérifier le refus d'écrasement en cas de conflit de révision. Ne jamais utiliser de vrais historiques pour les essais.
5. **Validation éditoriale** : comparer Word/PDF au modèle approuvé ; contrôler date facultative, références liturgiques, monition, quatre intentions et absence de parties réservées au célébrant.
6. **Mise en service** : relire les changements de la PR #38, vérifier les tests du dernier commit, obtenir l'accord explicite de fusion, puis effectuer un contrôle après déploiement. Prévoir le retour à la version Git précédente et la restauration de l'état Supabase si nécessaire.

## Conditions de blocage
- Sauvegarde privée non réalisée ou non vérifiée.
- Échec des tests ou de la recette Streamlit.
- Écriture Supabase non confirmée, conflit de révision ou altération d'une rubrique historique.
- Export Word/PDF incomplet, incorrect ou non conforme.
- Absence d'autorisation explicite de mise en production.

Ce document est un plan de recette : il **ne constitue pas une attestation d'essais fonctionnels réels**.
