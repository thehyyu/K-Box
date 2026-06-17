import os
import shutil
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from backend import exporter
from backend.database import db

@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """Isolates the database path for tests."""
    db_file = tmp_path / "test_exporter_db.json"
    with db.lock:
        db.db_path = db_file
        db._save_data({"albums": {}, "songs": {}})
    yield

def test_usb_detector_mac():
    """Verify macOS USB detection scans volumes, ignoring system ones."""
    with patch("os.name", "posix"), \
         patch("os.uname") as mock_uname, \
         patch("psutil.disk_usage") as mock_usage, \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "iterdir") as mock_iterdir:
         
        mock_uname.return_value.sysname = "Darwin"
        
        # Setup mock volumes
        mock_usb = MagicMock()
        mock_usb.is_dir.return_value = True
        mock_usb.is_symlink.return_value = False
        mock_usb.name = "MomUSB"
        mock_usb.__str__.return_value = "/Volumes/MomUSB"
        
        mock_system = MagicMock()
        mock_system.is_dir.return_value = True
        mock_system.is_symlink.return_value = False
        mock_system.name = "Macintosh HD"
        mock_system.__str__.return_value = "/Volumes/Macintosh HD"
        
        mock_iterdir.return_value = [mock_usb, mock_system]
        
        # Mock disk usage
        mock_usage.return_value = MagicMock(free=5000000, total=8000000)
        
        drives = exporter.get_usb_drives()
        assert len(drives) == 1
        assert drives[0]["path"] == "/Volumes/MomUSB"
        assert drives[0]["name"] == "MomUSB"

def test_sequential_copy_and_utime(tmp_path):
    """Test sequential copy order, sandboxed wipe, and os.utime timestamp sequencing."""
    # 1. Setup mock database records for 2 songs
    album_id = "CD_EXPORT_TEST"
    album_name = "美空ひばり經典"
    
    # Create mock source files inside the library songs dir
    library_songs_dir = tmp_path / "library" / "songs" / album_id
    library_songs_dir.mkdir(parents=True)
    
    song1_file = library_songs_dir / "T01_Song1.mp4"
    song1_file.write_bytes(b"content1")
    song2_file = library_songs_dir / "T02_Song2.mp4"
    song2_file.write_bytes(b"content2")
    
    # Update config.SONGS_DIR mock so it searches in our temporary directory
    with patch("backend.exporter.SONGS_DIR", tmp_path / "library" / "songs"):
        db.add_album(album_id, album_name)
        db.add_or_update_song("song1", {
            "album_id": album_id,
            "album_name": album_name,
            "track_number": 1,
            "title": "Song 1",
            "artist": "Singer A",
            "file_path": f"songs/{album_id}/T01_Song1.mp4",
            "status": "completed"
        })
        db.add_or_update_song("song2", {
            "album_id": album_id,
            "album_name": album_name,
            "track_number": 2,
            "title": "Song 2",
            "artist": "Singer B",
            "file_path": f"songs/{album_id}/T02_Song2.mp4",
            "status": "completed"
        })

        # 2. Setup mock USB destination structure
        usb_dir = tmp_path / "usb_mount"
        usb_dir.mkdir()
        
        # Pre-existing unrelated file in USB root (should not be touched!)
        unrelated_file = usb_dir / "important_document.txt"
        unrelated_file.write_text("Don't touch me!")
        
        # Pre-existing sandbox folder with old track
        sandbox_dir = usb_dir / "K-Box_Songs"
        sandbox_dir.mkdir()
        old_track = sandbox_dir / "1000 - OldSong.mp4"
        old_track.write_text("old file")
        
        # 3. Patch os.utime to track calls
        with patch("os.utime") as mock_utime, \
             patch("shutil.copy2") as mock_copy:
             
            exporter.run_export_thread(
                song_ids=["song1", "song2"],
                usb_path=str(usb_dir),
                wipe_first=True,
                naming_strategy="ktv_number"
            )
            
            # Check sandbox safety: unrelated file should still exist
            assert unrelated_file.exists()
            assert unrelated_file.read_text() == "Don't touch me!"
            
            # Verify copy was triggered for both files sequentially
            assert mock_copy.call_count == 2
            
            # Check sequential naming: first called copy should be song 1 (code 1001), then song 2 (code 1002)
            first_copy_args = mock_copy.call_args_list[0][0]
            second_copy_args = mock_copy.call_args_list[1][0]
            
            assert "1001 - Song 1 - Singer A.mp4" in str(first_copy_args[1])
            assert "1002 - Song 2 - Singer B.mp4" in str(second_copy_args[1])
            
            # Verify utime was touched twice (once for each file)
            assert mock_utime.call_count == 2
            
            # Verify modification times are sequential and incrementing
            first_mtime = mock_utime.call_args_list[0][0][1][1]
            second_mtime = mock_utime.call_args_list[1][0][1][1]
            
            assert second_mtime == first_mtime + 1

def test_export_to_root_vs_subfolder(tmp_path):
    """Test both subfolder and root export targets, along with selective file-level cleaning."""
    album_id = "CD_EXPORT_ROOT_TEST"
    album_name = "Root Test Album"
    
    # Create mock source files
    library_songs_dir = tmp_path / "library" / "songs" / album_id
    library_songs_dir.mkdir(parents=True, exist_ok=True)
    song_file = library_songs_dir / "T01_Song.mp4"
    song_file.write_bytes(b"content")
    
    with patch("backend.exporter.SONGS_DIR", tmp_path / "library" / "songs"):
        db.add_album(album_id, album_name)
        db.add_or_update_song("song_root_test", {
            "album_id": album_id,
            "album_name": album_name,
            "track_number": 1,
            "title": "Song Title",
            "artist": "Artist Name",
            "file_path": f"songs/{album_id}/T01_Song.mp4",
            "status": "completed"
        })
        
        # 1. Test export to subfolder (export_to_root=False)
        usb_dir_sub = tmp_path / "usb_mount_sub"
        usb_dir_sub.mkdir()
        
        exporter.run_export_thread(
            song_ids=["song_root_test"],
            usb_path=str(usb_dir_sub),
            wipe_first=True,
            naming_strategy="ktv_number",
            export_to_root=False
        )
        
        # Should create subfolder K-Box_Songs
        sub_folder = usb_dir_sub / "K-Box_Songs"
        assert sub_folder.exists()
        assert (sub_folder / "1001 - Song Title - Artist Name.mp4").exists()
        
        # 2. Test export to root (export_to_root=True)
        usb_dir_root = tmp_path / "usb_mount_root"
        usb_dir_root.mkdir()
        
        # Pre-populate unrelated file, a legacy folder, and an old K-Box file
        unrelated_file = usb_dir_root / "my_holiday_photo.jpg"
        unrelated_file.write_text("photo data")
        
        old_ktv_file = usb_dir_root / "1002 - Old Track.mp4"
        old_ktv_file.write_text("old video")
        
        exporter.run_export_thread(
            song_ids=["song_root_test"],
            usb_path=str(usb_dir_root),
            wipe_first=True,
            naming_strategy="ktv_number",
            export_to_root=True
        )
        
        # The new track should be in the root directory directly
        assert (usb_dir_root / "1001 - Song Title - Artist Name.mp4").exists()
        
        # The unrelated photo should still exist (sandbox safety)
        assert unrelated_file.exists()
        assert unrelated_file.read_text() == "photo data"
        
        # The old KTV code file should have been cleaned up
        assert not old_ktv_file.exists()
