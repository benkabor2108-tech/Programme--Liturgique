"""Export PDF A4 des présences mensuelles."""
import io
from datetime import date, datetime, timedelta
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MONTHS = ["Janvier","Février","Mars","Avril","Mai","Juin","Juillet","Août","Septembre","Octobre","Novembre","Décembre"]

def available_attendance_months(state, today=None):
    today = today or date.today()
    months = {(today.year, today.month)}
    for key, sheet in (state.get("attendance", {}) or {}).items():
        try:
            day = date.fromisoformat(str((sheet or {}).get("date") or key))
        except (TypeError, ValueError):
            continue
        if day <= today:
            months.add((day.year, day.month))
    return sorted(months, reverse=True)

def monthly_attendance_data(state, year, month, today=None):
    today = today or date.today()
    sheets = []
    for key, sheet in (state.get("attendance", {}) or {}).items():
        try:
            day = date.fromisoformat(str((sheet or {}).get("date") or key))
        except (TypeError, ValueError):
            continue
        if day.year == year and day.month == month and day <= today:
            sheets.append((day, sheet))
    sheets.sort(key=lambda item: item[0])
    codes, seen = [], set()
    roster = state.get("roster", {}) or {}
    for code in list(roster.get("FR", [])) + list(roster.get("MO", [])):
        if code not in seen:
            seen.add(code); codes.append(code)
    for _, sheet in sheets:
        for code in (sheet.get("members", []) or []):
            if code not in seen:
                seen.add(code); codes.append(code)
    rows = []
    for code in codes:
        statuses=[]; p=j=a=0
        for _, sheet in sheets:
            value=str((sheet.get("statuses", {}) or {}).get(code, "")).upper()
            value=value if value in ("P","J","A") else "—"
            statuses.append(value)
            p += value == "P"; j += value == "J"; a += value == "A"
        name=(state.get("names", {}) or {}).get(code, code)
        for _, sheet in reversed(sheets):
            if code in (sheet.get("names", {}) or {}):
                name=sheet["names"][code]; break
        rows.append({"code":code,"name":name,"lang":"FR" if str(code).startswith("F") else "MO",
                     "statuses":statuses,"P":p,"J":j,"A":a,"P+J":p+j})
    rows.sort(key=lambda r:(0 if r["lang"]=="FR" else 1,str(r["name"]).casefold()))
    return sheets, rows

def _next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _eligibility_for_next_month(state, year, month, today):
    """Applique les règles historiques au cycle clôturé le 15 du mois sélectionné."""
    start_month_end = date(year, month, 1) - timedelta(days=1)
    start = date(start_month_end.year, start_month_end.month, 16)
    end = date(year, month, 15)
    cycle = []
    for key, sheet in (state.get("attendance", {}) or {}).items():
        try:
            day = date.fromisoformat(str((sheet or {}).get("date") or key))
        except (TypeError, ValueError):
            continue
        if start <= day <= end:
            cycle.append(sheet)
    enforced = today >= end and len(cycle) >= 2
    return cycle, enforced, start, end


