"""Branded PDF generation: payment/donation receipts and the member ID card.

Pure-reportlab so it installs without system libraries (no Cairo/Pango). Text is
English-primary, matching the rest of the app where only the UI chrome is
translated — the brand identity block carries the bilingual association name.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .context_processors import BRAND

# Brand palette mirrored from static/css/mwar.css.
BRAND_900 = HexColor("#0A2A66")
BRAND_700 = HexColor("#14439E")
BRAND_050 = HexColor("#EEF3FC")
SUCCESS = HexColor("#1E8E5A")
INK_900 = HexColor("#15202B")
INK_600 = HexColor("#5A6B7B")
BORDER = HexColor("#D7DEE8")


def _clean(text) -> str:
    """Drop glyphs the built-in Helvetica can't render (e.g. Urdu in choice
    labels), then tidy any parentheses/whitespace left empty by the removal."""
    s = "".join(ch for ch in str(text or "") if ord(ch) < 0x250)
    s = re.sub(r"\(\s*\)", "", s)            # empty "()" left behind
    return re.sub(r"\s{2,}", " ", s).strip(" -")


def _fmt_amount(amount, currency: str = "PKR") -> str:
    value = Decimal(amount or 0)
    return f"{currency} {value:,.0f}" if value == value.to_integral() else f"{currency} {value:,.2f}"


def _fmt_date(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %I:%M %p")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    return str(value or "")


def _brand_header(c: canvas.Canvas, width: float, top: float) -> float:
    """Draw the association identity band; return the y just below it."""
    band_h = 26 * mm
    c.setFillColor(BRAND_900)
    c.rect(0, top - band_h, width, band_h, stroke=0, fill=1)

    x = 18 * mm
    y = top - 10 * mm
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x, y, BRAND["short"])
    c.setFont("Helvetica", 9.5)
    c.drawString(x + 42 * mm, y + 1, BRAND["name"])
    c.setFillColor(BRAND_050)
    c.setFont("Helvetica", 8)
    c.drawString(
        x,
        y - 6 * mm,
        f'Reg. No. {BRAND["reg_no"]} • {BRAND["locality"]} • “{BRAND["tagline"]}”',
    )
    return top - band_h


def _detail_rows(c: canvas.Canvas, x: float, y: float, rows: list[tuple[str, str]],
                 width: float, line_h: float = 9 * mm) -> float:
    for label, value in rows:
        c.setFillColor(INK_600)
        c.setFont("Helvetica", 9.5)
        c.drawString(x, y, _clean(label).upper())
        c.setFillColor(INK_900)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x + 48 * mm, y, _clean(value))
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.4)
        c.line(x, y - 2.5 * mm, x + width, y - 2.5 * mm)
        y -= line_h
    return y


def receipt_pdf(*, title: str, receipt_number: str, amount, currency: str,
                payer_label: str, payer_value: str, rows: list[tuple[str, str]],
                issued_on, received_by: str = "", verify_note: str = "") -> bytes:
    """Render a single-page A4 receipt and return the PDF bytes."""
    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"{title} {receipt_number}")

    body_top = _brand_header(c, width, height)

    # Title + receipt number / date.
    x = 18 * mm
    y = body_top - 16 * mm
    c.setFillColor(BRAND_900)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(x, y, _clean(title))
    c.setFillColor(INK_600)
    c.setFont("Helvetica", 10)
    c.drawRightString(width - 18 * mm, y + 6, f"Receipt #  {receipt_number}")
    c.drawRightString(width - 18 * mm, y - 7, f"Date  {_fmt_date(issued_on)}")

    # Amount highlight box.
    y -= 16 * mm
    box_h = 20 * mm
    c.setFillColor(BRAND_050)
    c.roundRect(x, y - box_h, width - 36 * mm, box_h, 4, stroke=0, fill=1)
    c.setFillColor(INK_600)
    c.setFont("Helvetica", 9.5)
    c.drawString(x + 6 * mm, y - 7 * mm, "AMOUNT RECEIVED")
    c.setFillColor(SUCCESS)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(x + 6 * mm, y - 16 * mm, _fmt_amount(amount, currency))

    # Detail rows.
    y -= box_h + 14 * mm
    all_rows = [(payer_label, payer_value)] + rows
    y = _detail_rows(c, x, y, all_rows, width - 36 * mm)

    # Footer: received-by / signature, verification + computer-generated note.
    y -= 10 * mm
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.6)
    c.line(x, y, x + 55 * mm, y)
    c.line(width - 18 * mm - 55 * mm, y, width - 18 * mm, y)
    c.setFillColor(INK_600)
    c.setFont("Helvetica", 8.5)
    c.drawString(x, y - 5 * mm, f"Received by: {received_by or '—'}")
    c.drawRightString(width - 18 * mm, y - 5 * mm, "Authorised signature")

    c.setFillColor(INK_600)
    c.setFont("Helvetica-Oblique", 8)
    note = "This is a computer-generated receipt and is valid without a physical signature."
    c.drawCentredString(width / 2, 22 * mm, note)
    if verify_note:
        c.drawCentredString(width / 2, 17 * mm, verify_note)

    c.showPage()
    c.save()
    return buf.getvalue()


def _qr_image(data: str):
    """Return a reportlab-embeddable QR image for the given payload."""
    import qrcode
    from reportlab.lib.utils import ImageReader

    img = qrcode.make(data, box_size=10, border=1)
    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return ImageReader(bio)


def id_card_pdf(*, member_name: str, member_number: str, membership_class: str,
                residency: str, issued_on, expires_on, verify_url: str,
                status: str = "Active") -> bytes:
    """Render a CR80 (credit-card sized) member ID card as a one-page PDF."""
    buf = io.BytesIO()
    cw, ch = 86 * mm, 54 * mm           # CR80 landscape
    c = canvas.Canvas(buf, pagesize=(cw, ch))
    c.setTitle(f"M.W.A.R Member Card {member_number}")

    # Card background + brand header strip.
    c.setFillColor(HexColor("#FFFFFF"))
    c.rect(0, 0, cw, ch, stroke=0, fill=1)
    strip = 14 * mm
    c.setFillColor(BRAND_900)
    c.rect(0, ch - strip, cw, strip, stroke=0, fill=1)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(5 * mm, ch - 6 * mm, BRAND["short"])
    c.setFillColor(BRAND_050)
    c.setFont("Helvetica", 5.5)
    c.drawString(5 * mm, ch - 10.5 * mm, BRAND["name"])
    c.drawString(5 * mm, ch - 13 * mm, f'Reg. No. {BRAND["reg_no"]} • {BRAND["locality"]}')

    # Member details (left), QR (right).
    x = 5 * mm
    y = ch - strip - 6 * mm
    c.setFillColor(INK_600)
    c.setFont("Helvetica", 5.5)
    c.drawString(x, y, "MEMBER")
    c.setFillColor(INK_900)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y - 5 * mm, _clean(member_name))

    issued = issued_on.date() if isinstance(issued_on, datetime) else issued_on
    rows = [
        ("MEMBER NO.", member_number),
        ("CLASS", membership_class),
        ("RESIDENCY", residency),
        ("VALID", f"{_fmt_date(issued)} - {_fmt_date(expires_on) if expires_on else 'Ongoing'}"),
    ]
    ry = y - 10 * mm
    for label, value in rows:
        c.setFillColor(INK_600)
        c.setFont("Helvetica", 5)
        c.drawString(x, ry, label)
        c.setFillColor(INK_900)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(x, ry - 3 * mm, _clean(value))
        ry -= 6 * mm

    # QR bottom-right with status pill above it.
    qr_size = 20 * mm
    qx = cw - qr_size - 5 * mm
    qy = 5 * mm
    c.drawImage(_qr_image(verify_url), qx, qy, qr_size, qr_size,
                preserveAspectRatio=True, mask="auto")
    c.setFillColor(SUCCESS if status.lower() == "active" else HexColor("#C0392B"))
    c.setFont("Helvetica-Bold", 6)
    c.drawCentredString(qx + qr_size / 2, qy + qr_size + 2 * mm, status.upper())
    c.setFillColor(INK_600)
    c.setFont("Helvetica", 4.5)
    c.drawCentredString(qx + qr_size / 2, qy - 2 * mm, "Scan to verify")

    c.showPage()
    c.save()
    return buf.getvalue()
