import pytest

from app import main as app_main


@pytest.fixture(autouse=True)
def isolate_process_local_rate_limit_state():
    """Prevent one test's requests from rate-limiting unrelated tests."""
    app_main._hits.clear()
    app_main._last_rate_limit_cleanup = 0.0
    yield
    app_main._hits.clear()
    app_main._last_rate_limit_cleanup = 0.0
