#!/usr/bin/env python3
import os
import sys
import subprocess
import socket
import time
import json
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading
import signal

class Config:
    """Configuration constants"""
    SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.avif'}
    PORT_RANGE = (8000, 9000)
    WINDOW_SIZE = "1200,800"
    SERVER_TIMEOUT = 10
    USER_DATA_DIR = "/tmp/chromium-image-viewer"

class FileManager:
    """Handles file operations"""

    @staticmethod
    def get_image_files(directory):
        """Get sorted list of image files in directory"""
        image_files = []
        for file_path in Path(directory).iterdir():
            if file_path.is_file() and file_path.suffix.lower() in Config.SUPPORTED_EXTENSIONS:
                image_files.append(file_path.name)
        return sorted(image_files)

    @staticmethod
    def validate_input_file(file_path):
        """Validate that the input file exists and is accessible"""
        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"File '{file_path}' does not exist")
        return path

class ServerManager:
    """Manages the HTTP server operations"""

    def __init__(self):
        self.server = None
        self.server_thread = None

    @staticmethod
    def find_free_port():
        """Find a free port in the configured range"""
        for port in range(Config.PORT_RANGE[0], Config.PORT_RANGE[1] + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        return Config.PORT_RANGE[0]

    def start_server(self, directory, port):
        """Start HTTP server in a separate thread"""
        os.chdir(directory)

        handler = SimpleHTTPRequestHandler
        self.server = HTTPServer(("127.0.0.1", port), handler)

        def serve():
            try:
                self.server.serve_forever()
            except Exception as e:
                print(f"Server error: {e}")

        self.server_thread = threading.Thread(target=serve, daemon=True)
        self.server_thread.start()
        return self.server

    def stop_server(self):
        """Stop HTTP server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def wait_for_server(self, port, max_attempts=10):
        """Wait for server to become available"""
        for attempt in range(max_attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        print(f"✅ Server running on http://127.0.0.1:{port}")
                        return True
            except Exception:
                pass

            time.sleep(1)
            if attempt == max_attempts - 1:
                print("❌ Server failed to start after 10 attempts")
                return False
        return True

class HTMLGenerator:
    """Handles HTML content generation"""

    @staticmethod
    def create_viewer_html(directory):
        """Create the HTML viewer file with zoom and pan functionality"""
        html_content = HTMLGenerator._get_html_template()
        viewer_path = Path(directory) / "viewer.html"
        viewer_path.write_text(html_content, encoding='utf-8')
        return viewer_path

    @staticmethod
    def _get_html_template():
        """Return the HTML template with viewer functionality"""
        return """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Image Viewer</title>
    <style>
        body {
            margin: 0;
            background: #000;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
            cursor: default;
        }
        body.panning {
            cursor: grabbing;
        }
        .container {
            position: relative;
            width: 100vw;
            height: 100vh;
            overflow: hidden;
        }
        img {
            position: absolute;
            max-width: none;
            max-height: none;
            transition: transform 0.1s ease;
            transform-origin: 0 0;
        }
        .filename {
            position: fixed;
            top: 15px;
            left: 15px;
            color: rgba(255, 255, 255, 0.5);
            font-size: 12px;
            font-family: system-ui, sans-serif;
            background: rgba(0, 0, 0, 0.4);
            padding: 5px 10px;
            border-radius: 5px;
            backdrop-filter: blur(5px);
            opacity: 0;
            transition: opacity 0.3s ease;
            z-index: 1000;
        }
        .zoom-info {
            position: fixed;
            top: 15px;
            right: 15px;
            color: rgba(255, 255, 255, 0.5);
            font-size: 12px;
            font-family: system-ui, sans-serif;
            background: rgba(0, 0, 0, 0.4);
            padding: 5px 10px;
            border-radius: 5px;
            backdrop-filter: blur(5px);
            opacity: 0;
            transition: opacity 0.3s ease;
            z-index: 1000;
        }
        body:hover .filename, body:hover .zoom-info {
            opacity: 1;
        }
        .controls {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.6);
            padding: 10px;
            border-radius: 10px;
            backdrop-filter: blur(5px);
            opacity: 0;
            transition: opacity 0.3s ease;
            z-index: 1000;
        }
        body:hover .controls {
            opacity: 1;
        }
        .controls button {
            background: rgba(255, 255, 255, 0.2);
            border: none;
            color: white;
            padding: 8px 12px;
            margin: 0 5px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
        }
        .controls button:hover {
            background: rgba(255, 255, 255, 0.3);
        }
    </style>
