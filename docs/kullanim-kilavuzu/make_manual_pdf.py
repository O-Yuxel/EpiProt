"""Builds EpiProt-Kullanim-Kilavuzu.pdf from EpiProt-Kullanim-Kilavuzu.md (the Markdown file is the source).

Handles the Markdown used in the manual: # / ## / ### headings, paragraphs, **bold**, - and 1. lists (also
indented), | tables |, ![images](file.png), > notes and ---. Needs reportlab and the Segoe UI fonts (Windows) or
DejaVu Sans:
  python docs/kullanim-kilavuzu/make_manual_pdf.py
"""
import os
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "EpiProt-Kullanim-Kilavuzu.md")
OUT = os.path.join(HERE, "EpiProt-Kullanim-Kilavuzu.pdf")

TEAL, TEAL_D, TEAL_S = colors.HexColor("#0E7C86"), colors.HexColor("#075E66"), colors.HexColor("#DDF1F1")
CORAL, CORAL_S = colors.HexColor("#B0302A"), colors.HexColor("#FBE3E0")
INK, INK_S, LINE, BG = colors.HexColor("#1B2B2E"), colors.HexColor("#5B6B6E"), colors.HexColor("#D5E0E0"), colors.HexColor("#F4F8F8")

FONT_DIRS = [os.environ.get("FONT_DIR", ""), "C:/Windows/Fonts", "/usr/share/fonts/truetype/win", "/usr/share/fonts/truetype/dejavu"]


def font(names):
    for d in FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if d and os.path.exists(p):
                return p
    raise SystemExit(f"font not found: {names}")


pdfmetrics.registerFont(TTFont("R", font(["segoeui.ttf", "DejaVuSans.ttf"])))
pdfmetrics.registerFont(TTFont("B", font(["segoeuib.ttf", "DejaVuSans-Bold.ttf"])))
pdfmetrics.registerFontFamily("R", normal="R", bold="B", italic="R", boldItalic="B")

S = {
    "title": ParagraphStyle("title", fontName="B", fontSize=30, leading=36, textColor=TEAL_D, spaceAfter=8),
    "sub": ParagraphStyle("sub", fontName="R", fontSize=15, leading=20, textColor=INK_S, spaceAfter=18),
    "h2": ParagraphStyle("h2", fontName="B", fontSize=17, leading=22, textColor=TEAL_D, spaceBefore=4, spaceAfter=8),
    "h3": ParagraphStyle("h3", fontName="B", fontSize=12.5, leading=16, textColor=INK, spaceBefore=8, spaceAfter=4),
    "p": ParagraphStyle("p", fontName="R", fontSize=10.5, leading=15, textColor=INK, spaceAfter=6, alignment=TA_LEFT),
    "li": ParagraphStyle("li", fontName="R", fontSize=10.5, leading=14.5, textColor=INK),
    "cell": ParagraphStyle("cell", fontName="R", fontSize=9.5, leading=12.5, textColor=INK),
    "head": ParagraphStyle("head", fontName="B", fontSize=9.5, leading=12.5, textColor=INK),
    "note": ParagraphStyle("note", fontName="R", fontSize=10.5, leading=15, textColor=INK),
    "small": ParagraphStyle("small", fontName="R", fontSize=8.5, leading=11, textColor=INK_S),
}


