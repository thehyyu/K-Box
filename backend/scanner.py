import os
import re
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Dict
from backend.config import FFPROBE_PATH

def detect_optical_drives() -> List[str]:
    """
    Detects mounted optical drives (CD-ROM/DVD) on the system.
    Returns a list of drive paths (e.g., ['D:\\'] on Windows or ['/Volumes/VCD_NAME'] on Mac).
    """
    drives = []
    
    if os.name == "nt":  # Windows
        try:
            import ctypes
            # Get logical drives bitmask (bit 0 = A:, bit 1 = B:, etc.)
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    drive_letter = f"{chr(65 + i)}:\\"
                    # DRIVE_CDROM = 5
                    drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_letter)
                    if drive_type == 5:
                        drives.append(drive_letter)
        except Exception as e:
            print(f"Error detecting Windows optical drives: {e}")
            # Fallback to psutil disk partitions check
            try:
                import psutil
                for partition in psutil.disk_partitions(all=True):
                    if "cdrom" in partition.opts.lower() or partition.fstype == "":
                        drives.append(partition.mountpoint)
            except Exception:
                pass
    else:  # macOS / Linux
        # On macOS, optical drives mount under /Volumes
        volumes_path = Path("/Volumes")
        if volumes_path.exists():
            for child in volumes_path.iterdir():
                # Skip symlinks and system folders
                if child.is_dir() and not child.is_symlink():
                    if child.name not in ("Macintosh HD", "Preboot", "Recovery", "VM"):
                        # Basic check: optical disks on Mac often show up as read-only
                        # We include them as candidates
                        drives.append(str(child))
                        
    return list(set(drives))

def probe_dvd_chapters(vob_path: str) -> List[dict]:
    """
    Uses ffprobe to extract chapter markers from a VOB or composite media file.
    Supports semicolon-separated paths (e.g. path1;path2) using the concat demuxer.
    Returns a list of chapters with 'index', 'start_time', 'end_time', and 'duration'.
    """
    import tempfile
    temp_list_path = None
    if ";" in vob_path:
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
                for p in vob_path.split(";"):
                    f.write(f"file '{Path(p).resolve().as_posix()}'\n")
                temp_list_path = f.name
            cmd = [
                FFPROBE_PATH,
                "-v", "error",
                "-show_chapters",
                "-print_format", "json",
                "-f", "concat",
                "-safe", "0",
                temp_list_path
            ]
        except Exception as e:
            print(f"Error preparing concat file for probe: {e}")
            return []
    else:
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-show_chapters",
            "-print_format", "json",
            vob_path
        ]
        
    try:
        try:
            # Hide command window on Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                encoding="utf-8", 
                errors="replace", 
                check=True, 
                startupinfo=startupinfo
            )
            data = json.loads(result.stdout)
            
            chapters = []
            for index, ch in enumerate(data.get("chapters", [])):
                start_time = float(ch.get("start_time", 0.0))
                end_time = float(ch.get("end_time", 0.0))
                duration = end_time - start_time
                
                # Skip very short chapters (e.g. less than 10 seconds, usually transition/menu chunks)
                if duration < 10.0:
                    continue
                    
                chapters.append({
                    "index": index + 1,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration
                })
            return chapters
        finally:
            if temp_list_path and os.path.exists(temp_list_path):
                try:
                    os.unlink(temp_list_path)
                except Exception:
                    pass
    except Exception as e:
        print(f"Error probing chapters for {vob_path}: {e}")
        return []

