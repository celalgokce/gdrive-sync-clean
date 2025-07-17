import os
from pathlib import Path

class Config:
    def __init__(self):
        # Host environment için path'ler
        if os.path.exists('/app'):  # Docker container
            self.GDRIVE_CREDENTIALS_FILE = Path('/app/credentials.json')
            self.GDRIVE_TOKEN_FILE = Path('/app/token.pickle')
            self.LOGS_DIR = Path('/app/logs')
            self.SYNC_STATE_FILE = Path('/app/sync_state.json')
        else:  # Host system
            project_root = Path(__file__).parent.parent.parent
            self.GDRIVE_CREDENTIALS_FILE = project_root / 'src' / 'gdrive_client' / 'credentials.json'
            self.GDRIVE_TOKEN_FILE = project_root / 'src' / 'gdrive_client' / 'token.pickle'
            self.LOGS_DIR = project_root / 'logs'
            self.SYNC_STATE_FILE = project_root / 'sync_state.json'
        
        # Environment variables
        self.GDRIVE_FOLDER_ID = os.getenv('GDRIVE_FOLDER_ID', '1TcG_cbVfaRvPUyaPaqyPZVEd5p_eA_s_')
        self.AWS_S3_BUCKET = os.getenv('AWS_S3_BUCKET', 'gdrive-sync-demo')
        self.AWS_REGION = os.getenv('AWS_REGION', 'eu-central-1')
        self.RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://gdrive_user:gdrive_pass123@localhost:5672/gdrive_sync')
        self.WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'http://localhost:5000/webhook')
        self.WEBHOOK_HOST = os.getenv('WEBHOOK_HOST', '0.0.0.0')
        self.WEBHOOK_PORT = int(os.getenv('WEBHOOK_PORT', 5000))
        self.WEBHOOK_VERIFICATION_TOKEN = os.getenv('WEBHOOK_VERIFICATION_TOKEN', 'secure_webhook_token_2025')
        self.SYNC_CHECK_INTERVAL_MINUTES = int(os.getenv('SYNC_CHECK_INTERVAL_MINUTES', 2))
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        self.MAX_WORKERS = int(os.getenv('MAX_WORKERS', 3))
        self.ALLOWED_IPS = os.getenv('ALLOWED_IPS', '127.0.0.1,::1').split(',')
        
        # Logs klasörünü oluştur
        self.LOGS_DIR.mkdir(exist_ok=True)

config = Config()

def get_config():
    return config
