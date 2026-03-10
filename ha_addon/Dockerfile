FROM chvvkumar/simpleclouddetect:latest

# We use a real HTTP healthcheck to ensure the internal web server and processing loop are alive.
# This check hits the JSON state endpoint. If it fails, the HA Watchdog restarts the container.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://127.0.0.1:8099/api/state || exit 1

# Run as root to copy wrapper and properly map HA /share folder
USER root

COPY ha_wrapper.py /app/ha_wrapper.py
RUN chmod +x /app/ha_wrapper.py

# Set PYTHONPATH so ha_wrapper.py can reliably import detect.py
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/usr/bin/env", "python3"]
CMD ["-u", "/app/ha_wrapper.py"]
