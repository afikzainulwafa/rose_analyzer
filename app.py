import os
import sys
import json
import socket
import webbrowser
import subprocess
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import urllib.parse

PORT = 8088
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
WEB_DIR = os.path.join(BASE_DIR, 'web')
ROSE_DIR = os.path.join(BASE_DIR, 'ROSE')

class RoseAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # API: Segment Detail (Fetch exact txt file data on click)
        if path == '/api/segment_detail':
            self.handle_segment_detail(query)
            return

        # API: Video Streaming
        if path == '/video/survey':
            self.handle_video_stream()
            return

        # Default static file handling
        return super().do_GET()

    def handle_segment_detail(self, query):
        date_param = query.get('date', ['20261103'])[0]
        file_param = query.get('file', [''])[0]

        if not file_param:
            self.send_error(400, "Missing file parameter")
            return

        # Locate txt file
        # Folder mapping for 03, 04, 05, 06 Nov 2026
        folder_map = {
            '20261103': 'Accelerometer Data - 23000988_20261103-20261103 A27',
            '20261104': 'Accelerometer Data - 23000988_20261104-20261104 A27',
            '20261105': 'Accelerometer Data - 23000988_20261105-20261105',
            '20261106': 'Accelerometer Data - 23000988_20261106-20261106'
        }

        # Strip extension if needed for subdir
        subdir_name = os.path.splitext(file_param)[0]

        # Infer date from filename if possible (e.g. 23000988-20261105092607.txt -> 20261105)
        if '-' in subdir_name and len(subdir_name.split('-')[1]) >= 8:
            inferred_date = subdir_name.split('-')[1][:8]
            if inferred_date in folder_map:
                date_param = inferred_date

        target_folder_name = folder_map.get(date_param)

        candidate_path = None
        if target_folder_name:
            p = os.path.join(ROSE_DIR, target_folder_name, subdir_name, file_param)
            if os.path.exists(p):
                candidate_path = p

        # If not found directly, search all mapped folders and any Accelerometer Data folders in ROSE_DIR
        if not candidate_path:
            search_folders = list(folder_map.values())
            if os.path.exists(ROSE_DIR):
                for entry in os.listdir(ROSE_DIR):
                    if entry.startswith('Accelerometer Data') and entry not in search_folders:
                        search_folders.append(entry)
            for fld in search_folders:
                p = os.path.join(ROSE_DIR, fld, subdir_name, file_param)
                if os.path.exists(p):
                    candidate_path = p
                    break

        if not candidate_path or not os.path.exists(candidate_path):
            self.send_error(404, f"Segment file {file_param} not found")
            return

        try:
            with open(candidate_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            resp = json.dumps(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(resp)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(resp)
        except Exception as e:
            self.send_error(500, f"Error reading segment file: {str(e)}")

    def handle_video_stream(self):
        video_path = os.path.join(ROSE_DIR, 'Video', '04 Nov 2026', '20261104_111115.mp4')
        if not os.path.exists(video_path):
            self.send_error(404, "Survey video file not found")
            return

        size = os.path.getsize(video_path)
        range_header = self.headers.get('Range')

        if range_header:
            # Handle HTTP Range requests for video seeking
            try:
                ranges = range_header.replace('bytes=', '').split('-')
                start = int(ranges[0])
                end = int(ranges[1]) if ranges[1] else min(start + 2*1024*1024, size - 1)
                chunk_len = end - start + 1

                self.send_response(206)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.send_header('Content-Length', str(chunk_len))
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()

                with open(video_path, 'rb') as f:
                    f.seek(start)
                    self.wfile.write(f.read(chunk_len))
                return
            except Exception:
                pass

        # Full file fallback
        self.send_response(200)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Content-Length', str(size))
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()
        with open(video_path, 'rb') as f:
            while chunk := f.read(1024*1024):
                try:
                    self.wfile.write(chunk)
                except BrokenPipeError:
                    break


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def launch_popup_window(url):
    """
    Launch browser in standalone app mode (--app=URL)
    This creates a clean pop-up window without address bar or browser tabs,
    looking like a native desktop app.
    """
    browsers = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
    ]

    for exe in browsers:
        if os.path.exists(exe):
            cmd = [exe, f'--app={url}', '--window-size=1440,900']
            try:
                subprocess.Popen(cmd)
                print(f"Launched native pop-up window using: {exe}")
                return True
            except Exception as e:
                print(f"Could not launch {exe}: {e}")

    # Fallback to standard browser
    print("Opening in default browser...")
    webbrowser.open(url)
    return False


def run_server():
    global PORT
    while is_port_in_use(PORT):
        PORT += 1

    server_address = ('127.0.0.1', PORT)
    httpd = ThreadingHTTPServer(server_address, RoseAppHandler)
    url = f"http://127.0.0.1:{PORT}"

    print("=" * 60)
    print("  ROSE - PMSE Estate Road & Accelerometer Analytics App")
    print("=" * 60)
    print(f"  Server running locally at: {url}")
    print("  Opening pop-up application window...")
    print("=" * 60)

    # Launch local pop up window
    launch_popup_window(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()


if __name__ == '__main__':
    run_server()

