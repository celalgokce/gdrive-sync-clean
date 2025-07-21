#!/bin/bash
echo "=== BUILD STAGE ==="
echo "Building Docker images..."
docker-compose build --no-cache

echo "Tagging with build number..."
BUILD_ID=$(date +%Y%m%d-%H%M%S)
docker tag gdrive-s3-production-webhook-listener:latest gdrive-webhook:$BUILD_ID
docker tag gdrive-s3-production-s3-uploader:latest gdrive-s3-uploader:$BUILD_ID
docker tag gdrive-s3-production-auto-scheduler:latest gdrive-scheduler:$BUILD_ID

echo "Build completed: $BUILD_ID"
