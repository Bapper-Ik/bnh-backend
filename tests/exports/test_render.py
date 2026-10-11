import subprocess
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.exports.render import RenderFailure, render
from app.exports.schemas import Snapshot


def sample(**extra):
    return Snapshot.model_validate(
        {
            "reference": "BNH-2026-TEST",
            "requisition_id": str(uuid4()),
            "revision": 0,
            "request_version": 1,
            "state": "DRAFT",
            "current_state": "DRAFT",
            "requester": "Synthetic requester",
            "department": "Operations",
            "company": "Synthetic company",
            "authority": "",
            "route": "",
            "policy": "",
            "content": {
                "vendor": {
                    "name": "Synthetic vendor",
                    "account_number": "0012345678",
                    "bank_name": "Synthetic bank",
                    "account_name": "Supplier",
                },
                "description": 'Synthetic scope <img src="https://invalid.example/image"/> & text',
                "lines": [{"description": "Cost item", "quantity": "1.005", "unit_price": "1.00"}],
            },
            "total": "1.01",
            "redacted_fields": [],
            "as_of": datetime(2026, 1, 1, tzinfo=UTC),
            "signatures": [],
            "evidence": [],
            "board": [],
            "include_board": False,
            **extra,
        }
    )


def test_multipage_layout_exact_decimal_escaped_text_and_page_numbers(pdf_fonts, tmp_path):
    snapshot = sample()
    snapshot.content.description += " Long synthetic scope for pagination." * 120
    original = snapshot.content.lines[0]
    snapshot.content.lines = [
        original.model_copy(update={"description": f"Item {i}: " + "long cost description " * 12})
        for i in range(200)
    ]
    snapshot.total = "202.00"
    data, renderer, fonts = render(snapshot, str(uuid4()), "a" * 64, datetime.now(UTC), pdf_fonts)
    assert renderer.startswith("reportlab-") and fonts.startswith("bnh-liberation-v1:")
    target = tmp_path / "synthetic-layout.pdf"
    target.write_bytes(data)
    text = subprocess.check_output(["pdftotext", "-layout", str(target), "-"], text=True)
    assert "0012345678" in text and "202.00" in text and "1.01" in text
    assert "https://invalid.example/image" in text
    pages = text.rstrip("\f\n").split("\f")
    assert len(pages) > 10
    for number, page in enumerate(pages, 1):
        assert f"Page {number} of {len(pages)}" in page
        assert page.count("Amount (NGN)") <= 1
    assert text.count("Amount (NGN)") > 5
    assert "SHA-256" not in text and "Export verification" not in text


def test_unsupported_character_and_bad_total_fail_explicitly(pdf_fonts):
    snapshot = sample()
    snapshot.content.description = "Unrenderable: \U0001f9d0"
    with pytest.raises(RenderFailure, match="unsupported_font_characters"):
        render(snapshot, "test", "a" * 64, datetime.now(UTC), pdf_fonts)
    snapshot = sample(total="1.00")
    with pytest.raises(RenderFailure, match="snapshot_total_mismatch"):
        render(snapshot, "test", "a" * 64, datetime.now(UTC), pdf_fonts)


def test_bundled_fonts_embed_naira_and_accents_without_private_configuration(pdf_fonts):
    import io

    from pypdf import PdfReader

    from app.exports.render import available, load_fonts

    assert available()
    fonts, version = load_fonts(pdf_fonts)
    assert len(fonts) == 3 and version.startswith("bnh-liberation-v1:")
    snapshot = sample()
    snapshot.content.description = "Amount ₦1.01; café; Nigerian supplier"
    data, _, _ = render(snapshot, "bundled-fonts", "a" * 64, datetime.now(UTC), pdf_fonts)
    document = PdfReader(io.BytesIO(data))
    assert "Amount ₦1.01; café" in "".join(page.extract_text() for page in document.pages)
    embedded = set()
    for page in document.pages:
        for ref in page["/Resources"]["/Font"].values():
            font = ref.get_object()
            if "/FontDescriptor" in font:
                assert font["/FontDescriptor"]["/FontFile2"].get_data()
                embedded.add(str(font["/BaseFont"]))
    assert any("LiberationSerif" in name for name in embedded)
    assert any("LiberationSans-Bold" in name for name in embedded)


def test_extremely_tall_cost_row_splits_without_losing_content(pdf_fonts, tmp_path):
    snapshot = sample()
    snapshot.content.lines[0].description = "x\n" * 240
    data, _, _ = render(snapshot, "synthetic", "a" * 64, datetime.now(UTC), pdf_fonts)
    target = tmp_path / "tall-row.pdf"
    target.write_bytes(data)
    text = subprocess.check_output(["pdftotext", "-layout", str(target), "-"], text=True)
    assert len(text.split("\f")) > 4
    assert sum(line.strip() == "x" for line in text.splitlines()) >= 239
    assert "NGN 1.01" in text and "Total" in text


def approved_sample(**extra):
    return sample(
        revision=1,
        state="APPROVED",
        current_state="APPROVED",
        authority="chief_of_staff",
        policy="bnh-doa-v1",
        signatures=[
            dict(
                label="Requester declaration",
                name="Example requester",
                at="2026-10-11T09:00:00+00:00",
                statement="I confirm the details are correct.",
                digest="b" * 64,
                strokes=[[dict(x=0.1, y=0.7), dict(x=0.2, y=0.2), dict(x=0.4, y=0.6)]],
            ),
            dict(
                label="Approval",
                name="Example approver",
                at="2026-10-11T11:00:00+00:00",
                statement="I approve this requisition.",
                digest="c" * 64,
                strokes=[[dict(x=0.1, y=0.6), dict(x=0.3, y=0.1), dict(x=0.5, y=0.5)]],
            ),
        ],
        **extra,
    )


