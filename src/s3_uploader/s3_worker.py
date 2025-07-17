import logging
import pika
import json
import boto3
import sys
import os
import unicodedata
from datetime import datetime
from pathlib import Path

# Add paths for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../shared')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../gdrive_client')))

from config import get_config
from gdrive_manager import GoogleDriveManager

# Initialize config
config = get_config()

# Logging configuration
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def sanitize_ascii(value):
    """S3 metadata için ASCII karakter temizleme"""
    if not isinstance(value, str):
        return str(value)
    return unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')

def sanitize_filename(filename):
    """S3 key için güvenli dosya adı oluşturur"""
    safe_name = sanitize_ascii(filename)
    safe_name = safe_name.replace(' ', '_')
    safe_name = safe_name.replace('/', '_')
    safe_name = safe_name.replace('\\', '_')
    safe_name = safe_name.replace('?', '_')
    safe_name = safe_name.replace('#', '_')
    safe_name = safe_name.replace('[', '_')
    safe_name = safe_name.replace(']', '_')
    safe_name = safe_name.replace('@', '_')
    safe_name = safe_name.replace('!', '_')
    safe_name = safe_name.replace('$', '_')
    safe_name = safe_name.replace('&', '_')
    safe_name = safe_name.replace("'", '_')
    safe_name = safe_name.replace('(', '_')
    safe_name = safe_name.replace(')', '_')
    safe_name = safe_name.replace('*', '_')
    safe_name = safe_name.replace('+', '_')
    safe_name = safe_name.replace(',', '_')
    safe_name = safe_name.replace(';', '_')
    safe_name = safe_name.replace('=', '_')
    
    # Çoklu underscorları tek underscore'a çevir
    while '__' in safe_name:
        safe_name = safe_name.replace('__', '_')
    
    safe_name = safe_name.strip('_')
    return safe_name if safe_name else 'unnamed_file'

