import calendar
import csv
import io
import json
import random
from copy import deepcopy
from datetime import date

import streamlit as st

st.set_page_config(page_title="Programmation liturgique", layout="wide")

FR = [f"F{i}" for i in range(1, 11)]
MO = [f"M{i}" for i in range(1, 9)]
GROUPS = {"FR": FR, "MO": MO}
MONTHS = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def blank_person():
    return {
        "next_role": None,  # None, LECTURE ou MONITION
        "last_reading": None,
        "last_service": None,
        "last_announcement": None,
        "reading_count": 0,
        "monition_count": 0,
        "announcement_count": 0,
    }


def initial_state():
    return {
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
    for key in state:
        if key in raw and key != "people":
            state[key] = raw[key]
    for code in FR + MO:
        state["people"][code].update(raw.get("people", {}).get(code, {}))
    return state


def as_date(value):
    return date.fromisoformat(value) if value else None


def days_since(value, today):
    return 10000 if not value else (today - as_date(value)).days


def sundays(year, month):
    cal = calendar.Calendar(firstweekday=calendar.MONDAY)
    return [d for d in cal.itermonthdates(year, month)
            if d.month == month and d.weekday() == 6]


def reading_pool(state, lang, excluded):
    codes = GROUPS[lang]
    seen = set(state["reading_cycle_seen"][lang])
    if len(seen) == len(codes):
        state["reading_cycle_seen"][lang] = []
        seen = set()
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
            "La rotation actuelle ne permet pas une lecture sans casser une règle. "
            "Réinitialisez l'état ou importez un état antérieur cohérent."
        )
    old_pairs = {tuple(p) for p in state["reading_pairs"]}
    choices = []
    for f in fr_pool:
        for m in mo_pool:
            score = (
                1 if (f, m) in old_pairs else 0,
                reading_rank(state, f, today),
                reading_rank(state, m, today),
                rng.random(),
            )
            choices.append((score, f, m))
    choices.sort(key=lambda x: x[0])
    return choices[0][1], choices[0][2]


def monition_pool(state, lang, excluded):
    return [
        c for c in GROUPS[lang]
        if c not in excluded
        and state["people"][c]["next_role"] in (None, "MONITION")
    ]


def monition_rank(state, code, today):
    p = state["people"][code]
    return (
        p["monition_count"],
        -days_since(p["last_service"], today),
        code,
    )


def choose_monitions(state, today, excluded, rng):
    fr_pool = monition_pool(state, "FR", excluded)
    mo_pool = monition_pool(state, "MO", excluded)
    if not fr_pool or not mo_pool:
        raise RuntimeError(
            "Impossible d'attribuer la monition/P.U. sans casser l'alternance individuelle."
        )
    old_pairs = {tuple(p) for p in state["monition_pairs"]}
    choices = []
    for f in fr_pool:
        for m in mo_pool:
            score = (
                1 if (f, m) in old_pairs else 0,
                monition_rank(state, f, today),
                monition_rank(state, m, today),
                rng.random(),
            )
            choices.append((score, f, m))
    choices.sort(key=lambda x: x[0])
    return choices[0][1], choices[0][2]


def announcement_rank(state, code, today):
    p = state["people"][code]
    return (
        p["announcement_count"],
        -days_since(p["last_announcement"], today),
        code,
    )


def choose_announcement(state, lang, today, excluded, rng):
    pool = [c for c in GROUPS[lang] if c not in excluded]
    if not pool:
        pool = GROUPS[lang][:]
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
    else:
        p["announcement_count"] += 1
        p["last_announcement"] = today.isoformat()


def parse_refs(text, dates):
    refs = {d.isoformat(): {"r1": "", "r2": "", "ev": ""} for d in dates}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 4:
            refs[parts[0]] = {"r1": parts[1], "r2": parts[2], "ev": parts[3]}
    return refs


def generate_month(state, year, month, refs, seed):
    state = normalize_state(deepcopy(state))
    rng = random.Random(seed + year * 100 + month)
    month_dates = {d.isoformat() for d in sundays(year, month)}
    if any(row.get("date") in month_dates for row in state["history"]):
        raise RuntimeError("Ce mois figure déjà dans l'historique. Réinitialisez ou importez l'état précédent.")

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
        row = {
            "date": sunday.isoformat(),
            "Dx": f"D{sunday.day}",
            "Réf.D": f"1re : {ref['r1']}\n2e : {ref['r2']}\nÉv. : {ref['ev']}",
            "Lecteurs": f"1re : {r1_lang} — {r1_code}\n2e : {r2_lang} — {r2_code}",
            "Monition introductive + P.U.": f"FR — {f_mon}\nMO — {m_mon}",
            "Chargés d’annonce": f"FR — {f_ann}\nMO — {m_ann}",
        }
        rows.append(row)
        state["history"].append(row)
    return rows, state


