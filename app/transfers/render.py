"""Fixed bank letter layout; uses only the captured approval and bank snapshot."""

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import reportlab  # type: ignore[import-untyped]
from reportlab.graphics.shapes import Circle, Drawing, PolyLine  # type: ignore[import-untyped]
from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.enums import (  # type: ignore[import-untyped]
    TA_CENTER,
    TA_JUSTIFY,
    TA_LEFT,
    TA_RIGHT,
)
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from app.exports import render as rendering
from app.exports.render import MARGIN, RenderFailure
from app.exports.schemas import Snapshot
from app.transfers.words import naira_words

ROLES = {
    "hod": "Head of Department",
    "chief_of_staff": "Chief of Staff",
    "md": "Managing Director",
    "Board Chairman": "Board Chairman",
}


def render_transfer(
    snapshot: Snapshot,
    export_id: str,
    snapshot_digest: str,
    generated_at: datetime,
    directory: Path,
) -> tuple[bytes, str, str]:
    transfer = snapshot.transfer
    if (
        snapshot.state != "APPROVED"
        or transfer is None
        or transfer.debit is None
        or transfer.missing
        or transfer.amount != snapshot.total
        or len(snapshot.signatures) != 1
        or not snapshot.signatures[0].strokes
    ):
        raise RenderFailure("transfer_details_missing")
    fonts, version = rendering.load_fonts(directory)
    body = ParagraphStyle(
        "TransferBody",
        fontName=fonts["body"],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#595959"),
        alignment=TA_JUSTIFY,
        spaceAfter=9,
    )
    left = ParagraphStyle("TransferLeft", parent=body, alignment=TA_LEFT)
    right = ParagraphStyle("TransferRight", parent=body, alignment=TA_RIGHT)
    title = ParagraphStyle(
        "TransferTitle",
        parent=left,
        fontName=fonts["heading"],
        fontSize=16,
        leading=20,
        textColor=colors.black,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    heading = ParagraphStyle(
        "TransferHeading",
        parent=left,
        fontName=fonts["heading"],
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1A1A1A"),
    )

    def p(text: str, style: ParagraphStyle = left) -> Paragraph:
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
        face = pdfmetrics.getFont(style.fontName).face
        if any(ord(c) not in face.charToGlyph and not c.isspace() for c in text):
            raise RenderFailure("unsupported_font_characters")
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    signer = snapshot.signatures[0]
    date = datetime.fromisoformat(signer.at).astimezone(ZoneInfo("Africa/Lagos"))
    account = transfer.debit
    story = [p(snapshot.company, title)]
    if account.company_address:
        story.append(
            p(
                account.company_address,
                ParagraphStyle("CompanyAddress", parent=body, alignment=TA_CENTER),
            )
        )
    story.extend(
        [
            Spacer(1, 18),
            p(date.strftime("%d %B %Y"), right),
            Spacer(1, 12),
            p("The Manager,"),
            p(account.bank_name),
            p(account.branch_address),
            Spacer(1, 12),
            p(
                "PAYMENT INSTRUCTION",
                ParagraphStyle("Subject", parent=heading, alignment=TA_CENTER),
            ),
            p(f"Requisition: {snapshot.reference}"),
            Spacer(1, 10),
            p(
                "Kindly take this as our instruction to transfer the total sum of "
                + naira_words(transfer.amount)
                + f" (NGN {Decimal(transfer.amount):,.2f}) "
                + f"from {account.account_name}, account number {account.account_number}, "
                + f"held with {account.bank_name}, to the beneficiary account below.",
                body,
            ),
            Spacer(1, 10),
            p("Account name: " + transfer.beneficiary_name, heading),
            p("Account number: " + transfer.beneficiary_account, heading),
            p("Bank: " + transfer.beneficiary_bank, heading),
            Spacer(1, 20),
        ]
    )
    drawing = Drawing(210, 65)
    for stroke in signer.strokes:
        points = [
            coordinate
            for point in stroke
            for coordinate in (5 + point.x * 200, 5 + (1 - point.y) * 55)
        ]
        if points and len(set(zip(points[::2], points[1::2], strict=True))) == 1:
            # Preserve isolated pen marks as well as continuous signature strokes.
            drawing.add(
                Circle(
                    points[0],
                    points[1],
                    0.6,
                    fillColor=colors.HexColor("#1A1A1A"),
                    strokeColor=None,
                )
            )
        elif len(points) >= 4:
            drawing.add(PolyLine(points, strokeColor=colors.HexColor("#1A1A1A"), strokeWidth=1.2))
    story.append(
        KeepTogether(
            [
                p("Thank you."),
                Spacer(1, 8),
                drawing,
                p(signer.name, heading),
                p(ROLES.get(signer.label, signer.label)),
            ]
        )
    )
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"{snapshot.reference} - bank transfer request",
        author=snapshot.company,
    )

    doc.build(story)
    return buffer.getvalue(), "reportlab-" + reportlab.Version, version
