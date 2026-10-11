import pytest

from app.exports.render import font_directory
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_workflow import organisation as organisation


@pytest.fixture
def pdf_fonts():
    """Exercise the approved bundled fonts used by the production renderer."""
    return font_directory()


@pytest.fixture
async def exports(context):
    return context
