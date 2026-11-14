"""Excel export with formatting, autofilter and colour-coded lead tags."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from database import Lead
from enricher import COLD, HOT, WARM

COLUMNS = [
    ("Tag", 12), ("Motiv", 30), ("Nume", 36), ("Categorie", 24), ("Rating", 8), ("Recenzii", 10),
    ("Telefon", 18), ("Email", 32), ("Website", 36), ("Status site", 11), ("HTTPS", 8),
    ("Adresa", 45), ("Link Google Maps", 18), ("Cautare", 28), ("Data extragerii", 19),
]

FILLS = {
    HOT: PatternFill("solid", start_color="F8CBAD"),
    WARM: PatternFill("solid", start_color="FFF2CC"),
    COLD: PatternFill("solid", start_color="FFFFFF"),
}
TAG_FONTS = {
    HOT: Font(bold=True, color="C00000"),
    WARM: Font(bold=True, color="9C6500"),
    COLD: Font(color="595959"),
}
_TAG_ORDER = {HOT: 0, WARM: 1, COLD: 2}


def slugify(text: str) -> str:
    text = text.lower()
    for a, b in {"ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t"}.items():
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:60] or "leads"


def _row(lead: Lead) -> list:
    status = "" if lead.site_status is None else ("nu raspunde" if lead.site_status == 0 else lead.site_status)
    https = "" if lead.https is None else ("DA" if lead.https else "NU")
    return [
        lead.tag, lead.tag_reason, lead.name, lead.category, lead.rating, lead.reviews,
        lead.phone, ", ".join(lead.emails), lead.website, status, https,
        lead.address, lead.maps_url, lead.query, lead.scraped_at,
    ]


def export_excel(leads: Iterable[Lead], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    leads = sorted(leads, key=lambda l: (_TAG_ORDER.get(l.tag, 3), -(l.reviews or 0)))

    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"

    header_fill = PatternFill("solid", start_color="1F3864")
    header_font = Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for idx, (title, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=idx, value=title)
        cell.fill, cell.font, cell.border = header_fill, header_font, border
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.row_dimensions[1].height = 22

    col = {title: i for i, (title, _) in enumerate(COLUMNS, start=1)}
    for r, lead in enumerate(leads, start=2):
        fill = FILLS.get(lead.tag, FILLS[COLD])
        for c, value in enumerate(_row(lead), start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.fill, cell.border = fill, border
            cell.alignment = Alignment(vertical="center")
        ws.cell(row=r, column=col["Tag"]).font = TAG_FONTS.get(lead.tag, Font())
        ws.cell(row=r, column=col["Rating"]).number_format = "0.0"

        maps = ws.cell(row=r, column=col["Link Google Maps"])
        maps.hyperlink, maps.value, maps.font = lead.maps_url, "Deschide harta", Font(color="0563C1", underline="single")
        if lead.has_website:
            web = ws.cell(row=r, column=col["Website"])
            web.hyperlink, web.font = lead.website, Font(color="0563C1", underline="single")

    last_col = get_column_letter(len(COLUMNS))
    ws.auto_filter.ref = f"A1:{last_col}{max(len(leads) + 1, 1)}"
    ws.freeze_panes = "A2"

    # Summary sheet
    summary = wb.create_sheet("Sumar")
    counts = {t: sum(1 for l in leads if l.tag == t) for t in (HOT, WARM, COLD)}
    rows = [
        ("Generat la", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Total leads", len(leads)),
        (HOT, counts[HOT]),
        (WARM, counts[WARM]),
        (COLD, counts[COLD]),
        ("Cu email", sum(1 for l in leads if l.emails)),
        ("Fara website", sum(1 for l in leads if not l.has_website)),
    ]
    for r, (k, v) in enumerate(rows, start=1):
        summary.cell(row=r, column=1, value=k).font = Font(bold=True)
        summary.cell(row=r, column=2, value=v)
        if k in FILLS:
            summary.cell(row=r, column=1).fill = FILLS[k]
    summary.column_dimensions["A"].width = 18
    summary.column_dimensions["B"].width = 20

    wb.save(path)
    return path
