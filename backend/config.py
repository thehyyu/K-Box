import os
import shutil
from pathlib import Path
import psutil

# Root folder of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Auto-detect default library path (sandbox folder: K-Box_Library)
def detect_library_dir() -> Path:
    # 1. Check if there's an environment variable set
    env_dir = os.getenv("KBOX_LIBRARY_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 2. Check all active drive partitions for an existing "K-Box_Library" directory
    # This automatically detects if the external hard drive with K-Box_Library is plugged in.
    try:
        for partition in psutil.disk_partitions(all=False):
            # Skip read-only mounts
            if "ro" in partition.opts:
                continue
            mount_path = Path(partition.mountpoint)
            candidate = mount_path / "K-Box_Library"
            if candidate.exists() and candidate.is_dir():
                return candidate
    except Exception as e:
        print(f"Error scanning partitions: {e}")

    # 3. If no external drive contains the folder, look for any writeable removable drive
    # and create the folder there.
    try:
        for partition in psutil.disk_partitions(all=False):
            if "removable" in partition.opts.lower() and partition.fstype != "":
                mount_path = Path(partition.mountpoint)
                candidate = mount_path / "K-Box_Library"
                try:
                    candidate.mkdir(parents=True, exist_ok=True)
                    return candidate
                except Exception:
                    continue
    except Exception:
        pass

    # 4. Fallback: User's home directory
    fallback = Path.home() / "K-Box_Library"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

LIBRARY_DIR = detect_library_dir()
SONGS_DIR = LIBRARY_DIR / "songs"
SONGS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = LIBRARY_DIR / "library.json"

# Auto-detect FFmpeg and FFprobe binaries
def detect_binary_path(binary_name: str) -> str:
    # On Windows, binaries end with .exe
    suffix = ".exe" if os.name == "nt" else ""
    full_name = f"{binary_name}{suffix}"

    # 1. Check local project bin folder (e.g. backend/bin/ffmpeg.exe)
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

    # Fallback to default name
    return binary_name

FFMPEG_PATH = detect_binary_path("ffmpeg")
FFPROBE_PATH = detect_binary_path("ffprobe")
