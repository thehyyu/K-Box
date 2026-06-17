// K-Box Global Application State Manager
const API_BASE = ""; // Relative URL, since it's hosted from the same FastAPI server

// Active state caches
let currentTab = "import-tab";
let scannedTracks = [];
let librarySongs = [];
let libraryAlbums = [];
let activeFilter = "all";

// Pollers intervals
let importPoller = null;
let exportPoller = null;

// Page Initializer
document.addEventListener("DOMContentLoaded", () => {
    checkSystemStatus();
    detectDrives();
    detectUSBs();
    loadLibrary();
    
    // Auto-refresh USB lists and Library every 10 seconds silently
    setInterval(detectUSBs, 10000);
    setInterval(checkSystemStatus, 10000);
});

// Tab Switcher
function switchTab(tabId, el) {
    // Update Sidebar Navigation highlights
    document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active"));
    el.classList.add("active");
    
    // Switch panels
    document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.remove("active"));
    const activePanel = document.getElementById(tabId);
    activePanel.classList.add("active");
    
    currentTab = tabId;
    
    // Specific tab activations
    if (tabId === "library-tab") {
        loadLibrary();
    } else if (tabId === "export-tab") {
        loadLibrary(); // Reload songs list for exporting
        detectUSBs();
    }
}

// ----------------------------------------------------
// SYSTEM STATUS ENGINE
// ----------------------------------------------------
async function checkSystemStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/system-status`);
        if (!response.ok) throw new Error("API Offline");
        const status = await response.json();
        
        const dot = document.getElementById("sys-dot");
        const text = document.getElementById("sys-text");
        
        if (status.ffmpeg_ok && status.ffprobe_ok) {
            dot.className = "sys-dot ok";
            text.textContent = "曲庫 & FFmpeg 偵測正常";
        } else {
            dot.className = "sys-dot error";
            text.textContent = "警告: 找不到 FFmpeg 執行檔";
        }
    } catch (err) {
        const dot = document.getElementById("sys-dot");
        const text = document.getElementById("sys-text");
        dot.className = "sys-dot error";
        text.textContent = "連線後端失敗";
    }
}

// ----------------------------------------------------
// TAB 1: IMPORT CD MODE
// ----------------------------------------------------
async function detectDrives() {
    try {
        const select = document.getElementById("drive-select");
        select.innerHTML = '<option value="">-- 正在偵測光碟槽 --</option>';
        
        const response = await fetch(`${API_BASE}/api/drives`);
        const data = await response.json();
        
        select.innerHTML = "";
        if (!data.drives || data.drives.length === 0) {
            select.innerHTML = '<option value="">-- 未偵測到光碟機 --</option>';
            return;
        }
        
        data.drives.forEach(drive => {
            const opt = document.createElement("option");
            opt.value = drive;
            opt.textContent = drive;
            select.appendChild(opt);
        });
    } catch (err) {
        console.error("Failed to detect drives:", err);
    }
}

async function scanDrive() {
    const drivePath = document.getElementById("drive-select").value;
    if (!drivePath) {
        alert("請先選擇光碟槽！");
        return;
    }
    
    const card = document.getElementById("tracks-card");
    const tbody = document.getElementById("tracks-table-body");
    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 30px;">🔍 正在掃描光碟影音軌，請稍候...</td></tr>';
    card.style.display = "block";
    
    try {
        const response = await fetch(`${API_BASE}/api/scan`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: drivePath })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || "掃描失敗");
        }
        
        const data = await response.json();
        scannedTracks = data.tracks || [];
        
        renderScannedTracks();
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--danger); padding: 30px;">❌ 掃描失敗: ${err.message}</td></tr>`;
    }
}