def csv_data(rows):
    out = io.StringIO()
    fields = ["Dx", "Réf.D", "Lecteurs", "Monition introductive + P.U.", "Chargés d’annonce"]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row[k] for k in fields})
    return out.getvalue().encode("utf-8-sig")


def render_table(rows):
    import html
    cols = ["Dx", "Réf.D", "Lecteurs", "Monition introductive + P.U.", "Chargés d’annonce"]
    output = "<table style='border-collapse:collapse;width:100%'><thead><tr>"
    for c in cols:
        output += f"<th style='border:1px solid #999;padding:8px'>{html.escape(c)}</th>"
    output += "</tr></thead><tbody>"
    for row in rows:
        output += "<tr>"
        for c in cols:
            value = html.escape(row[c]).replace("\n", "<br>")
            output += f"<td style='border:1px solid #999;padding:8px;vertical-align:top'>{value}</td>"
        output += "</tr>"
    return output + "</tbody></table>"


st.title("Programmation liturgique automatique")
st.caption("Aucun nom : uniquement F1–F10 et M1–M8")

if "scheduler_state" not in st.session_state:
    st.session_state.scheduler_state = initial_state()
if "last_rows" not in st.session_state:
    st.session_state.last_rows = []

with st.sidebar:
    st.header("Paramètres")
    year = int(st.number_input("Année", 2020, 2100, 2026, 1))
    month = st.selectbox("Mois", range(1, 13), index=8, format_func=lambda m: MONTHS[m-1])
    seed = int(st.number_input("Graine de brassage", 0, 999999, 2026, 1))
    lang = st.radio("Langue de la prochaine 1re lecture", ["FR", "MO"], horizontal=True,
                    index=0 if st.session_state.scheduler_state["next_first_language"] == "FR" else 1)
    st.session_state.scheduler_state["next_first_language"] = lang

    uploaded = st.file_uploader("Importer l'état de rotation (JSON)", type=["json"])
    if uploaded is not None:
        try:
            st.session_state.scheduler_state = normalize_state(json.load(uploaded))
            st.success("État importé.")
        except Exception as exc:
            st.error(f"Import impossible : {exc}")

    if st.button("Réinitialiser la rotation"):
        st.session_state.scheduler_state = initial_state()
        st.session_state.last_rows = []
        st.rerun()

month_sundays = sundays(year, month)
example = "\n".join(f"{d.isoformat()}|||" for d in month_sundays)

st.subheader("1. Références bibliques")
st.write("Saisissez une ligne par dimanche : `AAAA-MM-JJ | 1re lecture | 2e lecture | Évangile`.")
refs_text = st.text_area("Références", value=example, height=max(150, 35 * len(month_sundays)))

st.subheader("2. Générer")
st.write(
    "Règles : alternance FR/MO des 1re et 2e lectures ; alternance individuelle "
    "Lecture ↔ Monition/P.U. au prochain passage ; aucun doublon de lecture avant "
    "que la catégorie ait effectué son cycle ; espacement des lectures ; binômes "
    "non figés ; annonces indépendantes et sans cumul de fonction le même dimanche."
)

if st.button("Générer le programme", type="primary"):
    try:
        refs = parse_refs(refs_text, month_sundays)
        rows, new_state = generate_month(st.session_state.scheduler_state, year, month, refs, seed)
        st.session_state.scheduler_state = new_state
        st.session_state.last_rows = rows
    except Exception as exc:
        st.error(str(exc))

if st.session_state.last_rows:
    st.subheader("3. Programme généré")
    st.markdown(render_table(st.session_state.last_rows), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Télécharger le programme CSV", csv_data(st.session_state.last_rows),
                           "programme_liturgique.csv", "text/csv")
    with c2:
        state_bytes = json.dumps(st.session_state.scheduler_state, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button("Télécharger l'état JSON", state_bytes,
                           "etat_programmation.json", "application/json")

st.subheader("4. Contrôle de la rotation")
control = []
for code in FR + MO:
    p = st.session_state.scheduler_state["people"][code]
    control.append({
        "Code": code,
        "Prochaine fonction": p["next_role"] or "Libre (départ)",
        "Lectures": p["reading_count"],
        "Monitions/P.U.": p["monition_count"],
        "Annonces": p["announcement_count"],
        "Dernière lecture": p["last_reading"] or "—",
        "Dernier passage Lecture/Monition": p["last_service"] or "—",
    })
st.dataframe(control, use_container_width=True, hide_index=True)
