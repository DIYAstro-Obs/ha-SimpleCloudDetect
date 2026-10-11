FROM chvvkumar/simpleclouddetect:latest

# HTTP healthcheck against the JSON state endpoint. The endpoint answers 503 when the detection
# loop has stopped completing cycles, so a hung loop marks the container unhealthy.
# The start period covers the TensorFlow import and model load on slow hardware.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://127.0.0.1:8099/api/state || exit 1

# Run as root to copy wrapper and properly map HA /share folder
USER root

COPY ha_wrapper.py safety_logic.py mqtt_setup.py /app/
RUN chmod +x /app/ha_wrapper.py

# Set PYTHONPATH so ha_wrapper.py can reliably import detect.py
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/usr/bin/env", "python3"]
CMD ["-u", "/app/ha_wrapper.py"]
