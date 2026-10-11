"""Fixed A4 template; only escaped text and stored vector signatures are rendered."""

import hashlib
import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import reportlab  # type: ignore[import-untyped]
from reportlab.graphics.shapes import Drawing, Line, PolyLine  # type: ignore[import-untyped]
from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.enums import TA_LEFT, TA_RIGHT  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]
from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    LongTable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    TableStyle,
)

from app.authority.policy import calculate_lines
from app.exports.schemas import SigningRecord, Snapshot

MARGIN = 43.2
WIDTH = A4[0] - 2 * MARGIN
FONT_LOCK = Lock()
STATES = {
    "DRAFT": "Draft - not submitted",
    "PENDING_AUTHORITY": "Awaiting approval",
    "AWAITING_BOARD_RESOLUTION": "Awaiting Board resolution",
    "AWAITING_CHAIRMAN_SIGNOFF": "Awaiting Chairman sign-off",
    "RETURNED_FOR_REVISION": "Returned for revision",
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
    "DEFERRED": "Deferred",
    "CONDITIONALLY_APPROVED": "Conditional approval - on hold",
}


class RenderFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


TEMPLATE_VERSION = "requisition-v2"

FONT_PROFILE = "bnh-liberation-v1"
FONT_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT_FILES = {
    "body": ("LiberationSerif-Regular.ttf", "Liberation Serif", "Regular"),
    "heading": ("LiberationSans-Bold.ttf", "Liberation Sans", "Bold"),
    "footer": ("LiberationSerif-Regular.ttf", "Liberation Serif", "Regular"),
}


def load_fonts(directory: Path) -> tuple[dict[str, str], str]:
    try:
        fonts = {}
        version = hashlib.sha256(FONT_PROFILE.encode())
        with FONT_LOCK:
            for role, (filename, expected_family, required_style) in FONT_FILES.items():
                path = directory / filename
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                version.update(data)
                name = "Custodian-" + role + "-" + digest[:16]
                if name not in pdfmetrics.getRegisteredFontNames():
                    font = TTFont(name, io.BytesIO(data))
                    pdfmetrics.registerFont(font)
                font = pdfmetrics.getFont(name)
                family = font.face.familyName
                family = family.decode("utf-8") if isinstance(family, bytes) else family
                style = font.face.styleName
                style = style.decode("utf-8") if isinstance(style, bytes) else style
                if family != expected_family or (required_style and required_style != style):
                    raise ValueError("Font family/style mismatch")
                fonts[role] = name
        return fonts, FONT_PROFILE + ":" + version.hexdigest()
    except Exception as exc:
        raise RenderFailure("fonts_unavailable") from exc


def font_directory() -> Path:
    return FONT_DIRECTORY


def available() -> bool:
    try:
        load_fonts(font_directory())
        return True
    except RenderFailure:
        return False


def time_label(value: datetime | str) -> str:
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    return stamp.astimezone(ZoneInfo("Africa/Lagos")).strftime("%d %b %Y, %H:%M:%S WAT")


