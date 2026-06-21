import os
import shutil
import threading
import time
import re
from pathlib import Path
from typing import List, Dict, Optional
from backend.config import LIBRARY_DIR, SONGS_DIR
from backend.database import db

# Global status tracker for copy/export operations
export_status = {
    "status": "idle",       # 'idle', 'processing', 'completed', 'failed'
    "progress": 0.0,
    "current_file": "",
    "copied_files": 0,
    "total_files": 0,
    "error": ""
}
export_lock = threading.Lock()

def get_usb_drives() -> List[Dict[str, str]]:
    """
    Detects removable USB drives connected to the Windows or macOS system.
    Returns a list of dicts with 'path', 'name', and 'free_space'.
    """
    drives = []
    
    if os.name == "nt":  # Windows
        try:
            import ctypes
            # Scan drive letters
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    drive_letter = f"{chr(65 + i)}:\\"
                    # DRIVE_REMOVABLE = 2
                    drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_letter)
                    if drive_type == 2:
                        # Fetch storage information
                        import psutil
                        try:
                            usage = psutil.disk_usage(drive_letter)
                            # Try to get volume label
                            import win32api
                            vol_name = win32api.GetVolumeInformation(drive_letter)[0]
                            name = vol_name if vol_name else f"USB Drive ({drive_letter.strip('/')})"
                        except Exception:
                            name = f"USB Drive ({drive_letter.strip('/')})"
                            class DummyUsage:
                                free = 0
                                total = 0
                            usage = DummyUsage()
                            
                        drives.append({
                            "path": drive_letter,
                            "name": f"{name} - {drive_letter}",
                            "free_space": getattr(usage, "free", 0),
                            "total_space": getattr(usage, "total", 0)
                        })
        except Exception as e:
            print(f"Error detecting Windows USB drives: {e}")
            # Fallback to psutil disk partitions check
            try:
                import psutil
                for partition in psutil.disk_partitions(all=False):
                    if "removable" in partition.opts.lower():
                        usage = psutil.disk_usage(partition.mountpoint)
                        drives.append({
                            "path": partition.mountpoint,
                            "name": f"USB Drive ({partition.mountpoint})",
                            "free_space": usage.free,
                            "total_space": usage.total
                        })
            except Exception:
                pass
    else:  # macOS / Linux
        # Scan /Volumes for macOS, exclude system volumes
        search_paths = ["/Volumes"] if os.uname().sysname == "Darwin" else ["/media", "/mnt"]
        for search_path in search_paths:
            p = Path(search_path)
            if not p.exists():
                continue
            for child in p.iterdir():
                if child.is_dir() and not child.is_symlink():
                    if child.name in ("Macintosh HD", "Preboot", "Recovery", "VM"):
                        continue
                    try:
                        import psutil
                        usage = psutil.disk_usage(str(child))
                        drives.append({
                            "path": str(child),
                            "name": child.name,
                            "free_space": usage.free,
                            "total_space": usage.total
                        })
                    except Exception as e:
                        print(f"Error accessing mount {child}: {e}")
                        
    return drives

