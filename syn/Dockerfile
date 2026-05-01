ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.name="Syn" \
    io.hass.description="AI-assisted scene creation add-on" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Copy requirements and install
COPY requirements.txt .
RUN apk add --no-cache python3 py3-pip
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app ./app
COPY integration ./integration

# Expose port
EXPOSE 8000

# Run FastAPI with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
