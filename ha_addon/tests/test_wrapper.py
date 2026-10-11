"""Wrapper of the Home Assistant add-on (ha_addon/ha_wrapper.py): downloads, model conversion,
web server and the detection loop with a fake detector and a fake clock. No TensorFlow, broker
or Home Assistant needed."""
import contextlib
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the ha_addon folder

import ha_wrapper  # noqa: E402

IS_SAFE = "homeassistant/sensor/clouddetect_addon_instance/is_safe/state"
IS_SAFE_CONFIG = "homeassistant/sensor/clouddetect_addon_instance/is_safe/config"


class StateIsolatedTest(unittest.TestCase):
    """GLOBAL_STATE and LOOP_HEARTBEAT are module globals; every test gets its own copy."""

    def setUp(self):
        for target in (ha_wrapper.GLOBAL_STATE, ha_wrapper.LOOP_HEARTBEAT):
            patcher = mock.patch.dict(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)


class FakeResponse:
    def __init__(self, chunks, headers=None, fail_after=None):
        self.chunks = chunks
        self.headers = headers or {}
        self.fail_after = fail_after

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=8192):
        for index, chunk in enumerate(self.chunks):
            if self.fail_after is not None and index >= self.fail_after:
                raise requests.exceptions.ChunkedEncodingError("connection cut")
            yield chunk


class DownloadFileTest(StateIsolatedTest):

    def download(self, response):
        destination = self.tmp / "keras_model.h5"
        with mock.patch.object(ha_wrapper.requests, "get", return_value=response):
            ok = ha_wrapper.download_file("http://example/keras_model.h5", destination)
        return ok, destination

    def test_complete_download_appears_under_its_name(self):
        ok, destination = self.download(FakeResponse([b"abc", b"def"], {"Content-Length": "6"}))
        self.assertTrue(ok)
        self.assertEqual(destination.read_bytes(), b"abcdef")
        self.assertFalse(destination.with_name("keras_model.h5.part").exists())

    def test_interrupted_download_leaves_nothing_behind(self):
        ok, destination = self.download(FakeResponse([b"abc", b"def"], fail_after=1))
        self.assertFalse(ok)
        self.assertFalse(destination.exists())
        self.assertFalse(destination.with_name("keras_model.h5.part").exists())

    def test_short_download_is_rejected(self):
        ok, destination = self.download(FakeResponse([b"abc"], {"Content-Length": "10"}))
        self.assertFalse(ok)
        self.assertFalse(destination.exists())

    def test_empty_download_is_rejected(self):
        ok, destination = self.download(FakeResponse([]))
        self.assertFalse(ok)
        self.assertFalse(destination.exists())

    def test_content_length_is_not_compared_with_encoded_transfer(self):
        ok, destination = self.download(
            FakeResponse([b"abcdef"], {"Content-Length": "3", "Content-Encoding": "gzip"}))
        self.assertTrue(ok)