def attendance_pdf_bytes(state, year, month, generated_at=None):
    generated_at = generated_at or datetime.now()
    today = generated_at.date()
    # Le mois sélectionné est celui à programmer ; la période se termine le 15 précédent.
    previous = date(year, month, 1) - timedelta(days=1)
    cycle, enforced, cycle_start, cycle_end = _eligibility_for_next_month(
        state, previous.year, previous.month, today
    )
    sheets = []
    for key, sheet in (state.get("attendance", {}) or {}).items():
        try:
            day = date.fromisoformat(str((sheet or {}).get("date") or key))
        except (TypeError, ValueError):
            continue
        if cycle_start <= day <= cycle_end and day <= today:
            sheets.append((day, sheet))
    sheets.sort(key=lambda item: item[0])
    roster = state.get("roster", {}) or {}
    codes = list(dict.fromkeys(
        list(roster.get("FR", [])) + list(roster.get("MO", []))
        + [code for _, sheet in sheets for code in (sheet.get("members", []) or [])]
    ))
    rows = []
    for code in codes:
        statuses = []
        for _, sheet in sheets:
            value = str((sheet.get("statuses", {}) or {}).get(code, "")).upper()
            statuses.append(value if value in ("P", "J", "A") else "—")
        name = (state.get("names", {}) or {}).get(code, code)
        for _, sheet in reversed(sheets):
            name = (sheet.get("names", {}) or {}).get(code, name)
        rows.append({"code": code, "name": name,
                     "lang": "FR" if str(code).startswith("F") else "MO",
                     "statuses": statuses,
                     "P+J": sum(v in ("P", "J") for v in statuses)})
    rows.sort(key=lambda r: (0 if r["lang"] == "FR" else 1, str(r["name"]).casefold()))
    title = f"Liste des présences — Programme de {MONTHS[month-1]} {year}"
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=landscape(A4), leftMargin=8*mm, rightMargin=8*mm,
        topMargin=8*mm, bottomMargin=8*mm, title=title, author="Programme liturgique"
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("AttendanceTitle", parent=styles["Title"],
        fontName="Helvetica-Bold", fontSize=14, leading=17,
        alignment=TA_CENTER, spaceAfter=2*mm)
    note_style = ParagraphStyle("AttendanceNote", parent=styles["Normal"],
        fontSize=7.2, leading=9, alignment=TA_CENTER,
        textColor=colors.HexColor("#4B5563"))
    head_style = ParagraphStyle("AttendanceHead", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=7, leading=9, alignment=TA_CENTER)
    cell_style = ParagraphStyle("AttendanceCell", parent=styles["Normal"],
        fontSize=7.2, leading=9)
    center_style = ParagraphStyle("AttendanceCenter", parent=cell_style, alignment=TA_CENTER)

    story = [Paragraph(title, title_style)]
    story.append(Paragraph(
        f"État extrait le {generated_at.strftime('%d/%m/%Y à %H:%M')} · "
        f"{len(sheets)} feuille(s) du cycle · "
        f"Cycle du {cycle_start.strftime('%d/%m/%Y')} au {cycle_end.strftime('%d/%m/%Y')}",
        note_style
    ))
    story.append(Spacer(1, 3*mm))

    headers = [Paragraph("Nom", head_style), Paragraph("Langue", head_style)]
    headers += [Paragraph(day.strftime("%d/%m"), head_style) for day, _ in sheets]
    headers += [Paragraph("Total (P + J)", head_style), Paragraph("Observation", head_style)]
    data = [headers]
    for row in rows:
        code = row["code"]
        p = j = 0
        for sheet in cycle:
            status = str((sheet.get("statuses", {}) or {}).get(code, "")).upper()
            p += status == "P"
            j += status == "J"
        eligible = p + j >= 2 and j < 3
        observation = ("Éligible" if eligible else "Non éligible") if enforced else "À confirmer"
        data.append([
            Paragraph(str(row["name"]), cell_style),
            Paragraph("Français" if row["lang"] == "FR" else "Mooré", center_style),
            *[Paragraph(v, center_style) for v in row["statuses"]],
            Paragraph(str(row["P+J"]), center_style),
            Paragraph(observation, center_style),
        ])

    available = 277*mm
    name_w, lang_w, total_w, observation_w = 59*mm, 27*mm, 26*mm, 35*mm
    date_count = len(sheets)
    date_w = (available - name_w - lang_w - total_w - observation_w) / max(1, date_count)
    widths = [name_w, lang_w] + [date_w]*date_count + [total_w, observation_w]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="CENTER")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#DCEAF7")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#1F2937")),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#9CA3AF")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 3),
        ("RIGHTPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    story.extend([table, Spacer(1, 3*mm)])
    story.append(Paragraph(
        "P = présent · J = absence justifiée comptabilisée · A = absence non justifiée · "
        "— = non renseigné. Le total est celui du cycle de programmation.",
        note_style
    ))
    story.append(Paragraph(
        f"L'observation pour {MONTHS[month-1]} {year} est calculée sur le cycle "
        f"du {cycle_start.strftime('%d/%m/%Y')} au {cycle_end.strftime('%d/%m/%Y')} : "
        "P + J ≥ 2 et moins de 3 J. "
        + ("Cycle clôturé, critères appliqués." if enforced else
           "À confirmer : cycle non clôturé ou moins de 2 feuilles enregistrées."),
        note_style
    ))
    if not sheets:
        story.append(Paragraph(
            "Aucune feuille de présence enregistrée pour ce cycle.", note_style
        ))
    doc.build(story)
    output.seek(0)
    return output.getvalue()
