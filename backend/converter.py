import os
import re
import subprocess
import threading
import queue
import time
from pathlib import Path
from typing import Dict, Optional, List
from backend.config import FFMPEG_PATH, FFPROBE_PATH, SONGS_DIR
from backend.database import db

# Thread-safe queue for transcoding tasks
conversion_queue = queue.Queue()
# Map to track active/past job progress and statuses: {song_id: {status, progress, speed, ...}}
job_status: Dict[str, dict] = {}
# Holds the currently running job dict
current_active_job: Optional[dict] = None
# Thread synchronization locks
status_lock = threading.Lock()

def get_media_duration(file_path: str) -> float:
    """Uses ffprobe to query total duration of a media file in seconds."""
    import tempfile
    temp_list_path = None
    if ";" in file_path:
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
                for p in file_path.split(";"):
                    f.write(f"file '{Path(p).resolve().as_posix()}'\n")
                temp_list_path = f.name
            cmd = [
                FFPROBE_PATH,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                "-f", "concat",
                "-safe", "0",
                temp_list_path
            ]
        except Exception as e:
            print(f"Error preparing concat file for duration probe: {e}")
            return 0.0
    else:
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
    try:
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
        return float(result.stdout.strip())
    except Exception as e:
        print(f"Error reading duration for {file_path}: {e}")
        return 0.0
    finally:
        if temp_list_path and os.path.exists(temp_list_path):
            try:
                os.unlink(temp_list_path)
            except Exception:
                pass

def run_transcode(song_id: str, src_path: str, dest_path: str, start_time: Optional[float] = None, end_time: Optional[float] = None) -> bool:
    """
    Spawns FFmpeg to convert the source file to H.264/AAC 480p MP4.
    If start_time and end_time are provided, FFmpeg slices that specific chapter duration.
    """
    import tempfile
    dest_path_obj = Path(dest_path)
    dest_path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Calculate duration for progress tracking
    if start_time is not None and end_time is not None:
        slice_duration = end_time - start_time
    else:
        slice_duration = get_media_duration(src_path)
        if slice_duration <= 0.0:
            slice_duration = 240.0  # Fallback to 4 minutes

    temp_list_path = None
    
    # Assemble FFmpeg command
    if ";" in src_path:
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
                for p in src_path.split(";"):
                    f.write(f"file '{Path(p).resolve().as_posix()}'\n")
                temp_list_path = f.name
            cmd = [
                FFMPEG_PATH,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", temp_list_path
            ]
        except Exception as e:
            print(f"Error preparing concat file for transcode: {e}")
            return False
    else:
        cmd = [
            FFMPEG_PATH,
            "-y",
            "-i", src_path
        ]
        
    # Accurate output seeking for segment slicing (placed AFTER input -i)
    if start_time is not None and slice_duration is not None:
        cmd.extend(["-ss", f"{start_time:.3f}", "-t", f"{slice_duration:.3f}"])
        
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-vf", "scale=-2:480",  # Scale to 480p, preserving aspect ratio, multiple of 2
        "-c:a", "aac",
        "-b:a", "128k",
        "-progress", "pipe:1",  # Output progress parameters to stdout
        str(dest_path_obj)
    ])
    
    try:
        try:
            # Hide command prompt window on Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Redirect stderr to stdout to catch everything in one stream
                text=True,
                encoding="utf-8",
                errors="replace",          # Replace invalid characters instead of raising UnicodeDecodeError
                startupinfo=startupinfo
            )
            
            time_pattern = re.compile(r"out_time_ms=(\d+)")
            speed_pattern = re.compile(r"speed=\s*([\d\.]+)x")
            
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                    
                # Parse progress timestamps
                time_match = time_pattern.search(line)
                if time_match:
                    try:
                        time_us = int(time_match.group(1))
                        curr_time_sec = time_us / 1000000.0
                        progress = min(curr_time_sec / slice_duration, 0.99)  # Cap at 99% until complete
                        with status_lock:
                            if song_id in job_status:
                                job_status[song_id]["progress"] = progress
                    except ValueError:
                        pass
                
                # Parse transcode speeds
                speed_match = speed_pattern.search(line)
                if speed_match:
                    with status_lock:
                        if song_id in job_status:
                            job_status[song_id]["speed"] = speed_match.group(1) + "x"
    
            process.wait()
            return process.returncode == 0
        finally:
            if temp_list_path and os.path.exists(temp_list_path):
                try:
                    os.unlink(temp_list_path)
                except Exception:
                    pass
        
    except Exception as e:
        print(f"FFmpeg transcode execution error for {src_path}: {e}")
        return False

