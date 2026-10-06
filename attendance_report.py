"""Export PDF A4 des présences mensuelles."""
import io
from datetime import date, datetime
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

def attendance_pdf_bytes(state, year, month, generated_at=None):
    generated_at=generated_at or datetime.now()
    today=generated_at.date()
    sheets,rows=monthly_attendance_data(state,year,month,today=today)
    title=f"État des présences — {MONTHS[month-1]} {year}"
    current=(year,month)==(today.year,today.month)
    output=io.BytesIO()
    doc=SimpleDocTemplate(output,pagesize=landscape(A4),leftMargin=8*mm,rightMargin=8*mm,
        topMargin=8*mm,bottomMargin=8*mm,title=title,author="Programme liturgique")
    styles=getSampleStyleSheet()
    title_style=ParagraphStyle("AttendanceTitle",parent=styles["Title"],fontName="Helvetica-Bold",
        fontSize=15,leading=17,alignment=TA_CENTER,spaceAfter=2*mm)
    note_style=ParagraphStyle("AttendanceNote",parent=styles["Normal"],fontSize=7.5,leading=9,
        alignment=TA_CENTER,textColor=colors.HexColor("#4B5563"))
    head_style=ParagraphStyle("AttendanceHead",parent=styles["Normal"],fontName="Helvetica-Bold",
        fontSize=7,leading=8,alignment=TA_CENTER)
    cell_style=ParagraphStyle("AttendanceCell",parent=styles["Normal"],fontSize=7.2,leading=8.5)
    center_style=ParagraphStyle("AttendanceCenter",parent=cell_style,alignment=TA_CENTER)
    story=[Paragraph(title,title_style)]
    state_label="État provisoire du mois en cours" if current else "État du mois écoulé"
    story.append(Paragraph(f"{state_label} · extrait le {generated_at.strftime('%d/%m/%Y à %H:%M')} · {len(sheets)} feuille(s) enregistrée(s)",note_style))
    story.append(Spacer(1,3*mm))
    headers=[Paragraph("Membre",head_style),Paragraph("Groupe",head_style)]
    headers += [Paragraph(day.strftime("%d/%m"),head_style) for day,_ in sheets]
    headers += [Paragraph(x,head_style) for x in ("P","J","A","P+J")]
    data=[headers]
    for row in rows:
        data.append([Paragraph(str(row["name"]),cell_style),
            Paragraph("Francophone" if row["lang"]=="FR" else "Mooréphone",center_style),
            *[Paragraph(v,center_style) for v in row["statuses"]],
            *[Paragraph(str(row[x]),center_style) for x in ("P","J","A","P+J")]])
    available=277*mm; member_w=52*mm; group_w=26*mm; total_w=12*mm
    date_w=max(14*mm,(available-member_w-group_w-4*total_w)/max(1,len(sheets)))
    widths=[member_w,group_w]+[date_w]*len(sheets)+[total_w]*4
    table=Table(data,colWidths=widths,repeatRows=1,hAlign="CENTER")
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DCEAF7")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#1F2937")),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#9CA3AF")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F8FAFC")]),
    ]))
    story += [table,Spacer(1,3*mm),Paragraph(
        "Légende : P = présent · J = absence justifiée (comptée comme présence) · A = absence non justifiée · — = aucun statut enregistré. P+J = total des présences comptabilisées.",
        note_style)]
    if not sheets:
        story += [Spacer(1,2*mm),Paragraph("Aucune feuille de présence n'est enregistrée pour ce mois à la date de l'extraction.",note_style)]
    doc.build(story); output.seek(0); return output.getvalue()
