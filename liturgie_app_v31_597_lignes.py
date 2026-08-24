import calendar
import csv
import io
import json
import random
from copy import deepcopy
from datetime import date
from urllib.parse import quote

import requests
import streamlit as st

APP_VERSION = "2026.08.24-persistant-supabase-v3.1"
TABLE_NAME = "liturgie_state"

st.set_page_config(page_title="Programme liturgique", page_icon="⛪", layout="wide")

FR = [f"F{i}" for i in range(1, 11)]
MO = [f"M{i}" for i in range(1, 9)]
GROUPS = {"FR": FR, "MO": MO}
MONTHS = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]

DEFAULT_NAMES = {
    "F1": "Mme Nacoulma",
    "F2": "Mme Sawadogo n°1",
    "F3": "M. Kabré Denis",
    "F4": "M. Bamouni",
    "F5": "Mme Kiendrebeogo",
    "F6": "M. Kaboré",
    "F7": "Mme Yaméogo",
    "F8": "Mme Traoré",
    "F9": "Mme Sawadogo n°2",
    "F10": "Mlle Zie",
    "M1": "M. Zoundi",
    "M2": "Mme Zoungrana",
    "M3": "Mlle Brigitte",
    "M4": "M. Zoungrana",
    "M5": "M. Koala",
    "M6": "M. Grégoire",
    "M7": "Mlle Gladys",
    "M8": "Mlle Jeanette",
}


def blank_person():
    return {
        "next_role": None,
        "last_reading": None,
        "last_service": None,
        "last_announcement": None,
        "reading_count": 0,
        "monition_count": 0,
        "announcement_count": 0,
    }


def initial_state():
    return {
        "version": APP_VERSION,
        "names": dict(DEFAULT_NAMES),
        "active": {code: True for code in FR + MO},
        "people": {code: blank_person() for code in FR + MO},
        "reading_cycle_seen": {"FR": [], "MO": []},
        "reading_pairs": [],
        "monition_pairs": [],
        "next_first_language": "FR",
        "history": [],
    }


def normalize_state(raw):
    state = initial_state()
    if not isinstance(raw, dict):
        return state

    if isinstance(raw.get("names"), dict):
        for code in FR + MO:
            value = str(raw["names"].get(code, "")).strip()
            if value:
                state["names"][code] = value

    if isinstance(raw.get("active"), dict):
        for code in FR + MO:
            state["active"][code] = bool(raw["active"].get(code, True))

    if isinstance(raw.get("people"), dict):
        for code in FR + MO:
            if isinstance(raw["people"].get(code), dict):
                state["people"][code].update(raw["people"][code])

    for key in ["reading_cycle_seen", "reading_pairs", "monition_pairs", "next_first_language", "history"]:
        if key in raw:
            state[key] = raw[key]

    state["version"] = APP_VERSION
    return state


def supabase_config():
    try:
        cfg = st.secrets.get("supabase", {})
        url = str(cfg.get("url", "")).rstrip("/")
        api_key = str(cfg.get("api_key", ""))
        state_key = str(cfg.get("state_key", "programme-liturgique-principal"))
        return url, api_key, state_key
    except Exception:
        return "", "", "programme-liturgique-principal"


def supabase_ready():
    url, api_key, _ = supabase_config()
    return bool(url and api_key)


def load_remote_state():
    url, api_key, state_key = supabase_config()
    if not (url and api_key):
        return None, "Secrets Supabase absents"

    endpoint = f"{url}/rest/v1/{TABLE_NAME}"
    params = {
        "select": "state_json",
        "app_key": f"eq.{state_key}",
        "limit": "1",
    }
    headers = {"apikey": api_key, "Accept": "application/json"}
    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return None, "Aucun état distant enregistré"
        return normalize_state(rows[0].get("state_json")), "État chargé depuis Supabase"
    except Exception as exc:
        return None, f"Lecture Supabase impossible : {exc}"


