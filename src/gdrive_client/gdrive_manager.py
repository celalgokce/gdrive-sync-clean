import os
import pickle
import logging
from datetime import datetime
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GoogleDriveManager:
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
    
    def __init__(self, credentials_file='credentials.json'):
        """
        Google Drive yöneticisi başlatılır.
        credentials_file: Google API OAuth 2.0 client credentials dosyası
        """
        self.credentials_file = credentials_file
        self.service = None
        self.authenticate()
    
    def authenticate(self):
        """
        Google Drive API ile kimlik doğrulama işlemi.
        Eğer daha önce alınmış bir token varsa onu kullanır.
        Yoksa kullanıcıdan yeniden kimlik doğrulama ister.
        """
        creds = None
        token_path = 'token.pickle'
        
        # Daha önce alınmış yetkilendirme varsa kullan
        if os.path.exists(token_path):
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)
        
        # Token geçersizse veya yoksa yeniden yetkilendirme başlat
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Yeni token'ı kaydet
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
        
        # Google Drive servisini başlat
        self.service = build('drive', 'v3', credentials=creds)
        logger.info("Google Drive API authenticated successfully")
    
    def get_folder_files(self, folder_id):
        """
        Belirli bir klasördeki dosyaları getirir (silinmemiş olanlar).
        :param folder_id: Google Drive klasör ID'si
        :return: Dosya sözlüklerinden oluşan liste
        """
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.service.files().list(
                q=query,
                fields="files(id, name, mimeType, modifiedTime, size)",
                orderBy="modifiedTime desc"
            ).execute()
            
            files = results.get('files', [])
            logger.info(f"Found {len(files)} files in folder {folder_id}")
            return files
            
        except Exception as e:
            logger.error(f"Error getting folder files: {e}")
            return []
    
    def download_file(self, file_id):
        """
        Dosyayı indirir. Google Workspace (Docs/Sheets/Slides) belgeleri export edilir.
        :param file_id: Google Drive'daki dosyanın ID'si
        :return: Dosya içeriği (bytes)
        """
        try:
            # Dosya metadata'sını al
            file_info = self.service.files().get(fileId=file_id).execute()
            mime_type = file_info.get('mimeType', '')

            if mime_type.startswith('application/vnd.google-apps'):
                # Google belgeleri export edilerek indirilir
                return self.export_google_doc(file_id, mime_type)
            else:
                # Diğer dosyalar direkt binary olarak indirilir
                request = self.service.files().get_media(fileId=file_id)
                return request.execute()

        except Exception as e:
            logger.error(f"Error downloading file with ID {file_id}: {e}")
            return None

    def export_google_doc(self, file_id, mime_type):
        """
        Google Docs, Sheets, Slides dosyalarını Office formatlarına dönüştürerek indirir.
        PDF yerine: .docx, .xlsx, .pptx dönüşümü yapılır.
        :param file_id: Dosyanın Drive ID'si
        :param mime_type: Dosya türü
        :return: Dönüştürülmüş içerik (bytes)
        """
        try:
            export_formats = {
                'application/vnd.google-apps.document': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.google-apps.spreadsheet': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'application/vnd.google-apps.presentation': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            }

            export_mime_type = export_formats.get(mime_type)
            if not export_mime_type:
                logger.warning(f"No supported export format for MIME type: {mime_type}")
                return None

            request = self.service.files().export_media(
                fileId=file_id,
                mimeType=export_mime_type
            )
            file_content = request.execute()
            logger.info(f"Exported Google Doc ({file_id}) as {export_mime_type}")
            return file_content

        except Exception as e:
            logger.error(f"Error exporting Google Doc with ID {file_id}: {e}")
            return None

# Test amaçlı örnek kullanım (isteğe bağlı)
if __name__ == "__main__":
    folder_id = "1TcG_cbVfaRvPUyaPaqyPZVEd5p_eA_s_"
    manager = GoogleDriveManager()
    files = manager.get_folder_files(folder_id)
    
    for file in files:
        print(f"{file['name']} ({file['mimeType']}) - {file['id']}")
