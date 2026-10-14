"""Export PDF autonome des textes proclamés par les lecteurs."""
import io
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def _fonts():
    regular = os.path.join(FONT_DIR, "DejaVuSerif.ttf")
    bold = os.path.join(FONT_DIR, "DejaVuSerif-Bold.ttf")
    if os.path.isfile(regular) and os.path.isfile(bold):
        if "ReaderSerif" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ReaderSerif", regular))
            pdfmetrics.registerFont(TTFont("ReaderSerif-Bold", bold))
            pdfmetrics.registerFontFamily("ReaderSerif", normal="ReaderSerif", bold="ReaderSerif-Bold")
        return "ReaderSerif"
    # Ne pas produire un PDF corrompu ou dépourvu d'accents.
    raise RuntimeError("Polices Unicode DejaVu indisponibles pour l'export PDF.")


def build_reader_pdf(meta, monition, intentions):
    """Même contenu lecteur que le Word : aucune partie réservée au célébrant."""
    font = _fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title="Monition et prière universelle",
    )
    base = ParagraphStyle("reader", fontName=font, fontSize=11, leading=17,
                          alignment=TA_JUSTIFY, spaceAfter=9)
    center = ParagraphStyle("reader_center", parent=base, alignment=TA_CENTER)
    title = ParagraphStyle("reader_title", parent=center, fontSize=12, leading=17, spaceAfter=6)
    subtitle = ParagraphStyle("reader_subtitle", parent=center, fontSize=9, leading=13, spaceAfter=4)
    section = ParagraphStyle("reader_section", parent=center, fontSize=13, leading=18,
                             spaceBefore=16, spaceAfter=12)
    refs = meta.get("references", "")
    if not refs and isinstance(meta.get("refs"), dict):
        refs = " • ".join(str(meta["refs"].get(k) or "").strip()
                          for k in ("r1", "ps", "r2", "ev") if meta["refs"].get(k))
    story = []
    if meta.get("celebration"):
        story.append(Paragraph("<b>" + escape(str(meta["celebration"]).upper()) + "</b>", title))
    if meta.get("date_label"):
        story.append(Paragraph(escape(str(meta["date_label"])), subtitle))
    if refs:
        story.append(Paragraph("<i>" + escape(str(refs)) + "</i>", subtitle))
    if story:
        story.extend([Spacer(1, 7), HRFlowable(width="100%", thickness=0.6, color=colors.grey)])
    story.append(Paragraph("<b>MONITION</b>", section))
    for part in str(monition or "").strip().split("\n\n"):
        if part.strip():
            story.append(Paragraph(escape(" ".join(part.split())), base))
    story.append(Paragraph("<b>PRIÈRE UNIVERSELLE</b>", section))
    nonempty_intentions = [value for value in list(intentions or [])[:4] if str(value or "").strip()]
    for idx, raw in enumerate(nonempty_intentions, 1):
        body = str(raw or "").strip()
        ending = "Prions le Seigneur."
        if body.endswith(ending):
            body = body[:-len(ending)].rstrip()
        else:
            body = body.rstrip()
        if body:
            story.append(Paragraph(
                "<b>" + str(idx) + ".</b> " + escape(" ".join(body.split()))
                + " <b>" + ending + "</b>", base,
            ))
    doc.build(story)
    return buf.getvalue()
