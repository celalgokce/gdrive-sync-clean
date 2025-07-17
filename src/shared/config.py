import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Merkezi konfigürasyon sınıfı - Tüm path'ler ve ayarlar burada"""
    
    def __init__(self):
        # Proje ana klasörü
        self.PROJECT_ROOT = Path(__file__).parent.parent.parent
        
        # Google Drive ayarları
        self.GDRIVE_CREDENTIALS_FILE = self.PROJECT_ROOT / 'src' / 'gdrive_client' / 'credentials.json'
        self.GDRIVE_TOKEN_FILE = self.PROJECT_ROOT / 'src' / 'gdrive_client' / 'token.pickle'
        self.GDRIVE_FOLDER_ID = os.getenv('GDRIVE_FOLDER_ID', '1TcG_cbVfaRvPUyaPaqyPZVEd5p_eA_s_')
        
        # AWS ayarları
        self.AWS_S3_BUCKET = os.getenv('AWS_S3_BUCKET', 'gdrive-sync-demo')
        self.AWS_REGION = os.getenv('AWS_REGION', 'eu-central-1')
        
        # RabbitMQ ayarları
        self.RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://gdrive_user:gdrive_pass123@localhost:5672/gdrive_sync')
        
        # Webhook ayarları
        self.WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'http://localhost:5000/webhook')
        self.WEBHOOK_HOST = os.getenv('WEBHOOK_HOST', '0.0.0.0')
        self.WEBHOOK_PORT = int(os.getenv('WEBHOOK_PORT', 5000))
        self.WEBHOOK_VERIFICATION_TOKEN = os.getenv('WEBHOOK_VERIFICATION_TOKEN', 'secure_webhook_token_2025')
        
        # Scheduler ayarları
        self.SYNC_CHECK_INTERVAL_MINUTES = int(os.getenv('SYNC_CHECK_INTERVAL_MINUTES', 2))
        self.SYNC_STATE_FILE = self.PROJECT_ROOT / 'sync_state.json'
        
        # Log ayarları
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        self.LOGS_DIR = self.PROJECT_ROOT / 'logs'
        
        # Diğer ayarlar
        self.MAX_WORKERS = int(os.getenv('MAX_WORKERS', 3))
        self.ALLOWED_IPS = os.getenv('ALLOWED_IPS', '127.0.0.1,::1').split(',')
        
        # Logs klasörünü oluştur
        self.LOGS_DIR.mkdir(exist_ok=True)
        
        # Dosya varlığını kontrol et
        self.validate_files()
    
    def validate_files(self):
        """Gerekli dosyaların varlığını kontrol et"""
        if not self.GDRIVE_CREDENTIALS_FILE.exists():
            raise FileNotFoundError(f"Google Drive credentials not found: {self.GDRIVE_CREDENTIALS_FILE}")
        
        # Token dosyası yoksa uyar ama hata verme (ilk çalıştırmada oluşacak)
        if not self.GDRIVE_TOKEN_FILE.exists():
            print(f"⚠️  Token file not found: {self.GDRIVE_TOKEN_FILE} (will be created on first auth)")
    
    def __str__(self):
        """Config özeti"""
        return f"""
🔧 GDRIVE-S3-SYNC CONFIGURATION
================================
Project Root: {self.PROJECT_ROOT}
Google Drive Folder: {self.GDRIVE_FOLDER_ID}
S3 Bucket: {self.AWS_S3_BUCKET}
Webhook URL: {self.WEBHOOK_URL}
Check Interval: {self.SYNC_CHECK_INTERVAL_MINUTES} minutes
Log Level: {self.LOG_LEVEL}
================================
        """

# Global config instance
config = Config()

def get_config():
    """Global config instance'ını döndür"""
    return config

if __name__ == '__main__':
    # Config test
    print(config)