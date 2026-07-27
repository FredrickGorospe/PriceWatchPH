# Pinned to a resolved patch tag (verified against Docker Hub at task-implementation
# time) rather than a floating `3.12` tag, so the image doesn't silently drift.
FROM python:3.12.13-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