def save_remote_state(state):
    url, api_key, state_key = supabase_config()
    if not (url and api_key):
        return False, "Secrets Supabase absents"

    endpoint = f"{url}/rest/v1/{TABLE_NAME}?on_conflict=app_key"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    payload = {"app_key": state_key, "state_json": state}
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        return True, "Sauvegardé dans Supabase"
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
    if show_success:
        if ok:
            st.success(message)
        else:
            st.error(message)
    return ok


def as_date(value):
    return date.fromisoformat(value) if value else None


def days_since(value, today):
    return 10000 if not value else (today - as_date(value)).days


def sundays(year, month):
    cal = calendar.Calendar(firstweekday=calendar.MONDAY)
    return [
        d for d in cal.itermonthdates(year, month)
        if d.month == month and d.weekday() == 6
    ]


def active_codes(state, lang):
    return [c for c in GROUPS[lang] if state["active"].get(c, True)]


def reading_pool(state, lang, excluded):
    codes = active_codes(state, lang)
    seen = [c for c in state["reading_cycle_seen"].get(lang, []) if c in codes]
    if codes and len(set(seen)) >= len(codes):
        state["reading_cycle_seen"][lang] = []
        seen = []
    seen = set(seen)
    return [
        c for c in codes
        if c not in excluded
        and c not in seen
        and state["people"][c]["next_role"] in (None, "LECTURE")
    ]


def reading_rank(state, code, today):
    p = state["people"][code]
    return (
        p["reading_count"],
        -days_since(p["last_reading"], today),
        -days_since(p["last_service"], today),
        code,
    )


def choose_readers(state, today, rng):
    fr_pool = reading_pool(state, "FR", set())
    mo_pool = reading_pool(state, "MO", set())
    if not fr_pool or not mo_pool:
        raise RuntimeError(
            "La rotation ne permet pas de choisir les deux lecteurs sans casser une règle. "
            "Vérifiez les membres actifs ou réinitialisez uniquement la rotation."
        )
    old_pairs = {tuple(p) for p in state.get("reading_pairs", [])}
    choices = []
    for f in fr_pool:
        for m in mo_pool:
            choices.append(((
                1 if (f, m) in old_pairs else 0,
                reading_rank(state, f, today),
                reading_rank(state, m, today),
                rng.random(),
            ), f, m))
    choices.sort(key=lambda x: x[0])
    return choices[0][1], choices[0][2]


def monition_pool(state, lang, excluded):
    return [
        c for c in active_codes(state, lang)
        if c not in excluded
        and state["people"][c]["next_role"] in (None, "MONITION")
    ]


def monition_rank(state, code, today):
    p = state["people"][code]
    return (p["monition_count"], -days_since(p["last_service"], today), code)


def choose_monitions(state, today, excluded, rng):
    fr_pool = monition_pool(state, "FR", excluded)
    mo_pool = monition_pool(state, "MO", excluded)
    if not fr_pool or not mo_pool:
        raise RuntimeError(
            "Impossible d'attribuer la monition/P.U. sans casser l'alternance individuelle Lecture ↔ Monition."
        )
    old_pairs = {tuple(p) for p in state.get("monition_pairs", [])}
    choices = []
    for f in fr_pool:
        for m in mo_pool:
            choices.append(((
                1 if (f, m) in old_pairs else 0,
                monition_rank(state, f, today),
                monition_rank(state, m, today),
                rng.random(),
            ), f, m))
    choices.sort(key=lambda x: x[0])
    return choices[0][1], choices[0][2]


def announcement_rank(state, code, today):
    p = state["people"][code]
    return (p["announcement_count"], -days_since(p["last_announcement"], today), code)


def choose_announcement(state, lang, today, excluded, rng):
    pool = [c for c in active_codes(state, lang) if c not in excluded]
    if not pool:
        raise RuntimeError(f"Aucun membre {lang} disponible pour les annonces sans cumul de fonction.")
    rng.shuffle(pool)
    return min(pool, key=lambda c: announcement_rank(state, c, today))


