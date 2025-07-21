#!/bin/bash

ENV=${1:-development}

echo "🐳 Starting Docker Compose Deployment - Environment: $ENV"
echo "================================================="

# Go to project root
cd "$(dirname "$0")/../.."

# Check environment exists
if [ ! -d "environments/$ENV" ]; then
    echo "Environment $ENV not found. Using default configuration."
    ENV="default"
fi

# Check prerequisites
echo "Checking prerequisites..."
if [ ! -f "src/gdrive_client/credentials.json" ]; then
    echo "❌ Missing credentials.json"
    exit 1
fi

if [ ! -f "src/gdrive_client/token.pickle" ]; then
    echo "❌ Missing token.pickle"
    exit 1
fi

# Load environment variables if exists
if [ -f "environments/$ENV/.env" ]; then
    echo "Loading environment variables from environments/$ENV/.env"
    export $(cat environments/$ENV/.env | xargs)
else
    echo "Using default environment variables"
fi

# Clean up existing containers
echo "Cleaning up existing containers..."
docker-compose -f deployment/docker/docker-compose.yml down -v
docker system prune -f

# Build and deploy
echo "Building and deploying services..."
if [ -f "environments/$ENV/.env" ]; then
    docker-compose -f deployment/docker/docker-compose.yml --env-file environments/$ENV/.env build --no-cache
    docker-compose -f deployment/docker/docker-compose.yml --env-file environments/$ENV/.env up -d
else
    docker-compose -f deployment/docker/docker-compose.yml build --no-cache
    docker-compose -f deployment/docker/docker-compose.yml up -d
fi

# Wait for services to be ready
echo "Waiting for services to be ready..."
sleep 60

# Health checks
echo "Running health checks..."
echo "Webhook: $(curl -s http://localhost:5000/health | jq -r .status || echo "Not ready")"
echo "Prometheus: $(curl -s http://localhost:9090/-/healthy || echo "Not ready")"
echo "Grafana: $(curl -s http://localhost:3000/api/health | jq -r .status || echo "Not ready")"

# Display service status
echo ""
echo "Service Status:"
docker-compose -f deployment/docker/docker-compose.yml ps

echo ""
echo "✅ Docker deployment complete for $ENV environment!"
echo "🌐 Webhook: http://localhost:5000"
echo "📊 Prometheus: http://localhost:9090"
echo "📈 Grafana: http://localhost:3000 (admin/admin123)"
echo "🐰 RabbitMQ: http://localhost:15672 (gdrive_user/gdrive_pass123)"

if [ "$ENV" != "default" ]; then
    echo "🪣 S3 Bucket: $AWS_S3_BUCKET"
    echo "📊 Log Level: $LOG_LEVEL"
fi