class EnsureModelsTest(StateIsolatedTest):

    def setUp(self):
        super().setUp()
        self.share = self.tmp / "share"
        self.app = self.tmp / "app"
        self.app.mkdir()
        for target, value in (("SHARE_DIR", self.share), ("APP_DIR", self.app)):
            patcher = mock.patch.object(ha_wrapper, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.convert = mock.Mock()
        patcher = mock.patch.dict(sys.modules, {"convert": types.SimpleNamespace(convert_model=self.convert)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_existing_files_are_kept_and_the_model_is_converted(self):
        self.share.mkdir()
        (self.share / "keras_model.h5").write_bytes(b"custom")
        (self.share / "labels.txt").write_text("0 Clear")
        with mock.patch.object(ha_wrapper, "download_file") as download:
            ha_wrapper.ensure_models()
        download.assert_not_called()
        self.assertEqual((self.share / "keras_model.h5").read_bytes(), b"custom")
        self.convert.assert_called_once_with(str(self.share / "keras_model.h5"))

    def test_missing_files_are_downloaded_then_converted(self):
        def fake_download(url, destination):
            destination.write_bytes(b"data")
            return True
        with mock.patch.object(ha_wrapper, "download_file", side_effect=fake_download) as download:
            ha_wrapper.ensure_models()
        self.assertEqual(download.call_count, 2)
        self.convert.assert_called_once_with(str(self.share / "keras_model.h5"))

    def test_failed_download_is_not_fatal_and_nothing_is_converted(self):
        with mock.patch.object(ha_wrapper, "download_file", return_value=False):
            ha_wrapper.ensure_models()
        self.convert.assert_not_called()

    def test_default_files_are_copied_from_the_image_first(self):
        (self.app / "keras_model.h5").write_bytes(b"image model")
        (self.app / "labels.txt").write_text("0 Clear")
        with mock.patch.object(ha_wrapper, "download_file") as download:
            ha_wrapper.ensure_models()
        download.assert_not_called()
        self.assertEqual((self.share / "keras_model.h5").read_bytes(), b"image model")

    def test_a_failing_conversion_does_not_stop_the_start(self):
        self.share.mkdir()
        (self.share / "keras_model.h5").write_bytes(b"custom")
        (self.share / "labels.txt").write_text("0 Clear")
        self.convert.side_effect = OSError("read-only file system")
        ha_wrapper.ensure_models()


class WebServerTest(StateIsolatedTest):

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(ha_wrapper, "TMP_IMAGE_PATH", self.tmp / "latest.jpg")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ha_wrapper.WebUIHandler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path):
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}/{path}"
        try:
            with self.opener.open(url, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.read()

    def test_state_is_served(self):
        status, body = self.get("api/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertFalse(state["stale"])
        self.assertIn("is_safe", state)

    def test_state_is_503_when_the_loop_stopped_completing_cycles(self):
        ha_wrapper.LOOP_HEARTBEAT.update(last=time.time() - 1000, timeout=100)
        status, body = self.get("api/state")
        self.assertEqual(status, 503)
        self.assertTrue(json.loads(body)["stale"])

    def test_a_recent_heartbeat_is_healthy(self):
        ha_wrapper.LOOP_HEARTBEAT.update(last=time.time() - 10, timeout=100)
        self.assertEqual(self.get("api/state")[0], 200)

    def test_state_is_healthy_before_the_loop_has_started(self):
        ha_wrapper.LOOP_HEARTBEAT.update(last=None, timeout=None)
        self.assertEqual(self.get("api/state")[0], 200)

    def test_latest_image_is_404_until_written_then_a_complete_jpeg(self):
        self.assertEqual(self.get("latest.jpg")[0], 404)
        ha_wrapper.save_latest_image(Image.new("RGB", (8, 8), (10, 20, 30)))
        status, body = self.get("latest.jpg")
        self.assertEqual(status, 200)
        self.assertEqual(body[:2], b"\xff\xd8")
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])

    def test_page_is_english(self):
        status, body = self.get("")
        self.assertEqual(status, 200)
        self.assertNotIn(b"Wechsel", body)
        self.assertIn(b"Switching to", body)


class FakeClock:
    """Stands in for the time module: sleeping advances the clock and ends the loop after N cycles."""

    class Stop(Exception):
        pass

    def __init__(self, start, cycles):
        self.now = start
        self.cycles = cycles
        self.sleeps = 0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps >= self.cycles:
            raise self.Stop()
        self.now += seconds

    def strftime(self, fmt):
        return "2026-01-01 00:00:00"


class FakeDiscovery:
    availability_topic = "homeassistant/sensor/clouddetect_addon_instance/availability"

    def __init__(self):
        self.published = 0

    def get_device_info(self):
        return {"identifiers": ["clouddetect_addon_instance"]}

    def publish_discovery_configs(self):
        self.published += 1


class FakeDetector:
    results = []
    instances = []

    def __init__(self, config, mqtt_client=None):
        self.config = config
        self.mqtt_client = mqtt_client
        self.session = types.SimpleNamespace(headers={})
        self.class_names = ["0 Clear\n", "1 Overcast\n"]
        self.ha_discovery = FakeDiscovery() if mqtt_client else None
        FakeDetector.instances.append(self)

    def detect(self, return_image=False):
        item = FakeDetector.results.pop(0)
        if isinstance(item, Exception):
            raise item
        result = {"class_name": item[0], "confidence_score": item[1], "Detection Time (Seconds)": 0.5}
        if return_image:
            result["image"] = Image.new("RGB", (4, 4))
        return result

    def publish_result(self, result):
        pass


class FakeConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeMqttClient:
    def __init__(self):
        self.published = []  # (topic, payload, retain)

    def publish(self, topic, payload=None, retain=False):
        self.published.append((topic, payload, retain))

    def is_connected(self):
        return True

    def states(self):
        """Non-retained payloads on the is_safe topic, one per detection cycle."""
        return [p for t, p, r in self.published if t == IS_SAFE and not r]


BASE_OPTIONS = {
    "camera_url": "http://cam/img.jpg", "camera_entity": "",
    "mqtt_broker": "core-mosquitto", "mqtt_port": 1883, "mqtt_user": "user", "mqtt_password": "pw",
    "mqtt_topic": "simpleclouddetect/state", "mqtt_discovery_prefix": "homeassistant",
    "scan_interval": 60, "safe_wait_time": 300, "unsafe_wait_time": 0,
    "safe_conditions": [{"label": "Clear", "threshold": 50}], "mqtt_lwt_logic": "unsafe",
}


class MainLoopTest(StateIsolatedTest):

    def run_main(self, results, cycles, options=None, environ=None, credentials=None):
        options = dict(BASE_OPTIONS, **(options or {}))
        share = self.tmp / "share"
        share.mkdir()
        (share / "keras_model.h5").write_bytes(b"model")
        (share / "labels.txt").write_text("0 Clear\n1 Overcast\n")
        options_path = self.tmp / "options.json"
        options_path.write_text(json.dumps(options))

        FakeDetector.results = list(results)
        FakeDetector.instances = []
        client = FakeMqttClient()
        captured = {}

        def fake_build_client(mqtt_lib, host, port, user, password, lwt, availability, is_safe, on_connected):
            captured.update(host=host, port=port, user=user, password=password, lwt=lwt,
                            availability=availability, is_safe=is_safe, on_connected=on_connected)
            return client

        fake_detect = types.ModuleType("detect")
        fake_detect.CloudDetector = FakeDetector
        fake_detect.Config = FakeConfig
        self.convert = mock.Mock()
        self.supervisor_credentials = mock.Mock(return_value=credentials or (None, None))
        clock = FakeClock(1000.0, cycles)

        with contextlib.ExitStack() as stack:
            for target, value in (("OPTIONS_PATH", str(options_path)), ("SHARE_DIR", share),
                                  ("APP_DIR", self.tmp), ("TMP_IMAGE_PATH", self.tmp / "latest.jpg"),
                                  ("start_web_server", mock.Mock()), ("time", clock)):
                stack.enter_context(mock.patch.object(ha_wrapper, target, value))
            stack.enter_context(mock.patch.object(ha_wrapper.mqtt_setup, "build_client", fake_build_client))
            stack.enter_context(mock.patch.object(
                ha_wrapper.mqtt_setup, "supervisor_mqtt_credentials", self.supervisor_credentials))
            stack.enter_context(mock.patch.dict(sys.modules, {
                "detect": fake_detect, "convert": types.SimpleNamespace(convert_model=self.convert)}))
            stack.enter_context(mock.patch("os.chdir"))
            stack.enter_context(mock.patch.object(sys, "path", list(sys.path)))
            stack.enter_context(mock.patch.dict(os.environ, environ or {}))
            with self.assertRaises(FakeClock.Stop):
                ha_wrapper.main()
        return client, captured, (FakeDetector.instances[0] if FakeDetector.instances else None)

    def test_state_is_published_every_cycle_also_while_waiting(self):
        client, captured, detector = self.run_main([("Clear", 90.0)] * 7, cycles=7)
        # Five cycles until safe_wait (300 s) has elapsed: the safe default is published meanwhile.
        self.assertEqual(client.states(), ["false"] * 5 + ["true"] * 2)
        self.assertEqual(captured["lwt"], "unsafe")
        self.assertEqual((captured["user"], captured["password"]), ("user", "pw"))
        self.assertTrue(ha_wrapper.GLOBAL_STATE["is_safe"])
        self.assertTrue((self.tmp / "latest.jpg").exists())
        self.convert.assert_called_once_with(str(self.tmp / "share" / "keras_model.h5"))

    def test_discovery_and_the_initial_false_are_published_once_at_start(self):
        client, _, detector = self.run_main([("Clear", 90.0)], cycles=1)
        self.assertEqual(detector.ha_discovery.published, 1)
        self.assertIn((IS_SAFE_CONFIG, mock.ANY, True), client.published)
        self.assertEqual([p for p in client.published if p[0] == IS_SAFE and p[2]], [(IS_SAFE, "false", True)])

    def test_unsafe_reading_is_reported_at_once(self):
        client, _, _ = self.run_main([("Overcast", 90.0)] * 2, cycles=2)
        self.assertEqual(client.states(), ["false", "false"])
        self.assertFalse(ha_wrapper.GLOBAL_STATE["is_safe"])

    def test_dead_camera_turns_a_safe_state_unsafe(self):
        results = [("Clear", 90.0)] * 6 + [RuntimeError("camera 500")] * 6
        client, _, _ = self.run_main(results, cycles=12)
        # safe at cycle 5 (last success at +300 s); failures from +360 s; limit of 180 s reached at +480 s
        self.assertEqual(client.states(), ["false"] * 5 + ["true"] * 3 + ["false"] * 4)
        self.assertIn("No new picture since", ha_wrapper.GLOBAL_STATE["error"])
        self.assertIn("camera 500", ha_wrapper.GLOBAL_STATE["error"])

    def test_error_is_cleared_when_pictures_return(self):
        results = [RuntimeError("camera 500"), ("Clear", 90.0)]
        self.run_main(results, cycles=2)
        self.assertIsNone(ha_wrapper.GLOBAL_STATE["error"])

    def test_error_before_any_picture_says_so(self):
        self.run_main([RuntimeError("no route to host")], cycles=1)
        self.assertEqual(ha_wrapper.GLOBAL_STATE["error"], "No new picture yet: no route to host")

    def test_reconnect_announces_again_and_republishes_the_state(self):
        client, captured, detector = self.run_main([("Clear", 90.0)] * 7, cycles=7)
        before = len(client.published)
        captured["on_connected"]()  # paho's on_connect after a broker restart
        self.assertEqual(detector.ha_discovery.published, 2)
        new = client.published[before:]
        self.assertIn((IS_SAFE_CONFIG, mock.ANY, True), new)
        self.assertEqual(new[-1], (IS_SAFE, "true", False))
        self.assertNotIn((IS_SAFE, "false", True), new)  # the retained default is only sent at start

    def test_login_comes_from_the_supervisor_when_the_options_are_empty(self):
        _, captured, _ = self.run_main(
            [("Clear", 90.0)], cycles=1, options={"mqtt_user": "", "mqtt_password": ""},
            environ={"SUPERVISOR_TOKEN": "tok"}, credentials=("svc-user", "svc-pw"))
        self.assertEqual((captured["user"], captured["password"]), ("svc-user", "svc-pw"))
        self.supervisor_credentials.assert_called_once()

    def test_configured_login_is_not_replaced(self):
        self.run_main([("Clear", 90.0)], cycles=1)
        self.supervisor_credentials.assert_not_called()

    def test_camera_entity_goes_through_the_supervisor_proxy(self):
        _, _, detector = self.run_main(
            [("Clear", 90.0)], cycles=1, options={"camera_url": "", "camera_entity": "allsky"},
            environ={"SUPERVISOR_TOKEN": "tok"})
        self.assertEqual(detector.config.image_url, "http://supervisor/core/api/camera_proxy/camera.allsky")
        self.assertEqual(detector.session.headers, {"Authorization": "Bearer tok"})

    def test_without_a_camera_the_ui_says_so(self):
        with self.assertLogs("ha_wrapper", level="ERROR"):
            self.run_main([], cycles=1, options={"camera_url": "", "camera_entity": ""})
        self.assertEqual(ha_wrapper.GLOBAL_STATE["status"], "Not configured")
        self.assertIn("camera_entity", ha_wrapper.GLOBAL_STATE["error"])


if __name__ == '__main__':
    unittest.main()