def pdf_pages(snapshot, pdf_fonts, **kwargs):
    import io

    from pypdf import PdfReader

    data, _, _ = render(snapshot, "sample-export", "a" * 64, datetime.now(UTC), pdf_fonts, **kwargs)
    return PdfReader(io.BytesIO(data)).pages, data


def test_template_summary_and_side_by_side_signatures_without_internal_metadata(
    pdf_fonts, tmp_path
):
    import xml.etree.ElementTree as ET

    pages, data = pdf_pages(approved_sample(), pdf_fonts)
    assert len(pages) == 1
    first = pages[0].extract_text()
    for label in [
        "Approved Requisition",
        "TOTAL",
        "STATUS",
        "AUTHORITY",
        "1. Requester",
        "2. Vendor",
        "3. Scope of work",
        "4. Cost breakdown",
        "5. Declaration",
        "6. Approval",
        "Example requester",
        "Example approver",
        "One Naira and One Kobo Only",
    ]:
        assert label in first
    assert "11 Oct 2026, 12:00 WAT" in first  # Actual decision, not export time.
    assert "a" * 64 not in first and "b" * 64 not in first
    assert "c" * 64 not in first
    assert "Signature reference" not in first and "Template:" not in first
    path = tmp_path / "aligned.pdf"
    path.write_bytes(data)
    xml = subprocess.check_output(["pdftotext", "-bbox", str(path), "-"], text=True)
    tree = ET.fromstring(xml)
    page = tree.find(".//{*}page")
    words = list(page.iterfind(".//{*}word"))
    declaration = next(w for w in words if w.text == "Declaration")
    approval = next(w for w in words if w.text == "Approval")
    assert abs(float(declaration.attrib["yMin"]) - float(approval.attrib["yMin"])) < 1
    assert float(approval.attrib["xMin"]) > float(declaration.attrib["xMax"])
    total = next(w for w in words if w.text == "TOTAL")
    assert float(total.attrib["xMin"]) > 400


@pytest.mark.parametrize(
    "state,title",
    [
        ("DRAFT", "Draft Requisition"),
        ("PENDING_AUTHORITY", "Requisition for Approval"),
        ("REJECTED", "Rejected Requisition"),
        ("RETURNED_FOR_REVISION", "Returned Requisition"),
        ("DEFERRED", "Deferred Requisition"),
        ("CONDITIONALLY_APPROVED", "Conditional Requisition"),
    ],
)
def test_template_preserves_nonapproved_states_and_restricted_banks(pdf_fonts, state, title):
    snapshot = sample(state=state, current_state=state, redacted_fields=["vendor.bank_details"])
    pages, _ = pdf_pages(snapshot, pdf_fonts)
    text = "".join(page.extract_text() for page in pages)
    assert title in text and "Approved Requisition" not in text
    assert "Restricted in this export." in text and "0012345678" not in text
    assert "No final decision has been recorded." in text


def test_legacy_template_remains_available_for_predeployment_jobs(pdf_fonts):
    pages, _ = pdf_pages(sample(), pdf_fonts, template_version="requisition-v1")
    text = "".join(page.extract_text() for page in pages)
    assert "Requisition and approval record" in text
    assert "SHA-256" not in text and "Export reference" not in text
    with pytest.raises(RenderFailure, match="unsupported_template"):
        pdf_pages(sample(), pdf_fonts, template_version="unknown")


def test_long_scope_starts_on_summary_page_and_continues_without_loss(pdf_fonts):
    snapshot = approved_sample()
    sentence = "Detailed scope with delivery and commissioning requirements. "
    snapshot.content.description = sentence * 70
    pages, _ = pdf_pages(snapshot, pdf_fonts)
    text = " ".join(" ".join(page.extract_text().split()) for page in pages)
    assert "Detailed scope" in pages[0].extract_text()
    # Running headers/footers may interrupt a sentence at the page boundary.
    for word in ("Detailed", "commissioning", "requirements."):
        assert text.count(word) == 70
    assert "5. Declaration" in text and "6. Approval" in text


@pytest.mark.parametrize("template", ["requisition-v1", "requisition-v2"])
def test_extra_details_preserve_business_evidence_without_exposing_internal_ids(
    pdf_fonts, template
):
    snapshot = approved_sample(
        evidence=[dict(id="private-attachment-id", filename="supplier-quote.pdf", digest="d" * 64)]
    )
    snapshot.signatures[1].reason = "Approved for the replacement equipment."
    snapshot.signatures[0].signature_id = "private-signature-id"
    snapshot.signatures[0].statement = "Actual signed declaration. " * 20
    pages, _ = pdf_pages(snapshot, pdf_fonts, template_version=template)
    text = " ".join(" ".join(page.extract_text().split()) for page in pages)
    assert "supplier-quote.pdf" in text and "Approved for the replacement equipment." in text
    assert text.count("Actual signed declaration.") >= 20
    for value in [
        "private-attachment-id",
        "private-signature-id",
        "sample-export",
        "SHA-256",
        "Template:",
        "Export verification",
    ]:
        assert value not in text
    for letter in "abcd":
        assert letter * 64 not in text
