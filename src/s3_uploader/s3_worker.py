import logging
import pika
import json
import boto3
import sys
import os
import unicodedata
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Google Drive manager import
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../gdrive_client')))
from gdrive_manager import GoogleDriveManager

# Logging configuration
log_level = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def sanitize_ascii(value):
    """
    S3 metadata'da kullanılabilmesi için ASCII karakter dışı verileri temizler.
    """
    if not isinstance(value, str):
        return str(value)
    return unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')

def sanitize_filename(filename):
    """
    S3 key için güvenli dosya adı oluşturur
    """
    # ASCII'ye çevir ve güvenli karakterlere dönüştür
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
    
    # Başta ve sonda underscore varsa temizle
    safe_name = safe_name.strip('_')
    
    return safe_name if safe_name else 'unnamed_file'

class S3Worker:
    def __init__(self):
        """
        S3 yükleyici ve Google Drive senkronizasyon işçisi başlatılır.
        Environment variables'lardan config alır.
        """
        # AWS S3 Configuration from environment
        self.bucket_name = os.getenv('AWS_S3_BUCKET', 'gdrive-sync-demo')
        aws_region = os.getenv('AWS_REGION', 'eu-central-1')
        
        # S3 client oluştur
        self.s3_client = boto3.client('s3', region_name=aws_region)
        
        # Google Drive Configuration from environment
        credentials_path = os.getenv('GDRIVE_CREDENTIALS_FILE', 'credentials.json')
        if not os.path.exists(credentials_path):
            # Relative path dene
            relative_path = f'../{os.path.dirname(__file__)}/gdrive_client/{credentials_path}'
            if os.path.exists(relative_path):
                credentials_path = relative_path
            else:
                logger.error(f"Google Drive credentials file not found: {credentials_path}")
                raise FileNotFoundError(f"Credentials file not found: {credentials_path}")
        
        self.gdrive_manager = GoogleDriveManager(credentials_path)
        self.folder_id = os.getenv('GDRIVE_FOLDER_ID', '1TcG_cbVfaRvPUyaPaqyPZVEd5p_eA_s_')
        
        # RabbitMQ Configuration from environment
        rabbitmq_url = os.getenv('RABBITMQ_URL', 'amqp://gdrive_user:gdrive_pass123@localhost:5672/gdrive_sync')
        
        try:
            self.connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
            self.channel = self.connection.channel()
            
            # Declare exchange and queue
            self.channel.exchange_declare(exchange='gdrive_events', exchange_type='topic', durable=True)
            self.channel.queue_declare(queue='webhook_queue', durable=True)
            self.channel.queue_bind(exchange='gdrive_events', queue='webhook_queue', routing_key='file.*')
            
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
        
        # Worker Configuration
        self.max_workers = int(os.getenv('MAX_WORKERS', 3))
        
        logger.info("S3 Worker initialized with Google Drive integration")
        logger.info(f"Monitoring S3 Bucket: {self.bucket_name}")
        logger.info(f"Monitoring Google Drive folder: {self.folder_id}")

    def start_consuming(self):
        """
        RabbitMQ kuyruğundan mesaj almaya başlar.
        """
        logger.info("Starting to consume messages from webhook_queue")
        logger.info(f"Max workers: {self.max_workers}")

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
        """
        Webhook mesajını işleyip yeni dosya varsa S3'e senkronize eder.
        """
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
        """
        Drive'daki tek bir dosyayı indirip S3'e yükler. 
        Tüm dosya tiplerini destekler ve metadata ile log oluşturur.
        """
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
        """
        Google Workspace dosyaları için uygun uzantı ekler
        """
        # Uzantı mapping'i - daha kapsamlı format desteği
        mime_to_ext = {
            # Google Workspace Apps - Çoklu format desteği
            'application/vnd.google-apps.document': '.docx',  # Google Docs -> Word
            'application/vnd.google-apps.spreadsheet': '.xlsx',  # Google Sheets -> Excel
            'application/vnd.google-apps.presentation': '.pptx',  # Google Slides -> PowerPoint
            'application/vnd.google-apps.drawing': '.png',  # Google Drawings -> PNG
            'application/vnd.google-apps.script': '.gs',  # Google Apps Script
            'application/vnd.google-apps.site': '.html',  # Google Sites
            'application/vnd.google-apps.form': '.json',  # Google Forms
            
            # Microsoft Office Formats
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
            'application/msword': '.doc',
            'application/vnd.ms-excel': '.xls',
            'application/vnd.ms-powerpoint': '.ppt',
            
            # PDF
            'application/pdf': '.pdf',
            
            # Images
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/bmp': '.bmp',
            'image/svg+xml': '.svg',
            'image/webp': '.webp',
            
            # Text files
            'text/plain': '.txt',
            'text/html': '.html',
            'text/css': '.css',
            'text/javascript': '.js',
            'text/csv': '.csv',
            'application/json': '.json',
            'application/xml': '.xml',
            'text/xml': '.xml',
            
            # Archives
            'application/zip': '.zip',
            'application/x-rar-compressed': '.rar',
            'application/x-7z-compressed': '.7z',
            'application/gzip': '.gz',
            
            # Audio
            'audio/mpeg': '.mp3',
            'audio/wav': '.wav',
            'audio/ogg': '.ogg',
            'audio/mp4': '.m4a',
            
            # Video
            'video/mp4': '.mp4',
            'video/avi': '.avi',
            'video/quicktime': '.mov',
            'video/webm': '.webm',
            
            # Other common formats
            'application/rtf': '.rtf',
            'application/epub+zip': '.epub',
        }
        
        file_ext = mime_to_ext.get(mime_type, '')
        
        # Eğer dosya adında zaten doğru uzantı varsa, ekleme
        if file_ext and not file_name.lower().endswith(file_ext.lower()):
            final_name = file_name + file_ext
            logger.debug(f"Added extension: {file_name} -> {final_name}")
            return final_name
        
        return file_name

    def upload_to_s3(self, content, s3_key, file_info, final_filename):
        """
        S3'e dosya yükler. Metadata ASCII formatına çevrilerek eklenir.
        """
        try:
            # Content type belirleme - daha akıllı detection
            content_type = file_info.get('mimeType', 'application/octet-stream')
            
            # Eğer Google Apps dosyasıysa, export edilen format'ın MIME type'ını kullan
            if content_type.startswith('application/vnd.google-apps'):
                export_mime_types = {
                    'application/vnd.google-apps.document': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'application/vnd.google-apps.spreadsheet': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    'application/vnd.google-apps.presentation': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                    'application/vnd.google-apps.drawing': 'image/png',
                }
                content_type = export_mime_types.get(content_type, 'application/octet-stream')

            # Metadata hazırlama - ASCII safe
            original_name = file_info.get('name', '')
            ascii_original_name = sanitize_ascii(original_name)
            
            if ascii_original_name != original_name:
                logger.warning(f"Non-ASCII characters sanitized in metadata: {original_name} -> {ascii_original_name}")

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
            logger.debug(f"Content-Type: {content_type}, Size: {len(content)} bytes")

        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            raise

    def create_metadata_file(self, file_info, s3_key, webhook_message, final_filename):
        """
        Senkronizasyon işlemiyle ilgili metadata bilgisini JSON formatında S3'e kaydeder.
        """
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
                    "region": os.getenv('AWS_REGION', 'eu-central-1')
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
        """
        Eğer klasörde dosya yoksa, gelen webhook mesajını loglayan bir .txt dosyası oluşturur.
        """
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
    logger.info("Starting S3 Worker with environment configuration")
    logger.info(f"AWS S3 Bucket: {os.getenv('AWS_S3_BUCKET', 'gdrive-sync-demo')}")
    logger.info(f"Google Drive Folder ID: {os.getenv('GDRIVE_FOLDER_ID', 'not_set')}")
    logger.info(f"Log Level: {os.getenv('LOG_LEVEL', 'INFO')}")
    
    try:
        worker = S3Worker()
        worker.start_consuming()
    except Exception as e:
        logger.error(f"Failed to start S3 Worker: {e}")
        exit(1)