def assign(state, code, role, today):
    p = state["people"][code]
    if role == "LECTURE":
        p["reading_count"] += 1
        p["last_reading"] = today.isoformat()
        p["last_service"] = today.isoformat()
        p["next_role"] = "MONITION"
        lang = "FR" if code.startswith("F") else "MO"
        if code not in state["reading_cycle_seen"][lang]:
            state["reading_cycle_seen"][lang].append(code)
    elif role == "MONITION":
        p["monition_count"] += 1
        p["last_service"] = today.isoformat()
        p["next_role"] = "LECTURE"
    elif role == "ANNONCE":
        p["announcement_count"] += 1
        p["last_announcement"] = today.isoformat()


def parse_refs(text, dates):
    refs = {d.isoformat(): {"r1": "", "r2": "", "ev": ""} for d in dates}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 4 and parts[0] in refs:
            refs[parts[0]] = {"r1": parts[1], "r2": parts[2], "ev": parts[3]}
    return refs


def generate_month(state, year, month, refs, seed):
    state = normalize_state(deepcopy(state))
    rng = random.Random(seed + year * 100 + month)
    month_dates = {d.isoformat() for d in sundays(year, month)}
    if any(row.get("date") in month_dates for row in state["history"]):
        raise RuntimeError(
            "Ce mois figure déjà dans l'historique. Supprimez d'abord ce mois de l'historique ou choisissez un autre mois."
        )

    if len(active_codes(state, "FR")) < 3 or len(active_codes(state, "MO")) < 3:
        raise RuntimeError("Il faut au moins 3 membres actifs dans chaque langue pour respecter les fonctions sans cumul.")

    rows = []
    for sunday in sundays(year, month):
        f_read, m_read = choose_readers(state, sunday, rng)
        first = state["next_first_language"]
        if first == "FR":
            r1_code, r1_lang, r2_code, r2_lang = f_read, "FR", m_read, "MO"
        else:
            r1_code, r1_lang, r2_code, r2_lang = m_read, "MO", f_read, "FR"

        excluded = {f_read, m_read}
        f_mon, m_mon = choose_monitions(state, sunday, excluded, rng)
        excluded.update({f_mon, m_mon})
        f_ann = choose_announcement(state, "FR", sunday, excluded, rng)
        m_ann = choose_announcement(state, "MO", sunday, excluded, rng)

        assign(state, f_read, "LECTURE", sunday)
        assign(state, m_read, "LECTURE", sunday)
        state["reading_pairs"].append([f_read, m_read])
        assign(state, f_mon, "MONITION", sunday)
        assign(state, m_mon, "MONITION", sunday)
        state["monition_pairs"].append([f_mon, m_mon])
        assign(state, f_ann, "ANNONCE", sunday)
        assign(state, m_ann, "ANNONCE", sunday)
        state["next_first_language"] = "MO" if first == "FR" else "FR"

        ref = refs[sunday.isoformat()]
        names = state["names"]
        row = {
            "date": sunday.isoformat(),
            "Dimanche": sunday.strftime("%d/%m/%Y"),
            "Références": f"1re : {ref['r1']}\n2e : {ref['r2']}\nÉv. : {ref['ev']}",
            "Lecteurs": f"1re ({r1_lang}) : {names[r1_code]}\n2e ({r2_lang}) : {names[r2_code]}",
            "Monition + P.U.": f"FR : {names[f_mon]}\nMO : {names[m_mon]}",
            "Annonces": f"FR : {names[f_ann]}\nMO : {names[m_ann]}",
            "codes": {
                "r1": r1_code, "r2": r2_code,
                "f_mon": f_mon, "m_mon": m_mon,
                "f_ann": f_ann, "m_ann": m_ann,
            },
        }
        rows.append(row)
        state["history"].append(row)

    return rows, state


