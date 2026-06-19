import os
import json
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import db

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """Isolates the database for testing."""
    db_file = tmp_path / "test_main_library.json"
    with db.lock:
        db.db_path = db_file
        db._save_data({"albums": {}, "songs": {}})
    yield

def test_system_status():
    """Verify system status returns FFmpeg detection and library path config."""
    response = client.get("/api/system-status")
    assert response.status_code == 200
    data = response.json()
    assert "ffmpeg_ok" in data
    assert "library_dir" in data
    assert "os" in data

@patch("backend.main.scan_drive_tracks")
def test_scan_endpoint(mock_scan):
    """Verify scan endpoint maps requests to scanner logic and handles errors."""
    mock_scan.return_value = [
        {"original_path": "D:\\MPEGAV\\AVSEQ01.DAT", "filename": "AVSEQ01.DAT", "track_number": 1}
    ]
    
    # 1. Successful Scan
    response = client.post("/api/scan", json={"path": "."})
    assert response.status_code == 200
    assert len(response.json()["tracks"]) == 1
    assert response.json()["tracks"][0]["filename"] == "AVSEQ01.DAT"
    
    # 2. Empty Path Error
    response = client.post("/api/scan", json={"path": ""})
    assert response.status_code == 400

@patch("backend.main.add_transcode_job")
def test_import_endpoint(mock_add_job):
    """Verify import endpoint auto-generates album ID/name and adds transcode jobs."""
    mock_add_job.return_value = "CD_AUTO_T01"
    
    payload = {
        "tracks": [
            {
                "original_path": "D:\\MPEGAV\\AVSEQ01.DAT",
                "track_number": 1,
                "title": "川の流れのように",
                "artist": "美空ひばり"
            }
        ]
    }
    
    response = client.post("/api/import", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    # Check that it returned the auto-generated CD timestamp metadata
    assert "album_id" in data
    assert data["album_id"].startswith("CD_")
    assert "song_ids" in data
    assert len(data["song_ids"]) == 1
    
    # Verify add_transcode_job was called with the auto-generated details
    mock_add_job.assert_called_once()
    args, kwargs = mock_add_job.call_args
    assert kwargs["album_id"] == data["album_id"]
    assert kwargs["title"] == "川の流れのように"
    assert kwargs["artist"] == "美空ひばり"

def test_song_crud():
    """Verify API CRUD operations for editing song titles/artists and deleting entries."""
    album_id = "CD_API_TEST"
    album_name = "美空ひばり精選"
    song_id = f"{album_id}_T01"
    
    # Setup database entry
    db.add_album(album_id, album_name)
    db.add_or_update_song(song_id, {
        "album_id": album_id,
        "album_name": album_name,
        "track_number": 1,
        "title": "Track 01",
        "artist": "",
        "status": "completed"
    })
    
    # 1. Rename Song
    response = client.post(f"/api/songs/{song_id}/rename", json={
        "title": "悲しい酒",
        "artist": "美空ひばり"
    })
    assert response.status_code == 200
    
    # Verify rename in database
    song = db.get_song(song_id)
    assert song["title"] == "悲しい酒"
    assert song["artist"] == "美空ひばり"
    
    # Verify album automatically transitioned to completed
    album = db.get_album(album_id)
    assert album["status"] == "completed"
    
    # 2. Delete Song
    response = client.delete(f"/api/songs/{song_id}?delete_file=false")
    assert response.status_code == 200
    assert db.get_song(song_id) is None

def test_upload_endpoint(tmp_path):
    """Verify upload endpoint successfully saves files to UPLOAD_DIR and extracts duration."""
    from pathlib import Path
    
    with patch("backend.main.UPLOAD_DIR", tmp_path), \
         patch("backend.converter.get_media_duration", return_value=120.5):
        
        # 1. Success case (.vob)
        files = {"files": ("test_song.vob", b"dummy vob content", "video/dvd")}
        response = client.post("/api/upload", files=files)
        
        assert response.status_code == 200
        data = response.json()
        assert "files" in data
        assert len(data["files"]) == 1
        
        uploaded = data["files"][0]
        assert uploaded["filename"] == "test_song.vob"
        assert uploaded["title"] == "test_song"
        assert uploaded["artist"] == ""
        assert uploaded["duration"] == 120.5
        assert uploaded["file_size"] == len(b"dummy vob content")
        assert Path(uploaded["original_path"]).exists()
        
        # 2. Invalid Extension Error
        files = {"files": ("test_song.txt", b"dummy text content", "text/plain")}
        response = client.post("/api/upload", files=files)
        assert response.status_code == 400
        assert "不支援的檔案格式" in response.json()["detail"]

@patch("backend.main.add_transcode_job")
def test_import_endpoint_with_custom_album(mock_add_job):
    """Verify import endpoint accepts and uses custom album ID and name."""
    mock_add_job.return_value = "UPLOAD_20260619_T01"
    
    payload = {
        "tracks": [
            {
                "original_path": "/path/to/upload.vob",
                "track_number": 1,
                "title": "愛拼才會贏",
                "artist": "葉啟田"
            }
        ],
        "album_id": "UPLOAD_20260619_2215",
        "album_name": "本機上傳歌曲 2026-06-19"
    }
    
    response = client.post("/api/import", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert data["album_id"] == "UPLOAD_20260619_2215"
    assert data["album_name"] == "本機上傳歌曲 2026-06-19"
    
    mock_add_job.assert_called_once()
    args, kwargs = mock_add_job.call_args
    assert kwargs["album_id"] == "UPLOAD_20260619_2215"
    assert kwargs["album_name"] == "本機上傳歌曲 2026-06-19"

