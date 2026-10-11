# ha-SimpleCloudDetect

Home Assistant add-on that runs the AI cloud detection of [chvvkumar/simpleCloudDetect](https://github.com/chvvkumar/simpleCloudDetect) next to Home Assistant. It classifies the image of an all-sky camera and publishes the result through MQTT discovery: the sky condition, the confidence and an `Is Safe` sensor with configurable wait times, per-label thresholds and a fail-safe for a camera that stops delivering pictures.

This repository contains only the add-on wrapper. The detection engine and the default model belong to the original project; the add-on builds on its published Docker image and downloads the default model at the first start. It is not affiliated with the original project.

## Installation

Add `https://github.com/DIYAstro-Obs/ha-SimpleCloudDetect` as a repository in the Home Assistant add-on store and install **Simple Cloud Detect MQTT**. The steps and all options are in [ha_addon/readme.md](ha_addon/readme.md).

## Documentation

- [ha_addon/readme.md](ha_addon/readme.md): features, configuration, custom models, dashboard
- [ha_addon/architecture.md](ha_addon/architecture.md): structure, start sequence, safety logic, Last Will
- Unit tests: `python -m unittest discover -s ha_addon/tests` (no TensorFlow, broker or Home Assistant needed)

## License

[0BSD](LICENSE)
