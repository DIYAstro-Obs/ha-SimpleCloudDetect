# Simple Cloud Detect MQTT - Home Assistant Add-on

This add-on integrates the AI-based cloud detection from [chvvkumar/simpleCloudDetect](https://github.com/chvvkumar/simpleCloudDetect) into Home Assistant. It analyzes images from your All-Sky camera and reports the safety status ("Safe" or "Unsafe") via MQTT.

This add-on is maintained independently of the original project and is not affiliated with it. It builds on the original's published Docker image (`chvvkumar/simpleclouddetect`) and downloads the default model from the original repository at the first start.

## Features

- **Camera Entity Support**: Select your Home Assistant camera directly (no separate URL/password needed).
- **AI Analysis**: Classification of the sky (the labels of the model, e.g. Clear, Mostly Cloudy, Overcast, Rain) using TensorFlow/Keras models.
- **WebUI (Ingress)**: A dashboard accessible via the Home Assistant sidebar showing live images.
- **Image View**: Click on the camera image in the dashboard to enlarge it in a modal view.
- **Safety Sensor**: A binary sensor (`is_safe`) classifies the sky status.
- **Configurable Safe States**: Choose exactly which AI classes (e.g., Clear, Wisps) trigger the "Safe" status.
- **Configurable Wait Times**:
  - `Safe Wait Time`: Delay when switching to "Safe" state.
  - `Unsafe Wait Time`: Delay when switching to "Unsafe" state.
- **MQTT Discovery**: Internal sensors are automatically recognized by Home Assistant.
- **Translated UI**: Fully translated configuration fields within the Home Assistant UI (English & German).

## Installation

To install this add-on, add this GitHub repository to your Home Assistant instance:

1. In Home Assistant, navigate to **Settings -> Add-ons -> Add-on Store**.
2. Click the three dots in the top right corner and select **Repositories**.
3. Add the URL: `https://github.com/DIYAstro-Obs/ha-SimpleCloudDetect`
4. Close the dialog and search for **Simple Cloud Detect MQTT**.
5. Click **Install**.

## Configuration

Options are available under the **Configuration** tab:

- `camera_entity`: (Recommended) The Home Assistant camera entity ID (e.g., `camera.allsky`). If you only enter the name (e.g., `allsky`), the add-on will automatically add the `camera.` prefix. This option takes priority over `camera_url`.
- `camera_url`: URL for your camera snapshot. This field is ignored if `camera_entity` is set.
- `device_name`: Name for the device in Home Assistant (Default: "Cloud Detector").
- `scan_interval`: Time in seconds between analyses (5 to 3600, Default: 60s).
- `safe_wait_time`: Seconds the sky must be clear before switching to "Safe" (Default: 300s).
- `unsafe_wait_time`: Seconds before switching to "Unsafe" when clouds are detected (Default: 0s).
- `safe_conditions`: A list of AI classes considered "Safe", each with a minimum confidence in percent. Type the class name exactly as it appears in `labels.txt` (upper/lower case is ignored). The labels of the default model are `Clear`, `Mostly Cloudy`, `Overcast`, `Partly Cloudy`, `Rain`, `Snow`.
- `mqtt_user`, `mqtt_password`: Optional. If both are empty, the add-on uses the login of the Supervisor's MQTT service (the Mosquitto add-on).
- `mqtt_discovery_prefix`: Prefix for Auto-Discovery (Default: "homeassistant").
- `mqtt_lwt_logic`: Behavior when the add-on disconnects or crashes. Options: `unsafe` (sets state to false), `safe` (sets state to true), `none` (keeps last state). Default: `unsafe`.

## Dashboard

Enable the **"Show in sidebar"** toggle in the add-on settings to access the dashboard. 

## Custom Models

> [!IMPORTANT]
> The automatically downloaded default model is specifically trained for a particular camera and environment. While it serves as a working example, its accuracy may vary significantly for your setup. For instructions on how to train and create your own custom model, please refer to the [main project documentation](https://github.com/chvvkumar/simpleCloudDetect).

You can use your own AI models by replacing the default files. 

1. Install a file access add-on (e.g., **Samba share**, **File Editor**, or **SSH & Web Terminal**).
2. Navigate to the Home Assistant `share` folder.
3. Locate the `simple_cloud_detect` directory.
4. Replace the following files with your own:
   - `keras_model.h5`: Your Keras model file.
   - `labels.txt`: Your labels file.
5. Restart the add-on to load the new model.

## Technical Details

The add-on uses an internal HTTP server on port `8099` for Ingress. Default models are automatically downloaded from GitHub to `/share/simple_cloud_detect/` during the first startup if they are not already present.

### MQTT Last Will (LWT)
To ensure reliable status reporting, the add-on uses the MQTT LWT mechanism. MQTT allows one Last Will per connection, so `mqtt_lwt_logic` selects it: with `unsafe` or `safe` the broker sets the `is_safe` sensor to `false` or `true` when the add-on crashes or loses the network (the other sensors keep their last values); with `none` the broker marks all sensors of the device as unavailable instead.

### Camera failures
If no usable picture could be fetched for `max(3 x scan_interval, 120 s)`, the add-on reports `Is Safe` as `false` until pictures arrive again and the wait times have elapsed, and the dashboard shows the error. `Is Safe` is published every cycle, also while a change is still waiting for its wait time.
