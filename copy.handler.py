# drive_helpers.py
import os
import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from typing import Optional   
from google.auth.transport.requests import Request     
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import subprocess
from typing import Optional, Tuple
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
import re
import logging

# Setup logging
logger = logging.getLogger(__name__)

# Konfigurasi Draw.io (sesuaikan path jika perlu)
DRAWIO_PATH = r"C:\Program Files\draw.io\drawio.exe"
import logging
logger = logging.getLogger(__name__)
# Tambahkan import ini:
from google.oauth2 import service_account
# Scope untuk Sheets
SHEETS_SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# Reuse file OAuth yang sama dengan Drive
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE       = 'token.json'
# --------------------
# Google Drive Setup
# --------------------
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'
# --------------------
# Google Drive Setup
# --------------------
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
CREDENTIALS_FILE = 'credentials.json'  # OAuth file

def get_drive_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

# --------------------
# Connectivity
# --------------------
def list_sto_folders(parent_id):
    service = get_drive_service()
    q = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=q, fields="files(id, name)").execute()
    return results.get('files', [])

def find_file_in_odc(sto_folder_id, odc_name, ds_prefix):
    service = get_drive_service()

    # 1. Cari folder ODC (ODC-XXX-YYY)
    q1 = f"'{sto_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and name = '{odc_name}' and trashed = false"
    odc_folders = service.files().list(q=q1, fields="files(id, name)").execute().get('files', [])
    if not odc_folders:
        return None

    odc_folder_id = odc_folders[0]['id']

    # 2. Cari file Sheets dengan awalan nama = DS prefix
    q2 = f"'{odc_folder_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and name contains '{ds_prefix}' and trashed = false"
    files = service.files().list(q=q2, fields="files(id, name)").execute().get('files', [])
    return files[0]['id'] if files else None

def export_pdf(file_id):
    service = get_drive_service()
    request = service.files().export_media(fileId=file_id, mimeType='application/pdf')
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

# --------------------
# KML
# --------------------
def find_kml_deep(root_id: str, odc_full: str) -> Optional[str]:
    """
    root_id: ID folder 'Done Masterpland'
    odc_full: misal 'ODC-SAN-FH'
    Struktur:
      root_id
       └── folder endswith 'SAN'
           └── Distribusi
               └── ODC-SAN-FH.kml
    """
    svc = get_drive_service()
    sto_code = odc_full.split('-')[1].upper()

    # 1. cari semua folder di root
    resp1 = svc.files().list(
        q=f"'{root_id}' in parents"
          " and mimeType='application/vnd.google-apps.folder'"
          " and trashed=false",
        fields="files(id,name)"
    ).execute().get('files', [])
    # cari folder STO
    sto = next((f for f in resp1 if f['name'].upper().endswith(sto_code)), None)
    if not sto:
        return None

    # 2. masuk ke Distribusi
    resp2 = svc.files().list(
        q=f"'{sto['id']}' in parents"
          " and mimeType='application/vnd.google-apps.folder'"
          " and trashed=false",
        fields="files(id,name)"
    ).execute().get('files', [])
    distrib = next((f for f in resp2 if f['name'].lower()=='distribusi'), None)
    if not distrib:
        return None

    # 3. cari file KML bernama {odc_full}.kml
    target = f"{odc_full}.kml"
    resp3 = svc.files().list(
        q=f"'{distrib['id']}' in parents"
          f" and name='{target}'"
          " and trashed=false",
        fields="files(id,name)"
    ).execute().get('files', [])
    if not resp3:
        return None

    return resp3[0]['id']

def get_sheets_service():
    """Buat service Google Sheets pakai OAuth flow yang sama dengan Drive."""
    creds = None
    # 1) Coba load token yang sudah ada
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SHEETS_SCOPES)
    # 2) Jika belum ada atau expired, refresh atau lakukan flow baru
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SHEETS_SCOPES)
            creds = flow.run_local_server(port=0)
        # Simpan token baru
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    # 3) Build service
    service = build('sheets', 'v4', credentials=creds)
    return service


