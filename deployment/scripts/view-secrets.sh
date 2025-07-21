#!/bin/bash

ENV=${1:-development}

if [ ! -f "environments/$ENV/helm/values.secrets.yaml" ]; then
    echo "❌ Secrets file not found for environment: $ENV"
    exit 1
fi

echo "👀 Viewing secrets for $ENV environment:"
echo "========================================"
sops --decrypt environments/$ENV/helm/values.secrets.yaml
