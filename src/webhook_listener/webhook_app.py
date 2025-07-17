import os
import sys
import json
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import pika
from werkzeug.middleware.proxy_fix import ProxyFix

# Add the shared directory to Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../shared')))

try:
    from config import get_config
    config = get_config()
except ImportError as e:
    print(f"❌ Config import error: {e}")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# RabbitMQ connection
def get_rabbitmq_connection():
    return pika.BlockingConnection(pika.URLParameters(config.RABBITMQ_URL))

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # Get webhook data
        data = request.get_json() or {}
        
        # Create webhook message
        webhook_message = {
            'timestamp': datetime.utcnow().isoformat(),
            'headers': dict(request.headers),
            'data': data,
            'source': 'webhook'
        }
        
        # Send to RabbitMQ
        try:
            connection = get_rabbitmq_connection()
            channel = connection.channel()
            channel.queue_declare(queue='webhook_queue', durable=True)
            
            channel.basic_publish(
                exchange='',
                routing_key='webhook_queue',
                body=json.dumps(webhook_message),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            
            connection.close()
            logger.info("Message sent to webhook_queue successfully")
            
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            return jsonify({'error': 'Failed to publish webhook message'}), 500
        
        return jsonify({'status': 'success', 'message': 'Webhook received and queued'}), 200
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({'error': 'Internal processing error'}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()}), 200

@app.route('/config', methods=['GET'])
def show_config():
    return jsonify({
        'config': {
            'gdrive_folder_id': config.GDRIVE_FOLDER_ID,
            's3_bucket': config.AWS_S3_BUCKET,
            'webhook_host': config.WEBHOOK_HOST,
            'webhook_port': config.WEBHOOK_PORT,
            'log_level': config.LOG_LEVEL
        }
    })

@app.route('/metrics', methods=['GET'])
def metrics():
    return "webhook_requests_total 1", 200

if __name__ == '__main__':
    logger.info("Starting webhook listener - IP control DISABLED")
    app.run(
        host=config.WEBHOOK_HOST,
        port=config.WEBHOOK_PORT,
        debug=False
    )
