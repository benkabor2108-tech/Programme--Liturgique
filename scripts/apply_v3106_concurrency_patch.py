#!/usr/bin/env python3
"""One-shot source patcher for v3.10.6 optimistic concurrency protection."""
from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def patch_app_wrapper() -> None:
    path = Path("liturgie_app.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.5-history-protected"',
        'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.6-concurrency-protected"',
        "app version",
    )
    text = replace_once(
        text,
        "from liturgical_drafts import persist_liturgical_state, render_liturgical_drafts_tab\n",
        "from liturgical_drafts import persist_liturgical_state, render_liturgical_drafts_tab\n"
        "from state_store import (\n"
        "    StateConflictError, StateNotFoundError, load_state_record, save_state_if_revision,\n"
        ")\n",
        "state store import",
    )

    marker = "    source = _replace_once(\n        source,\n        '''def latest_history_month(history):\n"
    if marker not in text:
        raise RuntimeError("persistence insertion marker not found")

    persistence_transform = r'''    persistence_start = source.find("def load_remote_state():\n")
    persistence_end = source.find("\n\ndef as_date(value):", persistence_start)
    if persistence_start < 0 or persistence_end < 0:
        raise RuntimeError(
            "Structure du cœur inattendue : bloc de persistance Supabase introuvable."
        )
    source = source[:persistence_start] + '''def load_remote_state():
    url, api_key, state_key = supabase_config()
    if not (url and api_key):
        st.session_state.supabase_revision = None
        return None, "Secrets Supabase absents"

    try:
        raw_state, revision, _updated_at = load_state_record(
            url,
            api_key,
            state_key,
            timeout=15,
        )
        st.session_state.supabase_revision = revision
        st.session_state.supabase_conflict = False
        return normalize_state(raw_state), f"État chargé depuis Supabase · révision {revision}"
    except StateNotFoundError:
        st.session_state.supabase_revision = None
        return None, "Aucun état distant enregistré"
    except Exception as exc:
        return None, f"Lecture Supabase impossible : {exc}"


def save_remote_state(state):
    url, api_key, state_key = supabase_config()
    if not (url and api_key):
        return False, "Secrets Supabase absents"

    expected_revision = st.session_state.get("supabase_revision")
    if expected_revision is None:
        st.session_state.supabase_conflict = True
        return False, (
            "Révision Supabase inconnue. Rechargez l'état distant avant toute nouvelle sauvegarde."
        )

    try:
        new_revision = save_state_if_revision(
            url,
            api_key,
            state_key,
            state,
            expected_revision,
            timeout=20,
        )
        st.session_state.supabase_revision = new_revision
        st.session_state.supabase_conflict = False
        return True, f"Sauvegardé dans Supabase · révision {new_revision}"
    except StateConflictError:
        st.session_state.supabase_conflict = True
        return False, (
            "Conflit de sauvegarde : une autre session ou automatisation a modifié les données depuis votre dernière lecture. "
            "Aucune donnée distante n'a été écrasée. Rechargez depuis Supabase avant de reprendre vos modifications."
        )
    except Exception as exc:
        return False, f"Sauvegarde Supabase impossible : {exc}"


def ensure_loaded():
    if "liturgie_state" in st.session_state:
        return
    remote, message = load_remote_state()
    st.session_state.liturgie_state = remote if remote else initial_state()
    st.session_state.supabase_message = message
    st.session_state.last_rows = []


def persist(show_success=False):
    ok, message = save_remote_state(st.session_state.liturgie_state)
    st.session_state.supabase_message = message
    if ok:
        if show_success:
            st.success(message)
    else:
        if st.session_state.get("supabase_conflict", False):
            st.error(message)
            st.warning(
                "Utilisez « Actualiser depuis Supabase » avant toute autre modification. "
                "La sauvegarde refusée reste seulement dans cette session et n'a pas écrasé la base."
            )
        elif show_success:
            st.error(message)
    return ok
''' + source[persistence_end:]

'''
    text = text.replace(marker, persistence_transform + marker, 1)

    namespace_marker = '        "latest_active_history_month": latest_active_history_month,\n'
    text = replace_once(
        text,
        namespace_marker,
        namespace_marker
        + '        "StateConflictError": StateConflictError,\n'
        + '        "StateNotFoundError": StateNotFoundError,\n'
        + '        "load_state_record": load_state_record,\n'
        + '        "save_state_if_revision": save_state_if_revision,\n',
        "runtime namespace",
    )
    write(str(path), text)


