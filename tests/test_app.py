"""The app renders from committed outputs with no API key."""
from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def test_app_renders():
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert any("verified" in m.label for m in at.metric)
    assert len(at.dataframe) >= 2
