"""Accès Supabase avec verrouillage optimiste pour l'état du Programme liturgique.

Chaque écriture doit fournir la révision lue auparavant. Une mise à jour ne réussit
que si cette révision est encore courante dans Supabase. Cela empêche deux
sessions ou automatisations de s'écraser silencieusement.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import requests

TABLE_NAME = "liturgie_state"


class StateStoreError(RuntimeError):
    """Erreur de stockage générique."""


class StateNotFoundError(StateStoreError):
    """Aucune ligne d'état n'existe pour la clé demandée."""


class StateConflictError(StateStoreError):
    """La ligne a été modifiée depuis la dernière lecture."""


def _headers(api_key: str) -> dict:
    key = str(api_key or "").strip()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def load_state_record(
    supabase_url: str,
    api_key: str,
    state_key: str,
    *,
    timeout: int = 20,
) -> tuple[dict, int, str]:
    """Charge l'état avec sa révision courante."""
    url = str(supabase_url or "").strip().rstrip("/")
    if not (url and api_key):
        raise StateStoreError("Configuration Supabase incomplète.")

    endpoint = f"{url}/rest/v1/{TABLE_NAME}"
    params = {
        "select": "state_json,revision,updated_at",
        "app_key": f"eq.{state_key}",
        "limit": "1",
    }
    response = requests.get(endpoint, headers=_headers(api_key), params=params, timeout=timeout)
    response.raise_for_status()
    rows = response.json()
    if not rows:
        raise StateNotFoundError("Aucun état Programme liturgique trouvé dans Supabase.")

    record = rows[0]
    state = record.get("state_json")
    if not isinstance(state, dict):
        raise StateStoreError("Le state_json Supabase est invalide.")

    try:
        revision = int(record.get("revision", 0))
    except Exception as exc:
        raise StateStoreError("La révision Supabase est invalide.") from exc

    return deepcopy(state), revision, str(record.get("updated_at") or "")


def save_state_if_revision(
    supabase_url: str,
    api_key: str,
    state_key: str,
    state: dict,
    expected_revision: int,
    *,
    timeout: int = 20,
) -> int:
    """Sauvegarde uniquement si `expected_revision` est toujours la révision courante.

    Le filtre `revision=eq.<n>` est appliqué dans la même requête SQL que l'UPDATE
    généré par PostgREST. Si une autre session a déjà écrit, aucune ligne n'est
    modifiée et `StateConflictError` est levée.
    """
    url = str(supabase_url or "").strip().rstrip("/")
    if not (url and api_key):
        raise StateStoreError("Configuration Supabase incomplète.")
    if not isinstance(state, dict):
        raise StateStoreError("L'état à sauvegarder doit être un dictionnaire.")

    try:
        expected = int(expected_revision)
    except Exception as exc:
        raise StateStoreError("Révision attendue invalide.") from exc
    if expected < 0:
        raise StateStoreError("Révision attendue invalide.")

    next_revision = expected + 1
    endpoint = f"{url}/rest/v1/{TABLE_NAME}"
    params = {
        "app_key": f"eq.{state_key}",
        "revision": f"eq.{expected}",
        "select": "revision,updated_at",
    }
    headers = _headers(api_key)
    headers["Prefer"] = "return=representation"
    payload = {
        "state_json": state,
        "revision": next_revision,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    response = requests.patch(endpoint, headers=headers, params=params, json=payload, timeout=timeout)
    response.raise_for_status()
    rows = response.json()
    if not rows:
        raise StateConflictError(
            "Conflit de sauvegarde : une modification plus récente existe déjà dans Supabase."
        )

    try:
        saved_revision = int(rows[0].get("revision"))
    except Exception as exc:
        raise StateStoreError("Supabase n'a pas retourné la nouvelle révision.") from exc
    if saved_revision != next_revision:
        raise StateStoreError("Révision Supabase inattendue après sauvegarde.")
    return saved_revision