def patch_liturgical_ui() -> None:
    path = Path("liturgical_drafts_ui.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from liturgical_drafts_word import build_word_document\n",
        "from liturgical_drafts_word import build_word_document\n"
        "from state_store import StateConflictError, save_state_if_revision\n",
        "liturgical ui state-store import",
    )

    start = text.find("def persist_liturgical_state(state, show_success=False):\n")
    end = text.find("\n\ndef saved_drafts(state):", start)
    if start < 0 or end < 0:
        raise RuntimeError("liturgical UI persistence block not found")
    new_block = '''def persist_liturgical_state(state, show_success=False):
    """Sauvegarde avec révision optimiste dans la même ligne Supabase que l'application."""
    if st is None:
        return False
    try:
        cfg = st.secrets.get("supabase", {})
        url = str(cfg.get("url", "")).rstrip("/")
        api_key = str(cfg.get("api_key", ""))
        state_key = str(cfg.get("state_key", "programme-liturgique-principal"))
    except Exception:
        url = api_key = ""
        state_key = "programme-liturgique-principal"
    if not (url and api_key):
        if show_success:
            st.error("Secrets Supabase absents.")
        return False

    expected_revision = st.session_state.get("supabase_revision") if hasattr(st, "session_state") else None
    if expected_revision is None:
        message = "Révision Supabase inconnue. Rechargez l'état avant d'enregistrer le brouillon."
        if hasattr(st, "session_state"):
            st.session_state.supabase_conflict = True
            st.session_state.supabase_message = message
        st.error(message)
        return False

    try:
        new_revision = save_state_if_revision(
            url,
            api_key,
            state_key,
            state,
            expected_revision,
            timeout=20,
        )
        if hasattr(st, "session_state"):
            st.session_state.supabase_revision = new_revision
            st.session_state.supabase_conflict = False
            st.session_state.supabase_message = f"Sauvegardé dans Supabase · révision {new_revision}"
        if show_success:
            st.success(f"Sauvegardé dans Supabase · révision {new_revision}")
        return True
    except StateConflictError:
        message = (
            "Conflit de sauvegarde : les données ont changé depuis votre dernière lecture. "
            "Le brouillon n'a pas écrasé la version distante. Rechargez depuis Supabase."
        )
        if hasattr(st, "session_state"):
            st.session_state.supabase_conflict = True
            st.session_state.supabase_message = message
        st.error(message)
        return False
    except Exception as exc:
        message = f"Sauvegarde Supabase impossible : {exc}"
        if hasattr(st, "session_state"):
            st.session_state.supabase_message = message
        if show_success:
            st.error(message)
        return False
'''
    text = text[:start] + new_block + text[end:]
    write(str(path), text)


def patch_drafts_automation() -> None:
    path = Path("scripts/liturgical_drafts_automation.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from liturgical_drafts_themes import APP_TIMEZONE\n",
        "from liturgical_drafts_themes import APP_TIMEZONE\n"
        "from state_store import StateConflictError, load_state_record, save_state_if_revision\n",
        "draft automation state-store import",
    )

    start = text.find("def load_state(cfg: dict) -> dict:\n")
    end = text.find("\n\ndef draft_key(service_date", start)
    if start < 0 or end < 0:
        raise RuntimeError("draft automation storage helpers not found")
    new_helpers = '''def load_state_with_revision(cfg: dict):
    return load_state_record(
        cfg["supabase_url"],
        cfg["supabase_api_key"],
        cfg["supabase_state_key"],
        timeout=20,
    )


def load_state(cfg: dict) -> dict:
    state, _revision, _updated_at = load_state_with_revision(cfg)
    return state
'''
    text = text[:start] + new_helpers + text[end:]

    start = text.find("def persist_record(cfg: dict, target: dict, record: dict, now: datetime) -> bool:\n")
    end = text.find("\n\ndef run(now: datetime | None = None) -> int:", start)
    if start < 0 or end < 0:
        raise RuntimeError("draft automation persist_record not found")
    new_persist = '''def persist_record(cfg: dict, target: dict, record: dict, now: datetime) -> bool:
    """Ajoute un brouillon avec réessai CAS, sans écraser une correction manuelle."""
    for attempt in range(1, 6):
        latest, revision, _updated_at = load_state_with_revision(cfg)
        latest = deepcopy(latest)
        drafts = latest.setdefault("liturgical_drafts", {})
        if not isinstance(drafts, dict):
            drafts = {}
            latest["liturgical_drafts"] = drafts

        key = draft_key(target["date"])
        existing = drafts.get(key)
        if isinstance(existing, dict) and not needs_auto_refresh(existing):
            print(f"Brouillon déjà présent pour {target['date'].isoformat()} : aucun écrasement.")
            return False

        action = "liturgical_draft_auto_refreshed" if needs_auto_refresh(existing) else "liturgical_draft_auto_generated"
        drafts[key] = record
        audit = latest.setdefault("audit_log", [])
        if not isinstance(audit, list):
            audit = []
            latest["audit_log"] = audit
        audit.append({
            "at": now.astimezone(APP_TIMEZONE).isoformat(),
            "actor": AUTO_ACTOR,
            "action": action,
            "date": target["date"].isoformat(),
            "celebration": record.get("celebration", ""),
            "rule": target.get("rule", ""),
            "generator_version": DRAFT_GENERATOR_VERSION,
        })
        try:
            save_state_if_revision(
                cfg["supabase_url"],
                cfg["supabase_api_key"],
                cfg["supabase_state_key"],
                latest,
                revision,
                timeout=20,
            )
            return True
        except StateConflictError:
            if attempt >= 5:
                raise
            print(f"[concurrency] état modifié pendant l'écriture ; nouvelle tentative {attempt + 1}/5.")
    return False
'''
    text = text[:start] + new_persist + text[end:]
    write(str(path), text)


