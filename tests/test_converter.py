import io
from unittest.mock import patch, MagicMock
import pytest
from backend import converter
from backend.database import db

@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """Resets database instance path to a temporary sandbox file for test isolation."""
    db_file = tmp_path / "test_converter_library.json"
    with db.lock:
        db.db_path = db_file
        db._save_data({"albums": {}, "songs": {}})
    yield

@patch("subprocess.Popen")
@patch("backend.converter.get_media_duration", return_value=100.0)
def test_ffmpeg_progress_parse(mock_duration, mock_popen):
    """Verify that FFmpeg output parsing correctly computes progress percentage and speed."""
    # Setup mock subprocess Popen instance
    mock_process = MagicMock()
    mock_process.returncode = 0
    
    # Simulate FFmpeg stdout output lines
    ffmpeg_lines = [
        "frame=  120\n",
        "fps= 25.0\n",
        "out_time_ms=25000000\n",  # 25 seconds
        "speed= 2.5x\n",
        "frame=  240\n",
        "out_time_ms=50000000\n",  # 50 seconds
        "speed= 2.8x\n"
    ]
    # File-like wrapper around generator to support readline()
    class MockStdout:
        def __init__(self, lines):
            self.iterator = iter(lines)
        def readline(self):
            try:
                return next(self.iterator)
            except StopIteration:
                return ""
                
    mock_process.stdout = MockStdout(ffmpeg_lines)
    mock_process.wait.return_value = None
    mock_popen.return_value = mock_process
    
    # Initialize job status tracking for this fake song
    song_id = "CD_TEST_T01"
    with converter.status_lock:
        converter.job_status[song_id] = {
            "status": "processing",
            "progress": 0.0,
            "speed": "0x",
            "title": "Test Song",
            "artist": "Test Artist"
        }
        
    success = converter.run_transcode(song_id, "dummy_src.dat", "dummy_dest.mp4")
    
    assert success is True
    # Progress at 50s / 100s duration = 0.50 (50%)
    assert converter.job_status[song_id]["progress"] == 0.50
    assert converter.job_status[song_id]["speed"] == "2.8x"

def test_add_transcode_job():
    """Verify that adding a job registers it in the DB and pushes it to the queue."""
    album_id = "CD_QUEUE_TEST"
    album_name = "美空ひばり經典"
    track_num = 5
    title = "柔"
    artist = "美空ひばり"
    src_path = "mock_source_file.vob"
    
    # Ensure queue is empty before test
    while not converter.conversion_queue.empty():
        converter.conversion_queue.get()
        
    # Add job
    song_id = converter.add_transcode_job(
        album_id=album_id,
        album_name=album_name,
        track_num=track_num,
        title=title,
        artist=artist,
        src_path=src_path
    )
    
    assert song_id == f"{album_id}_T05"
    
    # Verify it entered database as processing
    song = db.get_song(song_id)
    assert song is not None
    assert song["title"] == title
    assert song["artist"] == artist
    assert song["status"] == "processing"
    
    # Verify it entered job status tracking
    assert song_id in converter.job_status
    assert converter.job_status[song_id]["title"] == title
    assert converter.job_status[song_id]["artist"] == artist
