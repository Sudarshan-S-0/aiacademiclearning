from app import main as app_main
from app.api.routes import safe_download_filename


def test_rate_limit_pruning_removes_expired_client_keys():
    original = {key: list(value) for key, value in app_main._hits.items()}
    try:
        app_main._hits.clear()
        app_main._hits.update({
            "expired-client": [1.0, 2.0],
            "active-client": [940.0, 970.0],
            "mixed-client": [10.0, 995.0],
        })

        app_main._prune_rate_limit_hits(1000.0)

        assert "expired-client" not in app_main._hits
        assert app_main._hits["active-client"] == [970.0]
        assert app_main._hits["mixed-client"] == [995.0]
    finally:
        app_main._hits.clear()
        app_main._hits.update(original)


def test_rate_limit_client_map_has_explicit_capacity():
    assert app_main._RATE_LIMIT_MAX_CLIENTS > 0
    assert app_main._RATE_LIMIT_MAX_REQUESTS > 0
    assert app_main._RATE_LIMIT_WINDOW_SECONDS > 0


def test_download_filename_strips_header_control_characters_and_paths():
    value = safe_download_filename('notes"\\r\\nX-Injected: yes/../../file.pdf')
    assert "\\r" not in value and "\\n" not in value
    assert '"' not in value
    assert "/" not in value and "\\\\" not in value
    assert value