def scan_drive_tracks(drive_path: str) -> List[dict]:
    """
    Scans the drive path for Karaoke-compatible tracks.
    Identifies VCD (DAT files in MPEGAV), DVD (VOB files in VIDEO_TS),
    and general media formats.
    """
    root_path = Path(drive_path)
    if not root_path.exists():
        return []

    tracks = []
    video_extensions = {".dat", ".vob", ".mp4", ".avi", ".mpg", ".mpeg", ".mkv", ".wmv"}
    
    # 1. Look for VCD structure (MPEGAV/AVSEQXX.DAT)
    vcd_mpegav = root_path / "MPEGAV"
    if vcd_mpegav.exists() and vcd_mpegav.is_dir():
        for file in sorted(vcd_mpegav.iterdir()):
            if file.suffix.lower() == ".dat":
                size_mb = file.stat().st_size / (1024 * 1024)
                if size_mb > 10.0:  # Skip system headers
                    track_num = len(tracks) + 1
                    match = re.search(r'\d+', file.name)
                    if match:
                        track_num = int(match.group())
                    tracks.append({
                        "original_path": str(file),
                        "filename": file.name,
                        "file_size": file.stat().st_size,
                        "track_number": track_num,
                        "type": "VCD",
                        "chapter_index": None,
                        "start_time": None,
                        "end_time": None
                    })
        if tracks:
            return tracks

    # 2. Look for DVD structure (VIDEO_TS/*.VOB)
    vvd_ts = root_path / "VIDEO_TS"
    if vvd_ts.exists() and vvd_ts.is_dir():
        # Search for video VOB files (usually VTS_XX_X.VOB where X >= 1)
        # We skip VTS_XX_0.VOB as they are menu assets
        vob_files = []
        for file in sorted(vvd_ts.iterdir()):
            if file.suffix.lower() == ".vob" and not file.name.endswith("_0.VOB"):
                # Skip VIDEO_TS.VOB (menu)
                if file.name.upper() == "VIDEO_TS.VOB":
                    continue
                size_mb = file.stat().st_size / (1024 * 1024)
                if size_mb > 15.0:  # Skip small files
                    vob_files.append(file)

        # Check if we have multiple VOBs.
        # Often Karaoke DVDs have one big Title Set (VTS_01_1.VOB, VTS_01_2.VOB...)
        # or multiple VTS sets (VTS_01_1.VOB, VTS_02_1.VOB...) representing separate songs.
        # Let's inspect the files.
        vts_groups = {}
        for file in vob_files:
            # Group by VTS set: VTS_01, VTS_02, etc.
            match = re.match(r'(VTS_\d+)', file.name, re.IGNORECASE)
            if match:
                group_name = match.group(1).upper()
                vts_groups.setdefault(group_name, []).append(file)

        for group_name, files in sorted(vts_groups.items()):
            sorted_files = sorted(files)
            # Semicolon-separated paths representing the concatenated title set
            concat_path = ";".join(str(f) for f in sorted_files)
            
            # Check for chapters across the entire concatenated VTS group
            chapters = probe_dvd_chapters(concat_path)
            if chapters:
                for ch in chapters:
                    tracks.append({
                        "original_path": concat_path,
                        "filename": f"{group_name} (章節 {ch['index']})",
                        "file_size": sum(f.stat().st_size for f in sorted_files),
                        "track_number": len(tracks) + 1,
                        "type": "DVD_CHAPTER",
                        "chapter_index": ch["index"],
                        "start_time": ch["start_time"],
                        "end_time": ch["end_time"]
                    })
                continue # Handled via chapter splitting

            # Otherwise, treat each VOB file as an individual track (Scenario A: one song per VTS file)
            for file in sorted(files):
                # Try to extract track number from VTS name
                track_num = len(tracks) + 1
                match = re.search(r'VTS_(\d+)', file.name, re.IGNORECASE)
                if match:
                    track_num = int(match.group(1))
                    
                tracks.append({
                    "original_path": str(file),
                    "filename": file.name,
                    "file_size": file.stat().st_size,
                    "track_number": track_num,
                    "type": "DVD_VOB",
                    "chapter_index": None,
                    "start_time": None,
                    "end_time": None
                })
        if tracks:
            return tracks

    # 3. Fallback: Scan root directory recursively for any compatible media files
    for root, _, files in os.walk(root_path):
        for file in sorted(files):
            file_path = Path(root) / file
            if file_path.suffix.lower() in video_extensions:
                size_mb = file_path.stat().st_size / (1024 * 1024)
                if size_mb > 10.0:  # Ignore small metadata files
                    track_num = len(tracks) + 1
                    tracks.append({
                        "original_path": str(file_path),
                        "filename": file,
                        "file_size": file_path.stat().st_size,
                        "track_number": track_num,
                        "type": "FILE",
                        "chapter_index": None,
                        "start_time": None,
                        "end_time": None
                    })
                    
    return tracks
