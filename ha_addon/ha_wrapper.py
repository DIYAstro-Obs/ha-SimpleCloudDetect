#!/usr/bin/env python3

import json
import os
import shutil
import time
import logging
import sys
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

import paho.mqtt.client as mqtt
import requests

# We will import CloudDetector and Config after adjusting the sys.path in main()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

OPTIONS_PATH = "/data/options.json"
SHARE_DIR = Path("/share/simple_cloud_detect")
APP_DIR = Path("/app")

# Global state for WebUI
GLOBAL_STATE = {
    "status": "Starting...",
    "is_safe": False,
    "confidence": 0.0,
    "time": "0.0",
    "last_update": "System initializing"
}
STATE_LOCK = threading.Lock()

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>Cloud Detect</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            margin: 0; padding: 20px;
            font-family: 'Inter', -apple-system, sans-serif;
            background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
            color: #fff;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .glass-card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            max-width: 600px;
            width: 100%;
            text-align: center;
        }
        h1 { margin-top: 0; font-weight: 300; letter-spacing: 2px; }
        .camera-feed {
            width: 100%;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5);
            background: #000;
            min-height: 300px;
            object-fit: contain;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .camera-feed:hover { transform: scale(1.02); }
        .status-badge {
            display: inline-block;
            padding: 10px 25px;
            border-radius: 30px;
            font-size: 1.2rem;
            font-weight: bold;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 1px;
            transition: all 0.3s ease;
        }
        .safe { background: rgba(46, 204, 113, 0.2); color: #2ecc71; border: 1px solid #2ecc71; }
        .unsafe { background: rgba(231, 76, 60, 0.2); color: #e74c3c; border: 1px solid #e74c3c; }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            text-align: left;
            margin-top: 20px;
        }
        .stat-box {
            background: rgba(0, 0, 0, 0.2);
            padding: 15px;
            border-radius: 10px;
        }
        .stat-label { font-size: 0.8rem; color: #aaa; text-transform: uppercase; display:block; margin-bottom: 5px;}
        .stat-value { font-size: 1.2rem; font-weight: bold; }
        .footer { margin-top: 30px; font-size: 0.8rem; color: #888; line-height: 1.5; }
        
        /* Modal Styles */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.9);
            backdrop-filter: blur(5px);
        }
        .modal-content {
            margin: auto;
            display: block;
            max-width: 95%;
            max-height: 95%;
            position: relative;
            top: 50%;
            transform: translateY(-50%);
            border-radius: 8px;
            box-shadow: 0 0 40px rgba(0,0,0,0.8);
        }
        .close {
            position: absolute;
            top: 20px;
            right: 35px;
            color: #f1f1f1;
            font-size: 40px;
            font-weight: bold;
            transition: 0.3s;
            cursor: pointer;
        }
        .close:hover, .close:focus { color: #bbb; text-decoration: none; cursor: pointer; }
    </style>
</head>
<body>
    <div class="glass-card">
        <h1>CLOUD DETECT</h1>
        <div>
            <img id="feed" class="camera-feed" src="latest.jpg" alt="Camera Feed" title="Click to enlarge">
        </div>
        <div id="statusBadge" class="status-badge safe">Loading...</div>
        
        <div class="grid">
            <div class="stat-box">
                <span class="stat-label">Condition</span>
                <span id="conditionVal" class="stat-value">-</span>
            </div>
            <div class="stat-box">
                <span class="stat-label">Confidence</span>
                <span id="confidenceVal" class="stat-value">- %</span>
            </div>
        </div>
        
        <div class="footer">
            Last Update: <span id="lastUpdate">-</span><br>
            Processing Time: <span id="timeVal">-</span>s
        </div>
    </div>

    <!-- The Modal -->
    <div id="imageModal" class="modal">
        <span class="close">&times;</span>
        <img class="modal-content" id="img01">
    </div>

    <script>
        // Modal Logic
        const modal = document.getElementById("imageModal");
        const img = document.getElementById("feed");
        const modalImg = document.getElementById("img01");
        const span = document.getElementsByClassName("close")[0];

        img.onclick = function(){
            modal.style.display = "block";
            modalImg.src = this.src; // Initialize with current frame
        }

        span.onclick = function() { modal.style.display = "none"; }
        modal.onclick = function(e) { if(e.target === modal) modal.style.display = "none"; }

        function updateData() {
            fetch('api/state')
                .then(r => r.json())
                .then(data => {
                    const badge = document.getElementById('statusBadge');
                    if(data.is_safe) {
                        badge.className = 'status-badge safe';
                        badge.innerText = 'SAFE';
                    } else {
                        badge.className = 'status-badge unsafe';
                        badge.innerText = 'UNSAFE';
                    }
                    
                    document.getElementById('conditionVal').innerText = data.status;
                    document.getElementById('confidenceVal').innerText = data.confidence + '%';
                    document.getElementById('lastUpdate').innerText = data.last_update;
                    document.getElementById('timeVal').innerText = data.time;
                    
                    const timestampMs = new Date().getTime();
                    const newFrameUrl = 'latest.jpg?t=' + timestampMs;
                    
                    // Update main feed
                    document.getElementById('feed').src = newFrameUrl;
                    
                    // Update modal background image if it is open so it stays live
                    if (modal.style.display === "block") {
                        modalImg.src = newFrameUrl;
                    }
                })
                .catch(e => console.error(e));
        }
        
        updateData();
        setInterval(updateData, 5000);
    </script>
</body>
</html>"""

class WebUIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
        
    def do_GET(self):
        try:
            path = self.path.split('?')[0].strip('/')
            if path == '':
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
            elif path == 'api/state':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                with STATE_LOCK:
                    state_json = json.dumps(GLOBAL_STATE)
                self.wfile.write(state_json.encode('utf-8'))
            elif path == 'latest.jpg':
                img_path = SHARE_DIR / "latest.jpg"
                if img_path.exists():
                    self.send_response(200)
                    self.send_header('Content-type', 'image/jpeg')
                    self.send_header('Cache-Control', 'no-store, must-revalidate')
                    self.end_headers()
                    with open(img_path, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.send_error(404, "Image not generated yet")
            else:
                self.send_error(404)
        except Exception as e:
            logger.error(f"HTTP Server error: {e}")
            self.send_error(500)

def load_options():
    """Load add-on options from HA's options.json"""
    try:
        with open(OPTIONS_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load options from {OPTIONS_PATH}, falling back to defaults: {e}")
        # Default options for fallback testing
        return {
            "camera_url": "",
            "mqtt_broker": "core-mosquitto",
            "mqtt_user": "",
            "mqtt_password": "",
            "mqtt_topic": "simpleclouddetect/state",
            "scan_interval": 60
        }

def download_file(url, destination):
    """Download a file from an URL to a destination path"""
    try:
        logger.info(f"Downloading {url} to {destination}...")
        response = requests.get(url, timeout=30, stream=True)
        response.raise_for_status()
        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Successfully downloaded {destination}")
        return True
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return False

def ensure_models():
    """Ensure Keras model and labels exist in HA's /share directory"""
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Base URLs for downloads
    REPO_RAW_URL = "https://raw.githubusercontent.com/chvvkumar/simpleCloudDetect/main"
    
    files_to_check = [
        ("keras_model.h5", f"{REPO_RAW_URL}/keras_model.h5"),
        ("labels.txt", f"{REPO_RAW_URL}/labels.txt")
    ]
    
    for filename, download_url in files_to_check:
        dest_path = SHARE_DIR / filename
        app_path = APP_DIR / filename
        
        if dest_path.exists():
            logger.info(f"Using existing {filename} at {dest_path}")
            continue
            
        # If not in /share, try to copy from /app
        if app_path.exists():
            logger.info(f"Copying default {filename} from {app_path} to {dest_path}")
            shutil.copy2(app_path, dest_path)
        else:
            # If not in /app, download from GitHub
            logger.info(f"{filename} not found in {APP_DIR}. Attempting download...")
            if not download_file(download_url, dest_path):
                logger.error(f"Could not ensure {filename} exists!")
                # We don't exit here, maybe the user manually places it or it's a transient network error
                # detect.py will fail later anyway if the file is missing when loading the model

def main():
    logger.info("Starting simpleCloudDetect Native Home Assistant Add-on Wrapper")
    
    # Change working directory to /app so detect.py and components are in path
    os.chdir(APP_DIR)
    sys.path.append(str(APP_DIR))
    
    options = load_options()
    
    camera_url = options.get("camera_url") or ""
    camera_entity = options.get("camera_entity") or ""
    
    auth_headers = {}
    
    if camera_entity:
        # Auto-fix: add 'camera.' prefix if the user only entered the entity name
        if not camera_entity.startswith("camera."):
            camera_entity = f"camera.{camera_entity}"
            logger.info(f"Auto-prefixed entity ID to: {camera_entity}")
        logger.info(f"Using Home Assistant camera entity: {camera_entity}")
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            logger.error("SUPERVISOR_TOKEN not found! Cannot use camera_entity.")
        else:
            camera_url = f"http://supervisor/core/api/camera_proxy/{camera_entity}"
            auth_headers = {"Authorization": f"Bearer {token}"}
            logger.info(f"Set proxy URL: {camera_url}")

    if not camera_url:
        logger.error("No camera_url or camera_entity configured! Please set one in the Add-on options.")
        # While loop to keep add-on running to so it doesn't crash continuously on start 
        # while user configs the add-on
        while True:
            time.sleep(60)
        
    ensure_models()
    
    mqtt_broker = options.get("mqtt_broker", "core-mosquitto")
    mqtt_port = options.get("mqtt_port", 1883)
    mqtt_user = options.get("mqtt_user")
    mqtt_password = options.get("mqtt_password")
    mqtt_topic = options.get("mqtt_topic", "simpleclouddetect/state")
    mqtt_discovery_prefix = options.get("mqtt_discovery_prefix", "homeassistant")
    scan_interval = int(options.get("scan_interval", 60))
    safe_wait_time = int(options.get("safe_wait_time", 300))
    unsafe_wait_time = int(options.get("unsafe_wait_time", 0))
    safe_conditions = options.get("safe_conditions", ["Clear", "Wisps"])
    device_name = options.get("device_name", "Cloud Detector")
    verify_ssl = options.get("verify_ssl", False)
    
    # Initialize the core cloud detection logic using the original Config dataclass
    # Import here to ensure the sys.path modification has taken effect
    try:
        from detect import CloudDetector, Config
    except ImportError as e:
        logger.error(f"Failed to import detect module from {os.getcwd()}: {e}")
        time.sleep(10)
        return
    except Exception as e:
        logger.exception(f"Unexpected error during import: {e}")
        time.sleep(10)
        return

    # IMPORTANT: We need to enable `homeassistant` discovery mode
    # We will pass a dummy device_id to satisfy the Config requirements
    device_id = "addon_instance"
    
    config = Config(
        image_url=camera_url,
        model_path=str(SHARE_DIR / "keras_model.h5"),
        label_path=str(SHARE_DIR / "labels.txt"),
        broker=mqtt_broker,
        port=mqtt_port,
        topic=mqtt_topic,
        detect_interval=scan_interval,
        mqtt_username=mqtt_user,
        mqtt_password=mqtt_password,
        verify_ssl=verify_ssl,
        mqtt_discovery_mode="homeassistant",
        mqtt_discovery_prefix=mqtt_discovery_prefix,
        device_name=device_name,
        device_id=device_id
    )
    
    logger.info("Initializing original CloudDetector...")
    try:
        detector = CloudDetector(config)
        if auth_headers:
            logger.info("Injecting authorization headers into detector session")
            detector.session.headers.update(auth_headers)
    except Exception as e:
        logger.error(f"Failed to initialize CloudDetector: {e}")
        return
        
    # We need to manually register our extra `is_safe` boolean sensor
    # since it's not part of the standard `CloudDetector` class.
    # The CloudDetector class already registers standard sensors (Status, Confidence, Time)
    # and sets availability as "online".
    if detector.ha_discovery and detector.mqtt_client:
        device_info = detector.ha_discovery.get_device_info()
        safety_config = {
            "name": "Is Safe (Clear/Wisps)",
            "unique_id": f"clouddetect_{device_id}_is_safe",
            "state_topic": f"{mqtt_discovery_prefix}/sensor/clouddetect_{device_id}/is_safe/state",
            "availability_topic": detector.ha_discovery.availability_topic,
            "icon": "mdi:shield-check",
            "device": device_info
        }
        detector.mqtt_client.publish(
            f"{mqtt_discovery_prefix}/sensor/clouddetect_{device_id}/is_safe/config",
            json.dumps(safety_config),
            retain=True
        )
        logger.info("Published configuration for custom 'Is Safe' sensor.")

    logger.info("Starting internal HTTP Server for Ingress WebUI on port 8099...")
    try:
        httpd = HTTPServer(('0.0.0.0', 8099), WebUIHandler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    except Exception as e:
        logger.error(f"Failed to start HTTP server: {e}")

    logger.info(f"Starting main detection loop (Interval: {scan_interval}s)")
    
    # State tracking variables for Safe/Unsafe Wait Time logic
    reported_is_safe = None
    current_condition = None
    condition_start_time = 0
    last_logged_wait_state = None
    
    while True:
        try:
            # 1. Fetch image, run prediction, and evaluate result using original logic
            # This also internally publishes the standard stats via ha_discovery
            # Pass return_image=True so we can save and serve it
            result = detector.detect(return_image=True)
            
            # Save latest image to disk for the WebUI
            if 'image' in result:
                try:
                    result['image'].save(SHARE_DIR / "latest.jpg", "JPEG")
                except Exception as e:
                    logger.error(f"Failed to save latest image: {e}")
                # Remove it before publishing over MQTT
                del result['image']

            # Publish standard results via original logic
            detector.publish_result(result)
            
            # 2. Extract and format values for our extra logic
            status = result.get("class_name", "Unknown").strip()
            
            # 'is_safe' is True if the current status matches any of the user's selected safe_conditions
            lower_status = status.lower()
            is_safe = False
            for safe_label in safe_conditions:
                # E.g., user selected "Clear", and status is "0 Clear" or "Clear"
                if safe_label.lower() in lower_status:
                    is_safe = True
                    break
            
            # 3. Apply Safe / Unsafe Wait Time logic
            now = time.time()
            if current_condition != is_safe:
                current_condition = is_safe
                condition_start_time = now
                logger.info(f"Condition changed to {'Safe' if is_safe else 'Unsafe'}. Waiting for {'safe' if is_safe else 'unsafe'} wait time...")

            wait_time = safe_wait_time if is_safe else unsafe_wait_time

            if now - condition_start_time >= wait_time:
                # We have held the condition for long enough, we can report it
                if reported_is_safe != is_safe:
                    reported_is_safe = is_safe
                    if detector.mqtt_client:
                        detector.mqtt_client.publish(
                            f"{mqtt_discovery_prefix}/sensor/clouddetect_{device_id}/is_safe/state",
                            str(reported_is_safe).lower()
                        )
                        logger.info(f"Published Is Safe state to MQTT: {reported_is_safe}")
                last_logged_wait_state = None # Reset log state once published
            else:
              # If time hasn't passed, we don't publish yet.
                remaining = int(wait_time - (now - condition_start_time))
                if remaining > 0:
                    if last_logged_wait_state != is_safe:
                        logger.info(f"Delaying state publish... waiting for {'Safe' if is_safe else 'Unsafe'} state to stabilize.")
                        last_logged_wait_state = is_safe
                else:
                    last_logged_wait_state = None
            
            # Update WebUI global state
            with STATE_LOCK:
                GLOBAL_STATE["status"] = result.get("class_name", "Unknown")
                GLOBAL_STATE["is_safe"] = is_safe
                GLOBAL_STATE["confidence"] = result.get("confidence_score", 0.0)
                GLOBAL_STATE["time"] = result.get("Detection Time (Seconds)", 0.0)
                GLOBAL_STATE["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
        except Exception as e:
            logger.error(f"Error during detection loop: {e}")
            
        time.sleep(scan_interval)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception(f"FATAL UNHANDLED EXCEPTION IN WRAPPER: {e}")
        time.sleep(10)  # Wait so HA logger can capture it
        sys.exit(1)
