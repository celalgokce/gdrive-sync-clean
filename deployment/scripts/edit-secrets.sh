#!/bin/bash

ENV=${1:-development}

if [ ! -f "environments/$ENV/helm/values.secrets.yaml" ]; then
    echo "❌ Secrets file not found for environment: $ENV"
    echo "Available environments:"
    ls environments/*/helm/values.secrets.yaml 2>/dev/null | sed 's|environments/||; s|/helm/values.secrets.yaml||'
    exit 1
fi

echo "✏️  Editing secrets for $ENV environment..."
sops environments/$ENV/helm/values.secrets.yaml
