# Simple Cloud Detect MQTT - Home Assistant Add-on

This add-on brings the AI-based cloud detection from [DiMoGro1/simpleCloudDetect](https://github.com/DiMoGro1/simpleCloudDetect) natively to Home Assistant. It analyzes images from your All-Sky camera and reports the safety status ("Safe" or "Unsafe") via MQTT to Home Assistant.

## Features

- 🧠 **AI Analysis**: Automatic classification (Clear, Wisps, Overcast, Rain) using TensorFlow/Keras models.
- 🎨 **Sleek WebUI (Ingress)**: A dedicated dashboard directly in the HA sidebar with live images and glassmorphism design.
- 🔍 **Detail View**: Click on the camera image in the dashboard to enlarge it in a high-resolution modal view.
- 🛡️ **Specialized Safety Sensor**: A dedicated binary logic sensor (`is_safe`) that classifies "Clear" and "Wisps" as safe.
- ⏱️ **Adjustable Wait Times**:
  - `Safe Wait Time`: Delay when switching to "Safe" (prevents flickering during short cloud gaps).
  - `Unsafe Wait Time`: Immediate reporting when clouds or rain are detected.
- 🔗 **MQTT Auto-Discovery**: Automatically recognizes sensors in Home Assistant without manual YAML configuration.

## Installation

The easiest way to install this add-on is by adding this GitHub repository directly to your Home Assistant instance:

1. In your Home Assistant UI, navigate to **Settings -> Add-ons -> Add-on Store**.
2. Click the three dots in the top right corner and select **Repositories**.
3. Add the URL of this GitHub repository: `https://github.com/DiMoGro1/simpleCloudDetect`
4. Close the dialog and the store will refresh.
5. Search for **Simple Cloud Detect MQTT** and click **Install**.

## Configuration

Configure the add-on via the **Configuration** tab in the add-on interface:

- `camera_url`: The full HTTP(S) URL to your All-Sky camera snapshot.
- `device_name`: Device name in Home Assistant (Default: "Cloud Detector").
- `scan_interval`: Interval in seconds between AI analyses (Default: 60s).
- `safe_wait_time`: Time in seconds the sky must be continuously clear before the sensor switches to "Safe" (True) (Default: 300s).
- `unsafe_wait_time`: Time in seconds before switching to "Unsafe" when clouds are detected (Default: 0s for immediate protection).
- `mqtt_discovery_prefix`: Prefix for Home Assistant Auto-Discovery (Default: "homeassistant").

## Dashboard & Ingress

Enable the **"Show in sidebar"** toggle in the add-on settings to pin the dashboard to the left menu. Here you can see:
- The last image analyzed by the AI.
- The current safety status in real-time.
- The estimated AI confidence score.

## Technical Details

The add-on uses an internal lightweight HTTP server on port `8099` to ensure Ingress compatibility. The models (`keras_model.h5` and `labels.txt`) are automatically copied to `/share/simple_cloud_detect/` during the first start, where they can be replaced with custom models if desired.
