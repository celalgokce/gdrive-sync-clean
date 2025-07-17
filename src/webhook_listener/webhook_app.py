import os
import sys
import logging
from flask import Flask, request, jsonify
import pika
import json
from datetime import datetime
from functools import wraps
import ipaddress

# Add paths for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../shared')))

from config import get_config

# Initialize config
config = get_config()

# Logging configuration
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class WebhookValidator:
    """Webhook validation and security"""
    
    def __init__(self):
        self.verification_token = config.WEBHOOK_VERIFICATION_TOKEN
        self.allowed_ips = self._parse_allowed_ips()
    
    def _parse_allowed_ips(self):
        """Parse allowed IP addresses from config"""
        try:
            return [ipaddress.ip_address(ip.strip()) for ip in config.ALLOWED_IPS]
        except Exception as e:
            logger.warning(f"Error parsing allowed IPs: {e}")
            return [ipaddress.ip_address('127.0.0.1')]
    
    def validate_ip(self, client_ip):
        """Validate client IP address"""
        try:
            client_addr = ipaddress.ip_address(client_ip)
            return client_addr in self.allowed_ips
        except Exception as e:
            logger.warning(f"IP validation error: {e}")
            return False
    
    def validate_headers(self, headers):
        """Validate webhook headers"""
        logger.info(f"Validating headers: {headers}")
        
        # Check verification token
        token = headers.get('X-Goog-Channel-Token')
        logger.info(f"Token from header: '{token}', Expected: '{self.verification_token}'")
        
        if token != self.verification_token:
            logger.warning(f"Invalid verification token: {token}")
            return False
        
        # Check required headers
        required_headers = ['X-Goog-Channel-Id', 'X-Goog-Resource-State']
        for header in required_headers:
            if header not in headers:
                logger.warning(f"Missing required header: {header}")
                return False
            logger.info(f"Found required header: {header} = {headers[header]}")
        
        # Validate resource state
        valid_states = ['sync', 'update', 'exists', 'not_exists', 'trash', 'untrash']
        resource_state = headers.get('X-Goog-Resource-State')
        logger.info(f"Resource state: '{resource_state}', Valid states: {valid_states}")
        
        if resource_state not in valid_states:
            logger.warning(f"Invalid resource state: {resource_state}")
            return False
        
        logger.info("All headers validated successfully")
        return True

class RabbitMQManager:
    """RabbitMQ connection management"""
    
    def __init__(self):
        self.rabbitmq_url = config.RABBITMQ_URL
        self.connection = None
        self.channel = None
        self._connect()
    
    def _connect(self):
        """Connect to RabbitMQ"""
        try:
            self.connection = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
            self.channel = self.connection.channel()
            
            # Declare exchange and queue
            self.channel.exchange_declare(exchange='gdrive_events', exchange_type='topic', durable=True)
            self.channel.queue_declare(queue='webhook_queue', durable=True)
            self.channel.queue_bind(exchange='gdrive_events', queue='webhook_queue', routing_key='file.*')
            
            logger.info("Connected to RabbitMQ successfully")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    def publish_message(self, message, routing_key='file.webhook'):
        """Publish message to RabbitMQ"""
        try:
            if not self.connection or self.connection.is_closed:
                self._connect()
            
            self.channel.basic_publish(
                exchange='gdrive_events',
                routing_key=routing_key,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # Persistent message
                    timestamp=int(datetime.utcnow().timestamp()),
                    content_type='application/json'
                )
            )
            logger.info(f"Message published to queue: {routing_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            return False

# Initialize components
validator = WebhookValidator()
rabbitmq_manager = RabbitMQManager()

def require_valid_ip(f):
    """Decorator to validate client IP"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = request.remote_addr
        if not validator.validate_ip(client_ip):
            logger.warning(f"Blocked request from unauthorized IP: {client_ip}")
            return jsonify({'error': 'Unauthorized IP address'}), 403
        return f(*args, **kwargs)
    return decorated_function

@app.route('/webhook', methods=['POST'])
@require_valid_ip
def webhook():
    """Google Drive webhook endpoint with validation"""
    try:
        # Extract headers
        headers = dict(request.headers)
        client_ip = request.remote_addr
        
        logger.info(f"Webhook received from {client_ip}")
        logger.debug(f"Headers: {headers}")
        
        # Validate headers
        if not validator.validate_headers(headers):
            return jsonify({'error': 'Invalid webhook headers'}), 400
        
        # Create message
        message = {
            'event_id': headers.get('X-Goog-Channel-Id'),  # Note: lowercase 'd'
            'event_type': 'webhook_received',
            'resource_state': headers.get('X-Goog-Resource-State'),
            'resource_id': headers.get('X-Goog-Resource-ID', ''),
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'client_ip': client_ip,
            'headers': headers
        }
        
        # Publish to queue
        if rabbitmq_manager.publish_message(message):
            logger.info(f"Webhook processed successfully: {message['event_id']}")
            return jsonify({
                'status': 'success',
                'event_id': message['event_id'],
                'timestamp': message['timestamp']
            }), 200
        else:
            logger.error("Failed to publish webhook message")
            return jsonify({'error': 'Internal processing error'}), 500
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Check RabbitMQ connection
        rabbitmq_status = 'healthy' if (rabbitmq_manager.connection and 
                                       not rabbitmq_manager.connection.is_closed) else 'unhealthy'
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'services': {
                'rabbitmq': rabbitmq_status,
                'webhook_listener': 'healthy'
            },
            'version': '1.0.0',
            'config': {
                'webhook_port': config.WEBHOOK_PORT,
                'log_level': config.LOG_LEVEL,
                'verification_token_set': bool(config.WEBHOOK_VERIFICATION_TOKEN)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 503

@app.route('/config', methods=['GET'])
def show_config():
    """Show current configuration (for debugging)"""
    try:
        return jsonify({
            'config': {
                'webhook_host': config.WEBHOOK_HOST,
                'webhook_port': config.WEBHOOK_PORT,
                'gdrive_folder_id': config.GDRIVE_FOLDER_ID,
                'aws_s3_bucket': config.AWS_S3_BUCKET,
                'aws_region': config.AWS_REGION,
                'log_level': config.LOG_LEVEL,
                'max_workers': config.MAX_WORKERS,
                'check_interval': config.SYNC_CHECK_INTERVAL_MINUTES,
                'allowed_ips': config.ALLOWED_IPS,
                'credentials_file_exists': config.GDRIVE_CREDENTIALS_FILE.exists(),
                'token_file_exists': config.GDRIVE_TOKEN_FILE.exists()
            },
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 200
    except Exception as e:
        logger.error(f"Config endpoint error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/metrics', methods=['GET'])
def metrics():
    """Basic metrics endpoint"""
    try:
        return jsonify({
            'webhook_listener_info': {
                'status': 'running',
                'uptime_seconds': 0,  # Can be tracked
                'total_requests': 0,  # Can be tracked
            },
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 200
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    logger.info("Starting webhook server with centralized configuration")
    logger.info(f"Config: {config}")
    logger.info(f"Server: {config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}")
    logger.info(f"Google Drive Folder: {config.GDRIVE_FOLDER_ID}")
    logger.info(f"S3 Bucket: {config.AWS_S3_BUCKET}")
    
    app.run(host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT, debug=False)