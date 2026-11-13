import os
import socket
import webbrowser
import subprocess
from http.server import ThreadingHTTPServer
from app import RoseAppHandler, is_port_in_use, launch_popup_window

PORT = 8089

def run_groundtruth_server():
    global PORT
    while is_port_in_use(PORT):
        PORT += 1

    server_address = ('127.0.0.1', PORT)
    httpd = ThreadingHTTPServer(server_address, RoseAppHandler)
    url = f"http://127.0.0.1:{PORT}/groundtruth.html"

    print("=" * 60)
    print("  ROSE - Dedicated Video Ground-Truth & Playback Viewer")
    print("=" * 60)
    print(f"  Server running locally at: {url}")
    print("  Opening ground-truth viewer window...")
    print("=" * 60)

    launch_popup_window(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ground-truth server...")
        httpd.server_close()

if __name__ == '__main__':
    run_groundtruth_server()