def patch_whatsapp_automation() -> None:
    path = Path("scripts/whatsapp_automation.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from history_protection import is_history_row_active\n",
        "from history_protection import is_history_row_active\n"
        "from state_store import StateConflictError, load_state_record, save_state_if_revision\n",
        "whatsapp state-store import",
    )

    start = text.find("def load_state(cfg: dict) -> dict:\n")
    end = text.find("\n\ndef next_published_sunday", start)
    if start < 0 or end < 0:
        raise RuntimeError("whatsapp storage helpers not found")
    new_helpers = '''def load_state_with_revision(cfg: dict):
    return load_state_record(
        cfg["supabase_url"],
        cfg["supabase_api_key"],
        cfg["supabase_state_key"],
        timeout=20,
    )


def load_state(cfg: dict) -> dict:
    state, _revision, _updated_at = load_state_with_revision(cfg)
    return state
'''
    text = text[:start] + new_helpers + text[end:]

    start = text.find("def record_success(cfg: dict, sunday: date, kind: str, job: dict, message_id: str) -> None:\n")
    end = text.find("\n\ndef resolve_kind", start)
    if start < 0 or end < 0:
        raise RuntimeError("whatsapp record_success not found")
    new_record = '''def record_success(cfg: dict, sunday: date, kind: str, job: dict, message_id: str) -> None:
    """Journalise un succès en réessayant si une autre écriture intervient simultanément."""
    for attempt in range(1, 7):
        latest, revision, _updated_at = load_state_with_revision(cfg)
        latest = deepcopy(latest)
        log = latest.setdefault("whatsapp_send_log", {})
        if not isinstance(log, dict):
            log = {}
            latest["whatsapp_send_log"] = log
        if job["send_key"] in log:
            return

        stamp = datetime.now(APP_TIMEZONE).isoformat()
        log[job["send_key"]] = {
            "status": "sent",
            "sent_at": stamp,
            "actor": "GitHub Actions — WhatsApp Cloud API",
            "message_id": message_id,
        }
        audit = latest.setdefault("audit_log", [])
        if not isinstance(audit, list):
            audit = []
            latest["audit_log"] = audit
        audit.append({
            "type": "whatsapp_reminder_sent",
            "date": sunday.isoformat(),
            "reminder": kind,
            "member": job["code"],
            "timestamp": stamp,
            "actor": "GitHub Actions — WhatsApp Cloud API",
            "message_id": message_id,
        })
        try:
            save_state_if_revision(
                cfg["supabase_url"],
                cfg["supabase_api_key"],
                cfg["supabase_state_key"],
                latest,
                revision,
                timeout=20,
            )
            return
        except StateConflictError:
            if attempt >= 6:
                raise
            print(f"[concurrency] journal WhatsApp modifié simultanément ; nouvelle tentative {attempt + 1}/6.")
'''
    text = text[:start] + new_record + text[end:]
    write(str(path), text)


def patch_ci() -> None:
    path = Path(".github/workflows/ci.yml")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "          python -m py_compile history_protection.py\n",
        "          python -m py_compile history_protection.py\n          python -m py_compile state_store.py\n",
        "CI compile state_store",
    )
    text = replace_once(
        text,
        "          python -m unittest tests/test_history_protection.py -v\n",
        "          python -m unittest tests/test_history_protection.py -v\n          python -m unittest tests/test_state_store.py -v\n",
        "CI state store tests",
    )
    write(str(path), text)


def patch_history_test_version() -> None:
    path = Path("tests/test_history_protection.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '"APP_VERSION_OVERRIDE": "2026.09.15-persistant-supabase-v3.10.5-history-protected",',
        '"APP_VERSION_OVERRIDE": "2026.09.15-persistant-supabase-v3.10.6-concurrency-protected",',
        "history test wrapper version",
    )
    text = replace_once(
        text,
        '            \'APP_VERSION = "2026.09.15-persistant-supabase-v3.10.5-history-protected"\',',
        '            \'APP_VERSION = "2026.09.15-persistant-supabase-v3.10.6-concurrency-protected"\',',
        "history test transformed version",
    )
    write(str(path), text)


def main() -> None:
    patch_app_wrapper()
    patch_liturgical_ui()
    patch_drafts_automation()
    patch_whatsapp_automation()
    patch_ci()
    patch_history_test_version()
    print("v3.10.6 concurrency patch applied")


if __name__ == "__main__":
    main()