function renderScannedTracks() {
    const tbody = document.getElementById("tracks-table-body");
    const selectAll = document.getElementById("select-all-tracks");
    selectAll.checked = true; // Default to select all
    
    if (scannedTracks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 30px; color: var(--text-muted);">光碟中沒有符合的歌曲檔案。</td></tr>';
        return;
    }
    
    tbody.innerHTML = "";
    scannedTracks.forEach((track, index) => {
        const tr = document.createElement("tr");
        
        // Formulate suggested name (defaults to blank, elder-friendly placeholders)
        const formatLabel = track.type === "DVD_CHAPTER" ? `DVD 章節 (${track.start_time}s - ${track.end_time}s)` : track.type;
        const sizeMb = (track.file_size / (1024 * 1024)).toFixed(1);
        
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="custom-checkbox track-row-check" value="${index}" checked onchange="updateSelectAllTracksHeader()">
            </td>
            <td style="font-weight: bold;"># ${track.track_number}</td>
            <td>
                <div style="font-size: var(--font-size-body); font-weight: bold; margin-bottom: 4px;">${track.filename}</div>
                <div style="font-size: var(--font-size-small); color: var(--text-muted);">${sizeMb} MB</div>
            </td>
            <td>
                <span class="status-badge status-completed" style="font-size: var(--font-size-small);">${formatLabel}</span>
            </td>
            <td>
                <input type="text" class="form-control track-title-input" 
                       placeholder="歌名 - 歌手 (例如: 川の流れのように - 美空ひばり)" 
                       style="font-size: 16px;" value="">
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function toggleSelectAllTracks(master) {
    document.querySelectorAll(".track-row-check").forEach(chk => chk.checked = master.checked);
}

function updateSelectAllTracksHeader() {
    const checks = document.querySelectorAll(".track-row-check");
    const checked = document.querySelectorAll(".track-row-check:checked");
    document.getElementById("select-all-tracks").checked = checks.length === checked.length;
}

// Ingestion triggers
async function importSelectedTracks() {
    const checkedBoxes = document.querySelectorAll(".track-row-check:checked");
    if (checkedBoxes.length === 0) {
        alert("請至少選擇一首歌曲進行轉檔！");
        return;
    }
    
    const tracksToImport = [];
    checkedBoxes.forEach(box => {
        const index = parseInt(box.value);
        const track = scannedTracks[index];
        
        // Fetch matching title input row
        const row = box.closest("tr");
        const rawInput = row.querySelector(".track-title-input").value.trim();
        
        // Parse Title & Artist from format "Title - Artist" or default to Track placeholder
        let title = `Track ${track.track_number.toString().padStart(2, '0')}`;
        let artist = "";
        
        if (rawInput) {
            const parts = rawInput.split("-");
            if (parts.length >= 2) {
                title = parts[0].trim();
                artist = parts.slice(1).join("-").trim();
            } else {
                title = rawInput;
            }
        }
        
        tracksToImport.push({
            original_path: track.original_path,
            track_number: track.track_number,
            title: title,
            artist: artist,
            start_time: track.start_time,
            end_time: track.end_time
        });
    });
    
    try {
        const response = await fetch(`${API_BASE}/api/import`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tracks: tracksToImport })
        });
        
        if (!response.ok) throw new Error("匯入佇列失敗");
        
        const data = await response.json();
        alert(data.message);
        
        // Reset scanned listing card
        document.getElementById("tracks-card").style.display = "none";
        scannedTracks = [];
        
        // Open/trigger transcode queue monitoring
        startQueuePolling();
    } catch (err) {
        alert(`匯入出錯: ${err.message}`);
    }
}

// Queue Monitor Polling
function startQueuePolling() {
    document.getElementById("queue-empty-state").style.display = "none";
    document.getElementById("queue-monitor").style.display = "block";
    
    if (importPoller) clearInterval(importPoller);
    pollQueueOnce(); // Immediate call
    importPoller = setInterval(pollQueueOnce, 1000); // Polling every 1s
}

