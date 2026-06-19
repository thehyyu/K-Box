import os
import shutil
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import BASE_DIR, FFMPEG_PATH, FFPROBE_PATH, LIBRARY_DIR, UPLOAD_DIR
from backend.database import db
from backend.scanner import detect_optical_drives, scan_drive_tracks
from backend.converter import add_transcode_job, get_job_statuses
from backend.exporter import get_usb_drives, start_export_task, get_export_status, generate_songbook_html

app = FastAPI(title="K-Box Karaoke Transfer System")

# Enable CORS for local cross-origin development (e.g. if testing frontend separately)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Request/Response Schemas
class ScanRequest(BaseModel):
    path: str

class TrackImportInfo(BaseModel):
    original_path: str
    track_number: int
    title: str
    artist: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None

class ImportRequest(BaseModel):
    tracks: List[TrackImportInfo]
    album_id: Optional[str] = None
    album_name: Optional[str] = None

class ExportRequest(BaseModel):
    song_ids: List[str]
    usb_path: str
    wipe_first: bool = False
    naming_strategy: str = "ktv_number"
    export_to_root: bool = True

class RenameSongRequest(BaseModel):
    title: str
    artist: str

# Endpoints
@app.get("/api/system-status")
def get_system_status():
    """Checks if FFmpeg/FFprobe binaries exist and returns environment configurations."""
    ffmpeg_ok = Path(FFMPEG_PATH).exists() or shutil_which_ok("ffmpeg")
    ffprobe_ok = Path(FFPROBE_PATH).exists() or shutil_which_ok("ffprobe")
    
    return {
        "ffmpeg_ok": ffmpeg_ok,
        "ffmpeg_path": FFMPEG_PATH,
        "ffprobe_ok": ffprobe_ok,
        "ffprobe_path": FFPROBE_PATH,
        "library_dir": str(LIBRARY_DIR),
        "os": os.name
    }

def shutil_which_ok(binary: str) -> bool:
    import shutil
    return shutil.which(binary) is not None

@app.get("/api/songs")
def get_songs():
    """Gets all songs registered in the K-Box library."""
    return db.get_songs()

@app.get("/api/albums")
def get_albums():
    """Gets all CD batch album sessions registered in the K-Box library."""
    return db.get_albums()

@app.get("/api/drives")
def get_optical_drives_endpoint():
    """Scans and lists active optical drive mount points on Windows / Mac."""
    try:
        drives = detect_optical_drives()
        return {"drives": drives}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed scanning optical drives: {e}")

@app.post("/api/scan")
def scan_directory(request: ScanRequest):
    """Scans the selected optical drive path or folder for tracks."""
    path = request.path.strip()
    if not path:
        raise HTTPException(status_code=400, detail="路徑不能為空")
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="找不到指定的路徑")
        
    try:
        tracks = scan_drive_tracks(path)
        return {"tracks": tracks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"掃描光碟失敗：{str(e)}")

