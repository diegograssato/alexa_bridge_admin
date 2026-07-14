ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.13-alpine3.22

ENV PYTHONUNBUFFERED=1 \
	PYTHONDONTWRITEBYTECODE=1 \
	PIP_NO_CACHE_DIR=1 \
	PYTHONPATH=/

WORKDIR /

COPY rootfs/app/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

COPY rootfs/app /app

EXPOSE 8099

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099", "--workers", "1", "--log-level", "info"]
