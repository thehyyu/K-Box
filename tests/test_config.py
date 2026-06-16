import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from backend import config

def test_config_paths():
    """Verify that configuration paths are defined and directories are created."""
    assert config.BASE_DIR.exists()
    assert config.LIBRARY_DIR.exists()
    assert config.SONGS_DIR.exists()
    assert config.DB_PATH.name == "library.json"

@patch("psutil.disk_partitions")
@patch("backend.config.Path")
def test_detect_library_dir_from_partition(mock_path, mock_partitions):
    """Test that library directory can be detected from a partition containing K-Box_Library."""
    # Setup mock partition
    mock_partition = MagicMock()
    mock_partition.mountpoint = "/mock_mount"
    mock_partition.opts = "rw"
    mock_partitions.return_value = [mock_partition]
    
    # Setup mock Path object returned by Path("/mock_mount") / "K-Box_Library"
    mock_candidate = MagicMock()
    mock_candidate.exists.return_value = True
    mock_candidate.is_dir.return_value = True
    
    # Mock the division operator: mount_path / "K-Box_Library"
    mock_path.return_value.__truediv__.return_value = mock_candidate
    
    # Call detection
    detected = config.detect_library_dir()
    
    # Verify the mock candidate is returned and division was called correctly
    assert detected == mock_candidate
    mock_path.return_value.__truediv__.assert_called_with("K-Box_Library")

def test_detect_binary_path():
    """Test that the binary path detector returns executable names."""
    ffmpeg_path = config.detect_binary_path("ffmpeg")
    assert "ffmpeg" in ffmpeg_path.lower()
    
    ffprobe_path = config.detect_binary_path("ffprobe")
    assert "ffprobe" in ffprobe_path.lower()