</head>
<body>
    <div class="container">
        <img id="currentImage" src="" alt="Image">
    </div>
    <div class="filename" id="filename"></div>
    <div class="zoom-info" id="zoomInfo"></div>
    <div class="controls">
        <button onclick="zoomOut()">-</button>
        <button onclick="resetZoom()">Reset</button>
        <button onclick="zoomIn()">+</button>
        <button onclick="fitToScreen()">Fit</button>
    </div>
    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const images = JSON.parse(urlParams.get('images') || '[]');
        let currentIndex = parseInt(urlParams.get('index') || '0');

        // Zoom and pan variables
        let scale = 1;
        let posX = 0;
        let posY = 0;
        let isPanning = false;
        let startX = 0;
        let startY = 0;
        let initialPinchDistance = null;

        const image = document.getElementById('currentImage');
        const container = document.querySelector('.container');
        const zoomInfo = document.getElementById('zoomInfo');

        function loadImage() {
            if (images.length > 0 && currentIndex >= 0 && currentIndex < images.length) {
                const img = new Image();
                img.onload = function() {
                    image.src = this.src;
                    document.getElementById('filename').textContent = images[currentIndex];
                    fitToScreen();
                };
                img.src = images[currentIndex];
            }
        }

        function updateTransform() {
            image.style.transform = `translate(${posX}px, ${posY}px) scale(${scale})`;
            if (scale === getMinScale()) {
                zoomInfo.textContent = "Fit";
            } else {
                zoomInfo.textContent = `${Math.round(scale * 100)}%`;
            }
        }

        function zoomIn(factor = 1.1) {
            const oldScale = scale;
            scale *= factor;
            if (scale > 10) scale = 10;

            const containerWidth = container.clientWidth;
            const containerHeight = container.clientHeight;
            posX = containerWidth/2 - (containerWidth/2 - posX) * (scale / oldScale);
            posY = containerHeight/2 - (containerHeight/2 - posY) * (scale / oldScale);

            constrainPosition();
            updateTransform();
        }

        function zoomOut(factor = 1.1) {
            const oldScale = scale;
            scale /= factor;

            const minScale = getMinScale();
            if (scale < minScale) {
                scale = minScale;
                centerImage();
            } else {
                const containerWidth = container.clientWidth;
                const containerHeight = container.clientHeight;
                posX = containerWidth/2 - (containerWidth/2 - posX) * (scale / oldScale);
                posY = containerHeight/2 - (containerHeight/2 - posY) * (scale / oldScale);
            }

            constrainPosition();
            updateTransform();
        }

        function resetZoom() {
            scale = 1;
            centerImage();
            updateTransform();
        }

        function fitToScreen() {
            scale = getMinScale();
            centerImage();
            updateTransform();
        }

        function getMinScale() {
            const containerWidth = container.clientWidth;
            const containerHeight = container.clientHeight;
            const imgWidth = image.naturalWidth;
            const imgHeight = image.naturalHeight;

            return Math.min(
                containerWidth / imgWidth,
                containerHeight / imgHeight
            );
        }

        function centerImage() {
            const containerWidth = container.clientWidth;
            const containerHeight = container.clientHeight;
            const scaledWidth = image.naturalWidth * scale;
            const scaledHeight = image.naturalHeight * scale;

            posX = (containerWidth - scaledWidth) / 2;
            posY = (containerHeight - scaledHeight) / 2;
        }

        function constrainPosition() {
            const containerWidth = container.clientWidth;
            const containerHeight = container.clientHeight;
            const scaledWidth = image.naturalWidth * scale;
            const scaledHeight = image.naturalHeight * scale;

            if (scaledWidth > containerWidth) {
                const maxX = (scaledWidth - containerWidth) / 2;
                const minX = -maxX;
                posX = Math.max(minX, Math.min(maxX, posX));
            } else {
                posX = (containerWidth - scaledWidth) / 2;
            }

            if (scaledHeight > containerHeight) {
                const maxY = (scaledHeight - containerHeight) / 2;
                const minY = -maxY;
                posY = Math.max(minY, Math.min(maxY, posY));
            } else {
                posY = (containerHeight - scaledHeight) / 2;
            }
        }

        // Event handlers
        image.addEventListener('mousedown', (e) => {
            if (e.button === 2 && scale > getMinScale()) {
                isPanning = true;
                document.body.classList.add('panning');
                startX = e.clientX - posX;
                startY = e.clientY - posY;
                e.preventDefault();
            }
        });

        document.addEventListener('mousemove', (e) => {
            if (isPanning) {
                posX = e.clientX - startX;
                posY = e.clientY - startY;
                constrainPosition();
                updateTransform();
            }
        });

        document.addEventListener('mouseup', (e) => {
            if (e.button === 2) {
                isPanning = false;
                document.body.classList.remove('panning');
            }
        });

        document.addEventListener('contextmenu', (e) => {
            if (scale > getMinScale()) {
                e.preventDefault();
            }
        });

        image.addEventListener('wheel', (e) => {
            e.preventDefault();
            const zoomIntensity = 0.001;
            const wheelDelta = e.deltaY;
            const zoomFactor = Math.exp(-wheelDelta * zoomIntensity);
            const newScale = scale * zoomFactor;
            const minScale = getMinScale();

            if (newScale >= minScale && newScale <= 10) {
                const rect = image.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const mouseY = e.clientY - rect.top;

                const oldScale = scale;
                scale = newScale;
                posX = mouseX - (mouseX - posX) * (scale / oldScale);
                posY = mouseY - (mouseY - posY) * (scale / oldScale);

                constrainPosition();
                updateTransform();
            }
        });

        function nextImage() {
            if (images.length > 0) {
                currentIndex = (currentIndex + 1) % images.length;
                loadImage();
            }
        }

        function prevImage() {
            if (images.length > 0) {
                currentIndex = (currentIndex - 1 + images.length) % images.length;
                loadImage();
            }
        }

        document.addEventListener('keydown', (e) => {
            switch(e.key) {
                case 'ArrowRight': nextImage(); break;
                case 'ArrowLeft': prevImage(); break;
                case 'Escape':
                    if (scale > getMinScale()) {
                        fitToScreen();
                    } else {
                        window.close();
                    }
                    break;
                case ' ': e.preventDefault(); nextImage(); break;
                case '+': case '=': e.preventDefault(); zoomIn(); break;
                case '-': e.preventDefault(); zoomOut(); break;
                case '0': e.preventDefault(); resetZoom(); break;
                case '1': e.preventDefault(); fitToScreen(); break;
            }
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.controls') && scale <= getMinScale()) {
                if (e.clientX > window.innerWidth / 2) nextImage();
                else prevImage();
            }
        });

        window.addEventListener('load', loadImage);
        window.addEventListener('resize', () => {
            if (scale <= getMinScale()) {
                fitToScreen();
            } else {
                constrainPosition();
                updateTransform();
            }
        });
    </script>
