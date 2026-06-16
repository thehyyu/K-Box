import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from backend import scanner

def test_detect_optical_drives_mac():
    """Verify that macOS volumes directory scanning returns non-system volumes."""
    with patch("os.name", "posix"), \
         patch("os.uname") as mock_uname, \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "iterdir") as mock_iterdir:
         
        mock_uname.return_value.sysname = "Darwin"
        
        # Mock volumes
        vol1 = MagicMock()
        vol1.is_dir.return_value = True
        vol1.is_symlink.return_value = False
        vol1.name = "MyVCD"
        vol1.__str__.return_value = "/Volumes/MyVCD"
        
        vol_mac_hd = MagicMock()
        vol_mac_hd.is_dir.return_value = True
        vol_mac_hd.is_symlink.return_value = False
        vol_mac_hd.name = "Macintosh HD"
        vol_mac_hd.__str__.return_value = "/Volumes/Macintosh HD"
        
        mock_iterdir.return_value = [vol1, vol_mac_hd]
        
        drives = scanner.detect_optical_drives()
        assert "/Volumes/MyVCD" in drives
        assert "/Volumes/Macintosh HD" not in drives

def test_probe_dvd_chapters():
    """Test parsing of chapters from mock ffprobe JSON output."""
    mock_ffprobe_output = {
        "chapters": [
            {
                "id": 0,
                "start_time": "0.000000",
                "end_time": "210.500000",
                "tags": {"title": "Chapter 01"}
            },
            {
                "id": 1,
                "start_time": "210.500000",
                "end_time": "450.000000",
                "tags": {"title": "Chapter 02"}
            },
            {
                "id": 2,
                "start_time": "450.000000",
                "end_time": "455.000000",
                "tags": {"title": "Short Chapter (Skip)"}
            }
        ]
    }
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = json.dumps(mock_ffprobe_output)
        mock_run.return_value.returncode = 0
        
        chapters = scanner.probe_dvd_chapters("/mock/path/VTS_01_1.VOB")
        
        # Verify result parses and filters correctly
        # The third chapter is under 10 seconds (duration = 5s), so it should be skipped
        assert len(chapters) == 2
        
        assert chapters[0]["index"] == 1
        assert chapters[0]["start_time"] == 0.0
        assert chapters[0]["end_time"] == 210.5
        assert chapters[0]["duration"] == 210.5
        
        assert chapters[1]["index"] == 2
        assert chapters[1]["start_time"] == 210.5
        assert chapters[1]["end_time"] == 450.0
        assert chapters[1]["duration"] == 239.5

def test_scan_drive_tracks_vcd(tmp_path):
    """Test VCD scanning which locates DAT files inside MPEGAV directory."""
    # Create mock VCD structure
    mpegav_dir = tmp_path / "MPEGAV"
    mpegav_dir.mkdir()
    
    # Create some dummy files: one large track DAT, one small dummy DAT
    track1 = mpegav_dir / "AVSEQ01.DAT"
    track1.write_bytes(b"0" * (12 * 1024 * 1024)) # 12MB
    
    dummy_meta = mpegav_dir / "AVSEQ02.DAT"
    dummy_meta.write_bytes(b"0" * 1024) # 1KB (should be skipped as too small)
    
    tracks = scanner.scan_drive_tracks(str(tmp_path))
    
    assert len(tracks) == 1
    assert tracks[0]["filename"] == "AVSEQ01.DAT"
    assert tracks[0]["type"] == "VCD"
    assert tracks[0]["track_number"] == 1
