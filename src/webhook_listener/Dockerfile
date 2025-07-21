FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/
COPY .env* ./

# Copy Google Drive credentials and token
COPY src/gdrive_client/credentials.json ./credentials.json
COPY src/gdrive_client/token.pickle ./token.pickle

# Set Python path
ENV PYTHONPATH=/app

# Create logs directory
RUN mkdir -p /app/logs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Expose port
EXPOSE 5000

# Run application
CMD ["python", "src/webhook_listener/webhook_app.py"]