def render(
    snapshot: Snapshot,
    export_id: str,
    snapshot_digest: str,
    generated_at: datetime,
    directory: Path,
    *,
    template_version: str = TEMPLATE_VERSION,
) -> tuple[bytes, str, str]:
    if snapshot.transfer is not None:
        from app.transfers.render import render_transfer

        return render_transfer(snapshot, export_id, snapshot_digest, generated_at, directory)
    if template_version == "requisition-v1":
        from app.exports.legacy import render_legacy

        return render_legacy(snapshot, export_id, snapshot_digest, generated_at, directory)
    if template_version != TEMPLATE_VERSION:
        raise RenderFailure("unsupported_template")
    from app.transfers.words import naira_words

    fonts, font_version = load_fonts(directory)
    body = ParagraphStyle(
        "Body",
        fontName=fonts["body"],
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#595959"),
        alignment=TA_LEFT,
        spaceAfter=0,
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
        spaceAfter=6,
        keepWithNext=True,
    )
    h2 = ParagraphStyle(
        "Section",
        parent=h1,
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#1A1A1A"),
        spaceBefore=11,
        spaceAfter=5,
    )
    muted = ParagraphStyle("Muted", parent=left, textColor=colors.HexColor("#8C8C8C"))
    small = ParagraphStyle("Small", parent=left, fontSize=9, leading=11)
    strong = ParagraphStyle(
        "Strong", parent=left, fontName=fonts["heading"], fontSize=10, leading=13
    )
    styles = {
        "muted": muted,
        "small": small,
        "strong": strong,
        "white": ParagraphStyle("White", parent=strong, textColor=colors.white),
        "total": ParagraphStyle("Total", parent=h1, alignment=TA_RIGHT, fontSize=15, leading=18),
        "total_cell": ParagraphStyle("TotalCell", parent=strong, alignment=TA_RIGHT),
        "right_label": ParagraphStyle(
            "RightLabel", parent=strong, alignment=TA_RIGHT, textColor=colors.HexColor("#8C8C8C")
        ),
        "words": ParagraphStyle("Words", parent=small, alignment=TA_RIGHT),
        "body": body,
        "left": left,
        "number": numeric,
        "h1": h1,
        "h2": h2,
        "field_heading": ParagraphStyle("Field heading", parent=h2, keepWithNext=False),
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

    title = {
        "APPROVED": "Approved Requisition",
        "DRAFT": "Draft Requisition",
        "REJECTED": "Rejected Requisition",
        "RETURNED_FOR_REVISION": "Returned Requisition",
        "DEFERRED": "Deferred Requisition",
        "CONDITIONALLY_APPROVED": "Conditional Requisition",
    }.get(snapshot.state, "Requisition for Approval")
    authority = {
        "hod": "Head of Department",
        "chief_of_staff": "Chief of Staff",
        "md": "Managing Director",
        "board": "Board of Directors",
    }.get(snapshot.authority, "Not assigned")
    requester_sign = snapshot.signatures[0] if snapshot.signatures else None
    decision_sign = snapshot.signatures[-1] if len(snapshot.signatures) > 1 else None
    if snapshot.include_board:
        # Only actual Chairman confirmations are decisions. Secretary recording
        # and a return to the Secretary must never look like financial approval.
        decision_sign = next(
            (
                signed
                for record in reversed(snapshot.board)
                for signed in reversed(record.signatures)
                if signed.label.startswith("Chairman: confirmed ")
            ),
            None,
        )

    def joined(*values: object) -> str:
        return " · ".join(str(v) for v in values if v) or "Not supplied"

    def compact_time(value: str) -> str:
        return (
            datetime.fromisoformat(value)
            .astimezone(ZoneInfo("Africa/Lagos"))
            .strftime("%d %b %Y, %H:%M WAT")
        )

    def grid(rows: list[list[Any]], widths: list[float], *, padding: float = 2) -> Any:
        table = LongTable(rows, colWidths=widths, splitByRow=1, splitInRow=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), padding),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                ]
            )
        )
        return table

    def fields(items: list[tuple[str, object]]) -> None:
        table = grid(
            [
                [paragraph(label, "muted"), paragraph(value or "Not supplied", "left")]
                for label, value in items
            ],
            [WIDTH * 0.24, WIDTH * 0.76],
        )
        # Let lengthy prose continue into the current page instead of moving
        # an entire label/value row to the next page and leaving a large gap.
        table.splitByRow = 0
        story.append(table)

    summary = grid(
        [
            [
                [paragraph(title, "h1"), paragraph(snapshot.reference, "left")],
                [
                    paragraph("TOTAL", "right_label"),
                    paragraph(f"NGN {Decimal(snapshot.total):,.2f}", "total"),
                    paragraph(naira_words(snapshot.total), "words"),
                ],
            ]
        ],
        [WIDTH * 0.49, WIDTH * 0.51],
        padding=0,
    )
    story.append(summary)
    story.append(Spacer(1, 14))
    status_time_label = "APPROVED" if snapshot.state == "APPROVED" else "LAST DECISION"
    banner = grid(
        [
            [
                [
                    paragraph("STATUS", "strong"),
                    paragraph(STATES.get(snapshot.state, snapshot.state)),
                ],
                [
                    paragraph(status_time_label, "strong"),
                    paragraph(
                        compact_time(decision_sign.at) if decision_sign else "Not yet recorded"
                    ),
                ],
                [paragraph("AUTHORITY", "strong"), paragraph(joined(snapshot.policy, authority))],
            ]
        ],
        [WIDTH * 0.30, WIDTH * 0.32, WIDTH * 0.38],
        padding=8,
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F2F2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(banner)
    story.append(CondPageBreak(60))
    p("1. Requester", "field_heading")
    fields(
        [
            ("Name", snapshot.requester),
            ("Department", joined(snapshot.department, snapshot.company)),
            (
                "Submitted",
                compact_time(requester_sign.at)
                if requester_sign
                else "Not submitted - saved draft",
            ),
        ]
    )
    story.append(CondPageBreak(60))
    p("2. Vendor", "field_heading")
    vendor = snapshot.content.vendor
    fields(
        [
            ("Vendor", joined(vendor.name, vendor.registration_id)),
            ("Contact", joined(vendor.contact_person, vendor.phone, vendor.email)),
            ("Address", vendor.address),
            (
                "Bank",
                "Restricted in this export."
                if "vendor.bank_details" in snapshot.redacted_fields
                else joined(vendor.bank_name, vendor.account_number, vendor.account_name),
            ),
        ]
    )
    story.append(CondPageBreak(60))
    p("3. Scope of work", "field_heading")

    def date_label(value: Any) -> str:
        return value.strftime("%d %b %Y") if value else "Not supplied"

    fields(
        [
            ("Work", snapshot.content.description),
            ("Location", snapshot.content.location),
            (
                "Period",
                date_label(snapshot.content.start_date)
                + " to "
                + date_label(snapshot.content.completion_date),
            ),
            ("Payment terms", snapshot.content.payment_terms),
            ("Warranty", snapshot.content.warranty),
        ]
    )
    totals, total = calculate_lines(
        [(line.quantity, line.unit_price) for line in snapshot.content.lines]
    )
    if total != snapshot.total:
        raise RenderFailure("snapshot_total_mismatch")
    rows = [
        [
            paragraph(x, "white")
            for x in ["Item", "Description", "Qty", "Amount (NGN)", "Total (NGN)"]
        ]
    ]
    for index, line in enumerate(snapshot.content.lines):
        rows.append(
            [
                paragraph(index + 1, "left"),
                paragraph(line.description, "left"),
                paragraph(line.quantity, "number"),
                paragraph(f"{Decimal(line.unit_price):,.2f}", "number"),
                paragraph(f"{Decimal(totals[index]):,.2f}", "number"),
            ]
        )

    rows.append(
        [
            paragraph(""),
            paragraph(""),
            paragraph(""),
            paragraph("Total", "total_cell"),
            paragraph(f"{Decimal(total):,.2f}", "number"),
        ]
    )

    content_height = A4[1] - 2 * MARGIN - 32

    class CostTable(LongTable):  # type: ignore[misc]
        def split(self, availWidth: float, availHeight: float) -> Any:
            parts = super().split(availWidth, availHeight)
            if parts or len(self._rowHeights) < 2:
                return parts
            # Keep ordinary rows intact. Split inside a row only when it cannot
            # fit on a full page (e.g. hundreds of explicit description newlines).
            if self._rowHeights[1] <= content_height - self._rowHeights[0]:
                return parts
            self.splitInRow = 1
            try:
                return super().split(availWidth, availHeight)
            finally:
                self.splitInRow = 0

    if snapshot.content.lines:
        table = CostTable(
            rows,
            colWidths=[WIDTH * 0.065, WIDTH * 0.455, WIDTH * 0.07, WIDTH * 0.205, WIDTH * 0.205],
            repeatRows=1,
            splitByRow=1,
            splitInRow=0,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A1A1A")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -2),
                        [colors.HexColor("#F2F2F2"), colors.white],
                    ),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F2F2F2")),
                    ("SPAN", (0, -1), (2, -1)),
                    ("LINEAFTER", (0, 1), (-2, -2), 0.3, colors.HexColor("#D9D9D9")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#595959")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#D9D9D9")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        table.wrap(WIDTH, content_height)
        first_rows = sum(table._rowHeights[:2])
        story.append(CondPageBreak(min(first_rows + 32, content_height)))
        p("4. Cost breakdown", "cost_heading")
        story.append(table)
    else:
        p("4. Cost breakdown", "h2")
        p("No cost items saved.")

    def signing_panel(
        heading: str, record: SigningRecord | None, empty: str, role: str
    ) -> list[Any]:
        result = [paragraph(heading, "h2")]
        if record is None:
            result.append(paragraph(empty))
            return result
        statement = record.statement or record.label
        if len(statement) > 360:
            statement = "The full signed declaration follows under Additional details."
        result.append(paragraph(statement))
        drawing = Drawing(WIDTH * 0.46, 38)
        if record.strokes:
            for stroke in record.strokes:
                points = [
                    coordinate
                    for point in stroke
                    for coordinate in (5 + point.x * 135, 4 + (1 - point.y) * 30)
                ]
                if len(points) >= 4:
                    drawing.add(
                        PolyLine(points, strokeColor=colors.HexColor("#1A1A1A"), strokeWidth=1.1)
                    )
        drawing.add(
            Line(0, 0, WIDTH * 0.46, 0, strokeColor=colors.HexColor("#8C8C8C"), strokeWidth=0.5)
        )
        result.append(drawing)
        result.append(Spacer(1, 5))
        result.append(paragraph(joined(record.name, role), "small"))
        result.append(paragraph(compact_time(record.at), "small"))
        if not record.strokes:
            result.append(paragraph("Signature image not included in this export.", "small"))
        return result

    approval_heading = "6. Approval" if snapshot.state == "APPROVED" else "6. Decision"
    left_panel = signing_panel(
        "5. Declaration", requester_sign, "No requester declaration has been signed.", "Requester"
    )
    right_panel = signing_panel(
        approval_heading,
        decision_sign,
        "No final decision has been recorded.",
        "Board Chairman" if snapshot.authority == "board" else authority,
    )
    if requester_sign and decision_sign:
        statement_heights = [
            panel[1].wrap(WIDTH * 0.48 - 6, A4[1])[1] for panel in (left_panel, right_panel)
        ]
        for panel, height in zip((left_panel, right_panel), statement_heights, strict=True):
            panel.insert(2, Spacer(1, max(statement_heights) - height))
    panels = grid(
        [[left_panel, "", right_panel]], [WIDTH * 0.48, WIDTH * 0.04, WIDTH * 0.48], padding=0
    )
    story.append(Spacer(1, 5))
    story.append(KeepTogether([panels]))
    story.append(Spacer(1, 10))
    p("Approved means authorised, not paid.", "small")
    extra_signatures = [
        record for record in snapshot.signatures if len(record.statement) > 360 or record.reason
    ]
    has_details = bool(
        snapshot.evidence
        or extra_signatures
        or snapshot.board
        or snapshot.current_state != snapshot.state
    )
    if has_details:
        story.append(PageBreak())
        p("Additional details", "h1")
    if snapshot.current_state != snapshot.state:
        field("Current request status", STATES.get(snapshot.current_state, snapshot.current_state))
    if snapshot.evidence:
        p("Supporting documents", "h2")
        for item in snapshot.evidence:
            p(item.filename)
    for signed_item in extra_signatures:
        signature(signed_item)
    if snapshot.board:
        p("Board resolution record", "h2")
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

    header = grid(
        [
            [
                paragraph("Brendan Nicholas Holdings", "strong"),
                paragraph(title + " · " + snapshot.reference, "words"),
            ]
        ],
        [WIDTH * 0.49, WIDTH * 0.51],
        padding=0,
    )
    _, header_height = header.wrap(WIDTH, A4[1])
    header_space = max(32, header_height + 14)

    def page_header(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        header.drawOn(canvas, MARGIN, A4[1] - MARGIN - header_height)
        canvas.setStrokeColor(colors.HexColor("#D9D9D9"))
        canvas.setLineWidth(0.5)
        canvas.line(
            MARGIN,
            A4[1] - MARGIN - header_height - 7,
            A4[0] - MARGIN,
            A4[1] - MARGIN - header_height - 7,
        )
        canvas.restoreState()

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
            onPage=page_header,
            frames=[
                Frame(
                    MARGIN,
                    MARGIN,
                    WIDTH,
                    A4[1] - 2 * MARGIN - header_space,
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
