# v3.10.11 — WhatsApp full-readiness gate

Cette étape ne réactive pas les envois WhatsApp.

Le workflow de production reste avec `WHATSAPP_AUTOMATION_ENABLED=false`.
Si ce verrou est volontairement passé à `true` plus tard, un contrôle global s'exécute avant tout envoi réel et bloque le workflow si une affectation future active n'est pas entièrement prête (numéro valide, consentement, rappels activés) ou si la configuration WhatsApp requise est incomplète.

Le contrôle couvre tous les programmes futurs actifs, pas uniquement le prochain dimanche, et n'affiche aucun numéro dans les diagnostics.