def run_export_thread(song_ids: List[str], usb_path: str, wipe_first: bool, naming_strategy: str, export_to_root: bool = True):
    """
    Background worker doing the sequential copying, sandboxed wiping, and mtime touch sequence.
    """
    global export_status
    
    usb_root = Path(usb_path)
    if not usb_root.exists() or not usb_root.is_dir():
        with export_lock:
            export_status["status"] = "failed"
            export_status["error"] = f"隨身碟路徑 {usb_path} 不存在。"
        return

    # Target directory path based on user preference (Root vs Subfolder)
    target_dir = usb_root if export_to_root else usb_root / "K-Box_Songs"
    
    try:
        if wipe_first:
            if export_to_root:
                # Safe selective file-level wipe in the root directory
                # We compile a list of names from our active database songs to target them specifically
                db_songs = db.get_songs()
                db_filenames = set()
                for song in db_songs:
                    artist = song.get("artist", "").strip()
                    title = song.get("title", "").strip()
                    if artist:
                        db_filenames.add(f"{artist} - {title}.mp4".lower())
                    db_filenames.add(f"{title}.mp4".lower())
                
                # Scan root directory for files to delete
                for item in usb_root.iterdir():
                    if item.is_file():
                        # Delete if it matches KTV code (e.g. 1001 - Title.mp4)
                        is_ktv_pattern = re.match(r'^\d{4} - .+\.mp4$', item.name, re.IGNORECASE)
                        # Delete if it matches one of our DB song names
                        is_db_name = item.name.lower() in db_filenames
                        
                        if is_ktv_pattern or is_db_name:
                            try:
                                item.unlink()
                            except Exception as e:
                                print(f"Failed to delete {item.name}: {e}")
                
                # Also delete the legacy folder K-Box_Songs if it exists to clean up
                legacy_dir = usb_root / "K-Box_Songs"
                if legacy_dir.exists() and legacy_dir.is_dir():
                    try:
                        shutil.rmtree(legacy_dir)
                    except Exception:
                        pass
            else:
                # Safely wipe only our specific sandbox directory if it exists
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                    
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        with export_lock:
            export_status["status"] = "failed"
            export_status["error"] = f"無法建立隨身碟目標資料夾：{e}"
        return

    with export_lock:
        export_status = {
            "status": "processing",
            "progress": 0.0,
            "current_file": "",
            "copied_files": 0,
            "total_files": len(song_ids),
            "error": ""
        }

    success_count = 0
    # Determine base mtime: sequential mtimes separated by 1 second, ending at current time
    base_time = int(time.time()) - len(song_ids)
    
    for index, song_id in enumerate(song_ids):
        song = db.get_song(song_id)
        if not song or song.get("status") != "completed":
            continue
            
        src_rel_path = song.get("file_path")
        if not src_rel_path:
            continue
            
        # Resolve source file path (relative to library directory)
        src_path = SONGS_DIR.parent / src_rel_path
        if not src_path.exists():
            print(f"Source file not found: {src_path}")
            continue
            
        # Format filename based on selected strategy
        artist = song.get("artist", "").strip()
        title = song.get("title", "").strip()
        ext = src_path.suffix
        
        if naming_strategy == "ktv_number":
            ktv_code = 1001 + index
            if artist:
                dest_name = f"{ktv_code:04d} - {title} - {artist}{ext}"
            else:
                dest_name = f"{ktv_code:04d} - {title}{ext}"
        elif naming_strategy == "artist_title":
            if artist:
                dest_name = f"{artist} - {title}{ext}"
            else:
                dest_name = f"{title}{ext}"
        else:  # flat_title
            dest_name = f"{title}{ext}"
            
        # Sanitize filename for Windows FAT32/exFAT filesystems
        dest_name = re.sub(r'[\\/*?:"<>|]', "", dest_name).strip()
        dest_path = target_dir / dest_name
        
        # Report progress
        with export_lock:
            export_status["current_file"] = dest_name
            export_status["progress"] = index / len(song_ids)
            
        try:
            # Skip copying if the file is already there (delta sync) and not wiping
            if not wipe_first and dest_path.exists() and dest_path.stat().st_size == src_path.stat().st_size:
                pass # Skip copy, but we still apply utime touch below to keep sequence intact
            else:
                # Sequential single-threaded copy
                shutil.copy2(src_path, dest_path)
                
            # UTime Touch: Force modification time for DVD player ordering
            target_mtime = base_time + index
            os.utime(dest_path, (target_mtime, target_mtime))
            
            success_count += 1
        except Exception as e:
            print(f"Error copying {dest_name} to USB: {e}")
            with export_lock:
                export_status["error"] = f"複製 {dest_name} 失敗: {str(e)}"
                
        with export_lock:
            export_status["copied_files"] = success_count

    with export_lock:
        if export_status["error"] and success_count == 0:
            export_status["status"] = "failed"
        else:
            export_status["status"] = "completed"
            export_status["progress"] = 1.0
            export_status["current_file"] = ""

def start_export_task(song_ids: List[str], usb_path: str, wipe_first: bool, naming_strategy: str = "ktv_number", export_to_root: bool = True) -> bool:
    """Spawns background thread copy worker."""
    global export_status
    with export_lock:
        if export_status["status"] == "processing":
            return False  # Block duplicate exports
            
    thread = threading.Thread(
        target=run_export_thread, 
        args=(song_ids, usb_path, wipe_first, naming_strategy, export_to_root), 
        daemon=True
    )
    thread.start()
    return True

def get_export_status() -> dict:
    """Retrieves current copy task status."""
    with export_lock:
        return dict(export_status)

