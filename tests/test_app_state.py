"""Page inputs must survive navigating away and back.

Streamlit discards the state of any widget it did not render on the current run,
so every control resets when you switch pages unless its value is mirrored into
a plain session-state key. This is the mechanism that stops that, tested on a
cheap page so the suite stays fast; the heavy Country-plots page uses the same
``sticky`` helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = streamlit_testing.AppTest

# AppTest resolves relative paths against the *calling* file, i.e. tests/.
ROOT = Path(__file__).resolve().parents[1]

# Keys that outlive a page switch: the canonical mirrors and the shared selection.
PERSIST_PREFIXES = ("_keep_",)
PERSIST_KEYS = {"required_vars", "optional_vars", "cmp_plotted"}


def carry_over(app) -> dict:
    """Exactly what Streamlit keeps when you navigate to another page."""
    return {
        key: value
        for key, value in app.session_state.filtered_state.items()
        if key.startswith(PERSIST_PREFIXES) or key in PERSIST_KEYS
    }


def run_page(path: str, state: dict | None = None, timeout: int = 120):
    app = AppTest.from_file(str(ROOT / path), default_timeout=timeout)
    for key, value in (state or {}).items():
        app.session_state[key] = value
    app.run()
    return app


def test_inputs_survive_a_page_switch():
    page = run_page("app_pages/find.py")
    page.text_input(key="query").set_value("education and fertility").run()
    page.slider(key="find_limit").set_value(55).run()
    page.toggle(key="find_allc").set_value(True).run()

    # Go to another page, then come back -- widget keys are culled in between.
    elsewhere = run_page("app_pages/coverage.py", carry_over(page))
    returned = run_page("app_pages/find.py", carry_over(elsewhere))

    assert returned.text_input(key="query").value == "education and fertility"
    assert returned.slider(key="find_limit").value == 55
    assert returned.toggle(key="find_allc").value is True
    assert not returned.exception


def test_shared_filters_survive_too():
    """`sample_filters` is mounted on two pages and must not reset between them."""
    coverage = run_page("app_pages/coverage.py", {"required_vars": ["EDATTAIN"]})
    coverage.slider(key="cov_years").set_value((1990, 2010)).run()
    assert coverage.slider(key="cov_years").value == (1990, 2010)

    elsewhere = run_page("app_pages/find.py", carry_over(coverage))
    returned = run_page("app_pages/coverage.py", carry_over(elsewhere))

    assert returned.slider(key="cov_years").value == (1990, 2010)


def test_variable_selection_survives_a_page_switch():
    browse = run_page("app_pages/browse.py", {"required_vars": ["EDATTAIN", "CHBORN"]})
    extract = run_page("app_pages/extract.py", carry_over(browse))

    picked = extract.multiselect(key="extract__required_vars").value
    assert picked == ["EDATTAIN", "CHBORN"]


def test_a_fresh_session_still_gets_the_defaults():
    """Persistence must not stop a first-time visitor seeing sensible defaults."""
    page = run_page("app_pages/find.py")
    assert page.text_input(key="query").value == ""
    assert page.slider(key="find_limit").value == 30
    assert page.toggle(key="find_allc").value is False
