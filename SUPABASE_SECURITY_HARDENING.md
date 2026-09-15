# Supabase security hardening — v3.10.7

Date : 2026-09-15

## Objectif

Réduire l'exposition de la fonction interne `public.rls_auto_enable()` sans modifier les données métier ni désactiver l'event trigger `ensure_rls` qui active automatiquement RLS lors de la création de tables dans le schéma `public`.

## Changement appliqué

Migration Supabase : `revoke_public_execute_rls_auto_enable`

```sql
revoke execute on function public.rls_auto_enable() from public;
revoke execute on function public.rls_auto_enable() from anon, authenticated, service_role;
```

La fonction reste détenue par `postgres`, reste `SECURITY DEFINER`, conserve `search_path=pg_catalog`, et son event trigger `ensure_rls` reste actif.

## Vérifications effectuées

- `anon` : `EXECUTE = false`
- `authenticated` : `EXECUTE = false`
- `service_role` : `EXECUTE = false`
- propriétaire `postgres` : `EXECUTE = true`
- test transactionnel de création de table : RLS activé automatiquement ; transaction ensuite annulée
- aucun objet de test conservé
- données métier inchangées : 4 lignes d'historique, 20 membres, 2 jours de présence, 1 brouillon liturgique, révision Supabase 0 au moment du contrôle
- advisor performance : aucun signal
- advisor sécurité : seul subsiste l'INFO `RLS Enabled No Policy` sur `public.liturgie_state`

## RLS sur `liturgie_state`

L'absence de policy est volontaire tant qu'aucun accès direct depuis un client public n'est requis. Elle maintient la table fermée aux rôles ordinaires. Si un accès direct `anon` ou `authenticated` devait être ajouté plus tard, il faudra créer des policies explicites et minimales avant de l'activer.

Référence Supabase : https://supabase.com/docs/guides/database/functions#function-privileges