def transcode_worker():
    """Infinite loop queue consumer running inside a daemon thread."""
    global current_active_job
    
    while True:
        try:
            job = conversion_queue.get()
            if job is None:  # Stop sentinel
                break
                
            song_id = job["song_id"]
            src_path = job["src_path"]
            dest_path = job["dest_path"]
            album_id = job["album_id"]
            album_name = job["album_name"]
            track_num = job["track_num"]
            title = job["title"]
            artist = job["artist"]
            start_time = job["start_time"]
            end_time = job["end_time"]
            
            with status_lock:
                job_status[song_id] = {
                    "status": "processing",
                    "progress": 0.0,
                    "speed": "0x",
                    "started_at": time.time(),
                    "title": title,
                    "artist": artist
                }
                current_active_job = job_status[song_id]
                current_active_job["song_id"] = song_id
            
            # Run the conversion
            success = run_transcode(
                song_id=song_id,
                src_path=src_path,
                dest_path=dest_path,
                start_time=start_time,
                end_time=end_time
            )
            
            with status_lock:
                if success:
                    job_status[song_id]["status"] = "completed"
                    job_status[song_id]["progress"] = 1.0
                    
                    # Update database on successful ingestion
                    duration = end_time - start_time if (start_time is not None and end_time is not None) else get_media_duration(dest_path)
                    file_size = Path(dest_path).stat().st_size
                    
                    db.add_or_update_song(song_id, {
                        "album_id": album_id,
                        "album_name": album_name,
                        "track_number": track_num,
                        "title": title,
                        "artist": artist,
                        "duration": duration,
                        "file_path": str(Path(dest_path).relative_to(SONGS_DIR.parent)),
                        "file_size": file_size,
                        "status": "completed"
                    })
                else:
                    job_status[song_id]["status"] = "failed"
                    # Mark database entry as failed
                    db.add_or_update_song(song_id, {
                        "album_id": album_id,
                        "album_name": album_name,
                        "track_number": track_num,
                        "title": title,
                        "artist": artist,
                        "status": "failed"
                    })
                    
                current_active_job = None
                
            conversion_queue.task_done()
            
        except Exception as e:
            print(f"Exception in transcode worker thread loop: {e}")
            time.sleep(1)

# Start background thread
worker_thread = threading.Thread(target=transcode_worker, daemon=True)
worker_thread.start()

def add_transcode_job(album_id: str, album_name: str, track_num: int, title: str, artist: str, src_path: str, start_time: Optional[float] = None, end_time: Optional[float] = None) -> str:
    """Inserts a pending track to database and schedules it to transcode queue."""
    song_id = f"{album_id}_T{track_num:02d}"
    
    # Sanitize title for filename
    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    dest_filename = f"T{track_num:02d}_{clean_title}.mp4"
    dest_path = SONGS_DIR / album_id / dest_filename
    
    # Save/update album entry (defaults to incomplete)
    db.add_album(album_id, album_name)
    
    # Initialize database entry as 'processing'
    db.add_or_update_song(song_id, {
        "album_id": album_id,
        "album_name": album_name,
        "track_number": track_num,
        "title": title,
        "artist": artist,
        "duration": 0.0,
        "file_path": "",
        "file_size": 0,
        "status": "processing"
    })
    
    with status_lock:
        job_status[song_id] = {
            "status": "pending",
            "progress": 0.0,
            "speed": "0x",
            "started_at": 0.0,
            "title": title,
            "artist": artist
        }
        
    # Put task details in the queue
    conversion_queue.put({
        "song_id": song_id,
        "src_path": src_path,
        "dest_path": str(dest_path),
        "album_id": album_id,
        "album_name": album_name,
        "track_num": track_num,
        "title": title,
        "artist": artist,
        "start_time": start_time,
        "end_time": end_time
    })
    
    return song_id

def get_job_statuses() -> dict:
    """Fetches a snapshot of current transcode queue statuses."""
    with status_lock:
        active_songs = [sid for sid, s in job_status.items() if s["status"] in ("pending", "processing")]
        completed_songs = [sid for sid, s in job_status.items() if s["status"] == "completed"]
        failed_songs = [sid for sid, s in job_status.items() if s["status"] == "failed"]
        
        return {
            "jobs": dict(job_status),
            "summary": {
                "active_count": len(active_songs),
                "completed_count": len(completed_songs),
                "failed_count": len(failed_songs),
                "queue_size": conversion_queue.qsize()
            }
        }