async function pollQueueOnce() {
    try {
        const response = await fetch(`${API_BASE}/api/import/status`);
        if (!response.ok) return;
        const status = await response.json();
        
        const summary = status.summary;
        const jobs = status.jobs;
        
        // Update summaries
        document.getElementById("queue-summary-active").textContent = `待處理: ${summary.queue_size + summary.active_count} 首`;
        document.getElementById("queue-summary-completed").textContent = `已完成: ${summary.completed_count} 首`;
        document.getElementById("queue-summary-failed").textContent = `失敗: ${summary.failed_count} 首`;
        
        // Find if there is an active job running
        let activeJobId = null;
        let activeJob = null;
        for (const [jid, job] of Object.entries(jobs)) {
            if (job.status === "processing") {
                activeJobId = jid;
                activeJob = job;
                break;
            }
        }
        
        if (activeJob) {
            document.getElementById("active-track-name").textContent = `正在轉檔: ${activeJob.title} (${activeJob.artist || "未知歌手"})`;
            document.getElementById("active-track-speed").textContent = `速度: ${activeJob.speed || "0x"}`;
            const pct = Math.round(activeJob.progress * 100);
            document.getElementById("active-track-percent").textContent = `${pct}%`;
            document.getElementById("active-track-progress-bar").style.width = `${pct}%`;
            document.getElementById("active-track-progress-text").textContent = `${pct}%`;
        } else {
            document.getElementById("active-track-name").textContent = "正在等待任務...";
            document.getElementById("active-track-speed").textContent = "速度: 0x";
            document.getElementById("active-track-percent").textContent = "0%";
            document.getElementById("active-track-progress-bar").style.width = "0%";
            document.getElementById("active-track-progress-text").textContent = "0%";
        }
        
        // Render queue list items (excluding completed/failed to keep clean, or show with badges)
        const qlist = document.getElementById("queue-list");
        qlist.innerHTML = "";
        
        // Sort jobs: show processing first, then pending, then failed
        const sortedJobs = Object.entries(jobs).sort((a, b) => {
            const order = { "processing": 0, "pending": 1, "failed": 2, "completed": 3 };
            return (order[a[1].status] ?? 4) - (order[b[1].status] ?? 4);
        });
        
        sortedJobs.forEach(([jid, job]) => {
            if (job.status === "completed") return; // Skip completed to save GUI noise
            const div = document.createElement("div");
            div.style.background = "rgba(255,255,255,0.03)";
            div.style.padding = "10px 14px";
            div.style.borderRadius = "8px";
            div.style.display = "flex";
            div.style.justify = "space-between";
            div.style.alignItems = "center";
            div.style.border = "1px solid var(--border-color)";
            
            let badgeClass = "status-incomplete";
            let statusName = "等待中";
            if (job.status === "processing") {
                badgeClass = "status-processing";
                statusName = "轉檔中";
            } else if (job.status === "failed") {
                badgeClass = "status-failed";
                statusName = "失敗";
            }
            
            div.innerHTML = `
                <div style="font-size: var(--font-size-small); font-weight: bold; max-width: 70%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    ${job.title}
                </div>
                <span class="status-badge ${badgeClass}" style="padding: 3px 8px; font-size: 12px;">${statusName}</span>
            `;
            qlist.appendChild(div);
        });
        
        // Stop poller if everything is completed or failed
        if (summary.active_count === 0 && summary.queue_size === 0) {
            clearInterval(importPoller);
            importPoller = null;
            
            // Reload Library list in Tab 2 silently
            loadLibrary();
            
            // Play success chime or sound if finished successfully
            if (summary.completed_count > 0 && summary.failed_count === 0) {
                try {
                    const audio = new Audio("https://actions.google.com/sounds/v1/alarms/digital_watch_alarm_long.ogg");
                    audio.volume = 0.3;
                    audio.play();
                } catch(e) {}
                alert("🎉 光碟選定歌曲已全部轉檔完成！您可以取出光碟並放入下一張。");
                
                // Clear monitor block back to idle
                document.getElementById("queue-empty-state").style.display = "block";
                document.getElementById("queue-monitor").style.display = "none";
            }
        }
    } catch (err) {
        console.error("Polling queue error:", err);
    }
}

