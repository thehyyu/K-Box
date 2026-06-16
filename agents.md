# 💿 K-Box Agent 實作規劃書

## 目標
建立一個專為 Windows 環境設計的本地端 Web 應用程式 (FastAPI + Vanilla JS)，協助父母進行卡拉OK伴唱 VCD/DVD 的**選擇性轉檔建庫**、**隨身碟順序對齊同步（外部歌曲收編）**以及**專屬 A4 點歌本列印**。

---

## 🛡️ 設計與安全原則 (Principles)
1. **安全沙盒 (Sandbox Safety)**：
   * 所有曲庫讀寫操作嚴格限定在行動硬碟的 `K-Box_Library/` 目錄。
   * 所有隨身碟操作嚴格限定在隨身碟的 `K-Box_Songs/` 目錄，深度重整時僅清空該目錄，絕不影響隨身碟與行動硬碟內的其他個人重要資料。
2. **阿嬤友善介面 (Elderly Friendly)**：
   * 大字體、高對比度、少層級、大按鈕。
   * 免手動命名光碟：自動以時間戳（`CD_YYYYMMDD_HHMM`）代稱 CD。
   * 免打字先建庫：允許歌名留空（以 `Track XX` 代替），由子女事後補齊。
3. **DVD 相容分割 (DVD Chapters Autocut)**：
   * 自動以 `ffprobe` 解析連續型 DVD 影片的章節，並使用 `ffmpeg` 精準分割轉檔。
4. **硬體排序相容性 (Hardware DVD player compatibility)**：
   * 隨身碟複製一律依 KTV 編號單執行緒**循序複製**。
   * 複製後自動使用 `os.utime()` **修改時間戳**成等差遞增。
   * 提供「深度重整（一鍵清空隨身碟專屬目錄並循序重寫）」功能。
5. **日語相容性 (Japanese UTF-8 support)**：
   * 資料庫、網頁與點歌本字型全面支援日文字元（漢字、平/片假名），不缺字。

---

## 📂 專案架構 (Project Structure)
```
K-Box/
├── backend/
│   ├── bin/                # 存放 ffmpeg.exe & ffprobe.exe
│   ├── config.py           # 行動硬碟路徑、FFmpeg 路徑與安全目錄定義
│   ├── database.py         # library.json 的 CRUD 執行器
│   ├── scanner.py          # Windows 光碟機掃描、DAT/VOB 偵測、DVD 章節解析
│   ├── converter.py        # 背景 FFmpeg 轉檔 queue 運作、即時進度解析
│   ├── exporter.py         # USB 偵測、循序寫入與時間戳重置、HTML 點歌本生成
│   └── main.py             # FastAPI 路由、靜態檔案掛載與 API 進入點
├── frontend/
│   ├── index.html          # SPA 主網頁（大字體、高對比、玻璃擬物化風格）
│   ├── style.css           # 專屬 CSS（無 Tailwind，純 CSS 設計系統）
│   └── app.js              # Vanilla JS 狀態管理器與 API 呼叫器
├── requirements.txt        # python 相容套件
└── 啟動K-Box.bat            # Windows 一鍵啟動腳本
```

---

## 🧪 TDD 與功能驗證計畫 (TDD & Verification Plan)

在實作前端前，必須先建立單元測試並對後端核心功能進行驗證：

| 測試模組 | 驗證內容 |
|----------|----------|
| `test_config_paths` | 驗證能正確偵測本機 `backend/bin/` 下的 FFmpeg，且預設曲庫資料夾能正確指向行動硬碟。 |
| `test_db_crud` | 驗證 `library.json` 的建立、寫入，特別是日文字元 (UTF-8) 讀寫與 `status="incomplete"` 的專輯標記。 |
| `test_windows_drive_scan` | 模擬 Windows 系統，驗證能正確識別 `CDROM` 槽位，並掃描出 `.DAT` 及 `.VOB` 檔案。 |
| `test_dvd_chapter_probe` | 使用 Mock 模擬 `ffprobe` 輸出，驗證能正確解析 DVD 章節的開始與結束時間。 |
| `test_ffmpeg_progress_parse` | 驗證轉換執行器能正確解析 FFmpeg 的 `out_time_ms` 並轉換為實時百分比進度。 |
| `test_usb_detector` | 驗證 `psutil` 能在 Windows 下正確識別 Removable USB 隨身碟及其掛載路徑。 |
| `test_sequential_copy_and_utime` | 驗證寫入 USB 時是依序進行，且寫入後檔案的修改時間 (mtime) 呈現嚴格等差遞增。 |

---

## 📝 實作待辦清單 (Todo List)

### 1. 專案基礎骨架
- [x] 撰寫 `requirements.txt`
- [x] 建立 `backend/config.py` 設定檔管理與 FFmpeg 自動探針
- [x] 建立 `backend/database.py` 支援 UTF-8 的 JSON 資料庫

### 2. 【第一階段】掃描與轉檔核心 (Scanner & Converter)
- [x] 實作 `backend/scanner.py`（Windows 光碟偵測、DVD 章節 `ffprobe` 解析）
- [x] 實作 `backend/converter.py`（背景 FFmpeg 轉檔任務隊列、進度條解析器）
- [x] 實作建庫模式對應的 API 路由 (`/api/scan`, `/api/import`, `/api/import/status`)

### 3. 【第二階段】隨身碟同步與重整核心 (Exporter)
- [x] 實作 `backend/exporter.py`：Windows USB 隨身碟掃描、既有舊歌分類
- [x] 實作 USB 寫入邏輯：**單執行緒依序複製**、**`os.utime()` 修改時間戳**
- [x] 實作 USB「深度重整（清空隨身碟專屬目錄並循序重寫）」機制
- [x] 實作 HTML 雙欄 KTV 點歌本生成器（支援中日雙語字型）
- [x] 實作匯出模式對應的 API 路由 (`/api/usb-drives`, `/api/export`, `/api/export/status`, `/songbook`)

### 4. 前端 UI 實作
- [ ] 建立 `frontend/style.css`：設計大字體、簡潔高對比度且具質感的玻璃擬物化風格 (Vanilla CSS)
- [ ] 建立 `frontend/index.html`：整合建庫模式、整理模式、匯出模式三大頁面
- [ ] 建立 `frontend/app.js`：實作資料綁定與實時 API 更新、LocalStorage 暫存區
- [ ] 撰寫 Windows 啟動腳本 `啟動K-Box.bat`