def convert_drawio_to_png(drawio_path: str, output_path: str) -> bool:
    try:
        from drive_helpers import DRAWIO_PATH
        result = subprocess.run(
            [DRAWIO_PATH, "--export", "--format", "png", "--output", output_path, drawio_path],
            check=True,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            logger.error(f"Draw.io error: {result.stderr}")
            return False
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Konversi gagal: {e.stderr}")
        return False
    except FileNotFoundError:
        logger.error(f"Draw.io CLI tidak ditemukan di path: {DRAWIO_PATH}")
        return False

def find_drawio_file(keyword: str, parent_id: str) -> Optional[Tuple[str, str]]:
    """
    Mencari file schematic (.drawio / .xml) di Google Drive berdasarkan keyword seperti:
    FE-LOB-FAM → cari di folder berakhiran 'LOB', lalu file yang mengandung FE-LOB dan kode 'FAM'.
    """
    import re
    try:
        service = get_drive_service()
        parts = keyword.upper().split('-')
        if len(parts) != 3:
            logger.warning("[find_drawio_file] Format keyword tidak sesuai.")
            return None

        prefix = '-'.join(parts[:2])  # Contoh: FE-LOB
        suffix = parts[2].strip().upper()  # Contoh: FAM
        sto_code = parts[1][-3:]  # Ambil 3 huruf terakhir sebagai kode STO

        logger.info(f"[DEBUG] prefix: {prefix}, suffix: {suffix}, sto_code: {sto_code}")

        # 1. Ambil semua folder di dalam parent_id
        folders = service.files().list(
            q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id,name)",
            pageSize=100
        ).execute().get('files', [])

        # 2. Temukan folder yang nama akhirnya cocok dengan kode STO
        target_folder = next(
            (f for f in folders if re.sub(r'[^A-Z0-9]', '', f['name'].upper())[-3:] == sto_code),
            None
        )

        if not target_folder:
            logger.warning(f"[find_drawio_file] Folder dengan kode STO '{sto_code}' tidak ditemukan.")
            return None

        logger.info(f"[DEBUG] Folder ditemukan: {target_folder['name']}")

        # 3. Ambil semua file di dalam folder tersebut
        result = service.files().list(
            q=f"'{target_folder['id']}' in parents and trashed=false",
            fields="files(id,name)",
            pageSize=100
        ).execute().get('files', [])

        logger.info(f"[DEBUG] Total file ditemukan: {len(result)}")

        for file in result:
            name_upper = file['name'].upper()

            if prefix not in name_upper:
                continue

            # Cek isi dalam tanda kurung (bisa mengandung banyak kode)
            match = re.search(r'\((.*?)\)', name_upper)
            if match:
                codes = [x.strip().replace(" ", "") for x in match.group(1).split(',')]
                suffix_clean = suffix.replace(" ", "")
                if any(suffix_clean in code for code in codes):
                    logger.info(f"[DEBUG] Cocok: {file['name']}")
                    return file['id'], file['name']
            elif suffix in name_upper:
                # fallback: jika tidak ada tanda kurung tapi suffix muncul
                logger.info(f"[DEBUG] Cocok fallback: {file['name']}")
                return file['id'], file['name']

        logger.warning(f"[find_drawio_file] Tidak ada file yang cocok untuk keyword: {keyword}")
        return None

    except Exception as e:
        logger.error(f"[find_drawio_file] Gagal memproses keyword: {keyword} – {e}", exc_info=True)
        return None



def download_file(file_id: str, destination_path: str) -> None:
    """
    Unduh file dari Google Drive ke path lokal.

    file_id: ID file di Google Drive
    destination_path: path tujuan penyimpanan file
    """
    from drive_helpers import get_drive_service
    import io
    from googleapiclient.http import MediaIoBaseDownload

    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(destination_path, 'wb')
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()
