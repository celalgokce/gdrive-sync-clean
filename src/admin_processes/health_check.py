#!/usr/bin/env python3
"""
Admin Process: System-wide health check
12-Factor compliant one-off process
"""
import sys
import os
import json
import requests
import time
from datetime import datetime

# Add shared directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../shared')))

from config import get_config
from state_manager import StateManager

def check_all_services():
    """Comprehensive system health check"""
    config = get_config()
    results = {}
    
    print("🏥 Running comprehensive health check...")
    print("=" * 50)
    
    # 1. Webhook Service (use container name)
    try:
        response = requests.get('http://webhook-listener:5000/health', timeout=10)
        results['webhook'] = {
            'status': 'healthy' if response.status_code == 200 else 'unhealthy',
            'response_time': response.elapsed.total_seconds(),
            'details': response.json()
        }
        print(f"✅ Webhook Service: {results['webhook']['status']} ({results['webhook']['response_time']:.3f}s)")
    except Exception as e:
        results['webhook'] = {'status': 'unhealthy', 'error': str(e)}
        print(f"❌ Webhook Service: {e}")
    
    # 2. Redis State Store
    try:
        state_manager = StateManager()
        test_result = state_manager.health_check()
        
        # Test actual state operations
        test_key = f"health_check_{int(time.time())}"
        state_manager.set_last_sync_time("test_value", test_key)
        retrieved_value = state_manager.get_last_sync_time(test_key)
        
        results['redis'] = {
            'status': 'healthy' if test_result and retrieved_value == "test_value" else 'unhealthy',
            'connection': test_result,
            'read_write_test': retrieved_value == "test_value"
        }
        print(f"✅ Redis State Store: {results['redis']['status']}")
    except Exception as e:
        results['redis'] = {'status': 'unhealthy', 'error': str(e)}
        print(f"❌ Redis State Store: {e}")
    
    # 3. Prometheus (use container name)
    try:
        response = requests.get('http://prometheus:9090/-/healthy', timeout=10)
        results['prometheus'] = {
            'status': 'healthy' if response.status_code == 200 else 'unhealthy',
            'response_time': response.elapsed.total_seconds()
        }
        print(f"✅ Prometheus: {results['prometheus']['status']} ({results['prometheus']['response_time']:.3f}s)")
    except Exception as e:
        results['prometheus'] = {'status': 'unhealthy', 'error': str(e)}
        print(f"❌ Prometheus: {e}")
    
    # 4. Grafana (use container name)
    try:
        response = requests.get('http://grafana:3000/api/health', timeout=10)
        results['grafana'] = {
            'status': 'healthy' if response.status_code == 200 else 'unhealthy',
            'response_time': response.elapsed.total_seconds(),
            'details': response.json() if response.status_code == 200 else None
        }
        print(f"✅ Grafana: {results['grafana']['status']} ({results['grafana']['response_time']:.3f}s)")
    except Exception as e:
        results['grafana'] = {'status': 'unhealthy', 'error': str(e)}
        print(f"❌ Grafana: {e}")
    
    # 5. RabbitMQ Health Check
    try:
        import pika
        connection = pika.BlockingConnection(pika.URLParameters(config.RABBITMQ_URL))
        channel = connection.channel()
        
        # Test queue operations
        test_queue = f"health_check_{int(time.time())}"
        channel.queue_declare(queue=test_queue, durable=False, auto_delete=True)
        channel.queue_delete(queue=test_queue)
        
        connection.close()
        
        results['rabbitmq'] = {
            'status': 'healthy',
            'queue_operations': True
        }
        print(f"✅ RabbitMQ: {results['rabbitmq']['status']}")
    except Exception as e:
        results['rabbitmq'] = {'status': 'unhealthy', 'error': str(e)}
        print(f"❌ RabbitMQ: {e}")
    
    # 6. Overall System Status
    healthy_services = len([s for s in results.values() if s['status'] == 'healthy'])
    total_services = len(results)
    
    overall_status = 'healthy' if healthy_services == total_services else 'degraded'
    
    print("=" * 50)
    print(f"📊 Overall System Status: {overall_status.upper()}")
    print(f"🎯 Services Healthy: {healthy_services}/{total_services}")
    print(f"⏱️  Check completed at: {datetime.now().isoformat()}")
    
    return results, overall_status

if __name__ == '__main__':
    results, status = check_all_services()
    
    # Save results to file
    timestamp = datetime.now().isoformat()
    report = {
        'timestamp': timestamp,
        'overall_status': status,
        'services': results,
        'environment': 'container_network'
    }
    
    # Container'da /tmp'e yazalım
    report_file = f'/tmp/health_check_{int(time.time())}.json'
    try:
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"📄 Health report saved: {report_file}")
    except Exception as e:
        print(f"⚠️  Could not save report: {e}")
    
    # Exit with appropriate code
    sys.exit(0 if status == 'healthy' else 1)
