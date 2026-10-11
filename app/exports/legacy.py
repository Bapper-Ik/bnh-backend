"""Fixed A4 template; only escaped text and stored vector signatures are rendered."""

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import reportlab  # type: ignore[import-untyped]
from reportlab.graphics.shapes import Drawing, PolyLine  # type: ignore[import-untyped]
from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_RIGHT  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    LongTable,
    PageTemplate,
    Paragraph,
    TableStyle,
)

from app.authority.policy import calculate_lines
from app.exports.render import MARGIN, STATES, WIDTH, RenderFailure, load_fonts, time_label
from app.exports.schemas import SigningRecord, Snapshot


def render_legacy(
    snapshot: Snapshot,
    export_id: str,
    snapshot_digest: str,
    generated_at: datetime,
    directory: Path,
) -> tuple[bytes, str, str]:
    if snapshot.transfer is not None:
        from app.transfers.render import render_transfer

        return render_transfer(snapshot, export_id, snapshot_digest, generated_at, directory)
    fonts, font_version = load_fonts(directory)
    body = ParagraphStyle(
        "Body",
        fontName=fonts["body"],
        fontSize=11,
        leading=14.5,
        textColor=colors.HexColor("#595959"),
        alignment=TA_JUSTIFY,
        spaceAfter=7,
        splitLongWords=True,
    )
    left = ParagraphStyle("Label", parent=body, alignment=TA_LEFT)
    numeric = ParagraphStyle("Number", parent=body, alignment=TA_RIGHT)
    h1 = ParagraphStyle(
        "Title",
        fontName=fonts["heading"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#000000"),
        spaceAfter=12,
        keepWithNext=True,
    )
    h2 = ParagraphStyle(
        "Section",
        parent=h1,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1A1A1A"),
        spaceBefore=14,
        spaceAfter=8,
    )
    styles = {
        "body": body,
        "left": left,
        "number": numeric,
        "h1": h1,
        "h2": h2,
        "cost_heading": ParagraphStyle("Cost heading", parent=h2, keepWithNext=False),
    }

    def paragraph(value: object, style: str = "body") -> Any:
        text = str(value) if value is not None else "Not supplied"
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
        face = pdfmetrics.getFont(styles[style].fontName).face
        if any(ord(c) not in face.charToGlyph and not c.isspace() for c in text):
            raise RenderFailure("unsupported_font_characters")
        return Paragraph(escape(text).replace("\n", "<br/>"), styles[style])

    story = []

    def p(value: object, style: str = "body") -> None:
        story.append(paragraph(value, style))

    def field(label: str, value: object) -> None:
        p(f"{label}: {value or 'Not supplied'}", "left")

    def signature(record: SigningRecord) -> None:
        group = [
            paragraph(record.label, "h2"),
            paragraph(record.name, "left"),
            paragraph(time_label(record.at), "left"),
        ]
        if record.strokes:
            drawing = Drawing(225, 65)
            for stroke in record.strokes:
                points = [
                    coordinate
                    for point in stroke
                    for coordinate in (5 + point.x * 215, 5 + (1 - point.y) * 55)
                ]
                if len(points) >= 4:
                    drawing.add(
                        PolyLine(points, strokeColor=colors.HexColor("#1A1A1A"), strokeWidth=1.2)
                    )
            group.append(drawing)
        story.append(KeepTogether(group))
        if record.statement:
            field("Signed declaration / intent", record.statement)
        if record.reason:
            field("Reason", record.reason)

    p("Brendan Nicholas Holdings", "h2")
    p("Requisition and approval record", "h1")
    p(STATES.get(snapshot.state, snapshot.state), "h2")
    p(
        "Approved means authorised, not paid. This document records the captured state; later actions may exist."
    )
    value: object
    for label, value in (
        ("Reference", snapshot.reference),
        ("Revision", snapshot.revision or f"Draft (saved version {snapshot.request_version})"),
        ("Company", snapshot.company),
        ("Requester", snapshot.requester),
        ("Department", snapshot.department),
        ("Record captured", time_label(snapshot.as_of)),
        ("PDF generated", time_label(generated_at)),
    ):
        field(label, value)
    if snapshot.current_state != snapshot.state:
        field(
            "Current request status when captured",
            STATES.get(snapshot.current_state, snapshot.current_state),
        )
    if snapshot.authority:
        field("Assigned authority", snapshot.authority.replace("_", " ").upper())
        field("Route", snapshot.route)
        field("Policy version", snapshot.policy)
    p("Vendor and beneficiary", "h2")
    vendor = snapshot.content.vendor
    for label, value in [
        ("Vendor", vendor.name),
        ("Contact person", vendor.contact_person),
        ("Phone", vendor.phone),
        ("Email", vendor.email),
        ("Business address", vendor.address),
        ("Registration / RC number", vendor.registration_id),
    ]:
        field(label, value)
    if "vendor.bank_details" in snapshot.redacted_fields:
        p("Bank details: Restricted in this export.")
    else:
        for label, value in [
            ("Bank", vendor.bank_name),
            ("Account name", vendor.account_name),
            ("Account number", vendor.account_number),
        ]:
            field(label, value or "Not yet supplied")
    p("Scope of work", "h2")
    p(snapshot.content.description or "Not supplied")
    for label, value in [
        ("Location", snapshot.content.location),
        ("Planned start", snapshot.content.start_date),
        ("Planned completion", snapshot.content.completion_date),
        ("Payment terms", snapshot.content.payment_terms),
        ("Warranty / guarantee", snapshot.content.warranty),
    ]:
        field(label, value)
    totals, total = calculate_lines(
        [(line.quantity, line.unit_price) for line in snapshot.content.lines]
    )
    if total != snapshot.total:
        raise RenderFailure("snapshot_total_mismatch")
    rows = [
        [
            paragraph(x, "left")
            for x in ["Item / description", "Quantity", "Unit price", "Line total"]
        ]
    ]
    for index, line in enumerate(snapshot.content.lines):
        rows.append(
            [
                paragraph(line.description, "left"),
                paragraph(line.quantity, "number"),
                paragraph(f"{Decimal(line.unit_price):,.2f}", "number"),
                paragraph(f"{Decimal(totals[index]):,.2f}", "number"),
            ]
        )

    class CostTable(LongTable):  # type: ignore[misc]
        def split(self, availWidth: float, availHeight: float) -> Any:
            parts = super().split(availWidth, availHeight)
            if parts or len(self._rowHeights) < 2:
                return parts
            # Keep ordinary rows intact. Split inside a row only when it cannot
            # fit on a full page (e.g. hundreds of explicit description newlines).
            if self._rowHeights[1] <= A4[1] - 2 * MARGIN - self._rowHeights[0]:
                return parts
            self.splitInRow = 1
            try:
                return super().split(availWidth, availHeight)
            finally:
                self.splitInRow = 0

    if snapshot.content.lines:
        table = CostTable(
            rows,
            colWidths=[WIDTH * 0.44, WIDTH * 0.12, WIDTH * 0.22, WIDTH * 0.22],
            repeatRows=1,
            splitByRow=1,
            splitInRow=0,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#595959")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#D9D9D9")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        table.wrap(WIDTH, A4[1] - 2 * MARGIN)
        first_rows = sum(table._rowHeights[:2])
        story.append(CondPageBreak(min(first_rows + 45, A4[1] - 2 * MARGIN)))
        p("Cost breakdown (NGN)", "cost_heading")
        story.append(table)
    else:
        p("Cost breakdown (NGN)", "h2")
        p("No cost items saved.")
    p(f"Grand total: NGN {Decimal(total):,.2f}", "h2")
    p("Supporting-document references", "h2")
    p(
        "References identify the recorded evidence. Files remain private in the application; malware scanning was not performed."
    )
    if not snapshot.evidence:
        p("No supporting documents recorded.")
    for item in snapshot.evidence:
        field("Document", item.filename)
    if not snapshot.signatures:
        p("Declaration and approval record", "h2")
        p("Draft only. No requester declaration or approval has been signed for this saved draft.")
    for signed_item in snapshot.signatures:
        signature(signed_item)
    if snapshot.authority == "board":
        p("Board resolution record", "h2")
        if not snapshot.include_board:
            p(
                "Private Board records, evidence references and signature images are omitted from this export. Confirmed outcomes above retain their recorded meaning."
            )
        elif not snapshot.board:
            p(
                "No submitted Board resolution recorded. Recording alone does not approve a requisition."
            )
        for record in snapshot.board:
            p(f"Resolution {record.number}: {record.reference}", "h2")
            for label, value in [
                ("Board", record.board_name),
                ("Record kind", record.kind),
                ("Actual meeting date", record.meeting_date),
                ("Record created", time_label(record.recorded_at)),
                ("Recorded meeting outcome", record.outcome.replace("_", " ")),
                ("Authorised amount (NGN)", record.amount),
                ("Decision", record.decision),
                ("Conditions", record.conditions),
                ("Attendance", record.attendance),
                ("Quorum basis (attested by Secretary)", record.quorum_basis),
                ("Correction summary", record.correction),
            ]:
                field(label, value)
            if record.evidence:
                field("Formal evidence", record.evidence.filename)
            for board_signature in record.signatures:
                signature(board_signature)
            if len(record.signatures) == 1:
                p("Awaiting Chairman review. Secretary recording is not final authorisation.")
    output = io.BytesIO()

    class NumberedCanvas(Canvas):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.states: list[dict[str, Any]] = []

        def showPage(self) -> None:
            if len(self.states) >= 200:
                raise RenderFailure("export_too_large")
            self.states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            pages = len(self.states)
            for state in self.states:
                self.__dict__.update(state)
                self.setFont(fonts["footer"], 8)
                self.setFillColor(colors.HexColor("#8C8C8C"))
                self.drawString(
                    MARGIN,
                    25,
                    snapshot.reference
                    + " | "
                    + ("Revision " + str(snapshot.revision) if snapshot.revision else "Draft"),
                )
                self.drawRightString(A4[0] - MARGIN, 25, f"Page {self._pageNumber} of {pages}")
                super().showPage()
            super().save()

    doc = BaseDocTemplate(
        output,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=snapshot.reference + " requisition record",
        author="Custodian by Brendan",
        allowSplitting=True,
    )
    doc.addPageTemplates(
        PageTemplate(
            id="record",
            frames=[
                Frame(
                    MARGIN,
                    MARGIN,
                    WIDTH,
                    A4[1] - 2 * MARGIN,
                    leftPadding=0,
                    rightPadding=0,
                    topPadding=0,
                    bottomPadding=0,
                )
            ],
        )
    )
    doc.build(story, canvasmaker=NumberedCanvas)
    data = output.getvalue()
    if len(data) > 10 * 1024 * 1024:
        raise RenderFailure("export_too_large")
    return data, "reportlab-" + str(reportlab.Version), font_version
