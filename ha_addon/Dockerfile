FROM chvvkumar/simpleclouddetect:latest

# We provide a dummy healthcheck to stop the Home Assistant loading spinner.
# The original web server is disabled, so we just declare it healthy immediately.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import sys; sys.exit(0)"

# Run as root to copy wrapper and properly map HA /share folder
USER root

COPY ha_wrapper.py /app/ha_wrapper.py
RUN chmod +x /app/ha_wrapper.py

# Set PYTHONPATH so ha_wrapper.py can reliably import detect.py
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/usr/bin/env", "python3"]
CMD ["-u", "/app/ha_wrapper.py"]