</body>
</html>"""

class BrowserLauncher:
    """Handles browser launching operations"""

    @staticmethod
    def launch_chromium(viewer_url, pid):
        """Launch Chromium with the viewer URL"""
        try:
            subprocess.run([
                "chromium",
                f"--app={viewer_url}",
                "--enable-features=WaylandColorManagement",
                f"--user-data-dir={Config.USER_DATA_DIR}-{pid}",
                f"--window-size={Config.WINDOW_SIZE}",
                "--window-position=center",
            ], check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Chromium error: {e}")
            return False
        except FileNotFoundError:
            print("Error: Chromium not found. Please install Chromium browser.")
            return False

class ImageViewer:
    """Main image viewer application"""

    def __init__(self):
        self.file_manager = FileManager()
        self.server_manager = ServerManager()
        self.html_generator = HTMLGenerator()
        self.browser_launcher = BrowserLauncher()

    def run(self):
        """Main execution function"""
        try:
            self._validate_arguments()
            image_file = self._process_input_file()
            image_files, current_index = self._get_image_list(image_file)
            port = self._start_services(image_file.parent, image_files, current_index)
            self._launch_browser(port, image_files, current_index)

        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nInterrupted by user")
        finally:
            self._cleanup(image_file.parent if 'image_file' in locals() else None)

    def _validate_arguments(self):
        """Validate command line arguments"""
        if len(sys.argv) < 2:
            print("Error: No image file specified")
            print(f"Usage: {sys.argv[0]} /path/to/image.jpg")
            sys.exit(1)

    def _process_input_file(self):
        """Process and validate the input file"""
        image_file = self.file_manager.validate_input_file(sys.argv[1])
        print(f"Image: {image_file.name}")
        print(f"Directory: {image_file.parent}")
        return image_file

    def _get_image_list(self, image_file):
        """Get image list and current index"""
        image_files = self.file_manager.get_image_files(image_file.parent)
        if not image_files:
            raise FileNotFoundError("No image files found in directory")

        try:
            current_index = image_files.index(image_file.name)
        except ValueError:
            print(f"Warning: Current image '{image_file.name}' not found in image list")
            current_index = 0

        print(f"Found {len(image_files)} images in directory")
        return image_files, current_index

    def _start_services(self, directory, image_files, current_index):
        """Start HTTP server and create HTML file"""
        port = self.server_manager.find_free_port()
        print(f"Server Port: {port}")

        self.html_generator.create_viewer_html(directory)
        self.server_manager.start_server(directory, port)

        if not self.server_manager.wait_for_server(port):
            raise RuntimeError("Server failed to start")

        return port

    def _launch_browser(self, port, image_files, current_index):
        """Launch browser with the viewer"""
        image_list_json = json.dumps(image_files).replace('"', '%22')
        viewer_url = f"http://127.0.0.1:{port}/viewer.html?images={image_list_json}&index={current_index}"

        success = self.browser_launcher.launch_chromium(viewer_url, os.getpid())
        if success:
            print("Chromium closed")
        else:
            print("Failed to launch browser")

    def _cleanup(self, directory):
        """Clean up resources"""
        print("Stopping server...")
        self.server_manager.stop_server()

        if directory:
            viewer_html = Path(directory) / "viewer.html"
            if viewer_html.exists():
                viewer_html.unlink()
                print("Removed viewer.html")

        print("Done")

def signal_handler(signum, frame):
    """Handle interrupt signals"""
    print("\nReceived interrupt signal, shutting down...")
    sys.exit(0)

def main():
    """Main entry point"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    viewer = ImageViewer()
    viewer.run()

if __name__ == "__main__":
    main()
