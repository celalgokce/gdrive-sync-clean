#!/bin/bash

echo "🚀 Starting GDrive-S3-Sync Production Deployment"
echo "================================================="

# Check prerequisites
echo "✅ Checking prerequisites..."
if [ ! -f "src/gdrive_client/credentials.json" ]; then
    echo "❌ Missing credentials.json"
    exit 1
fi

if [ ! -f "src/gdrive_client/token.pickle" ]; then
    echo "❌ Missing token.pickle"
    exit 1
fi

# Clean up existing containers
echo "🧹 Cleaning up existing containers..."
docker-compose down -v
docker system prune -f

# Build and deploy
echo "🔨 Building and deploying services..."
docker-compose build --no-cache
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 60

# Health checks
echo "🏥 Running health checks..."
echo "Webhook: $(curl -s http://localhost:5000/health | jq -r .status)"
echo "Prometheus: $(curl -s http://localhost:9090/-/healthy || echo "Not ready")"
echo "Grafana: $(curl -s http://localhost:3000/api/health | jq -r .status)"

# Display service status
echo ""
echo "📊 Service Status:"
docker-compose ps

echo ""
echo "🎯 Deployment complete!"
echo "Webhook: http://localhost:5000"
echo "Prometheus: http://localhost:9090"
echo "Grafana: http://localhost:3000 (admin/admin123)"
echo "RabbitMQ: http://localhost:15672 (gdrive_user/gdrive_pass123)"
