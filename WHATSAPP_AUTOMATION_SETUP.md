# Automatisation WhatsApp — Programme liturgique

## Objectif

Envoyer automatiquement les rappels aux membres programmés :

- mercredi à 18 h 30 (heure de Ouagadougou) ;
- vendredi à 18 h 30 (heure de Ouagadougou).

Le moteur utilise uniquement les membres du prochain dimanche publié dans l'application, respecte les indicateurs `consent` et `enabled`, et n'envoie pas deux fois le même rappel grâce au journal `whatsapp_send_log` enregistré dans Supabase.

## Architecture retenue

- **Streamlit** reste l'interface de gestion.
- **Supabase** reste la source de vérité pour le programme, les contacts et le journal des envois.
- **Meta WhatsApp Business Cloud API** effectue les envois de modèles approuvés.
- **GitHub Actions** déclenche automatiquement le moteur le mercredi et le vendredi à 18 h 30 UTC, soit 18 h 30 à Ouagadougou.

Le workflow est conçu pour rester inactif tant que la configuration Meta n'est pas complète et tant que `WHATSAPP_AUTOMATION_ENABLED` n'est pas explicitement positionné à `true`.

## Modèles Meta proposés

Les deux modèles doivent utiliser exactement trois paramètres de corps, dans cet ordre :

1. `{{1}}` = nom du membre ;
2. `{{2}}` = date du dimanche ;
3. `{{3}}` = rôle liturgique.

### Mercredi

Nom conseillé : `rappel_liturgique_mercredi`

Texte proposé :

> Bonjour {{1}}, premier rappel pour le dimanche {{2}}. Vous assurerez : {{3}}. Merci de bien vouloir confirmer la réception de ce message. Que Dieu vous bénisse dans ce service.

### Vendredi

Nom conseillé : `rappel_liturgique_vendredi`

Texte proposé :

> Bonjour {{1}}, deuxième rappel pour ce dimanche {{2}}. Votre service prévu est : {{3}}. Merci de prendre les dispositions nécessaires pour être à l'heure. Que Dieu vous accompagne dans ce service.

La catégorie sera à choisir dans Meta en fonction de sa classification courante ; pour un rappel de service attendu par un membre ayant donné son accord, **Utility** est généralement le point de départ logique, sous réserve de la classification finale de Meta.

## Paramètres Meta à obtenir

Dans Meta Business / WhatsApp Manager :

- compte WhatsApp Business (WABA) ;
- numéro expéditeur enregistré pour Cloud API ;
- `phone_number_id` correspondant ;
- jeton d'accès durable adapté à la production ;
- permission d'envoi WhatsApp Business requise par Meta ;
- deux modèles ci-dessus approuvés et activés ;
- code langue des modèles (par exemple `fr` si Meta l'affiche ainsi) ;
- version Graph API actuellement supportée par le compte Meta.

Ne jamais enregistrer le jeton Meta, la clé Supabase ou d'autres secrets dans un fichier GitHub public.

## Secrets GitHub à créer

Dans **Settings → Secrets and variables → Actions → New repository secret** :

- `SUPABASE_URL`
- `SUPABASE_API_KEY`
- `SUPABASE_STATE_KEY` (valeur habituelle : `programme-liturgique-principal`)
- `WHATSAPP_GRAPH_API_VERSION`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_TEMPLATE_WEDNESDAY`
- `WHATSAPP_TEMPLATE_FRIDAY`
- `WHATSAPP_TEMPLATE_LANGUAGE`
- `WHATSAPP_AUTOMATION_ENABLED`

Commencer avec :

`WHATSAPP_AUTOMATION_ENABLED=false`

Puis passer à `true` seulement après un test réussi.

## Procédure de validation

1. Enregistrer les secrets GitHub avec l'automatisation encore désactivée.
2. Ouvrir **Actions → WhatsApp reminders → Run workflow**.
3. Choisir `mercredi` ou `vendredi` et laisser **dry_run = true**.
4. Vérifier que les membres et rôles attendus apparaissent dans les logs sans numéro de téléphone ni secret.
5. Vérifier dans l'application que les membres concernés ont un numéro, le consentement et les rappels activés.
6. Tester l'envoi Meta sur un contexte contrôlé avant d'activer la production.
7. Mettre `WHATSAPP_AUTOMATION_ENABLED=true` seulement après validation.

## Comportements de sécurité

Le moteur :

- ne fait rien si les secrets Supabase sont absents ;
- ne fait rien si la configuration WhatsApp est incomplète ;
- ne fait rien tant que l'activation explicite n'est pas à `true` ;
- ignore les membres sans numéro valide, consentement ou activation ;
- ignore les rappels déjà enregistrés comme envoyés ;
- recharge l'état Supabase juste avant chaque écriture de journal afin de limiter le risque d'écraser une modification récente de l'application ;
- n'affiche aucun numéro de téléphone ni jeton dans les logs.

## Fichiers techniques

- `scripts/whatsapp_automation.py` : moteur d'envoi et journalisation ;
- `.github/workflows/whatsapp-reminders.yml` : ordonnanceur mercredi/vendredi 18 h 30.

## Remarque sur l'heure

GitHub Actions utilise UTC pour `cron`. Ouagadougou est en UTC+0, donc `30 18 * * 3` et `30 18 * * 5` correspondent à 18 h 30 heure de Ouagadougou. Les exécutions planifiées de GitHub Actions peuvent parfois démarrer avec quelques minutes de retard ; le moteur vérifie néanmoins la bonne date de rappel avant tout envoi.