# Printable HTML Songbook layout generator
def generate_songbook_html(song_ids: List[str], naming_strategy: str = "ktv_number") -> str:
    """
    Renders A4 dual-column printable HTML songbook for the selected song IDs.
    Sorted by sequence index (KTV number 1001, 1002, 1003...).
    """
    songs = []
    for index, song_id in enumerate(song_ids):
        song = db.get_song(song_id)
        if song:
            code = 1001 + index
            songs.append({
                "code": f"{code:04d}" if naming_strategy == "ktv_number" else "",
                "title": song.get("title", "Unknown"),
                "artist": song.get("artist", "Unknown Artist"),
                "album": song.get("album_name", "Unknown Album"),
                "track": song.get("track_number", 1)
            })

    # Read date
    date_str = time.strftime("%Y-%m-%d")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>K-Box 專屬點歌本</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;700&display=swap');
        
        body {{
            font-family: "Microsoft JhengHei", "Noto Sans TC", sans-serif;
            color: #2c3e50;
            margin: 0;
            padding: 20px;
            background: #fff;
        }}
        
        header {{
            text-align: center;
            border-bottom: 3px double #2c3e50;
            padding-bottom: 10px;
            margin-bottom: 25px;
        }}
        
        h1 {{
            margin: 0;
            font-size: 26px;
            letter-spacing: 2px;
        }}
        
        .subtitle {{
            margin: 5px 0 0 0;
            color: #7f8c8d;
            font-size: 13px;
        }}
        
        h2 {{
            border-bottom: 2px solid #34495e;
            padding-bottom: 4px;
            margin-top: 25px;
            font-size: 17px;
            color: #2c3e50;
            page-break-after: avoid;
        }}
        
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            column-gap: 30px;
        }}
        
        .column {{
        }}
        
        .song-item {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 3px 0;
            border-bottom: 1px dotted #bdc3c7;
            font-size: 12px;
            page-break-inside: avoid;
        }}
        
        .song-info {{
            display: flex;
            align-items: baseline;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 80%;
        }}
        
        .song-code {{
            font-family: monospace;
            font-weight: bold;
            color: #e74c3c;
            margin-right: 8px;
            font-size: 13px;
        }}
        
        .song-title {{
            font-weight: 600;
        }}
        
        .song-artist {{
            color: #7f8c8d;
            font-size: 11px;
            margin-left: 6px;
        }}
        
        .song-locator {{
            font-weight: bold;
            color: #34495e;
            font-size: 11px;
            flex-shrink: 0;
        }}
        
        .page-break {{
            page-break-before: always;
        }}
        
        .print-btn {{
            position: fixed;
            top: 20px;
            right: 20px;
            background-color: #e74c3c;
            color: white;
            border: none;
            padding: 8px 16px;
            font-size: 14px;
            border-radius: 4px;
            cursor: pointer;
            box-shadow: 0 4px 6px rgba(0,0,0,0.15);
            font-family: inherit;
            z-index: 1000;
        }}
        
        .print-btn:hover {{
            background-color: #c0392b;
        }}
        
        @media print {{
            .print-btn {{
                display: none;
            }}
            body {{
                padding: 0;
            }}
            @page {{
                size: A4;
                margin: 1.2cm;
            }}
        }}
    </style>
</head>
<body>
    <button class="print-btn" onclick="window.print()">🖨️ 列印點歌本 / 儲存 PDF</button>

    <header>
        <h1>K-Box 專屬伴唱點歌本</h1>
        <p class="subtitle">共收錄 {len(songs)} 首精選金曲 • 日期: {date_str}</p>
    </header>

    <h2>歌曲目錄 (依點歌代碼排序)</h2>
    <div class="grid">
    """
    
    # Render Columns
    mid = (len(songs) + 1) // 2
    col1 = songs[:mid]
    col2 = songs[mid:]
    
    def render_column(items: List[dict]) -> str:
        col_html = []
        for song in items:
            code_prefix = f'<span class="song-code">[{song["code"]}]</span>' if song["code"] else ''
            artist_str = f'<span class="song-artist">({song["artist"]})</span>' if song["artist"] else ''
            col_html.append(f"""
                <div class="song-item">
                    <div class="song-info">
                        {code_prefix}
                        <span class="song-title">{song["title"]}</span>
                        {artist_str}
                    </div>
                    <span class="song-locator">{song["album"][:10]} (Tr {song["track"]})</span>
                </div>
            """)
        return "".join(col_html)

    html += f"""
        <div class="column">
            {render_column(col1)}
        </div>
        <div class="column">
            {render_column(col2)}
        </div>
    </div>
</body>
</html>
    """
    return html
