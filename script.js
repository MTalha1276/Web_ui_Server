// JavaScript for the Android Device Demo Server Web GUI

let pollingInterval = null;
const POLL_INTERVAL = 3000; // 3 seconds

document.addEventListener('DOMContentLoaded', () => {
    // Initialize UI
    initUI();
    
    // Start polling for updates
    startPolling();
    
    // Set up event listeners
    setupEventListeners();
});

function initUI() {
    // Set initial status
    updateStatus('offline', 'Connecting to server...');
    
    // Clear logs initially
    clearLogs();
}

function setupEventListeners() {
    // Send button
    document.getElementById('send-btn').addEventListener('click', sendCommand);
    
    // Clear logs button
    document.getElementById('clear-logs-btn').addEventListener('click', clearLogs);
    
    // Enter key in command input
    document.getElementById('command-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendCommand();
        }
    });
    
    // Enter key in args input
    document.getElementById('args-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendCommand();
        }
    });
    
    // Quick command buttons
    document.querySelectorAll('.btn-small[data-cmd]').forEach(button => {
        button.addEventListener('click', () => {
            const cmd = button.getAttribute('data-cmd');
            document.getElementById('command-input').value = cmd;
            document.getElementById('args-input').value = '{}';
            sendCommand();
        });
    });
}

function startPolling() {
    // Clear any existing interval
    if (pollingInterval) {
        clearInterval(pollingInterval);
    }
    
    // Set up polling
    pollingInterval = setInterval(() => {
        fetchData();
    }, POLL_INTERVAL);
    
    // Initial fetch
    fetchData();
}

function fetchData() {
    // Fetch devices, logs, and stats in parallel
    Promise.all([
        fetch('/api/devices').then(r => r.json()),
        fetch('/api/logs').then(r => r.json()),
        fetch('/api/stats').then(r => r.json())
    ])
    .then(([devicesRes, logsRes, statsRes]) => {
        updateDevices(devicesRes);
        updateLogs(logsRes);
        updateStatus('online', 'Server connected');
    })
    .catch(err => {
        console.error('Error fetching data:', err);
        updateStatus('offline', 'Server disconnected');
    });
}

function updateStatus(state, message) {
    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    
    if (state === 'online') {
        statusIndicator.className = 'status-online';
        statusText.textContent = message;
    } else {
        statusIndicator.className = 'status-offline';
        statusText.textContent = message;
    }
}

function updateDevices(devices) {
    const container = document.getElementById('devices-container');
    
    if (!devices || devices.length === 0) {
        container.innerHTML = '<div class="device-list-empty">No devices connected</div>';
        return;
    }
    
    // Sort devices: online first, then by ID
    devices.sort((a, b) => {
        if (a.status === b.status) {
            return a.id - b.id;
        }
        return a.status === 'ONLINE' ? -1 : 1;
    });
    
    container.innerHTML = devices.map(device => {
        const statusClass = device.status === 'ONLINE' ? 'online' : 'offline';
        return `
            <div class="device-card">
                <div class="device-header">
                    <span class="device-id">#${device.id}</span>
                    <span class="device-status ${statusClass}">${device.status}</span>
                </div>
                <div class="device-info">
                    <div>IP: ${device.ip}</div>
                    <div>Model: ${device.model}</div>
                    <div>Images: ${device.images}</div>
                    <div>Videos: ${device.videos}</div>
                    <div>Notifications: ${device.notifications}</div>
                </div>
            </div>
        `;
    }).join('');
}

function updateLogs(data) {
    const logs = data.logs || [];
    const container = document.getElementById('logs-container');
    
    if (logs.length === 0) {
        container.innerHTML = '<div class="log-entry">No logs available</div>';
        return;
    }
    
    // Show newest logs at the bottom, so we reverse the array for display
    container.innerHTML = logs.reverse().map(logEntry => {
        // Extract timestamp and message from the log line
        // Format: [YYYY-MM-DD HH:MM:SS] message
        const match = logEntry.match(/^\[(.+?)\\] (.+)$/);
        if (match) {
            const timestamp = match[1];
            const message = match[2];
            return `
                <div class="log-entry">
                    <span class="log-timestamp">[${timestamp}]</span>
                    <span class="log-content">${message}</span>
                </div>
            `;
        } else {
            // Fallback if format doesn't match
            return `<div class="log-entry">${log_entries"`;
        }).join('');
    
    // Scroll to bottom to show latest logs
    container.scrollTop = container.scrollHeight;
}

function sendCommand() {
    const commandInput = document.getElementById('command-input');
    const argsInput = document.getElementById('args-input');
    
    const command = commandInput.value.trim();
    const args = argsInput.value.trim() || '{}';
    
    if (!command) {
        alert('Please enter a command');
        return;
    }
    
    // Validate JSON
    try {
        JSON.parse(args);
    } catch (e) {
        alert('Invalid JSON in arguments field');
        return;
    }
    
    // Disable button and show sending state
    const sendBtn = document.getElementById('send-btn');
    const originalText = sendBtn.textContent;
    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending...';
    
    // Send request
    fetch('/api/command', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ command, args })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return response.json();
    })
    .then(data => {
        // Add a log entry for the sent command
        const timestamp = new Date().toLocaleTimeString();
        const logEntry = `[${timestamp}] Sent command: ${command} ${args}`;
        const logsContainer = document.getElementById('logs-container');
        logsContainer.innerHTML += `
            <div class="log-entry">
                <span class="log-timestamp">[${timestamp}]</span>
                <span class="log-content">Sent command: ${command} ${args}</span>
            </div>
        `;
        logsContainer.scrollTop = logsContainer.scrollHeight;
        
        // Clear input fields
        commandInput.value = '';
        argsInput.value = '{}';
    })
    .catch(error => {
        console.error('Error sending command:', error);
        alert(`Failed to send command: ${error.message}`);
    })
    .finally(() => {
        // Re-enable button
        sendBtn.disabled = false;
        sendBtn.textContent = originalText;
    });
}

function clearLogs() {
    if (confirm('Clear all logs?')) {
        // We don't have a clear logs endpoint, so we just clear the display
        // The server will continue to log to its file and memory
        document.getElementById('logs-container').innerHTML = '<div class="log-entry">Logs cleared (server still logging)</div>';
    }
}

// Handle page visibility to pause/resume polling when tab is hidden
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        // Pause polling when tab is not visible
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    } else {
        // Resume polling when tab becomes visible
        if (!pollingInterval) {
            startPolling();
        }
    }
});

// Handle beforeunload to clean up
window.addEventListener('beforeunload', () => {
    if (pollingInterval) {
        clearInterval(pollingInterval);
    }
});