def csv_bytes(rows):
    out = io.StringIO()
    fields = ["Dimanche", "Références", "Lecteurs", "Monition + P.U.", "Annonces"]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fields})
    return out.getvalue().encode("utf-8-sig")


def rotation_reset_keep_names(state):
    fresh = initial_state()
    fresh["names"] = dict(state.get("names", DEFAULT_NAMES))
    fresh["active"] = dict(state.get("active", {c: True for c in FR + MO}))
    return fresh


def names_text(state, codes):
    return "\n".join(state["names"][c] for c in codes)


def apply_names_text(state, codes, text):
    values = [line.strip() for line in text.splitlines() if line.strip()]
    if len(values) != len(codes):
        return False, f"Il faut saisir exactement {len(codes)} noms. Vous en avez saisi {len(values)}."
    for code, value in zip(codes, values):
        state["names"][code] = value
    return True, "Noms enregistrés."


ensure_loaded()
state = st.session_state.liturgie_state

st.title("⛪ Programme liturgique")
st.caption(f"Version : {APP_VERSION}")
st.write("Programmation automatique — les codes techniques restent en arrière-plan, seuls les noms sont affichés.")

home_tab, generate_tab, members_tab, history_tab = st.tabs(["🏠 Accueil", "✨ Générer", "👥 Membres", "🕘 Historique"])

with home_tab:
    c1, c2, c3 = st.columns(3)
    c1.metric("Francophones", sum(1 for c in FR if state["active"].get(c, True)))
    c2.metric("Mooréphones", sum(1 for c in MO if state["active"].get(c, True)))
    c3.metric("Célébrations validées", len(state.get("history", [])))

    if supabase_ready():
        st.success("☁️ Persistance Supabase configurée.")
    else:
        st.warning("☁️ Persistance Supabase non configurée : les données ne survivront pas à un redémarrage.")

    if st.session_state.get("supabase_message"):
        st.caption(st.session_state.supabase_message)

    st.info(
        "Règles actives : alternance FR/MO des 1re et 2e lectures ; alternance individuelle "
        "Lecture ↔ Monition/P.U. au prochain passage ; équité des intervalles ; binômes non figés ; "
        "annonces indépendantes et sans cumul de fonction le même dimanche."
    )

    if st.button("🔄 Recharger depuis Supabase"):
        remote, message = load_remote_state()
        if remote:
            st.session_state.liturgie_state = remote
            st.session_state.supabase_message = message
            st.rerun()
        st.error(message)

with members_tab:
    st.subheader("👥 Membres")
    st.info(
        "Saisissez un nom par ligne. L'ordre correspond aux identifiants internes déjà créés. "
        "Les identifiants ne sont pas affichés dans le programme."
    )

    fr_text = st.text_area("Francophones — 10 noms", value=names_text(state, FR), height=300, key="fr_names")
    mo_text = st.text_area("Mooréphones — 8 noms", value=names_text(state, MO), height=250, key="mo_names")

    if st.button("💾 Enregistrer tous les noms", type="primary"):
        ok_fr, msg_fr = apply_names_text(state, FR, fr_text)
        ok_mo, msg_mo = apply_names_text(state, MO, mo_text)
        if ok_fr and ok_mo:
            st.session_state.liturgie_state = state
            if persist(show_success=True):
                st.rerun()
        else:
            if not ok_fr:
                st.error(msg_fr)
            if not ok_mo:
                st.error(msg_mo)

    st.divider()
    st.subheader("Disponibilité temporaire")
    st.caption("Un membre désactivé n'est plus programmé, mais son historique et sa prochaine fonction sont conservés.")
    with st.expander("Modifier les membres actifs"):
        for code in FR + MO:
            state["active"][code] = st.checkbox(
                state["names"][code],
                value=state["active"].get(code, True),
                key=f"active_{code}",
            )
        if st.button("💾 Enregistrer les disponibilités"):
            st.session_state.liturgie_state = state
            persist(show_success=True)