@app.post("/api/import")
def import_tracks(request: ImportRequest):
    """
    Groups selected tracks into a timestamped CD batch and adds them 
    to the background transcode queue.
    """
    if not request.tracks:
        raise HTTPException(status_code=400, detail="未選擇任何歌曲進行匯入")
        
    # Auto-generate CD ID & Name from current timestamp if not provided
    now = datetime.now()
    album_id = request.album_id or f"CD_{now.strftime('%Y%m%d_%H%M')}"
    album_name = request.album_name or f"{now.strftime('%Y-%m-%d %H:%M')} 匯入的光碟"
    
    queued_ids = []
    for track in request.tracks:
        song_id = add_transcode_job(
            album_id=album_id,
            album_name=album_name,
            track_num=track.track_number,
            title=track.title,
            artist=track.artist,
            src_path=track.original_path,
            start_time=track.start_time,
            end_time=track.end_time
        )
        queued_ids.append(song_id)
        
    return {
        "album_id": album_id,
        "album_name": album_name,
        "song_ids": queued_ids,
        "message": f"已成功將 {len(queued_ids)} 首歌曲加入背景轉檔佇列。"
    }

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Uploads local video files (VOB, MPG, etc.) to the sandbox uploads directory.
    Returns basic file details, which frontend can use to let parents customize 
    titles/artists before importing.
    """
    if not files:
        raise HTTPException(status_code=400, detail="未選擇任何檔案")
        
    results = []
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    
    for idx, file in enumerate(files):
        filename = file.filename
        ext = Path(filename).suffix.lower()
        if ext not in {".vob", ".mpg", ".mpeg", ".avi", ".mp4", ".mkv", ".ts", ".dat"}:
            raise HTTPException(status_code=400, detail=f"不支援的檔案格式：{filename}")
            
        # Create safe and unique filename
        safe_filename = f"{timestamp}_{idx}_{filename}"
        save_path = UPLOAD_DIR / safe_filename
        
        # Save file to sandbox UPLOAD_DIR
        try:
            with save_path.open("wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"儲存上傳檔案失敗 {filename}: {str(e)}")
            
        # Retrieve basic info
        file_size = save_path.stat().st_size
        
        # Get duration using ffprobe if available
        from backend.converter import get_media_duration
        duration = get_media_duration(str(save_path))
        
        # Default title is the filename without extension
        default_title = Path(filename).stem
        
        results.append({
            "original_path": str(save_path),
            "filename": filename,
            "title": default_title,
            "artist": "",
            "duration": duration,
            "file_size": file_size
        })
        
    return {"files": results}

@app.get("/api/import/status")
def get_import_status():
    """Gets transcode progress percentages and queue worker summaries."""
    return get_job_statuses()

@app.get("/api/usb-drives")
def get_usbs():
    """Detects and returns all removable USB drives currently plugged in."""
    return get_usb_drives()

@app.post("/api/export")
def export_songs(request: ExportRequest):
    """Spawns background copy worker to sync selected K-Box songs to the USB."""
    if not request.song_ids:
        raise HTTPException(status_code=400, detail="匯出歌單不能為空")
    if not request.usb_path:
        raise HTTPException(status_code=400, detail="未指定隨身碟目的地路徑")
        
    success = start_export_task(
        song_ids=request.song_ids,
        usb_path=request.usb_path,
        wipe_first=request.wipe_first,
        naming_strategy=request.naming_strategy,
        export_to_root=request.export_to_root
    )
    
    if not success:
        raise HTTPException(status_code=409, detail="隨身碟同步任務正在執行中，請勿重複提交。")
        
    return {"message": "隨身碟複製任務已啟動。"}

@app.get("/api/export/status")
def get_copy_status():
    """Gets USB copying progress status details."""
    return get_export_status()

@app.post("/api/songs/{song_id}/rename")
def rename_song(song_id: str, request: RenameSongRequest):
    """Modifies the title and artist of an existing song in the library."""
    if not request.title.strip():
        raise HTTPException(status_code=400, detail="歌名不能為空")
        
    success = db.rename_song(song_id, request.title, request.artist)
    if not success:
        raise HTTPException(status_code=404, detail="找不到指定的歌曲")
    return {"message": "歌曲資訊更新成功"}

@app.delete("/api/songs/{song_id}")
def delete_song(song_id: str, delete_file: bool = True):
    """Deletes a song from the database and disk storage."""
    success = db.delete_song(song_id, delete_file)
    if not success:
        raise HTTPException(status_code=404, detail="找不到指定的歌曲")
    return {"message": "歌曲已成功刪除"}

@app.delete("/api/albums/{album_id}")
def delete_album(album_id: str, delete_files: bool = True):
    """Deletes an entire CD batch and its underlying media files."""
    success = db.delete_album(album_id, delete_files)
    if not success:
        raise HTTPException(status_code=404, detail="找不到指定的光碟批次")
    return {"message": "整張光碟記錄與轉檔檔案已刪除"}

@app.get("/songbook", response_class=HTMLResponse)
def get_songbook_page(
    song_ids: str = Query(..., description="Comma-separated song IDs to print"),
    naming_strategy: str = "ktv_number"
):
    """Renders printable dual-column HTML KTV Songbook page."""
    ids = [sid.strip() for sid in song_ids.split(",") if sid.strip()]
    if not ids:
        return "<html><body><h1>錯誤：未選擇任何歌曲</h1></body></html>"
    return generate_songbook_html(ids, naming_strategy)

# Mount frontend files (index.html, style.css, app.js)
frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
else:
    print(f"Warning: frontend directory {frontend_dir} not found. Serve API only.")
