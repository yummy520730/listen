from pathlib import Path

from lingyin_server.storage import Store


def test_upload_and_job_lifecycle(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite3", upload_ttl_hours=1, job_ttl_days=1)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"voice")
    upload_id = store.add_upload(audio, "voice.wav", 5)
    assert store.get_upload(upload_id)["original_name"] == "voice.wav"

    job_id = store.create_job("upload", upload_id, "context")
    assert store.get_job(job_id)["status"] == "queued"
    store.set_status(job_id, "running")
    store.set_result(job_id, {"description": "heard"})
    job = store.get_job(job_id)
    assert job["status"] == "done"
    assert job["result"]["description"] == "heard"

    store.delete_upload(upload_id)
    assert not audio.exists()

