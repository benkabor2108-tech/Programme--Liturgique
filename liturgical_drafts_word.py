import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt


def build_word_document(meta, monition, pu_intro, intentions, pu_conclusion, response):
    """Construit le document final avec uniquement la monition et les 4 intentions."""
    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    normal = document.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(11.5)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    date_label = str(meta.get("date_label", "")).strip()

    heading = document.add_paragraph()
    run = heading.add_run(f"MONITION DU {date_label}" if date_label else "MONITION")
    run.bold = True
    run.font.size = Pt(14)

    p = document.add_paragraph(str(monition or "").strip())
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    heading = document.add_paragraph()
    run = heading.add_run(f"PRIÈRE UNIVERSELLE DU {date_label}" if date_label else "PRIÈRE UNIVERSELLE")
    run.bold = True
    run.font.size = Pt(14)

    for idx, intention in enumerate(list(intentions or [])[:4], start=1):
        p = document.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.4)
        p.paragraph_format.first_line_indent = Cm(-0.4)
        lead = p.add_run(f"{idx}. ")
        lead.bold = True
        p.add_run(str(intention).strip())
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer.add_run("Programme liturgique — document de préparation")
    fr.font.size = Pt(8)

    output = io.BytesIO()
    document.save(output)
    output.seek(0)
    return output.getvalue()