// ----------------------------------------------------
// TAB 2: LIBRARY MANAGE MODE
// ----------------------------------------------------
async function loadLibrary() {
    try {
        const resSongs = await fetch(`${API_BASE}/api/songs`);
        librarySongs = await resSongs.json();
        
        const resAlbums = await fetch(`${API_BASE}/api/albums`);
        libraryAlbums = await resAlbums.json();
        
        // Update total stats
        document.getElementById("library-total-count").textContent = librarySongs.length;
        
        // Count incomplete (needs to fill in names)
        const incompleteCount = librarySongs.filter(s => {
            const title = s.title.trim().toLowerCase();
            return !title || title.startsWith("track ") || !s.artist;
        }).length;
        document.getElementById("incomplete-count").textContent = incompleteCount;
        
        renderLibraryTable();
        renderExportTable();
    } catch (err) {
        console.error("Failed loading library:", err);
    }
}

function filterLibrary(filterType) {
    activeFilter = filterType;
    document.getElementById("filter-all-btn").className = filterType === "all" ? "btn btn-secondary active" : "btn btn-secondary";
    document.getElementById("filter-incomplete-btn").className = filterType === "incomplete" ? "btn btn-secondary active" : "btn btn-secondary";
    
    renderLibraryTable();
}

function renderLibraryTable() {
    const tbody = document.getElementById("library-table-body");
    tbody.innerHTML = "";
    
    // Filter list
    let list = librarySongs;
    if (activeFilter === "incomplete") {
        list = librarySongs.filter(s => {
            const title = s.title.trim().toLowerCase();
            return !title || title.startsWith("track ") || !s.artist;
        });
    }
    
    if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: var(--text-muted);">庫內無符合篩選條件的歌曲。</td></tr>';
        return;
    }
    
    list.forEach(song => {
        const tr = document.createElement("tr");
        tr.id = `lib-row-${song.id}`;
        
        const formatTime = (sec) => {
            const m = Math.floor(sec / 60);
            const s = Math.round(sec % 60);
            return `${m}:${s.toString().padStart(2, '0')}`;
        };
        
        const isSongIncomplete = !song.title || song.title.toLowerCase().startsWith("track ") || !song.artist;
        const statusBadge = isSongIncomplete 
            ? '<span class="status-badge status-incomplete">⚠️ 待補歌手/歌名</span>' 
            : '<span class="status-badge status-completed">🟢 歌手歌名完整</span>';
            
        const formattedDate = song.created_at ? song.created_at.slice(0, 16).replace("T", " ") : "--";
        
        tr.innerHTML = `
            <td>${statusBadge}</td>
            <td style="color: var(--text-muted); font-size: var(--font-size-small);">${formattedDate}</td>
            <td style="font-weight: bold; font-size: 20px;" class="cell-title">${song.title}</td>
            <td class="cell-artist">${song.artist || '<span style="color: var(--danger);">未填寫</span>'}</td>
            <td>${formatTime(song.duration)}</td>
            <td style="text-align: center;">
                <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" 
                        onclick="enterEditMode('${song.id}', '${song.title.replace(/'/g, "\\'")}', '${(song.artist || "").replace(/'/g, "\\'")}')">
                    ✏️ 編輯
                </button>
                <button class="btn btn-danger" style="padding: 8px 16px; font-size: 14px;" 
                        onclick="deleteSong('${song.id}')">
                    🗑️ 刪除
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// Inline Editing functions
function enterEditMode(songId, title, artist) {
    const tr = document.getElementById(`lib-row-${songId}`);
    
    const titleCell = tr.querySelector(".cell-title");
    const artistCell = tr.querySelector(".cell-artist");
    
    // Cache original content in case they cancel
    tr.dataset.oldTitle = title;
    tr.dataset.oldArtist = artist;
    
    // Inject inputs inline
    titleCell.innerHTML = `<input type="text" class="form-control edit-input-title" value="${title}" style="padding: 8px 12px; font-size: 18px;">`;
    artistCell.innerHTML = `<input type="text" class="form-control edit-input-artist" value="${artist}" placeholder="請輸入歌手" style="padding: 8px 12px; font-size: 18px;">`;
    
    // Replace buttons
    const actionsCell = tr.querySelector("td:last-child");
    actionsCell.innerHTML = `
        <button class="btn btn-primary" style="padding: 8px 16px; font-size: 14px; background: var(--success);" onclick="saveEdit('${songId}')">💾 儲存</button>
        <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="cancelEdit('${songId}')">❌ 取消</button>
    `;
}

async function saveEdit(songId) {
    const tr = document.getElementById(`lib-row-${songId}`);
    const newTitle = tr.querySelector(".edit-input-title").value.trim();
    const newArtist = tr.querySelector(".edit-input-artist").value.trim();
    
    if (!newTitle) {
        alert("歌名不能為空！");
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/songs/${songId}/rename`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: newTitle, artist: newArtist })
        });
        
        if (!response.ok) throw new Error("儲存修改失敗");
        
        // Reload library list
        loadLibrary();
    } catch (err) {
        alert(err.message);
    }
}

