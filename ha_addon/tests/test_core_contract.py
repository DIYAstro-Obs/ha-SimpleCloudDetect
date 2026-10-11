"""Contract between the add-on and the core project (detect.py of chvvkumar/simpleCloudDetect).

Skipped unless SIMPLECLOUDDETECT_DIR points to a clone of the core project, for example

    $env:SIMPLECLOUDDETECT_DIR = "C:\\Users\\you\\Documents\\Programming\\simpleCloudDetect"
    py -3.14 -m unittest discover -s ha_addon/tests

TensorFlow is not needed: keras is stubbed before detect.py is imported.
"""
import ast
import dataclasses
import importlib.util
import inspect
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ADDON_DIR = Path(__file__).resolve().parent.parent
CORE_DIR = Path(os.environ["SIMPLECLOUDDETECT_DIR"]) if os.environ.get("SIMPLECLOUDDETECT_DIR") else None
HAVE_CORE = CORE_DIR is not None and (CORE_DIR / "detect.py").is_file()

AVAILABILITY = "homeassistant/sensor/clouddetect_addon_instance/availability"


def load_core():
    """Import detect.py from the clone under its own module name, with keras stubbed."""
    keras = types.ModuleType("keras")
    models = types.ModuleType("keras.models")
    models.load_model = lambda *args, **kwargs: None
    keras.models = models
    # Only the stubs are removed again: numpy and friends must stay imported (C extensions cannot be
    # loaded twice), which is why sys.modules is not restored as a whole.
    added = [name for name in ("keras", "keras.models") if name not in sys.modules]
    sys.modules.setdefault("keras", keras)
    sys.modules.setdefault("keras.models", models)
    try:
        spec = importlib.util.spec_from_file_location("core_detect", CORE_DIR / "detect.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name in added:
            sys.modules.pop(name, None)
    return module


def wrapper_config_keywords():
    """Keyword names of the Config(...) call in ha_wrapper.py, read from the source."""
    tree = ast.parse((ADDON_DIR / "ha_wrapper.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Config":
            return {keyword.arg for keyword in node.keywords}
    raise AssertionError("no Config(...) call found in ha_wrapper.py")


class FakeClient:
    def __init__(self):
        self.published = []  # (topic, payload, retain)

    def publish(self, topic, payload=None, retain=False):
        self.published.append((topic, payload, retain))

    def is_connected(self):
        return True


@unittest.skipUnless(HAVE_CORE, "set SIMPLECLOUDDETECT_DIR to a clone of the core project")
class CoreContractTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.core = load_core()

    def make_config(self, **overrides):
        values = dict(
            image_url="http://camera/image.jpg", model_path="keras_model.h5", label_path="labels.txt",
            broker="core-mosquitto", port=1883, topic="simpleclouddetect/state", detect_interval=60,
            mqtt_username=None, mqtt_password=None, verify_ssl=False,
            mqtt_discovery_mode="homeassistant", mqtt_discovery_prefix="homeassistant",
            device_name="Cloud Detector", device_id="addon_instance")
        values.update(overrides)
        return self.core.Config(**values)

    def test_config_fields_match_what_the_wrapper_passes(self):
        fields = dataclasses.fields(self.core.Config)
        names = {f.name for f in fields}
        required = {f.name for f in fields
                    if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
        passed = wrapper_config_keywords()
        self.assertEqual(passed - names, set(), "the wrapper passes fields that Config no longer has")
        self.assertEqual(required - passed, set(), "Config has new required fields the wrapper does not pass")

    def test_cloud_detector_takes_a_client(self):
        parameter = inspect.signature(self.core.CloudDetector.__init__).parameters["mqtt_client"]
        self.assertIsNone(parameter.default)

    def test_detect_can_return_the_image(self):
        self.assertIn("return_image", inspect.signature(self.core.CloudDetector.detect).parameters)

    def test_discovery_manager(self):
        client = FakeClient()
        manager = self.core.HADiscoveryManager(self.make_config(), client)
        self.assertEqual(manager.availability_topic, AVAILABILITY)
        self.assertIn("identifiers", manager.get_device_info())

        manager.publish_discovery_configs()
        self.assertIn((AVAILABILITY, "online", True), client.published)

        before = len(client.published)
        manager.publish_states({"class_name": "Clear", "confidence_score": 91.5, "Detection Time (Seconds)": 0.4})
        topics = [topic for topic, _, _ in client.published[before:]]
        self.assertEqual(len(topics), 3)
        for suffix in ("/status/state", "/confidence/state", "/detection_time/state"):
            self.assertTrue(any(t.endswith(suffix) for t in topics), suffix)

    def test_wrapper_builds_the_same_availability_topic(self):
        source = (ADDON_DIR / "ha_wrapper.py").read_text(encoding="utf-8")
        self.assertIn('f"{mqtt_discovery_prefix}/sensor/clouddetect_{device_id}/availability"', source)

    def test_detector_with_a_fake_model(self):
        import numpy as np
        import requests
        from PIL import Image

        class FakeModel:
            def predict(self, array, verbose=0):
                assert array.shape == (1, 224, 224, 3)
                return np.array([[0.1, 0.9]])

        with tempfile.TemporaryDirectory() as tmp:
            picture = Path(tmp) / "sky.jpg"
            Image.new("RGB", (32, 32), (10, 20, 30)).save(picture)
            labels = Path(tmp) / "labels.txt"
            labels.write_text("0 Clear\n1 Overcast\n", encoding="utf-8")
            config = self.make_config(image_url=picture.as_uri(), label_path=str(labels))
            client = FakeClient()

            with mock.patch.object(self.core, "load_model", return_value=FakeModel()):
                detector = self.core.CloudDetector(config, mqtt_client=client)

            self.assertIs(detector.mqtt_client, client)
            self.assertIsInstance(detector.session, requests.Session)
            self.assertEqual(detector.class_names, ["0 Clear\n", "1 Overcast\n"])
            self.assertIsNotNone(detector.ha_discovery)
            self.assertIn((AVAILABILITY, "online", True), client.published)

            result = detector.detect(return_image=True)
            self.assertEqual(result["class_name"], "Overcast")
            self.assertEqual(result["confidence_score"], 90.0)
            self.assertIsInstance(result["Detection Time (Seconds)"], float)
            self.assertIsInstance(result.pop("image"), Image.Image)

            before = len(client.published)
            detector.publish_result(result)
            self.assertEqual(len(client.published) - before, 3)

            detector.config.image_url = (Path(tmp) / "missing.jpg").as_uri()
            with mock.patch.object(self.core.time, "sleep"):
                with self.assertRaises(Exception):
                    detector.detect()

    def test_convert_model_exists_in_the_image_sources(self):
        tree = ast.parse((CORE_DIR / "convert.py").read_text(encoding="utf-8"))
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("convert_model", functions)
        self.assertEqual(functions["convert_model"].args.args[0].arg, "model_path")

    def test_image_ships_the_files_the_add_on_imports(self):
        dockerfile = (CORE_DIR / "Dockerfile").read_text(encoding="utf-8")
        copy_lines = [line for line in dockerfile.splitlines() if line.strip().startswith("COPY")]
        self.assertTrue(any("convert.py" in line and "detect.py" in line for line in copy_lines))
        self.assertIn("WORKDIR /app", dockerfile)


if __name__ == "__main__":
    unittest.main()
