FROM python:3.13-alpine
ARG BUILD_VERSION=1.0.2
ARG BUILD_ARCH
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="aarch64|amd64"
WORKDIR /app
COPY relay.py /app/relay.py
EXPOSE 8766
CMD ["python", "-u", "/app/relay.py"]
