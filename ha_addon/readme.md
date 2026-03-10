# Simple Cloud Detect MQTT - Home Assistant Add-on

This add-on integrates the AI-based cloud detection from [chvvkumar/simpleCloudDetect](https://github.com/chvvkumar/simpleCloudDetect) into Home Assistant. It analyzes images from your All-Sky camera and reports the safety status ("Safe" or "Unsafe") via MQTT.

## Features

- **AI Analysis**: Classification (Clear, Wisps, Overcast, Rain) using TensorFlow/Keras models.
- **WebUI (Ingress)**: A dashboard accessible via the Home Assistant sidebar showing live images.
- **Image View**: Click on the camera image in the dashboard to enlarge it in a modal view.
- **Safety Sensor**: A binary sensor (`is_safe`) classifies "Clear" and "Wisps" as safe.
- **Configurable Wait Times**:
  - `Safe Wait Time`: Delay when switching to "Safe" state.
  - `Unsafe Wait Time`: Delay when switching to "Unsafe" state.
- **MQTT Discovery**: Internal sensors are automatically recognized by Home Assistant.

## Installation

To install this add-on, add this GitHub repository to your Home Assistant instance:

1. In Home Assistant, navigate to **Settings -> Add-ons -> Add-on Store**.
2. Click the three dots in the top right corner and select **Repositories**.
3. Add the URL: `https://github.com/DiMoGro1/simpleCloudDetect`
4. Close the dialog and search for **Simple Cloud Detect MQTT**.
5. Click **Install**.

## Configuration

Options are available under the **Configuration** tab:

- `camera_url`: URL for your camera snapshot.
- `device_name`: Name for the device in Home Assistant (Default: "Cloud Detector").
- `scan_interval`: Time in seconds between analyses (Default: 60s).
- `safe_wait_time`: Seconds the sky must be clear before switching to "Safe" (Default: 300s).
- `unsafe_wait_time`: Seconds before switching to "Unsafe" when clouds are detected (Default: 0s).
- `mqtt_discovery_prefix`: Prefix for Auto-Discovery (Default: "homeassistant").

## Dashboard

Enable the **"Show in sidebar"** toggle in the add-on settings to access the dashboard. 

## Custom Models

You can use your own AI models by replacing the default files. 

1. Install a file access add-on (e.g., **Samba share**, **File Editor**, or **SSH & Web Terminal**).
2. Navigate to the Home Assistant `share` folder.
3. Locate the `simple_cloud_detect` directory.
4. Replace the following files with your own:
   - `keras_model.h5`: Your Keras model file.
   - `labels.txt`: Your labels file.
5. Restart the add-on to load the new model.

## Technical Details

The add-on uses an internal HTTP server on port `8099` for Ingress. Default models are copied to `/share/simple_cloud_detect/` during the first startup if the directory is empty.
