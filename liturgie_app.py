import calendar
import html
import io
import json
import random
from copy import deepcopy
from datetime import date

import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Programme liturgique",
    page_icon="⛪",
    layout="centered",
    initial_sidebar_state="collapsed",
)

FR = [f"F{i}" for i in range(1, 11)]
MO = [f"M{i}" for i in range(1, 9)]
GROUPS = {"FR": FR, "MO": MO}
MONTHS = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]
ROLE_LABELS = {
    None: "Libre (départ)",
    "LECTURE": "Lecture",
    "MONITION": "Monition + P.U.",
}

# Interface mobile-first
st.markdown(
    """
    <style>
      .block-container {max-width: 900px; padding-top: 1rem; padding-bottom: 5rem;}
      div.stButton > button, div.stDownloadButton > button {
        width: 100%; min-height: 3rem; border-radius: 12px; font-weight: 700;
      }
      [data-testid="stMetricValue"] {font-size: 1.25rem;}
      .lit-card {border: 1px solid rgba(128,128,128,.25); border-radius: 14px;
                 padding: 14px; margin: 10px 0;}
      .lit-date {font-size: 1.15rem; font-weight: 800; margin-bottom: 8px;}
      .lit-grid {display:grid; grid-template-columns:1fr; gap:10px;}
      .lit-section {padding:10px; border-radius:10px; background:rgba(128,128,128,.07);}
      .lit-label {font-weight:800; margin-bottom:5px;}
      .small-note {font-size:.9rem; opacity:.8;}
      @media (min-width: 760px) {
        .lit-grid {grid-template-columns:1.15fr 1fr 1fr 1fr;}
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Etat et utilitaires
# -----------------------------------------------------------------------------
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
        "version": 2,
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
    return [
        d for d in cal.itermonthdates(year, month)
        if d.month == month and d.weekday() == 6
    ]


def history_has_month(state, year, month):
    prefix = f"{year:04d}-{month:02d}-"
    return any(str(row.get("date", "")).startswith(prefix) for row in state["history"])


def month_history(state, year, month):
    prefix = f"{year:04d}-{month:02d}-"
    return [row for row in state["history"] if str(row.get("date", "")).startswith(prefix)]


def reading_cycle_candidates(state, lang):
    codes = GROUPS[lang]
    seen = set(state["reading_cycle_seen"][lang])
    if len(seen) == len(codes):
        state["reading_cycle_seen"][lang] = []
        seen = set()
    return [c for c in codes if c not in seen]


def reading_pool(state, lang, excluded, unavailable):
    candidates = reading_cycle_candidates(state, lang)
    return [
        c for c in candidates
        if c not in excluded
        and c not in unavailable
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


def choose_reader(state, lang, today, excluded, unavailable, rng, locked=None):
    pool = reading_pool(state, lang, excluded, unavailable)
    if locked:
        if locked not in GROUPS[lang]:
            raise RuntimeError(f"{locked} n'appartient pas à la catégorie {lang}.")
        if locked in unavailable:
            raise RuntimeError(f"{locked} est indisponible le {today.strftime('%d/%m/%Y')}.")
        if locked not in pool:
            nxt = ROLE_LABELS[state["people"][locked]["next_role"]]
            raise RuntimeError(
                f"Verrou impossible pour {locked} en lecture le {today.strftime('%d/%m/%Y')}. "
                f"Sa prochaine fonction attendue est : {nxt}, ou son cycle de lecture n'est pas encore ouvert."
            )
        return locked
    if not pool:
        raise RuntimeError(
            f"Aucun lecteur {lang} disponible pour la lecture le {today.strftime('%d/%m/%Y')} "
            "sans casser la rotation individuelle ou le cycle d'équité."
        )
    rng.shuffle(pool)
    return min(pool, key=lambda c: reading_rank(state, c, today))


def monition_pool(state, lang, excluded, unavailable):
    return [
        c for c in GROUPS[lang]
        if c not in excluded
        and c not in unavailable
        and state["people"][c]["next_role"] in (None, "MONITION")
    ]


def monition_rank(state, code, today):
    p = state["people"][code]
    return (
        p["monition_count"],
        -days_since(p["last_service"], today),
        code,
    )


def choose_monition(state, lang, today, excluded, unavailable, rng, locked=None):
    pool = monition_pool(state, lang, excluded, unavailable)
    if locked:
        if locked not in GROUPS[lang]:
            raise RuntimeError(f"{locked} n'appartient pas à la catégorie {lang}.")
        if locked in unavailable:
            raise RuntimeError(f"{locked} est indisponible le {today.strftime('%d/%m/%Y')}.")
        if locked not in pool:
            nxt = ROLE_LABELS[state["people"][locked]["next_role"]]
            raise RuntimeError(
                f"Verrou impossible pour {locked} en monition/P.U. le {today.strftime('%d/%m/%Y')}. "
                f"Sa prochaine fonction attendue est : {nxt}."
            )
        return locked
    if not pool:
        raise RuntimeError(
            f"Aucun lecteur {lang} disponible pour monition/P.U. le {today.strftime('%d/%m/%Y')} "
            "sans casser l'alternance individuelle."
        )
    rng.shuffle(pool)
    return min(pool, key=lambda c: monition_rank(state, c, today))


def announcement_rank(state, code, today):
    p = state["people"][code]
    return (
        p["announcement_count"],
        -days_since(p["last_announcement"], today),
        code,
    )


def choose_announcement(state, lang, today, excluded, unavailable, rng, locked=None):
    pool = [
        c for c in GROUPS[lang]
        if c not in excluded and c not in unavailable
    ]
    if locked:
        if locked not in GROUPS[lang]:
            raise RuntimeError(f"{locked} n'appartient pas à la catégorie {lang}.")
        if locked in unavailable:
            raise RuntimeError(f"{locked} est indisponible le {today.strftime('%d/%m/%Y')}.")
        if locked in excluded:
            raise RuntimeError(f"{locked} a déjà une autre fonction le {today.strftime('%d/%m/%Y')}.")
        return locked
    if not pool:
        raise RuntimeError(f"Aucun {lang} disponible pour les annonces le {today.strftime('%d/%m/%Y')}.")
    rng.shuffle(pool)
    return min(pool, key=lambda c: announcement_rank(state, c, today))


def pair_penalty(pair, history_pairs):
    return 1 if list(pair) in history_pairs else 0


def choose_readers(state, today, unavailable, rng, locks):
    fr_locked = locks.get("lecture_fr")
    mo_locked = locks.get("lecture_mo")
    fr_pool = reading_pool(state, "FR", set(), unavailable)
    mo_pool = reading_pool(state, "MO", set(), unavailable)
    if fr_locked:
        fr_pool = [choose_reader(state, "FR", today, set(), unavailable, rng, fr_locked)]
    if mo_locked:
        mo_pool = [choose_reader(state, "MO", today, set(), unavailable, rng, mo_locked)]
    if not fr_pool or not mo_pool:
        raise RuntimeError(f"Impossible de constituer le binôme de lecture du {today.strftime('%d/%m/%Y')}.")

    choices = []
    for f in fr_pool:
        for m in mo_pool:
            score = (
                pair_penalty((f, m), state["reading_pairs"]),
                reading_rank(state, f, today),
                reading_rank(state, m, today),
                rng.random(),
            )
            choices.append((score, f, m))
    choices.sort(key=lambda x: x[0])
    return choices[0][1], choices[0][2]


def choose_monitions(state, today, excluded, unavailable, rng, locks):
    fr_locked = locks.get("monition_fr")
    mo_locked = locks.get("monition_mo")
    fr_pool = monition_pool(state, "FR", excluded, unavailable)
    mo_pool = monition_pool(state, "MO", excluded, unavailable)
    if fr_locked:
        fr_pool = [choose_monition(state, "FR", today, excluded, unavailable, rng, fr_locked)]
    if mo_locked:
        mo_pool = [choose_monition(state, "MO", today, excluded, unavailable, rng, mo_locked)]
    if not fr_pool or not mo_pool:
        raise RuntimeError(f"Impossible de constituer le binôme monition/P.U. du {today.strftime('%d/%m/%Y')}.")

    choices = []
    for f in fr_pool:
        for m in mo_pool:
            score = (
                pair_penalty((f, m), state["monition_pairs"]),
                monition_rank(state, f, today),
                monition_rank(state, m, today),
                rng.random(),
            )
            choices.append((score, f, m))
    choices.sort(key=lambda x: x[0])
    return choices[0][1], choices[0][2]


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
    errors = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 4:
            errors.append(f"Ligne {line_no}: format incomplet")
            continue
        try:
            date.fromisoformat(parts[0])
        except ValueError:
            errors.append(f"Ligne {line_no}: date invalide ({parts[0]})")
            continue
        refs[parts[0]] = {"r1": parts[1], "r2": parts[2], "ev": parts[3]}
    return refs, errors


def generate_month(state, year, month, refs, seed, unavailable_by_date=None, locks_by_date=None):
    state = normalize_state(deepcopy(state))
    rng = random.Random(seed + year * 100 + month)
    unavailable_by_date = unavailable_by_date or {}
    locks_by_date = locks_by_date or {}

    if history_has_month(state, year, month):
        raise RuntimeError(
            "Ce mois est déjà validé dans l'historique. Importez un état antérieur ou réinitialisez la rotation."
        )

    rows = []
    for sunday in sundays(year, month):
        key = sunday.isoformat()
        unavailable = set(unavailable_by_date.get(key, []))
        locks = locks_by_date.get(key, {})

        f_read, m_read = choose_readers(state, sunday, unavailable, rng, locks)
        first = state["next_first_language"]
        if first == "FR":
            r1_code, r1_lang, r2_code, r2_lang = f_read, "FR", m_read, "MO"
        else:
            r1_code, r1_lang, r2_code, r2_lang = m_read, "MO", f_read, "FR"

        excluded = {f_read, m_read}
        f_mon, m_mon = choose_monitions(state, sunday, excluded, unavailable, rng, locks)
        excluded.update({f_mon, m_mon})

        f_ann = choose_announcement(
            state, "FR", sunday, excluded, unavailable, rng, locks.get("annonce_fr")
        )
        m_ann = choose_announcement(
            state, "MO", sunday, excluded, unavailable, rng, locks.get("annonce_mo")
        )

        assign(state, f_read, "LECTURE", sunday)
        assign(state, m_read, "LECTURE", sunday)
        state["reading_pairs"].append([f_read, m_read])
        assign(state, f_mon, "MONITION", sunday)
        assign(state, m_mon, "MONITION", sunday)
        state["monition_pairs"].append([f_mon, m_mon])
        assign(state, f_ann, "ANNONCE", sunday)
        assign(state, m_ann, "ANNONCE", sunday)
        state["next_first_language"] = "MO" if first == "FR" else "FR"

        ref = refs.get(key, {"r1": "", "r2": "", "ev": ""})
        row = {
            "date": key,
            "Dx": f"D{sunday.day}",
            "Réf.D": f"1re : {ref['r1']}\n2e : {ref['r2']}\nÉv. : {ref['ev']}",
            "Lecteurs": f"1re : {r1_lang} — {r1_code}\n2e : {r2_lang} — {r2_code}",
            "Monition introductive + P.U.": f"FR — {f_mon}\nMO — {m_mon}",
            "Chargés d’annonce": f"FR — {f_ann}\nMO — {m_ann}",
        }
        rows.append(row)
        state["history"].append(row)

    return rows, state


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------
def rows_for_export(rows):
    fields = ["Dx", "Réf.D", "Lecteurs", "Monition introductive + P.U.", "Chargés d’annonce"]
    return fields, [{k: row.get(k, "") for k in fields} for row in rows]


def excel_data(rows, title="Programme liturgique"):
    fields, clean_rows = rows_for_export(rows)
    wb = Workbook()
    ws = wb.active
    ws.title = "Programme"
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(fields))
    ws.cell(1, 1, title)
    ws.cell(1, 1).font = Font(bold=True, size=16)
    ws.cell(1, 1).alignment = Alignment(horizontal="center")

    header_fill = PatternFill("solid", fgColor="D9EAD3")
    for col, field in enumerate(fields, start=1):
        cell = ws.cell(3, col, field)
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for r_idx, row in enumerate(clean_rows, start=4):
        for c_idx, field in enumerate(fields, start=1):
            cell = ws.cell(r_idx, c_idx, row[field])
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[r_idx].height = 58

    widths = [9, 30, 28, 30, 24]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    ws.freeze_panes = "A4"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def pdf_data(rows, title="Programme liturgique"):
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=landscape(A4),
        rightMargin=8 * mm,
        leftMargin=8 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
    )
    styles = getSampleStyleSheet()
    normal = styles["BodyText"]
    normal.fontName = "Helvetica"
    normal.fontSize = 7.5
    normal.leading = 9
    head = styles["Heading2"]
    head.alignment = 1

    fields, clean_rows = rows_for_export(rows)
    data = [[Paragraph(f"<b>{html.escape(f)}</b>", normal) for f in fields]]
    for row in clean_rows:
        data.append([
            Paragraph(html.escape(str(row[f])).replace("\n", "<br/>"), normal)
            for f in fields
        ])

    table = Table(data, colWidths=[18 * mm, 56 * mm, 50 * mm, 56 * mm, 48 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAD3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    doc.build([Paragraph(title, head), Spacer(1, 4 * mm), table])
    return out.getvalue()


def json_state_bytes(state):
    return json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")


# -----------------------------------------------------------------------------
# Rendu mobile
# -----------------------------------------------------------------------------
def render_mobile_cards(rows):
    for row in rows:
        st.markdown(
            f"""
            <div class="lit-card">
              <div class="lit-date">{html.escape(row['Dx'])}</div>
              <div class="lit-grid">
                <div class="lit-section"><div class="lit-label">Réf.D</div>{html.escape(row['Réf.D']).replace(chr(10), '<br>')}</div>
                <div class="lit-section"><div class="lit-label">Lecteurs</div>{html.escape(row['Lecteurs']).replace(chr(10), '<br>')}</div>
                <div class="lit-section"><div class="lit-label">Monition + P.U.</div>{html.escape(row['Monition introductive + P.U.']).replace(chr(10), '<br>')}</div>
                <div class="lit-section"><div class="lit-label">Annonces</div>{html.escape(row['Chargés d’annonce']).replace(chr(10), '<br>')}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def availability_key(year, month, day):
    return f"availability_{year}_{month}_{day}"


def lock_key(year, month, day, role):
    return f"lock_{year}_{month}_{day}_{role}"


def ensure_session():
    if "scheduler_state" not in st.session_state:
        st.session_state.scheduler_state = initial_state()
    if "draft_rows" not in st.session_state:
        st.session_state.draft_rows = []
    if "draft_state" not in st.session_state:
        st.session_state.draft_state = None
    if "draft_meta" not in st.session_state:
        st.session_state.draft_meta = None
    if "generation_nonce" not in st.session_state:
        st.session_state.generation_nonce = 0


ensure_session()

# -----------------------------------------------------------------------------
# En-tête
# -----------------------------------------------------------------------------
st.title("⛪ Programme liturgique")
st.caption("Programmation automatique avec F1–F10 et M1–M8 — sans noms")

home, generator, history_tab, rotation_tab, settings_tab = st.tabs([
    "🏠 Accueil", "✨ Générer", "🕘 Historique", "🔄 Rotation", "⚙️ Réglages"
])

# -----------------------------------------------------------------------------
# ACCUEIL
# -----------------------------------------------------------------------------
with home:
    state = st.session_state.scheduler_state
    c1, c2, c3 = st.columns(3)
    c1.metric("Francophones", len(FR))
    c2.metric("Mooréphones", len(MO))
    c3.metric("Dimanches validés", len(state["history"]))

    st.markdown("### Règles actives")
    st.markdown(
        "- **1re/2e lecture :** alternance FR ↔ MO chaque dimanche.\n"
        "- **Par personne :** Lecture ↔ Monition/P.U. à son prochain passage.\n"
        "- **Lectures :** équité du cycle et espacement du dernier passage.\n"
        "- **Binômes :** éviter de reformer les mêmes couples FR–MO.\n"
        "- **Annonces :** indépendantes de l'alternance Lecture/Monition.\n"
        "- **Même dimanche :** pas de cumul de deux fonctions."
    )

    if st.session_state.draft_rows:
        st.info("Un brouillon est en attente de validation dans l'onglet ✨ Générer.")

# -----------------------------------------------------------------------------
# GENERATEUR
# -----------------------------------------------------------------------------
with generator:
    st.markdown("### 1. Choisir la période")
    c1, c2 = st.columns(2)
    with c1:
        year = int(st.number_input("Année", 2020, 2100, 2026, 1, key="gen_year"))
    with c2:
        month = st.selectbox(
            "Mois", range(1, 13), index=8,
            format_func=lambda m: MONTHS[m - 1], key="gen_month"
        )

    month_sundays = sundays(year, month)
    st.caption("Dimanches : " + ", ".join(d.strftime("%d/%m") for d in month_sundays))

    if history_has_month(st.session_state.scheduler_state, year, month):
        st.warning("Ce mois est déjà validé dans l'historique. Vous pouvez le consulter dans 🕘 Historique.")

    st.markdown("### 2. Références bibliques")
    ref_default = "\n".join(f"{d.isoformat()} |  |  | " for d in month_sundays)
    refs_text = st.text_area(
        "Une ligne par dimanche : date | 1re lecture | 2e lecture | Évangile",
        value=ref_default,
        height=max(150, 38 * len(month_sundays)),
        key=f"refs_{year}_{month}",
        help="Exemple : 2026-09-06 | Ez 33,7-9 | Rm 13,8-10 | Mt 18,15-20",
    )

    with st.expander("🚫 Indisponibilités par dimanche", expanded=False):
        st.caption("Cochez les lecteurs absents. Ils ne recevront aucune fonction ce dimanche.")
        for d in month_sundays:
            st.multiselect(
                d.strftime("Dimanche %d/%m/%Y"),
                FR + MO,
                key=availability_key(year, month, d.day),
                placeholder="Aucune indisponibilité",
            )

    with st.expander("🔒 Verrouiller certaines affectations", expanded=False):
        st.caption("Optionnel. Laissez « Auto » pour laisser l'algorithme choisir.")
        for d in month_sundays:
            st.markdown(f"**{d.strftime('%d/%m/%Y')}**")
            a, b = st.columns(2)
            with a:
                st.selectbox("Lecture FR", ["Auto"] + FR, key=lock_key(year, month, d.day, "lecture_fr"))
                st.selectbox("Monition FR", ["Auto"] + FR, key=lock_key(year, month, d.day, "monition_fr"))
                st.selectbox("Annonce FR", ["Auto"] + FR, key=lock_key(year, month, d.day, "annonce_fr"))
            with b:
                st.selectbox("Lecture MO", ["Auto"] + MO, key=lock_key(year, month, d.day, "lecture_mo"))
                st.selectbox("Monition MO", ["Auto"] + MO, key=lock_key(year, month, d.day, "monition_mo"))
                st.selectbox("Annonce MO", ["Auto"] + MO, key=lock_key(year, month, d.day, "annonce_mo"))
            st.divider()

    st.markdown("### 3. Génération")
    seed = int(st.number_input("Graine de brassage", 0, 999999, 2026, 1, key="seed"))
    current_first = st.session_state.scheduler_state["next_first_language"]
    st.caption(f"Prochaine 1re lecture prévue : **{current_first}**")

    unavailable = {}
    locks = {}
    for d in month_sundays:
        key = d.isoformat()
        unavailable[key] = st.session_state.get(availability_key(year, month, d.day), [])
        day_locks = {}
        for role in ["lecture_fr", "lecture_mo", "monition_fr", "monition_mo", "annonce_fr", "annonce_mo"]:
            value = st.session_state.get(lock_key(year, month, d.day, role), "Auto")
            if value != "Auto":
                day_locks[role] = value
        locks[key] = day_locks

    generate_clicked = st.button("✨ Générer un brouillon", type="primary")
    if generate_clicked:
        refs, errors = parse_refs(refs_text, month_sundays)
        if errors:
            st.error("Références : " + " ; ".join(errors))
        else:
            try:
                effective_seed = seed + st.session_state.generation_nonce
                rows, draft_state = generate_month(
                    st.session_state.scheduler_state,
                    year,
                    month,
                    refs,
                    effective_seed,
                    unavailable,
                    locks,
                )
                st.session_state.draft_rows = rows
                st.session_state.draft_state = draft_state
                st.session_state.draft_meta = {"year": year, "month": month, "seed": effective_seed}
                st.success("Brouillon généré. Vérifiez-le avant validation.")
            except Exception as exc:
                st.error(str(exc))

    if st.session_state.draft_rows:
        meta = st.session_state.draft_meta or {}
        st.markdown("### 4. Brouillon")
        st.caption(
            f"{MONTHS[meta.get('month', month)-1]} {meta.get('year', year)} — non encore comptabilisé dans la rotation"
        )
        render_mobile_cards(st.session_state.draft_rows)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔀 Régénérer"):
                st.session_state.generation_nonce += 1
                st.session_state.draft_rows = []
                st.session_state.draft_state = None
                st.info("La graine de brassage a été modifiée. Appuyez sur « Générer un brouillon ».")
        with c2:
            if st.button("✅ Valider ce mois", type="primary"):
                st.session_state.scheduler_state = st.session_state.draft_state
                st.session_state.draft_rows = []
                st.session_state.draft_state = None
                st.session_state.draft_meta = None
                st.success("Programme validé et ajouté à l'historique.")
                st.rerun()

        st.caption("Pour modifier une affectation : utilisez les verrous ou les indisponibilités, puis régénérez le brouillon.")

        st.markdown("### 5. Exporter le brouillon")
        ex1, ex2 = st.columns(2)
        with ex1:
            st.download_button(
                "📊 Excel",
                excel_data(st.session_state.draft_rows, "Programme liturgique — Brouillon"),
                "programme_liturgique_brouillon.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with ex2:
            st.download_button(
                "📄 PDF",
                pdf_data(st.session_state.draft_rows, "Programme liturgique — Brouillon"),
                "programme_liturgique_brouillon.pdf",
                "application/pdf",
            )

# -----------------------------------------------------------------------------
# HISTORIQUE
# -----------------------------------------------------------------------------
with history_tab:
    st.markdown("### Historique validé")
    hist = st.session_state.scheduler_state["history"]
    if not hist:
        st.info("Aucun mois n'est encore validé.")
    else:
        years = sorted({int(r["date"][:4]) for r in hist})
        hy = st.selectbox("Année", years, index=len(years) - 1, key="hist_year")
        months_available = sorted({int(r["date"][5:7]) for r in hist if int(r["date"][:4]) == hy})
        hm = st.selectbox(
            "Mois", months_available, index=len(months_available) - 1,
            format_func=lambda m: MONTHS[m - 1], key="hist_month"
        )
        rows = month_history(st.session_state.scheduler_state, hy, hm)
        render_mobile_cards(rows)
        st.markdown("#### Export")
        a, b = st.columns(2)
        with a:
            st.download_button(
                "📊 Excel",
                excel_data(rows, f"Programme liturgique — {MONTHS[hm-1]} {hy}"),
                f"programme_{hy}_{hm:02d}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with b:
            st.download_button(
                "📄 PDF",
                pdf_data(rows, f"Programme liturgique — {MONTHS[hm-1]} {hy}"),
                f"programme_{hy}_{hm:02d}.pdf",
                "application/pdf",
            )

# -----------------------------------------------------------------------------
# ROTATION
# -----------------------------------------------------------------------------
with rotation_tab:
    st.markdown("### Contrôle individuel")
    group_filter = st.radio("Catégorie", ["Tous", "FR", "MO"], horizontal=True)
    codes = FR + MO if group_filter == "Tous" else GROUPS[group_filter]
    control = []
    for code in codes:
        p = st.session_state.scheduler_state["people"][code]
        control.append({
            "Code": code,
            "Prochaine fonction": ROLE_LABELS[p["next_role"]],
            "Lectures": p["reading_count"],
            "Monitions/P.U.": p["monition_count"],
            "Annonces": p["announcement_count"],
            "Dernière lecture": p["last_reading"] or "—",
            "Dernier passage L/M": p["last_service"] or "—",
        })
    st.dataframe(control, use_container_width=True, hide_index=True)

    st.markdown("### Cycle de lecture en cours")
    st.write("FR déjà passés :", ", ".join(st.session_state.scheduler_state["reading_cycle_seen"]["FR"]) or "—")
    st.write("MO déjà passés :", ", ".join(st.session_state.scheduler_state["reading_cycle_seen"]["MO"]) or "—")

# -----------------------------------------------------------------------------
# REGLAGES / SAUVEGARDE
# -----------------------------------------------------------------------------
with settings_tab:
    st.markdown("### Sauvegarder / restaurer")
    st.download_button(
        "💾 Sauvegarder l'état de rotation (JSON)",
        json_state_bytes(st.session_state.scheduler_state),
        "etat_programmation.json",
        "application/json",
    )

    uploaded = st.file_uploader("Restaurer un état JSON", type=["json"], key="restore_json")
    if uploaded is not None:
        try:
            restored = normalize_state(json.load(uploaded))
            st.session_state.scheduler_state = restored
            st.session_state.draft_rows = []
            st.session_state.draft_state = None
            st.success("État restauré.")
        except Exception as exc:
            st.error(f"Import impossible : {exc}")

    st.markdown("### Première langue")
    current = st.session_state.scheduler_state["next_first_language"]
    chosen = st.radio(
        "Langue de la prochaine 1re lecture",
        ["FR", "MO"], horizontal=True,
        index=0 if current == "FR" else 1,
        key="first_language_setting",
    )
    if chosen != current:
        st.session_state.scheduler_state["next_first_language"] = chosen
        st.success(f"Prochaine 1re lecture réglée sur {chosen}.")

    st.markdown("### Réinitialisation")
    st.warning("La réinitialisation efface l'historique et tous les compteurs de rotation.")
    confirm_reset = st.checkbox("Je confirme vouloir tout réinitialiser")
    if st.button("🗑️ Réinitialiser", disabled=not confirm_reset):
        st.session_state.scheduler_state = initial_state()
        st.session_state.draft_rows = []
        st.session_state.draft_state = None
        st.session_state.draft_meta = None
        st.success("Rotation réinitialisée.")
        st.rerun()

st.markdown("---")
st.markdown(
    '<div class="small-note">Conseil mobile : après déploiement, ajoutez la page à votre écran d’accueil pour l’ouvrir comme une application.</div>',
    unsafe_allow_html=True,
)
