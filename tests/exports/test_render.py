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
        assert page.count("Unit price") <= 1
    assert text.count("Unit price") > 5
    assert text.index("01 Jan 2026, 01:00:00 WAT") < text.index("PDF generated")


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
    assert "Grand total: NGN 1.01" in text