def inline(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", t)          # *italic* -> plain
    return t


def lists(lines):
    """Bullet / numbered list with one nesting level -> ListFlowable."""
    items, numbered = [], bool(re.match(r"\s*\d+\.", lines[0]))
    for ln in lines:
        m = re.match(r"(\s*)(?:[-*]|\d+\.)\s+(.*)", ln)
        if not m:
            continue
        depth = 1 if len(m.group(1)) >= 2 else 0
        items.append((depth, m.group(2)))
    out, i = [], 0
    while i < len(items):
        d, text = items[i]
        sub = []
        j = i + 1
        while j < len(items) and items[j][0] > d:
            sub.append(items[j][1]); j += 1
        flow = [Paragraph(inline(text), S["li"])]
        if sub:
            flow.append(ListFlowable([ListItem(Paragraph(inline(x), S["li"]), leftIndent=12) for x in sub],
                                     bulletType="bullet", start="–", leftIndent=14, bulletFontName="R"))
        out.append(ListItem(flow, leftIndent=16, value=None))
        i = j
    return ListFlowable(out, bulletType="1" if numbered else "bullet", start=None if numbered else "•",
                        leftIndent=16, bulletFontName="B" if numbered else "R", bulletColor=TEAL_D, spaceAfter=6)


def table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not re.match(r"^\|\s*-", r)]
    head = cells[0]
    has_head = any(h for h in head)
    data = [[Paragraph(inline(c), S["head"] if (k == 0 and has_head) else S["cell"]) for c in row] for k, row in enumerate(cells)]
    if not has_head:
        data = data[1:]
    ncol = len(cells[0])
    width = 170 * mm
    widths = [width * (0.42 if ncol == 2 and i == 0 else (0.58 if ncol == 2 else 1 / ncol)) for i in range(ncol)]
    t = Table(data, colWidths=widths, repeatRows=1 if has_head else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if has_head:
        style.append(("BACKGROUND", (0, 0), (-1, 0), TEAL_S))
    for r in range(1 if has_head else 0, len(data)):
        if r % 2 == 0:
            style.append(("BACKGROUND", (0, r), (-1, r), BG))
    t.setStyle(TableStyle(style))
    return [t, Spacer(1, 8)]


def note(text):
    t = Table([[Paragraph(inline(text), S["note"])]], colWidths=[170 * mm])
    warn = "ÖNEMLİ" in text or "UYARI" in text
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CORAL_S if warn else TEAL_S),
                           ("LINEBEFORE", (0, 0), (0, -1), 3, CORAL if warn else TEAL),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return [t, Spacer(1, 10)]


def image(path):
    p = os.path.join(HERE, path)
    img = Image(p)
    w = 160 * mm
    img.drawHeight = img.drawHeight * w / img.drawWidth
    img.drawWidth = w
    return [img, Spacer(1, 8)]


def build():
    lines = open(SRC, encoding="utf-8").read().splitlines()
    story, i, first_h2 = [], 0, True
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1; continue
        if ln.startswith("# "):
            story += [Spacer(1, 60), Paragraph(inline(ln[2:]), S["title"])]
            i += 1
            if i < len(lines) and lines[i].startswith("**"):
                story.append(Paragraph(inline(lines[i]).replace("<b>", "").replace("</b>", ""), S["sub"])); i += 1
            continue
        if ln.startswith("## "):
            if not first_h2:
                story.append(PageBreak())
            first_h2 = False
            story.append(Paragraph(inline(ln[3:]), S["h2"])); i += 1; continue
        if ln.startswith("### "):
            story.append(Paragraph(inline(ln[4:]), S["h3"])); i += 1; continue
        if ln.startswith("!["):
            m = re.match(r"!\[[^]]*]\(([^)]+)\)", ln)
            story += image(m.group(1)); i += 1; continue
        if ln.startswith(">"):
            block = []
            while i < len(lines) and lines[i].startswith(">"):
                block.append(lines[i].lstrip("> ").strip()); i += 1
            story += note(" ".join(block)); continue
        if ln.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i]); i += 1
            story += table(block); continue
        if re.match(r"\s*(?:[-*]|\d+\.)\s+", ln):
            block = []
            while i < len(lines) and (re.match(r"\s*(?:[-*]|\d+\.)\s+", lines[i])):
                block.append(lines[i]); i += 1
            story.append(lists(block)); continue
        if ln.strip() == "---":
            story.append(Spacer(1, 10)); i += 1; continue
        if ln.startswith("*") and ln.endswith("*") and not ln.startswith("**"):
            story.append(Paragraph(inline(ln), S["small"])); i += 1; continue
        block = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"(#|!\[|>|\||\s*(?:[-*]|\d+\.)\s)", lines[i]):
            block.append(lines[i]); i += 1
        story.append(Paragraph(inline(" ".join(block)), S["p"]))

    def footer(c, doc):
        c.saveState()
        c.setFont("R", 8)
        c.setFillColor(INK_S)
        c.drawString(20 * mm, 12 * mm, "EpiProt Kullanım Kılavuzu")
        c.drawRightString(190 * mm, 12 * mm, str(doc.page))
        c.setStrokeColor(LINE)
        c.line(20 * mm, 16 * mm, 190 * mm, 16 * mm)
        c.restoreState()

    doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=22 * mm, title="EpiProt Kullanım Kılavuzu", author="EpiProt")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("wrote", OUT)


build()
