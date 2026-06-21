import json
import threading
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from backend.config import DB_PATH, SONGS_DIR

class Database:
    def __init__(self):
        self.lock = threading.Lock()
        self.db_path = DB_PATH
        self._init_db()

    def _init_db(self):
        with self.lock:
            if not self.db_path.exists():
                self._save_data({"albums": {}, "songs": {}})

    def _load_data(self) -> dict:
        try:
            if self.db_path.exists():
                with open(self.db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading database: {e}")
        return {"albums": {}, "songs": {}}

    def _save_data(self, data: dict):
        try:
            # Write to a temporary file first, then swap to ensure atomic write
            temp_path = self.db_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.replace(self.db_path)
        except Exception as e:
            print(f"Error saving database: {e}")

    # Albums CRUD API
    def get_albums(self) -> List[dict]:
        with self.lock:
            data = self._load_data()
            return list(data.get("albums", {}).values())

    def get_album(self, album_id: str) -> Optional[dict]:
        with self.lock:
            data = self._load_data()
            return data.get("albums", {}).get(album_id)

    def add_album(self, album_id: str, name: str, status: str = "incomplete") -> dict:
        """Adds a new album if it doesn't exist, defaulting status to 'incomplete'."""
        with self.lock:
            data = self._load_data()
            if album_id not in data["albums"]:
                data["albums"][album_id] = {
                    "id": album_id,
                    "name": name,
                    "ingested_at": datetime.now().isoformat(),
                    "status": status
                }
                self._save_data(data)
            return data["albums"][album_id]

    def rename_album(self, album_id: str, new_name: str) -> bool:
        with self.lock:
            data = self._load_data()
            if album_id in data["albums"]:
                data["albums"][album_id]["name"] = new_name
                # Denormalize album_name in associated songs
                for song in data["songs"].values():
                    if song.get("album_id") == album_id:
                        song["album_name"] = new_name
                self._save_data(data)
                return True
            return False

    def update_album_status(self, album_id: str) -> bool:
        """
        Scans all songs in the album. If any song has a title starting with 'Track ' 
        or is empty/missing title/artist, the album is marked as 'incomplete'. 
        Otherwise, it is marked 'completed'.
        """
        with self.lock:
            data = self._load_data()
            if album_id not in data["albums"]:
                return False
            
            album_songs = [s for s in data["songs"].values() if s.get("album_id") == album_id]
            
            is_incomplete = False
            for song in album_songs:
                title = song.get("title", "").strip()
                artist = song.get("artist", "").strip()
                if not title or not artist or title.lower().startswith("track "):
                    is_incomplete = True
                    break
            
            new_status = "incomplete" if is_incomplete else "completed"
            if data["albums"][album_id].get("status") != new_status:
                data["albums"][album_id]["status"] = new_status
                self._save_data(data)
                return True
            return False

    def delete_album(self, album_id: str, delete_files: bool = True) -> bool:
        with self.lock:
            data = self._load_data()
            if album_id in data["albums"]:
                # Remove album record
                del data["albums"][album_id]
                
                # Delete associated songs
                song_ids_to_delete = [sid for sid, s in data["songs"].items() if s.get("album_id") == album_id]
                for sid in song_ids_to_delete:
                    song = data["songs"][sid]
                    if delete_files and "file_path" in song:
                        p = Path(song["file_path"])
                        # Resolve path relative to SONGS_DIR's parent (which is LIBRARY_DIR)
                        if not p.is_absolute():
                            p = SONGS_DIR.parent / p
                        try:
                            if p.exists():
                                p.unlink()
                        except Exception as e:
                            print(f"Failed to delete song file {p}: {e}")
                    del data["songs"][sid]
                
                # Clean up album folder in songs/
                album_dir = SONGS_DIR / album_id
                if album_dir.exists():
                    try:
                        shutil.rmtree(album_dir)
                    except Exception as e:
                        print(f"Failed to delete album directory {album_dir}: {e}")

                self._save_data(data)
                return True
            return False

    # Songs CRUD API
    def get_songs(self) -> List[dict]:
        with self.lock:
            data = self._load_data()
            songs = list(data.get("songs", {}).values())
            # Sort chronologically by creation/ingestion time
            songs.sort(key=lambda s: s.get("created_at", ""))
            return songs

    def get_songs_by_album(self, album_id: str) -> List[dict]:
        with self.lock:
            data = self._load_data()
            songs = [s for s in data.get("songs", {}).values() if s.get("album_id") == album_id]
            songs.sort(key=lambda s: s.get("track_number", 0))
            return songs

    def get_song(self, song_id: str) -> Optional[dict]:
        with self.lock:
            data = self._load_data()
            return data.get("songs", {}).get(song_id)

    def add_or_update_song(self, song_id: str, song_data: dict) -> dict:
        """Inserts or merges song details. Trigger status updates for the parent album."""
        with self.lock:
            data = self._load_data()
            existing = data["songs"].get(song_id, {})
            
            updated = {
                **existing,
                **song_data,
                "id": song_id,
                "updated_at": datetime.now().isoformat()
            }
            if "created_at" not in updated:
                updated["created_at"] = datetime.now().isoformat()
            
            data["songs"][song_id] = updated
            self._save_data(data)
            
        # Update album completion status outside the database write lock to avoid deadlock
        album_id = updated.get("album_id")
        if album_id:
            self.update_album_status(album_id)
            
        return updated

    def rename_song(self, song_id: str, title: str, artist: str) -> bool:
        """Renames a song, updates its title/artist info, and physically renames the file on disk."""
        import re
        with self.lock:
            data = self._load_data()
            if song_id not in data["songs"]:
                return False
                
            song = data["songs"][song_id]
            album_id = song.get("album_id")
            track_num = song.get("track_number", 1)
            old_rel_path = song.get("file_path")
            
            song["title"] = title.strip()
            song["artist"] = artist.strip()
            
            if old_rel_path and album_id:
                old_full_path = SONGS_DIR.parent / old_rel_path
                clean_title = re.sub(r'[\\/*?:"<>|]', "", title.strip()).strip()
                if not clean_title:
                    clean_title = f"Track_{track_num:02d}"
                dest_filename = f"T{track_num:02d}_{clean_title}.mp4"
                new_rel_path = f"songs/{album_id}/{dest_filename}"
                new_full_path = SONGS_DIR.parent / new_rel_path
                
                if old_full_path.exists() and old_full_path != new_full_path:
                    try:
                        new_full_path.parent.mkdir(parents=True, exist_ok=True)
                        if new_full_path.exists():
                            new_full_path.unlink()
                        old_full_path.rename(new_full_path)
                        song["file_path"] = new_rel_path
                    except Exception as e:
                        print(f"Error renaming physical file from {old_full_path} to {new_full_path}: {e}")
                else:
                    # Update file_path schema even if file hasn't been written yet
                    song["file_path"] = new_rel_path
                    
            self._save_data(data)
            
        if album_id:
            self.update_album_status(album_id)
        return True

    def delete_song(self, song_id: str, delete_file: bool = True) -> bool:
        with self.lock:
            data = self._load_data()
            if song_id in data["songs"]:
                song = data["songs"][song_id]
                album_id = song.get("album_id")
                
                # Delete file
                if delete_file and "file_path" in song:
                    p = Path(song["file_path"])
                    if not p.is_absolute():
                        p = SONGS_DIR.parent / p
                    try:
                        if p.exists():
                            p.unlink()
                    except Exception as e:
                        print(f"Failed to delete song file {p}: {e}")
                
                del data["songs"][song_id]
                self._save_data(data)
                
        if album_id:
            self.update_album_status(album_id)
        return True

    def delete_songs(self, song_ids: List[str], delete_file: bool = True) -> bool:
        album_ids_to_update = set()
        with self.lock:
            data = self._load_data()
            any_deleted = False
            for song_id in song_ids:
                if song_id in data["songs"]:
                    song = data["songs"][song_id]
                    album_id = song.get("album_id")
                    if album_id:
                        album_ids_to_update.add(album_id)
                    
                    # Delete file
                    if delete_file and "file_path" in song:
                        p = Path(song["file_path"])
                        if not p.is_absolute():
                            p = SONGS_DIR.parent / p
                        try:
                            if p.exists():
                                p.unlink()
                        except Exception as e:
                            print(f"Failed to delete song file {p}: {e}")
                    
                    del data["songs"][song_id]
                    any_deleted = True
            
            if any_deleted:
                self._save_data(data)
                
        for album_id in album_ids_to_update:
            self.update_album_status(album_id)
            
        return any_deleted

# Singleton database instance
db = Database()