function cancelEdit(songId) {
    loadLibrary(); // Quick lazy reload resets row structure completely
}

async function deleteSong(songId) {
    if (!confirm("⚠️ 確定要從您的行動硬碟庫中刪除這首歌嗎？檔案將會被永久移除！")) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/songs/${songId}?delete_file=true`, {
            method: "DELETE"
        });
        if (!response.ok) throw new Error("刪除失敗");
        loadLibrary();
    } catch (err) {
        alert(err.message);
    }
}

// ----------------------------------------------------
// TAB 3: EXPORT USB MODE
// ----------------------------------------------------
async function detectUSBs() {
    try {
        const select = document.getElementById("usb-select");
        const prevVal = select.value;
        select.innerHTML = '<option value="">-- 正在偵測隨身碟 --</option>';
        
        const response = await fetch(`${API_BASE}/api/usb-drives`);
        const drives = await response.json();
        
        select.innerHTML = "";
        if (drives.length === 0) {
            select.innerHTML = '<option value="">-- 未偵測到隨身碟 --</option>';
            return;
        }
        
        drives.forEach(drive => {
            const opt = document.createElement("option");
            opt.value = drive.path;
            const freeGb = (drive.free_space / (1024 * 1024 * 1024)).toFixed(1);
            opt.textContent = `${drive.name} (剩餘空間: ${freeGb} GB)`;
            select.appendChild(opt);
        });
        
        if (prevVal) select.value = prevVal;
    } catch (err) {
        console.error("USB detection error:", err);
    }
}

function renderExportTable() {
    const tbody = document.getElementById("export-table-body");
    tbody.innerHTML = "";
    
    if (librarySongs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 30px; color: var(--text-muted);">精選曲庫內沒有歌曲，請先從光碟匯入。</td></tr>';
        return;
    }
    
    librarySongs.forEach(song => {
        const tr = document.createElement("tr");
        
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="custom-checkbox export-row-check" value="${song.id}" checked onchange="updateSelectAllExportHeader()">
            </td>
            <td style="font-weight: bold; font-size: 18px;">${song.title}</td>
            <td>${song.artist || '<span style="color: var(--danger); font-size: var(--font-size-small);">未填寫</span>'}</td>
            <td style="color: var(--text-muted); font-size: var(--font-size-small);">${song.album_name}</td>
        `;
        tbody.appendChild(tr);
    });
    
    document.getElementById("select-all-export").checked = true; // Default select all
}

function toggleSelectAllExport(master) {
    document.querySelectorAll(".export-row-check").forEach(chk => chk.checked = master.checked);
}

function updateSelectAllExportHeader() {
    const checks = document.querySelectorAll(".export-row-check");
    const checked = document.querySelectorAll(".export-row-check:checked");
    document.getElementById("select-all-export").checked = checks.length === checked.length;
}

