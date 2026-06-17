import os
import shutil
from pathlib import Path
import psutil

# Root folder of the project
BASE_DIR = Path(__file__).resolve().parent.parent

def is_writable(path: Path) -> bool:
    """Helper to verify if a directory path is truly writable on the filesystem."""
    test_dir = path / ".kbox_write_test"
    try:
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / "test.tmp"
        test_file.write_text("write_test", encoding="utf-8")
        test_file.unlink()
        test_dir.rmdir()
        return True
    except Exception:
        return False

# Auto-detect default library path (sandbox folder: K-Box_Library)
def detect_library_dir() -> Path:
    # 1. Check if there's an environment variable set
    env_dir = os.getenv("KBOX_LIBRARY_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 2. Check all active drive partitions for an EXISTING and writable "K-Box_Library" directory.
    # This ensures that if the external hard drive is plugged in, we use it.
    try:
        import ctypes
        for partition in psutil.disk_partitions(all=False):
            # Skip read-only mounts in options
            if "ro" in partition.opts:
                continue
            
            mount_point = partition.mountpoint
            
            # Windows specific: Skip CD-ROM drives (DRIVE_CDROM = 5)
            if os.name == "nt":
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(mount_point)
                if drive_type == 5: # Skip CD-ROM
                    continue

            candidate = Path(mount_point) / "K-Box_Library"
            if candidate.exists() and candidate.is_dir() and is_writable(candidate):
                return candidate
    except Exception as e:
        print(f"Error scanning partitions for existing library: {e}")

    # 3. Fallback: User's home directory (always writable and local on C: drive).
    # We do NOT automatically create a new library on random removable USB drives
    # to avoid hijacking the export destination.
    fallback = Path.home() / "K-Box_Library"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

LIBRARY_DIR = detect_library_dir()
SONGS_DIR = LIBRARY_DIR / "songs"
SONGS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = LIBRARY_DIR / "library.json"

# Auto-detect FFmpeg and FFprobe binaries
def detect_binary_path(binary_name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    full_name = f"{binary_name}{suffix}"

    # 1. Check local project bin folder
    local_path = BASE_DIR / "backend" / "bin" / full_name
    if local_path.exists():
        return str(local_path)

    # 2. Check if binary is in system PATH
    system_path = shutil.which(binary_name)
    if system_path:
        return system_path

    # 3. Check common installation paths
    if os.name == "nt":  # Windows
        common_paths = [
            Path(r"C:\Program Files\ffmpeg\bin") / full_name,
            Path(r"C:\ffmpeg\bin") / full_name,
        ]
        for path in common_paths:
            if path.exists():
                return str(path)
    else:  # macOS / Linux
        common_paths = [
            Path("/opt/homebrew/bin") / full_name,
            Path("/usr/local/bin") / full_name,
            Path("/usr/bin") / full_name,
        ]
        for path in common_paths:
            if path.exists():
                return str(path)

    return binary_name

FFMPEG_PATH = detect_binary_path("ffmpeg")
FFPROBE_PATH = detect_binary_path("ffprobe")