class S3Worker:
    def __init__(self):
        """S3 Worker - Merkezi config kullanarak başlatılır"""
        self.config = config
        
        # AWS S3 Configuration
        self.bucket_name = self.config.AWS_S3_BUCKET
        self.s3_client = boto3.client('s3', region_name=self.config.AWS_REGION)
        
        # Google Drive Configuration
        self.gdrive_manager = GoogleDriveManager(str(self.config.GDRIVE_CREDENTIALS_FILE))
        self.folder_id = self.config.GDRIVE_FOLDER_ID
        
        # RabbitMQ Configuration
        try:
            self.connection = pika.BlockingConnection(pika.URLParameters(self.config.RABBITMQ_URL))
            self.channel = self.connection.channel()
            
            # Declare exchange and queue
            self.channel.exchange_declare(exchange='gdrive_events', exchange_type='topic', durable=True)
            self.channel.queue_declare(queue='webhook_queue', durable=True)
            self.channel.queue_bind(exchange='gdrive_events', queue='webhook_queue', routing_key='file.*')
            
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
        
        logger.info("S3 Worker initialized with Google Drive integration")
        logger.info(f"Monitoring S3 Bucket: {self.bucket_name}")
        logger.info(f"Monitoring Google Drive folder: {self.folder_id}")
        logger.info(f"Max workers: {self.config.MAX_WORKERS}")

    def start_consuming(self):
        """RabbitMQ kuyruğundan mesaj almaya başlar"""
        logger.info("Starting to consume messages from webhook_queue")

        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(
            queue='webhook_queue',
            on_message_callback=self.process_message
        )

        try:
            logger.info("Worker started. Waiting for webhook messages...")
            self.channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("Worker stopped by user")
            self.channel.stop_consuming()
            self.connection.close()

    def process_message(self, ch, method, properties, body):
        """Webhook mesajını işleyip yeni dosya varsa S3'e senkronize eder"""
        try:
            message = json.loads(body)
            logger.info(f"Processing webhook message: {message.get('event_id', 'unknown')}")

            files = self.gdrive_manager.get_folder_files(self.folder_id)

            if files:
                logger.info(f"Found {len(files)} files in Google Drive")
                success_count = 0
                for file_info in files:
                    if self.sync_file_to_s3(file_info, message):
                        success_count += 1
                logger.info(f"Successfully synced {success_count}/{len(files)} files")
            else:
                logger.info("No files found in Google Drive folder")
                self.create_webhook_event_file(message)

            ch.basic_ack(delivery_tag=method.delivery_tag)
            logger.info("Message processed successfully")

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def sync_file_to_s3(self, file_info, webhook_message):
        """Drive'daki tek bir dosyayı indirip S3'e yükler"""
        try:
            file_id = file_info['id']
            file_name = file_info['name']
            mime_type = file_info.get('mimeType', '')
            
            logger.info(f"Syncing file: {file_name} (MIME: {mime_type})")

            # Google Workspace dosyaları için uygun uzantı ekle
            file_name_with_ext = self.add_appropriate_extension(file_name, mime_type)
            
            # Drive'dan dosya içeriğini al
            file_content = self.gdrive_manager.download_file(file_id)

            if file_content is None:
                logger.error(f"Failed to download file: {file_name}")
                return False

            # S3 için güvenli anahtar üret
            timestamp = datetime.now().strftime("%Y/%m/%d/%H%M%S")
            safe_filename = sanitize_filename(file_name_with_ext)
            s3_key = f"gdrive-sync/files/{timestamp}_{safe_filename}"

            # Yükleme işlemi
            self.upload_to_s3(file_content, s3_key, file_info, file_name_with_ext)
            self.create_metadata_file(file_info, s3_key, webhook_message, file_name_with_ext)

            logger.info(f"Successfully synced: {file_name} -> {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"Error syncing file {file_info.get('name', 'unknown')}: {e}")
            return False

    def add_appropriate_extension(self, file_name, mime_type):
        """Google Workspace dosyaları için uygun uzantı ekler"""
        mime_to_ext = {
            'application/vnd.google-apps.document': '.docx',
            'application/vnd.google-apps.spreadsheet': '.xlsx',
            'application/vnd.google-apps.presentation': '.pptx',
            'application/vnd.google-apps.drawing': '.png',
            'application/vnd.google-apps.script': '.gs',
            'application/vnd.google-apps.site': '.html',
            'application/vnd.google-apps.form': '.json',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
            'application/msword': '.doc',
            'application/vnd.ms-excel': '.xls',
            'application/vnd.ms-powerpoint': '.ppt',
            'application/pdf': '.pdf',
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/bmp': '.bmp',
            'image/svg+xml': '.svg',
            'image/webp': '.webp',
            'text/plain': '.txt',
            'text/html': '.html',
            'text/css': '.css',
            'text/javascript': '.js',
            'text/csv': '.csv',
            'application/json': '.json',
            'application/xml': '.xml',
            'text/xml': '.xml',
            'application/zip': '.zip',
            'application/x-rar-compressed': '.rar',
            'application/x-7z-compressed': '.7z',
            'application/gzip': '.gz',
            'audio/mpeg': '.mp3',
            'audio/wav': '.wav',
            'audio/ogg': '.ogg',
            'audio/mp4': '.m4a',
            'video/mp4': '.mp4',
            'video/avi': '.avi',
            'video/quicktime': '.mov',
            'video/webm': '.webm',
            'application/rtf': '.rtf',
            'application/epub+zip': '.epub',
        }
        
        file_ext = mime_to_ext.get(mime_type, '')
        
        if file_ext and not file_name.lower().endswith(file_ext.lower()):
            final_name = file_name + file_ext
            logger.debug(f"Added extension: {file_name} -> {final_name}")
            return final_name
        
        return file_name

    def upload_to_s3(self, content, s3_key, file_info, final_filename):
        """S3'e dosya yükler"""
        try:
            content_type = file_info.get('mimeType', 'application/octet-stream')
            
            if content_type.startswith('application/vnd.google-apps'):
                export_mime_types = {
                    'application/vnd.google-apps.document': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'application/vnd.google-apps.spreadsheet': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    'application/vnd.google-apps.presentation': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                    'application/vnd.google-apps.drawing': 'image/png',
                }
                content_type = export_mime_types.get(content_type, 'application/octet-stream')

            # Metadata hazırlama
            original_name = file_info.get('name', '')
            ascii_original_name = sanitize_ascii(original_name)
            
            if ascii_original_name != original_name:
                logger.warning(f"Non-ASCII characters sanitized: {original_name} -> {ascii_original_name}")

            metadata = {
                'original_name': ascii_original_name,
                'final_filename': sanitize_ascii(final_filename),
                'google_drive_id': sanitize_ascii(file_info.get('id', '')),
                'sync_timestamp': sanitize_ascii(datetime.now().isoformat()),
                'file_size': sanitize_ascii(str(file_info.get('size', len(content)))),
                'original_mime_type': sanitize_ascii(file_info.get('mimeType', '')),
                'export_mime_type': sanitize_ascii(content_type),
                'modified_time': sanitize_ascii(file_info.get('modifiedTime', '')),
                'synced_by': 'gdrive-s3-sync-worker',
                'sync_version': '1.0.0'
            }

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=content,
                ContentType=content_type,
                Metadata=metadata
            )

            logger.info(f"Successfully uploaded to S3: s3://{self.bucket_name}/{s3_key}")

        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            raise

    def create_metadata_file(self, file_info, s3_key, webhook_message, final_filename):
        """Metadata dosyası oluşturur"""
        try:
            sync_timestamp = datetime.now().isoformat()
            
            metadata = {
                "sync_info": {
                    "timestamp": sync_timestamp,
                    "source": "Google Drive",
                    "destination": f"s3://{self.bucket_name}/{s3_key}",
                    "worker_version": "1.0.0",
                    "sync_method": "webhook_triggered"
                },
                "file_info": {
                    "original_name": file_info.get('name', ''),
                    "final_filename": final_filename,
                    "google_drive_id": file_info.get('id', ''),
                    "size_bytes": file_info.get('size', 0),
                    "original_mime_type": file_info.get('mimeType', ''),
                    "modified_time": file_info.get('modifiedTime', ''),
                    "is_google_workspace_file": file_info.get('mimeType', '').startswith('application/vnd.google-apps')
                },
                "webhook_trigger": {
                    "event_id": webhook_message.get('event_id', ''),
                    "event_type": webhook_message.get('event_type', ''),
                    "resource_state": webhook_message.get('resource_state', ''),
                    "timestamp": webhook_message.get('timestamp', ''),
                    "client_ip": webhook_message.get('client_ip', '')
                },
                "s3_info": {
                    "bucket": self.bucket_name,
                    "key": s3_key,
                    "region": self.config.AWS_REGION
                }
            }

            metadata_content = json.dumps(metadata, indent=2, ensure_ascii=False)
            metadata_key = s3_key.replace('/files/', '/metadata/') + '.json'

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=metadata_key,
                Body=metadata_content.encode('utf-8'),
                ContentType='application/json',
                Metadata={
                    'content_type': 'sync_metadata',
                    'created_at': sanitize_ascii(sync_timestamp),
                    'related_file': sanitize_ascii(s3_key)
                }
            )

            logger.info(f"Metadata file created: {metadata_key}")

        except Exception as e:
            logger.error(f"Error creating metadata file: {e}")

    def create_webhook_event_file(self, message):
        """Webhook event dosyası oluşturur"""
        try:
            event_content = f"Webhook event received at {datetime.now().isoformat()}\n"
            event_content += f"Event ID: {message.get('event_id', 'unknown')}\n"
            event_content += f"Resource State: {message.get('resource_state', 'unknown')}\n"
            event_content += f"Event details: {json.dumps(message, indent=2)}\n"
            event_content += "No files found in Google Drive folder to sync.\n"

            timestamp = datetime.now().strftime("%Y/%m/%d/%H%M%S")
            s3_key = f"gdrive-sync/webhook-events/{timestamp}_no_files.txt"

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=event_content.encode('utf-8'),
                ContentType='text/plain',
                Metadata={
                    'event_type': sanitize_ascii(message.get('event_type', 'webhook_received')),
                    'event_id': sanitize_ascii(message.get('event_id', 'unknown')),
                    'created_at': sanitize_ascii(datetime.now().isoformat())
                }
            )

            logger.info(f"Webhook event file created: {s3_key}")

        except Exception as e:
            logger.error(f"Error creating webhook event file: {e}")

if __name__ == '__main__':
    logger.info("Starting S3 Worker with centralized configuration")
    logger.info(f"Config: {config}")
    
    try:
        worker = S3Worker()
        worker.start_consuming()
    except Exception as e:
        logger.error(f"Failed to start S3 Worker: {e}")
        exit(1)