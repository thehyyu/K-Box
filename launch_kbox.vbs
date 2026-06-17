Set fso = CreateObject("Scripting.FileSystemObject")
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = ScriptDir

' 1. 清理 8080 端口以避免衝突 (靜音執行)
WshShell.Run "cmd.exe /c for /f ""tokens=5"" %a in ('netstat -aon ^| findstr 8080') do taskkill /F /PID %a 2>nul", 0, true

' 2. 在背景啟動 FastAPI 伺服器 (視窗隱藏 0, 不等待執行結束 false)
WshShell.Run "cmd.exe /c call .venv\Scripts\activate && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080", 0, false

' 3. 等待 2 秒讓伺服器啟動
WScript.Sleep 2000

' 4. 自動開啟預設瀏覽器進入點歌介面
WshShell.Run "cmd.exe /c start http://localhost:8080/", 0, false
