import os
from pathlib import Path
import pytest
from backend.database import Database

@pytest.fixture
def temp_db(tmp_path):
    """Fixture to create a temporary database in a safe testing sandbox."""
    db_file = tmp_path / "test_library.json"
    db_instance = Database()
    # Override properties for test isolation
    db_instance.db_path = db_file
    db_instance._init_db()
    return db_instance

def test_db_init(temp_db):
    """Ensure database initializes with empty lists/dicts."""
    assert temp_db.db_path.exists()
    data = temp_db._load_data()
    assert "albums" in data
    assert "songs" in data
    assert len(data["albums"]) == 0
    assert len(data["songs"]) == 0

def test_db_crud(temp_db):
    """Test Album & Song CRUD lifecycle with Japanese UTF-8 support."""
    album_id = "CD_20260616_TEST"
    album_name = "美空ひばり經典 Vol.1"
    
    # 1. Add Album (defaults to incomplete)
    album = temp_db.add_album(album_id, album_name)
    assert album["id"] == album_id
    assert album["name"] == album_name
    assert album["status"] == "incomplete"
    
    # 2. Add Song 1 (placeholder title)
    song_id_1 = f"{album_id}_T01"
    song_1 = temp_db.add_or_update_song(song_id_1, {
        "album_id": album_id,
        "album_name": album_name,
        "track_number": 1,
        "title": "Track 01", # Placeholder
        "artist": "",
        "status": "completed"
    })
    assert song_1["title"] == "Track 01"
    
    # Album status should still be incomplete
    updated_album = temp_db.get_album(album_id)
    assert updated_album["status"] == "incomplete"
    
    # 3. Add Song 2 (completed Japanese song details)
    song_id_2 = f"{album_id}_T02"
    song_2 = temp_db.add_or_update_song(song_id_2, {
        "album_id": album_id,
        "album_name": album_name,
        "track_number": 2,
        "title": "川の流れのように",
        "artist": "美空ひばり",
        "status": "completed"
    })
    assert song_2["title"] == "川の流れのように"
    assert song_2["artist"] == "美空ひばり"
    
    # 4. Rename Song 1 to proper Japanese song
    temp_db.rename_song(song_id_1, "悲しい酒", "美空ひばり")
    
    # Now all songs in the album have proper names & artists
    # The album status should automatically update to 'completed'
    updated_album = temp_db.get_album(album_id)
    assert updated_album["status"] == "completed"

    # 5. Retrieve items
    songs = temp_db.get_songs()
    assert len(songs) == 2
    assert songs[0]["title"] == "悲しい酒"
    
    songs_by_album = temp_db.get_songs_by_album(album_id)
    assert len(songs_by_album) == 2
    
    # 6. Delete Song
    temp_db.delete_song(song_id_1, delete_file=False)
    assert len(temp_db.get_songs()) == 1
    
    # 7. Delete Album
    temp_db.delete_album(album_id, delete_files=False)
    assert len(temp_db.get_albums()) == 0
    assert len(temp_db.get_songs()) == 0