// USB Sync Initiator
async function startUSBSync() {
    const usbPath = document.getElementById("usb-select").value;
    if (!usbPath) {
        alert("請選擇目標隨身碟！");
        return;
    }
    
    const checkedBoxes = document.querySelectorAll(".export-row-check:checked");
    if (checkedBoxes.length === 0) {
        alert("請至少選擇一首歌曲進行隨身碟匯出！");
        return;
    }
    
    const songIds = Array.from(checkedBoxes).map(box => box.value);
    
    // Strategy and Wiping details
    const namingStrategy = document.getElementById("naming-strategy-select").value;
    const syncRadios = document.getElementsByName("sync-type");
    let wipeFirst = false;
    for (const radio of syncRadios) {
        if (radio.checked && radio.value === "deep") {
            wipeFirst = true;
            break;
        }
    }
    const exportToRoot = document.getElementById("export-root-checkbox").checked;
    
    if (wipeFirst) {
        const warningMsg = exportToRoot
            ? "⚠️ 警告: 您選擇了【深度重整】隨身碟。\n這會清理隨身碟根目錄下所有符合 K-Box 命名規則的舊歌曲，但絕對不會刪除您的其他照片或文件。\n請問要繼續嗎？"
            : "⚠️ 警告: 您選擇了【深度重整】隨身碟。\n這會清空隨身碟內的 K-Box_Songs 資料夾並重新循序寫入。\n請問要繼續嗎？";
        if (!confirm(warningMsg)) {
            return;
        }
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/export`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                song_ids: songIds,
                usb_path: usbPath,
                wipe_first: wipeFirst,
                naming_strategy: namingStrategy,
                export_to_root: exportToRoot
            })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || "同步啟動失敗");
        }
        
        alert("🚀 隨身碟寫入任務已啟動！正在背景進行循序複製與時間戳修改，請勿拔出隨身碟...");
        startExportPolling();
    } catch (err) {
        alert(err.message);
    }
}

// USB Copy Progress Polling
function startExportPolling() {
    document.getElementById("export-monitor").style.display = "block";
    
    if (exportPoller) clearInterval(exportPoller);
    pollExportOnce(); // Immediate call
    exportPoller = setInterval(pollExportOnce, 1000); // Poll every 1s
}

async function pollExportOnce() {
    try {
        const response = await fetch(`${API_BASE}/api/export/status`);
        if (!response.ok) return;
        const status = await response.json();
        
        if (status.status === "processing") {
            document.getElementById("export-current-file").textContent = `正在寫入: ${status.current_file}`;
            document.getElementById("export-summary-text").textContent = `複製中 (${status.copied_files} / ${status.total_files})`;
            const pct = Math.round(status.progress * 100);
            document.getElementById("export-percent-text").textContent = `${pct}%`;
            document.getElementById("export-progress-bar").style.width = `${pct}%`;
            document.getElementById("export-progress-text").textContent = `${pct}%`;
        } else if (status.status === "completed") {
            clearInterval(exportPoller);
            exportPoller = null;
            
            document.getElementById("export-current-file").textContent = "隨身碟同步已完成！";
            document.getElementById("export-summary-text").textContent = `完成 (${status.copied_files} / ${status.total_files})`;
            document.getElementById("export-percent-text").textContent = "100%";
            document.getElementById("export-progress-bar").style.width = "100%";
            document.getElementById("export-progress-text").textContent = "100%";
            
            // Sound chime
            try {
                const audio = new Audio("https://actions.google.com/sounds/v1/alarms/digital_watch_alarm_long.ogg");
                audio.volume = 0.3;
                audio.play();
            } catch(e) {}
            
            alert("🎉 隨身碟複製與硬體排序時間戳重置完成！安全卸載後即可帶去播放器歌唱。");
        } else if (status.status === "failed") {
            clearInterval(exportPoller);
            exportPoller = null;
            
            document.getElementById("export-current-file").textContent = `錯誤: ${status.error}`;
            document.getElementById("export-progress-bar").style.width = "0%";
            document.getElementById("export-progress-text").textContent = "失敗";
            alert(`隨身碟同步失敗: ${status.error}`);
        }
    } catch (err) {
        console.error("USB polling error:", err);
    }
}

// Printable songbook page opener
function openPrintableSongbook() {
    const checkedBoxes = document.querySelectorAll(".export-row-check:checked");
    if (checkedBoxes.length === 0) {
        alert("請至少選擇一首歌曲以列印點歌本！");
        return;
    }
    
    const songIds = Array.from(checkedBoxes).map(box => box.value).join(",");
    const namingStrategy = document.getElementById("naming-strategy-select").value;
    
    const url = `${API_BASE}/songbook?song_ids=${encodeURIComponent(songIds)}&naming_strategy=${encodeURIComponent(namingStrategy)}`;
    window.open(url, "_blank");
}
