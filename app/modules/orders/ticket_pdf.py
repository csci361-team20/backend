"""Print-optimised PDF tickets (SRS 4.7, UC7).

One A4 page per ticket, black on white so it scans when printed in
grayscale. Text uses a Unicode font so Kazakh and Russian names print
correctly. No payment details appear on the ticket.
"""

import io
import logging
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.core.config import settings
from app.core.timezones import format_local

logger = logging.getLogger(__name__)

QR_SIZE = 70 * mm  # large enough to scan from paper at arm's length

_FONT_CANDIDATES = (
    # (regular, bold) pairs, first match wins
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
)


@dataclass(frozen=True)
class TicketPrint:
    """Everything printed on a ticket; built from the canonical ticket record."""

    ticket_id: str
    event_title: str
    start_at: datetime
    end_at: datetime
    timezone: str
    venue_name: str | None
    venue_address: str | None
    city: str | None
    ticket_type_name: str
    attendee_name: str
    status: str
    qr_payload: str | None
    seat: str | None = None


@cache
def unicode_font_paths() -> tuple[str, str] | None:
    """(regular, bold) TTF files that cover Kazakh and Russian, if any."""
    pairs = list(_FONT_CANDIDATES)
    if settings.TICKET_FONT_PATH:
        bold = settings.TICKET_FONT_BOLD_PATH or settings.TICKET_FONT_PATH
        pairs.insert(0, (settings.TICKET_FONT_PATH, bold))
    for regular, bold in pairs:
        if Path(regular).is_file() and Path(bold).is_file():
            return regular, bold
    return None


@cache
def _fonts() -> tuple[str, str]:
    """Register a Unicode TTF font; fall back to Helvetica (Latin only)."""
    paths = unicode_font_paths()
    if paths is None:
        logger.warning("No Unicode font found for tickets; Cyrillic will not print")
        return "Helvetica", "Helvetica-Bold"
    pdfmetrics.registerFont(TTFont("TicketSans", paths[0]))
    pdfmetrics.registerFont(TTFont("TicketSans-Bold", paths[1]))
    return "TicketSans", "TicketSans-Bold"


def _wrap(
    c: canvas.Canvas, text: str, font: str, size: float, width: float
) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if c.stringWidth(candidate, font, size) <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


def _draw_qr(c: canvas.Canvas, payload: str, x: float, y: float) -> None:
    widget = QrCodeWidget(payload, barLevel="M")
    left, bottom, right, top = widget.getBounds()
    drawing = Drawing(
        QR_SIZE,
        QR_SIZE,
        transform=[QR_SIZE / (right - left), 0, 0, QR_SIZE / (top - bottom), 0, 0],
    )
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


def _draw_ticket(c: canvas.Canvas, ticket: TicketPrint) -> None:
    regular, bold = _fonts()
    page_w, page_h = A4
    margin = 18 * mm
    text_w = page_w - 2 * margin

    # Header band
    c.setLineWidth(1.2)
    c.rect(margin, page_h - margin - 16 * mm, text_w, 16 * mm)
    c.setFont(bold, 14)
    c.drawString(
        margin + 5 * mm, page_h - margin - 10 * mm, "BiletFlow · Admission ticket"
    )

    y = page_h - margin - 30 * mm
    c.setFont(bold, 22)
    for line in _wrap(c, ticket.event_title, bold, 22, text_w):
        c.drawString(margin, y, line)
        y -= 9 * mm

    starts = format_local(ticket.start_at, ticket.timezone)
    ends = format_local(ticket.end_at, ticket.timezone, "%H:%M")
    venue = ", ".join(
        part for part in (ticket.venue_name, ticket.venue_address, ticket.city) if part
    )
    rows = [
        ("Date and time", f"{starts} – {ends} ({ticket.timezone})"),
        ("Venue", venue or "To be announced"),
        ("Ticket", ticket.ticket_type_name),
        ("Attendee", ticket.attendee_name),
    ]
    if ticket.seat:
        rows.append(("Seat", ticket.seat))
    rows.append(("Ticket ID", ticket.ticket_id))

    y -= 4 * mm
    for label, value in rows:
        c.setFont(regular, 9)
        c.drawString(margin, y, label.upper())
        y -= 5.5 * mm
        c.setFont(bold, 13)
        for line in _wrap(c, value, bold, 13, text_w):
            c.drawString(margin, y, line)
            y -= 6 * mm
        y -= 3 * mm

    qr_y = max(y - QR_SIZE - 6 * mm, 40 * mm)
    qr_x = (page_w - QR_SIZE) / 2
    if ticket.qr_payload and ticket.status in ("valid", "checked_in"):
        _draw_qr(c, ticket.qr_payload, qr_x, qr_y)
        c.setFont(regular, 10)
        c.drawCentredString(
            page_w / 2, qr_y - 6 * mm, "Show this code at the entrance."
        )
    else:
        # A void ticket gets no code at all, so it cannot be scanned in
        c.setLineWidth(3)
        c.rect(qr_x, qr_y, QR_SIZE, QR_SIZE)
        c.setFont(bold, 24)
        c.drawCentredString(page_w / 2, qr_y + QR_SIZE / 2, ticket.status.upper())

    c.setFont(regular, 8.5)
    footer = (
        "The printed and digital copies of this ticket are the same ticket and "
        "admit one person once. Do not share the code."
    )
    fy = 20 * mm
    for line in _wrap(c, footer, regular, 8.5, text_w):
        c.drawString(margin, fy, line)
        fy -= 4 * mm


def render_tickets_pdf(tickets: list[TicketPrint]) -> bytes:
    """One page per ticket."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4, pageCompression=1)
    c.setTitle("BiletFlow ticket" if len(tickets) == 1 else "BiletFlow tickets")
    c.setAuthor("BiletFlow")
    for ticket in tickets:
        _draw_ticket(c, ticket)
        c.showPage()
    c.save()
    return buffer.getvalue()
