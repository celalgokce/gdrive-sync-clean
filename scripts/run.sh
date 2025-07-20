#!/bin/bash
RELEASE_FILE=$1

if [ -z "$RELEASE_FILE" ]; then
    echo "Usage: ./run.sh <RELEASE_FILE>"
    exit 1
fi

echo "=== RUN STAGE ==="
echo "Deploying release: $RELEASE_FILE"

# Extract environment from release file
ENV=$(grep "environment:" $RELEASE_FILE | cut -d' ' -f2)

echo "Deploying to $ENV environment..."
docker-compose --env-file environments/$ENV/.env up -d

echo "Deployment completed for $ENV"
