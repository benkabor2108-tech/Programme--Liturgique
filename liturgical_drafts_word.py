import io
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from liturgical_drafts_source import normalize_text


def _set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def build_word_document(meta, monition, pu_intro, intentions, pu_conclusion, response):
    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(11.5)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("MONITION INTRODUCTIVE ET PRIÈRE UNIVERSELLE")
    run.bold = True
    run.font.size = Pt(15)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(meta.get("celebration", "Célébration liturgique"))
    run.bold = True
    run.font.size = Pt(12.5)

    season = str(meta.get("liturgical_season", "") or "").strip()
    if season:
        season_p = document.add_paragraph()
        season_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sr = season_p.add_run(season)
        sr.italic = True
        sr.font.size = Pt(10.5)

    date_p = document.add_paragraph()
    date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_p.add_run(meta["date_label"]).italic = True

    refs_table = document.add_table(rows=1, cols=2)
    refs_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    refs_table.style = "Table Grid"
    hdr = refs_table.rows[0].cells
    hdr[0].text = "Lecture"
    hdr[1].text = "Référence"
    for cell in hdr:
        _set_cell_shading(cell, "D9EAF7")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
    _set_repeat_table_header(refs_table.rows[0])

    for label, key in (("1re lecture", "r1"), ("Psaume", "ps"), ("2e lecture", "r2"), ("Évangile", "ev")):
        ref = meta.get("refs", {}).get(key, "")
        if not ref:
            continue
        cells = refs_table.add_row().cells
        cells[0].text = label
        cells[1].text = ref

    document.add_paragraph()
    heading = document.add_paragraph()
    run = heading.add_run("MONITION INTRODUCTIVE")
    run.bold = True
    run.font.size = Pt(13)

    p = document.add_paragraph(monition.strip())
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    heading = document.add_paragraph()
    run = heading.add_run("PRIÈRE UNIVERSELLE")
    run.bold = True
    run.font.size = Pt(13)

    p = document.add_paragraph(pu_intro.strip())
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    for idx, intention in enumerate(intentions, start=1):
        p = document.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.4)
        p.paragraph_format.first_line_indent = Cm(-0.4)
        lead = p.add_run(f"{idx}. ")
        lead.bold = True
        p.add_run(str(intention).strip())
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        if response.strip():
            resp = document.add_paragraph()
            resp.paragraph_format.left_indent = Cm(0.8)
            rr = resp.add_run(f"R/ {response.strip()}")
            rr.italic = True
            rr.bold = True

    conclusion_label = document.add_paragraph()
    conclusion_label.add_run("Prière de conclusion").bold = True
    p = document.add_paragraph(pu_conclusion.strip())
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    document.add_paragraph()
    note = document.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    nr = note.add_run(
        f"Références liturgiques : AELF — {meta.get('zone_label', meta.get('zone', 'romain'))}. "
        "Proposition de rédaction à relire et adapter si nécessaire avant proclamation."
    )
    nr.italic = True
    nr.font.size = Pt(8.5)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer.add_run("Programme liturgique — document de préparation")
    fr.font.size = Pt(8)

    output = io.BytesIO()
    document.save(output)
    output.seek(0)
    return output.getvalue()
