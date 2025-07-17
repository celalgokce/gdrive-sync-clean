import os
import logging
from flask import Flask, request, jsonify
import pika
import json
from datetime import datetime
from dotenv import load_dotenv
from functools import wraps
import ipaddress

# Load environment variables
load_dotenv()

# Logging configuration
log_level = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class WebhookValidator:
    """Webhook validation and security"""
    
    def __init__(self):
        self.verification_token = os.getenv('WEBHOOK_VERIFICATION_TOKEN', 'default_token')
        self.allowed_ips = self._parse_allowed_ips()
    
    def _parse_allowed_ips(self):
        """Parse allowed IP addresses from environment"""
        allowed_ips_str = os.getenv('ALLOWED_IPS', '127.0.0.1,::1')
        try:
            return [ipaddress.ip_address(ip.strip()) for ip in allowed_ips_str.split(',')]
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
        self.rabbitmq_url = os.getenv('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/')
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
            'event_id': headers.get('X-Goog-Channel-ID'),
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
            'version': '1.0.0'
        }), 200
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 503

@app.route('/metrics', methods=['GET'])
def metrics():
    """Basic metrics endpoint"""
    try:
        # Basic metrics (can be enhanced with Prometheus)
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
    host = os.getenv('WEBHOOK_HOST', '0.0.0.0')
    port = int(os.getenv('WEBHOOK_PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'production') == 'development'
    
    logger.info(f"Starting webhook server on {host}:{port}")
    logger.info(f"Environment: {os.getenv('FLASK_ENV', 'production')}")
    
    app.run(host=host, port=port, debug=debug)