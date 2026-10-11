"""MQTT client of the Home Assistant add-on (ha_addon/mqtt_setup.py)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the ha_addon folder

import mqtt_setup  # noqa: E402

AVAILABILITY = "homeassistant/sensor/clouddetect_addon_instance/availability"
IS_SAFE = "homeassistant/sensor/clouddetect_addon_instance/is_safe/state"


class FakeClient:
    def __init__(self, connect_error=None):
        self.connect_error = connect_error
        self.wills = []
        self.credentials = None
        self.on_connect = None
        self.calls = []

    def username_pw_set(self, username, password=None):
        self.credentials = (username, password)

    def will_set(self, topic, payload=None, qos=0, retain=False):
        self.wills.append((topic, payload, retain))

    def connect(self, host, port):
        self.calls.append("connect")
        if self.connect_error:
            raise self.connect_error

    def connect_async(self, host, port):
        self.calls.append("connect_async")

    def loop_start(self):
        self.calls.append("loop_start")


class FakeMqtt:
    def __init__(self, client):
        self._client = client

    def Client(self):  # noqa: N802 (name of the paho API)
        return self._client


def build(client, lwt="unsafe", username="user", password="pw", on_connected=None):
    return mqtt_setup.build_client(
        FakeMqtt(client), "core-mosquitto", 1883, username, password, lwt,
        AVAILABILITY, IS_SAFE, on_connected or (lambda: None))


class LastWillTest(unittest.TestCase):

    def test_unsafe_mode_sets_exactly_one_will_on_the_state_topic(self):
        client = FakeClient()
        build(client, lwt="unsafe")
        self.assertEqual(client.wills, [(IS_SAFE, "false", True)])

    def test_safe_mode_sets_exactly_one_will_on_the_state_topic(self):
        client = FakeClient()
        build(client, lwt="safe")
        self.assertEqual(client.wills, [(IS_SAFE, "true", True)])

    def test_none_mode_marks_the_entities_unavailable(self):
        client = FakeClient()
        build(client, lwt="none")
        self.assertEqual(client.wills, [(AVAILABILITY, "offline", True)])


class ConnectTest(unittest.TestCase):

    def test_connect_then_network_loop(self):
        client = FakeClient()
        build(client)
        self.assertEqual(client.calls, ["connect", "loop_start"])

    def test_unreachable_broker_keeps_retrying_instead_of_failing(self):
        client = FakeClient(connect_error=ConnectionRefusedError("refused"))
        build(client)
        self.assertEqual(client.calls, ["connect", "connect_async", "loop_start"])

    def test_username_without_password_is_used(self):
        client = FakeClient()
        build(client, username="user", password=None)
        self.assertEqual(client.credentials, ("user", None))

    def test_no_username_means_no_login(self):
        client = FakeClient()
        build(client, username=None, password=None)
        self.assertIsNone(client.credentials)


class OnConnectTest(unittest.TestCase):

    def test_every_successful_connect_runs_the_callback(self):
        client = FakeClient()
        callback = mock.Mock()
        build(client, on_connected=callback)
        client.on_connect(client, None, {}, 0)
        client.on_connect(client, None, {}, 0)  # reconnect after a broker restart
        self.assertEqual(callback.call_count, 2)

    def test_refused_connect_does_not_run_the_callback(self):
        client = FakeClient()
        callback = mock.Mock()
        build(client, on_connected=callback)
        client.on_connect(client, None, {}, 5)  # 5 = not authorised
        callback.assert_not_called()

    def test_mqtt_v5_signature_is_accepted(self):
        client = FakeClient()
        callback = mock.Mock()
        build(client, on_connected=callback)
        client.on_connect(client, None, {}, 0, None)
        callback.assert_called_once()

    def test_a_failing_callback_does_not_break_the_network_thread(self):
        client = FakeClient()
        build(client, on_connected=mock.Mock(side_effect=RuntimeError("boom")))
        client.on_connect(client, None, {}, 0)


class SupervisorCredentialsTest(unittest.TestCase):

    def response(self, payload):
        resp = mock.Mock()
        resp.json.return_value = payload
        return resp

    def test_reads_username_and_password(self):
        get = mock.Mock(return_value=self.response({"result": "ok", "data": {"username": "u", "password": "p"}}))
        self.assertEqual(mqtt_setup.supervisor_mqtt_credentials("token", get), ("u", "p"))
        url = get.call_args.args[0]
        self.assertEqual(url, "http://supervisor/services/mqtt")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer token"})

    def test_without_a_token_nothing_is_requested(self):
        get = mock.Mock()
        self.assertEqual(mqtt_setup.supervisor_mqtt_credentials(None, get), (None, None))
        get.assert_not_called()

    def test_errors_give_no_credentials(self):
        get = mock.Mock(side_effect=OSError("down"))
        self.assertEqual(mqtt_setup.supervisor_mqtt_credentials("token", get), (None, None))


if __name__ == '__main__':
    unittest.main()
