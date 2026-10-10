from app.services import storage


def test_storage_client_and_upload_fail_cleanly_when_storage_is_unavailable(monkeypatch):
    class BrokenMinio:
        def __init__(self, *args, **kwargs):
            pass

        def bucket_exists(self, bucket):
            raise ConnectionError("storage unavailable")

    monkeypatch.setattr(storage, "Minio", BrokenMinio)

    assert storage.client() is None
    assert storage.put_object("test.txt", b"data") is False
    assert storage.get_object("test.txt") is None
