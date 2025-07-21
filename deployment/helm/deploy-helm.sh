#!/bin/bash

ENV=${1:-development}
NAMESPACE=${2:-gdrive-s3-sync-$ENV}
RELEASE_NAME=${3:-gdrive-s3-sync-$ENV}

echo "🚀 Deploying GDrive-S3-Sync to $ENV environment"
echo "================================================"
echo "Environment: $ENV"
echo "Namespace: $NAMESPACE"
echo "Release: $RELEASE_NAME"
echo ""

# Go to project root
cd "$(dirname "$0")/../.."

# Validate environment
if [ ! -f "environments/$ENV/helm/values.secrets.yaml" ]; then
    echo "❌ Secrets file not found for environment: $ENV"
    echo "Expected: environments/$ENV/helm/values.secrets.yaml"
    exit 1
fi

# Check required files
if [ ! -f "src/gdrive_client/credentials.json" ]; then
    echo "❌ Missing credentials.json"
    exit 1
fi

if [ ! -f "src/gdrive_client/token.pickle" ]; then
    echo "❌ Missing token.pickle"
    exit 1
fi

# Create namespace if not exists
echo "📦 Creating namespace: $NAMESPACE"
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Decrypt secrets temporarily
echo "🔓 Decrypting secrets for $ENV..."
sops --decrypt environments/$ENV/helm/values.secrets.yaml > /tmp/values.secrets.decrypted.yaml

# Install/upgrade with Helm
echo "⛵ Installing/upgrading Helm chart..."
helm upgrade --install $RELEASE_NAME ./helm/gdrive-s3-sync \
  --namespace $NAMESPACE \
  --values helm/gdrive-s3-sync/values.yaml \
  --values /tmp/values.secrets.decrypted.yaml \
  --set-file secrets.gdrive.credentialsJson=src/gdrive_client/credentials.json \
  --set-file secrets.gdrive.tokenPickle=src/gdrive_client/token.pickle \
  --wait \
  --timeout=10m

# Clean up decrypted file
echo "🧹 Cleaning up temporary files..."
rm -f /tmp/values.secrets.decrypted.yaml

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Deployment completed successfully!"
    echo ""
    echo "📋 Useful commands:"
    echo "kubectl get pods -n $NAMESPACE"
    echo "kubectl logs -f deployment/$RELEASE_NAME-webhook -n $NAMESPACE"
    echo "kubectl port-forward svc/$RELEASE_NAME-webhook 5000:5000 -n $NAMESPACE"
    echo ""
    echo "🌐 Access webhook: http://localhost:5000"
else
    echo "❌ Deployment failed!"
    exit 1
fi
