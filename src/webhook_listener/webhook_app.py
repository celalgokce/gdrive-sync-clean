import os
import sys
import json
import logging
import threading
import time
from flask import Flask, request, jsonify
from datetime import datetime
import pika
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

# Add shared directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../shared')))

try:
    from config import get_config
    from signal_handler import GracefulShutdownHandler
    from startup_optimizer import StartupOptimizer
    config = get_config()
except ImportError as e:
    print(f"Config import error: {e}")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables for graceful shutdown
app = Flask(__name__)
shutdown_handler = GracefulShutdownHandler(shutdown_timeout=30)
startup_optimizer = StartupOptimizer()
rabbitmq_connection_pool = []

# Prometheus metrics
webhook_requests_total = Counter('webhook_requests_total', 'Total webhook requests received')
webhook_errors_total = Counter('webhook_errors_total', 'Total webhook errors')
startup_time_counter = Counter('webhook_startup_total', 'Total webhook service startups')

def init_rabbitmq_pool():
    """Initialize RabbitMQ connection pool for better performance"""
    try:
        logger.info("Initializing RabbitMQ connection pool...")
        for i in range(3):  # Pool of 3 connections
            conn = pika.BlockingConnection(pika.URLParameters(config.RABBITMQ_URL))
            rabbitmq_connection_pool.append(conn)
        logger.info(f"RabbitMQ connection pool initialized with {len(rabbitmq_connection_pool)} connections")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize RabbitMQ pool: {e}")
        return False

def get_rabbitmq_connection():
    """Get connection from pool or create new one"""
    if rabbitmq_connection_pool:
        try:
            conn = rabbitmq_connection_pool.pop()
            if conn.is_open:
                return conn
        except IndexError:
            pass
    
    # Fallback: create new connection
    return pika.BlockingConnection(pika.URLParameters(config.RABBITMQ_URL))

def return_rabbitmq_connection(connection):
    """Return connection to pool"""
    if len(rabbitmq_connection_pool) < 3 and connection.is_open:
        rabbitmq_connection_pool.append(connection)
    else:
        try:
            connection.close()
        except:
            pass

def test_health_endpoints():
    """Test that all required services are accessible"""
    try:
        # Test RabbitMQ
        conn = pika.BlockingConnection(pika.URLParameters(config.RABBITMQ_URL))
        conn.close()
        logger.info("RabbitMQ health check: OK")
        return True
    except Exception as e:
        logger.error(f"RabbitMQ health check failed: {e}")
        return False

def cleanup_connections():
    """Clean up all connections during shutdown"""
    logger.info("Cleaning up RabbitMQ connections...")
    for conn in rabbitmq_connection_pool:
        try:
            if conn.is_open:
                conn.close()
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")
    rabbitmq_connection_pool.clear()
    logger.info("Connection cleanup completed")

# Register shutdown callback
shutdown_handler.add_shutdown_callback(cleanup_connections)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint with graceful shutdown awareness"""
    if shutdown_handler.is_shutdown_requested():
        return jsonify({'error': 'Service is shutting down'}), 503
    
    webhook_requests_total.inc()
    connection = None
    
    try:
        # Get data safely
        content_type = request.headers.get('Content-Type', '')
        
        if 'application/json' in content_type:
            data = request.get_json(silent=True) or {}
        else:
            data = {}
        
        # Create webhook message
        webhook_message = {
            'timestamp': datetime.utcnow().isoformat(),
            'headers': dict(request.headers),
            'data': data,
            'source': 'webhook',
            'service_id': os.getenv('HOSTNAME', 'webhook-listener')
        }
        
        # Send to RabbitMQ with connection pooling
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
            
            return_rabbitmq_connection(connection)
            logger.info("Message sent to webhook_queue successfully")
            
        except Exception as e:
            webhook_errors_total.inc()
            logger.error(f"Failed to publish message: {e}")
            if connection:
                try:
                    connection.close()
                except:
                    pass
            return jsonify({'error': 'Failed to publish webhook message'}), 500
        
        return jsonify({'status': 'success', 'message': 'Webhook received and queued'}), 200
        
    except Exception as e:
        webhook_errors_total.inc()
        logger.error(f"Webhook processing error: {e}")
        return jsonify({'error': 'Internal processing error'}), 500

@app.route('/health', methods=['GET'])
def health():
    """Enhanced health check with shutdown awareness"""
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'shutdown_requested': shutdown_handler.is_shutdown_requested(),
        'connections_pool_size': len(rabbitmq_connection_pool)
    }
    
    # If shutting down, return 503
    if shutdown_handler.is_shutdown_requested():
        health_status['status'] = 'shutting_down'
        return jsonify(health_status), 503
    
    return jsonify(health_status), 200

@app.route('/ready', methods=['GET'])
def readiness():
    """Kubernetes-style readiness probe"""
    if shutdown_handler.is_shutdown_requested():
        return jsonify({'status': 'not_ready', 'reason': 'shutting_down'}), 503
    
    # Test RabbitMQ connectivity
    try:
        test_conn = get_rabbitmq_connection()
        return_rabbitmq_connection(test_conn)
        return jsonify({'status': 'ready'}), 200
    except Exception as e:
        return jsonify({'status': 'not_ready', 'reason': str(e)}), 503

@app.route('/config', methods=['GET'])
def show_config():
    """Show configuration"""
    return jsonify({
        'config': {
            'gdrive_folder_id': config.GDRIVE_FOLDER_ID,
            's3_bucket': config.AWS_S3_BUCKET,
            'webhook_host': config.WEBHOOK_HOST,
            'webhook_port': config.WEBHOOK_PORT,
            'log_level': config.LOG_LEVEL
        },
        'startup_metrics': startup_optimizer.get_startup_metrics()
    })

@app.route('/metrics', methods=['GET'])
def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

def run_optimized_startup():
    """Run optimized startup sequence"""
    startup_time_counter.inc()
    
    # Add startup tasks
    startup_optimizer.add_startup_task(
        name='rabbitmq_pool_init',
        func=init_rabbitmq_pool,
        critical=True,
        timeout=30
    )
    
    startup_optimizer.add_startup_task(
        name='health_check',
        func=test_health_endpoints,
        critical=True,
        timeout=15
    )
    
    # Run startup sequence
    success = startup_optimizer.run_startup_sequence()
    
    if not success:
        logger.error("Startup sequence failed")
        sys.exit(1)
    
    # Log startup metrics
    metrics = startup_optimizer.get_startup_metrics()
    logger.info(f"Startup completed - Total time: {metrics.get('total_time', 0):.2f}s")

def main():
    """Main function with graceful shutdown support"""
    logger.info("Starting webhook listener with Factor IX compliance")
    
    # Run optimized startup
    run_optimized_startup()
    
    try:
        # Start Flask app in a separate thread
        flask_thread = threading.Thread(
            target=lambda: app.run(
                host=config.WEBHOOK_HOST,
                port=config.WEBHOOK_PORT,
                debug=False,
                threaded=True
            )
        )
        flask_thread.daemon = True
        flask_thread.start()
        
        logger.info(f"Webhook listener started on {config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}")
        logger.info("Service ready to receive webhooks")
        
        # Wait for shutdown signal
        shutdown_handler.wait_for_shutdown()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
