"""MQTT connection of the add-on: Last Will, reconnect handling and credentials from the Supervisor."""
import logging

logger = logging.getLogger(__name__)

SUPERVISOR_MQTT_URL = "http://supervisor/services/mqtt"


def supervisor_mqtt_credentials(token, get, timeout=5):
    """Username and password of the MQTT service, as the Supervisor hands them to add-ons that
    declare `services: mqtt:need`. `get` is requests.get. Returns (None, None) if unavailable."""
    if not token:
        return None, None
    try:
        response = get(SUPERVISOR_MQTT_URL, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
        response.raise_for_status()
        data = response.json().get("data") or {}
        return data.get("username") or None, data.get("password") or None
    except Exception as err:
        logger.warning(f"Could not read the MQTT service from the Supervisor: {err}")
        return None, None


def build_client(mqtt_lib, host, port, username, password, lwt_logic,
                 availability_topic, is_safe_topic, on_connected):
    """Create the paho client, set its Last Will and start the network loop.

    MQTT allows one Will per connection, so `lwt_logic` decides which one it is:
    'unsafe' / 'safe' publish "false" / "true" on the is_safe topic, 'none' publishes "offline"
    on the availability topic (the entities then show as unavailable).

    `on_connected()` runs after every successful connect, including reconnects after a broker
    restart, from paho's network thread. A broker that is not reachable at start does not abort:
    paho keeps retrying in the background.
    """
    client = mqtt_lib.Client()
    if username:
        client.username_pw_set(username, password or None)

    if lwt_logic == "unsafe":
        client.will_set(is_safe_topic, "false", retain=True)
    elif lwt_logic == "safe":
        client.will_set(is_safe_topic, "true", retain=True)
    else:
        client.will_set(availability_topic, "offline", retain=True)

    # paho 1.x style (client, userdata, flags, rc); `properties` is passed by MQTT v5 only.
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc != 0:
            logger.error(f"MQTT broker {host}:{port} refused the connection (code {rc}); "
                         "check the MQTT user and password")
            return
        logger.info(f"Connected to MQTT broker at {host}:{port}")
        try:
            on_connected()
        except Exception as err:
            logger.error(f"Failed to publish after the MQTT connect: {err}")

    client.on_connect = on_connect

    try:
        client.connect(host, port)
    except OSError as err:
        logger.warning(f"MQTT broker {host}:{port} is not reachable yet ({err}); retrying in the background")
        client.connect_async(host, port)
    client.loop_start()
    return client
