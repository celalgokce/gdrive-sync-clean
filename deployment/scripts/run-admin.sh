#!/bin/bash
# 12-Factor Admin Process Runner

ENV=${1:-development}
PROCESS_NAME=${2:-health-check}
shift 2
ARGS="$@"

if [ -z "$PROCESS_NAME" ]; then
    echo "Usage: ./deployment/scripts/run-admin.sh <environment> <process-name> [args...]"
    echo "Available processes:"
    echo "  migrate-state  - Migrate state from file to Redis"
    echo "  health-check   - Run comprehensive health check"
    echo "  reset-state    - Reset sync state"
    exit 1
fi

# Go to project root
cd "$(dirname "$0")/../.."

echo "🔧 Running admin process: $PROCESS_NAME (env: $ENV)"
echo "================================================="

# Run as one-off container
docker run --rm \
    --network gdrive-s3-production_gdrive_network \
    -v $(pwd)/src:/app/src \
    -e ENV=$ENV \
    -e GDRIVE_FOLDER_ID=1TcG_cbVfaRvPUyaPaqyPZVEd5p_eA_s_ \
    -e AWS_S3_BUCKET=gdrive-sync-demo \
    -e RABBITMQ_URL=amqp://gdrive_user:gdrive_pass123@rabbitmq:5672/gdrive_sync \
    gdrive-s3-production-webhook-listener:latest \
    python src/admin_processes/admin.py $PROCESS_NAME $ARGS

echo "🏁 Admin process completed"
