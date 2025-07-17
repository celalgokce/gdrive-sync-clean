import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
import requests
import schedule

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

class AutoSyncScheduler:
    """Google Drive otomatik sync scheduler - Merkezi config kullanır"""
    
    def __init__(self):
        self.config = config
        
        # Configuration from centralized config
        self.folder_id = self.config.GDRIVE_FOLDER_ID
        self.webhook_url = self.config.WEBHOOK_URL
        self.check_interval_minutes = self.config.SYNC_CHECK_INTERVAL_MINUTES
        self.verification_token = self.config.WEBHOOK_VERIFICATION_TOKEN
        
        # Google Drive manager
        self.gdrive_manager = GoogleDriveManager(str(self.config.GDRIVE_CREDENTIALS_FILE))
        
        # State tracking
        self.state_file = str(self.config.SYNC_STATE_FILE)
        self.last_sync_time = self.load_last_sync_time()
        
        logger.info("Auto Sync Scheduler initialized with centralized config")
        logger.info(f"Monitoring folder: {self.folder_id}")
        logger.info(f"Check interval: {self.check_interval_minutes} minutes")
        logger.info(f"Webhook URL: {self.webhook_url}")
        logger.info(f"State file: {self.state_file}")
    
    def load_last_sync_time(self):
        """Son sync zamanını yükle"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    last_time = state.get('last_sync_time')
                    if last_time:
                        logger.info(f"Loaded last sync time: {last_time}")
                        return last_time
        except Exception as e:
            logger.error(f"Error loading sync state: {e}")
        
        # İlk çalıştırma - 10 dakika öncesinden başla
        initial_time = (datetime.utcnow() - timedelta(minutes=10)).isoformat() + 'Z'
        logger.info(f"Initial sync time set to: {initial_time}")
        return initial_time
    
    def save_last_sync_time(self, sync_time):
        """Son sync zamanını kaydet"""
        try:
            state = {
                'last_sync_time': sync_time,
                'last_update': datetime.utcnow().isoformat() + 'Z'
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
            logger.debug(f"Saved sync time: {sync_time}")
        except Exception as e:
            logger.error(f"Error saving sync state: {e}")
    
    def get_files_modified_after(self, after_time):
        """Belirtilen zamandan sonra değiştirilen dosyaları getir"""
        try:
            # Google Drive query - modifiedTime filter
            query = f"'{self.folder_id}' in parents and trashed=false and modifiedTime > '{after_time}'"
            
            results = self.gdrive_manager.service.files().list(
                q=query,
                orderBy='modifiedTime desc',
                pageSize=100,
                fields="files(id, name, mimeType, modifiedTime, size, parents)"
            ).execute()
            
            files = results.get('files', [])
            logger.info(f"Found {len(files)} files modified after {after_time}")
            
            return files
            
        except Exception as e:
            logger.error(f"Error getting modified files: {e}")
            return []
    
    def trigger_webhook(self, files_info):
        """Webhook endpoint'ini tetikle"""
        try:
            # Webhook payload oluştur
            payload = {
                'event_type': 'scheduled_sync',
                'trigger_source': 'auto_scheduler',
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'files_found': len(files_info),
                'file_details': [
                    {
                        'id': f.get('id'),
                        'name': f.get('name'),
                        'modified_time': f.get('modifiedTime')
                    } for f in files_info[:5]  # İlk 5 dosya detayı
                ]
            }
            
            # Headers
            headers = {
                'Content-Type': 'application/json',
                'X-Goog-Channel-Token': self.verification_token,
                'X-Goog-Channel-Id': f'auto-sync-{int(time.time())}',
                'X-Goog-Resource-State': 'update',
                'X-Auto-Sync': 'true'  # Otomatik sync işareti
            }
            
            # Webhook'u tetikle
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"Webhook triggered successfully: {len(files_info)} files")
                return True
            else:
                logger.error(f"Webhook failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error triggering webhook: {e}")
            return False
    
    def check_for_changes(self):
        """Drive'ı kontrol et ve değişiklik varsa webhook tetikle"""
        try:
            logger.info("🔍 Checking Google Drive for changes...")
            
            # Son sync'ten sonraki dosyaları al
            modified_files = self.get_files_modified_after(self.last_sync_time)
            
            if modified_files:
                logger.info(f"🆕 Found {len(modified_files)} new/modified files!")
                
                # Dosya detaylarını logla
                for file in modified_files[:3]:  # İlk 3 dosya
                    logger.info(f"   📄 {file.get('name')} (modified: {file.get('modifiedTime')})")
                
                # Webhook'u tetikle
                if self.trigger_webhook(modified_files):
                    # Sync zamanını güncelle
                    current_time = datetime.utcnow().isoformat() + 'Z'
                    self.save_last_sync_time(current_time)
                    self.last_sync_time = current_time
                    logger.info("✅ Auto sync completed successfully")
                else:
                    logger.error("❌ Failed to trigger webhook")
            else:
                logger.info("✅ No new files found since last sync")
                
        except Exception as e:
            logger.error(f"❌ Error during change check: {e}")
    
    def start_monitoring(self):
        """Periyodik monitoring başlat"""
        logger.info(f"🚀 Starting auto sync monitoring every {self.check_interval_minutes} minutes")
        
        # Schedule periyodik kontrol
        schedule.every(self.check_interval_minutes).minutes.do(self.check_for_changes)
        
        # İlk kontrolü hemen yap
        logger.info("🔄 Running initial check...")
        self.check_for_changes()
        
        # Sürekli çalış
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)  # 30 saniyede bir schedule kontrol
                
        except KeyboardInterrupt:
            logger.info("🛑 Auto sync scheduler stopped by user")
        except Exception as e:
            logger.error(f"❌ Scheduler error: {e}")
    
    def run_once(self):
        """Tek seferlik kontrol (test için)"""
        logger.info("🔄 Running one-time sync check...")
        self.check_for_changes()
    
    def reset_state(self):
        """Sync state'i sıfırla"""
        current_time = datetime.utcnow().isoformat() + 'Z'
        self.save_last_sync_time(current_time)
        self.last_sync_time = current_time
        logger.info(f"🔄 Sync state reset to: {current_time}")

def main():
    """Ana fonksiyon"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Google Drive Auto Sync Scheduler')
    parser.add_argument('--once', action='store_true', help='Run sync check once and exit')
    parser.add_argument('--reset', action='store_true', help='Reset sync state to current time')
    parser.add_argument('--config', action='store_true', help='Show configuration and exit')
    
    args = parser.parse_args()
    
    try:
        scheduler = AutoSyncScheduler()
        
        if args.config:
            print("🔧 CONFIGURATION")
            print("=" * 50)
            print(f"Google Drive Folder ID: {scheduler.folder_id}")
            print(f"Webhook URL: {scheduler.webhook_url}")
            print(f"Check Interval: {scheduler.check_interval_minutes} minutes")
            print(f"State File: {scheduler.state_file}")
            print(f"Last Sync Time: {scheduler.last_sync_time}")
            print(f"Credentials File: {scheduler.config.GDRIVE_CREDENTIALS_FILE}")
            print(f"S3 Bucket: {scheduler.config.AWS_S3_BUCKET}")
            print(f"Log Level: {scheduler.config.LOG_LEVEL}")
            print("=" * 50)
            return
        
        if args.reset:
            scheduler.reset_state()
            return
        
        if args.once:
            scheduler.run_once()
        else:
            scheduler.start_monitoring()
            
    except FileNotFoundError as e:
        logger.error(f"❌ Missing file: {e}")
        logger.info("💡 Make sure credentials.json exists in src/gdrive_client/")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == '__main__':
    main()