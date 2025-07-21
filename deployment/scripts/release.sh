#!/bin/bash
BUILD_ID=$1
ENV=$2

if [ -z "$BUILD_ID" ] || [ -z "$ENV" ]; then
    echo "Usage: ./release.sh <BUILD_ID> <ENV>"
    exit 1
fi

echo "=== RELEASE STAGE ==="
echo "Creating release for $ENV environment with build $BUILD_ID"

# Create release manifest
cat > releases/release-$BUILD_ID-$ENV.yml << EOL
build_id: $BUILD_ID
environment: $ENV
timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)
images:
  webhook: gdrive-webhook:$BUILD_ID
  s3-uploader: gdrive-s3-uploader:$BUILD_ID
  scheduler: gdrive-scheduler:$BUILD_ID
config_file: environments/$ENV/.env
EOL

echo "Release manifest created: releases/release-$BUILD_ID-$ENV.yml"
