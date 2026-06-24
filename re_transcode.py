#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil
from pathlib import Path

# Add project root to sys.path so we can import backend modules
sys.path.append(str(Path(__file__).resolve().parent))

try:
    from backend.config import FFMPEG_PATH, FFPROBE_PATH, LIBRARY_DIR, SONGS_DIR
    from backend.database import db
except ImportError as e:
    print(f"Error: Unable to import backend modules. Make sure you run this script from the project root directory. {e}")
    sys.exit(1)

def run_cmd(cmd):
    """Run a shell command and return stdout as string."""
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", startupinfo=startupinfo)
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def check_compatibility(file_path: Path):
    """
    Checks if the video is already in high compatibility AVI format:
    - Suffix == .avi
    - Width == 720
    - Height == 480
    - Video Codec == mpeg4
    - Audio Codec == mp3
    """
    if not file_path.exists():
        return False, "File does not exist"

    if file_path.suffix.lower() != ".avi":
        return False, f"File format is {file_path.suffix} instead of .avi"

    # Query video properties
    cmd_v = [
        FFPROBE_PATH, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name",
        "-of", "csv=p=0",
        str(file_path)
    ]
    code_v, out_v, _ = run_cmd(cmd_v)
    if code_v != 0 or not out_v:
        return False, "Failed to probe video stream"

    parts = out_v.split(',')
    if len(parts) < 3:
        return False, f"Unexpected video probe output: {out_v}"

    try:
        width = int(parts[0])
        height = int(parts[1])
        video_codec = parts[2].strip().lower()
    except ValueError:
        return False, f"Invalid values in probe: {out_v}"

    # Query audio codec
    cmd_a = [
        FFPROBE_PATH, "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "csv=p=0",
        str(file_path)
    ]
    code_a, out_a, _ = run_cmd(cmd_a)
    if code_a != 0:
        return False, "Failed to probe audio stream"
    
    audio_codec = out_a.strip().lower()

    # mpeg4 (Xvid/Divx) or msmpeg4/divx etc.
    is_compatible = (width == 720 and height == 480 and "mpeg4" in video_codec and audio_codec == "mp3")
    status_msg = f"Resolution: {width}x{height}, Video Codec: {video_codec}, Audio: {audio_codec}"
    
    return is_compatible, status_msg

def re_transcode_song(song_id: str, file_path: Path):
    """Re-transcode the song file to highly compatible AVI format in-place."""
    temp_old_path = file_path.with_suffix(f".old_format{file_path.suffix}")
    new_dest_path = file_path.with_suffix(".avi")
    
    try:
        # Rename original to temporary path
        shutil.move(file_path, temp_old_path)
        
        # Build FFmpeg command to re-encode to AVI (MPEG-4/Xvid with MP3 audio)
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", str(temp_old_path),
            "-c:v", "mpeg4",
            "-vtag", "XVID",
            "-qscale:v", "5",
            "-vf", "scale=720:480:force_original_aspect_ratio=decrease,scale=w='2*trunc(iw/2)':h='2*trunc(ih/2)',setsar=1,pad=720:480:(ow-iw)/2:(oh-ih)/2",
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            str(new_dest_path)
        ]
        
        print(f"[{song_id}] Re-encoding video to AVI...")
        code, stdout, stderr = run_cmd(cmd)
        
        if code == 0 and new_dest_path.exists():
            # Success! Remove backup file
            temp_old_path.unlink()
            
            # Update file size and duration in the database
            file_size = new_dest_path.stat().st_size
            
            # Probe new duration
            cmd_dur = [
                FFPROBE_PATH, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(new_dest_path)
            ]
            _, out_dur, _ = run_cmd(cmd_dur)
            try:
                duration = float(out_dur)
            except ValueError:
                duration = 0.0
                
            # Update db
            song_data = db.get_song(song_id)
            if song_data:
                song_data["file_size"] = file_size
                if duration > 0:
                    song_data["duration"] = duration
                # Update relative path to the new AVI extension
                song_data["file_path"] = str(Path(song_data["file_path"]).with_suffix(".avi").as_posix())
                db.add_or_update_song(song_id, song_data)
                
            print(f"[{song_id}] Success! File size: {file_size / 1024 / 1024:.2f} MB")
            return True
        else:
            print(f"[{song_id}] FFmpeg failed with exit code {code}.")
            print(f"Error output: {stderr}")
            # Restore original file on failure
            if temp_old_path.exists():
                if new_dest_path.exists():
                    new_dest_path.unlink()
                # Restore original path
                shutil.move(temp_old_path, file_path)
            return False
            
    except Exception as e:
        print(f"[{song_id}] Exception during re-transcoding: {e}")
        # Restore original file if possible
        if temp_old_path.exists() and not file_path.exists() and not new_dest_path.exists():
            try:
                shutil.move(temp_old_path, file_path)
            except Exception:
                pass
        return False

def main():
    print("=" * 60)
    print(" 💿 K-Box 曲庫就地相容性重新轉檔工具 (AVI 格式)")
    print(f" 曲庫路徑: {LIBRARY_DIR}")
    print("=" * 60)
    
    songs = db.get_songs()
    completed_songs = [s for s in songs if s.get("status") == "completed"]
    
    if not completed_songs:
        print("曲庫中沒有已完成轉檔的歌曲。")
        return
        
    print(f"找到 {len(completed_songs)} 首已完成轉檔的歌曲。正在進行相容性檢查...")
    
    to_process = []
    
    for song in completed_songs:
        song_id = song["id"]
        rel_path = song.get("file_path")
        if not rel_path:
            continue
            
        file_path = SONGS_DIR.parent / rel_path
        if not file_path.exists():
            print(f"⚠️  檔案不存在: {file_path}")
            continue
            
        is_ok, details = check_compatibility(file_path)
        if is_ok:
            print(f"✅ [{song_id}] 相容於老舊播放器: {song['title']} ({details})")
        else:
            print(f"🔄 [{song_id}] 需要重新轉檔: {song['title']} ({details})")
            to_process.append((song_id, file_path))
            
    if not to_process:
        print("\n🎉 所有歌曲皆已符合高相容規格，無須進行任何重新轉檔！")
        return
        
    print(f"\n共有 {len(to_process)} 首歌曲需要重新轉檔。")
    confirm = input("是否開始進行就地轉檔？ (y/N): ").strip().lower()
    if confirm != 'y':
        print("已取消作業。")
        return
        
    success_count = 0
    for idx, (song_id, file_path) in enumerate(to_process):
        print(f"\n[{idx + 1}/{len(to_process)}] 正在處理 {file_path.name}...")
        if re_transcode_song(song_id, file_path):
            success_count += 1
            
    print("\n" + "=" * 60)
    print(f"🎉 重新轉檔作業完成！成功: {success_count}/{len(to_process)}")
    print("現在您可以開啟 K-Box Web 介面，插入隨身碟，重新匯出所有歌曲！")
    print("=" * 60)

if __name__ == "__main__":
    main()