with generate_tab:
    st.subheader("1. Choisir la période")
    col1, col2 = st.columns(2)
    with col1:
        year = int(st.number_input("Année", min_value=2020, max_value=2100, value=2026, step=1))
    with col2:
        month = st.selectbox("Mois", range(1, 13), index=8, format_func=lambda m: MONTHS[m - 1])

    month_sundays = sundays(year, month)
    st.subheader("2. Calendrier et références bibliques")
    st.write("Les dimanches sont calculés automatiquement. Vous pouvez compléter les références bibliques avant de générer.")
    example = "\n".join(f"{d.isoformat()} |  |  | " for d in month_sundays)
    refs_text = st.text_area(
        "AAAA-MM-JJ | 1re lecture | 2e lecture | Évangile",
        value=example,
        height=max(160, 38 * len(month_sundays)),
        key=f"refs_{year}_{month}",
    )

    st.subheader("3. Paramètres de rotation")
    seed = int(st.number_input("Graine de brassage", min_value=0, max_value=999999, value=2026, step=1))
    first_lang = st.radio(
        "Langue de la prochaine 1re lecture",
        ["FR", "MO"],
        horizontal=True,
        index=0 if state.get("next_first_language", "FR") == "FR" else 1,
    )
    state["next_first_language"] = first_lang

    if st.button("✨ Générer le programme", type="primary"):
        try:
            refs = parse_refs(refs_text, month_sundays)
            rows, new_state = generate_month(state, year, month, refs, seed)
            st.session_state.liturgie_state = new_state
            st.session_state.last_rows = rows
            persist(show_success=False)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if st.session_state.get("last_rows"):
        st.subheader("4. Programme généré")
        display_rows = [
            {
                "Dimanche": r["Dimanche"],
                "Références": r["Références"],
                "Lecteurs": r["Lecteurs"],
                "Monition + P.U.": r["Monition + P.U."],
                "Annonces": r["Annonces"],
            }
            for r in st.session_state.last_rows
        ]
        st.dataframe(display_rows, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Télécharger le programme CSV",
            data=csv_bytes(st.session_state.last_rows),
            file_name=f"programme_liturgique_{year}_{month:02d}.csv",
            mime="text/csv",
        )

    st.subheader("5. Contrôle de la rotation")
    control = []
    for code in FR + MO:
        p = state["people"][code]
        control.append({
            "Membre": state["names"][code],
            "Langue": "Français" if code.startswith("F") else "Mooré",
            "Statut": "Actif" if state["active"].get(code, True) else "Retiré temporairement",
            "Prochaine fonction": p["next_role"] or "Libre (départ)",
            "Lectures": p["reading_count"],
            "Monitions/P.U.": p["monition_count"],
            "Annonces": p["announcement_count"],
            "Dernière lecture": p["last_reading"] or "—",
            "Dernier passage": p["last_service"] or "—",
        })
    st.dataframe(control, use_container_width=True, hide_index=True)

with history_tab:
    st.subheader("🕘 Historique")
    history = state.get("history", [])
    if history:
        display_history = [
            {
                "Dimanche": r.get("Dimanche", r.get("date", "")),
                "Références": r.get("Références", r.get("Réf.D", "")),
                "Lecteurs": r.get("Lecteurs", ""),
                "Monition + P.U.": r.get("Monition + P.U.", r.get("Monition introductive + P.U.", "")),
                "Annonces": r.get("Annonces", r.get("Chargés d’annonce", "")),
            }
            for r in history
        ]
        st.dataframe(display_history, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune célébration enregistrée pour le moment.")

    st.divider()
    st.subheader("Maintenance")
    if st.button("♻️ Réinitialiser uniquement la rotation"):
        st.session_state.liturgie_state = rotation_reset_keep_names(state)
        st.session_state.last_rows = []
        persist(show_success=False)
        st.rerun()

    state_bytes = json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button(
        "⬇️ Télécharger une sauvegarde JSON",
        data=state_bytes,
        file_name="etat_programme_liturgique.json",
        mime="application/json",
    )
