import pika
import json
from datetime import datetime

print("🚀 Hello from webhook listener!")
print("🐰 Testing RabbitMQ connection...")

try:
    # RabbitMQ'ya bağlan
    connection = pika.BlockingConnection(
        pika.URLParameters('amqp://gdrive_user:gdrive_pass123@localhost:5672/gdrive_sync')
    )
    channel = connection.channel()
    
    print("✅ RabbitMQ bağlantısı başarılı!")
    
    # Queue oluştur
    channel.queue_declare(queue='test_queue', durable=True)
    
    # Test mesajı hazırla
    message = {
        "event_type": "test",
        "file_name": "test.pdf",
        "timestamp": datetime.now().isoformat()
    }
    
    # Mesajı gönder
    channel.basic_publish(
        exchange='',
        routing_key='test_queue',
        body=json.dumps(message)
    )
    
    print("📤 Test mesajı gönderildi!")
    print(f"📝 Mesaj: {message}")
    
    # Bağlantıyı kapat
    connection.close()
    print("🔚 Bağlantı kapatıldı")
    
except Exception as e:
    print(f"❌ Hata: {e}")