# drive_helpers.py
import os
import io
import re
import logging
import subprocess
from typing import Optional 
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request     
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from typing import List, Tuple, Optional
from drive_auth import get_drive_service
import xml.etree.ElementTree as ET

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

def find_drawio_files(keyword: str, parent_id: str) -> List[Tuple[str, str]]:
    """
    Mencari semua file schematic (.drawio / .xml) di Google Drive yang cocok dengan keyword,
    termasuk file yang berisi embel-embel 'RESILIENCY'.
    """
    import re
    result_files = []
    try:
        service = get_drive_service()
        parts = keyword.upper().split('-')
        if len(parts) != 3:
            return []

        prefix = '-'.join(parts[:2])  # Contoh: FE-LOB
        suffix = parts[2].strip().upper()  # Contoh: FAM
        sto_code = parts[1][-3:]

        logger.info(f"[DEBUG] prefix: {prefix}, suffix: {suffix}, sto_code: {sto_code}")

        folders = service.files().list(
            q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id,name)", pageSize=100
        ).execute().get('files', [])

        target_folder = next(
            (f for f in folders if re.sub(r'[^A-Z0-9]', '', f['name'].upper())[-3:] == sto_code),
            None
        )
        if not target_folder:
            logger.warning(f"Folder STO {sto_code} tidak ditemukan.")
            return []

        logger.info(f"[DEBUG] Folder ditemukan: {target_folder['name']}")

        files = service.files().list(
            q=f"'{target_folder['id']}' in parents and trashed=false",
            fields="files(id,name)", pageSize=100
        ).execute().get('files', [])

        logger.info(f"[DEBUG] Total file ditemukan: {len(files)}")

        for file in files:
            name_upper = file['name'].upper()

            if prefix not in name_upper:
                continue

            match = re.search(r'\((.*?)\)', name_upper)
            if match:
                codes = [x.strip().replace(" ", "") for x in match.group(1).split(',')]
                suffix_clean = suffix.replace(" ", "")
                if any(suffix_clean in code for code in codes):
                    logger.info(f"[DEBUG] Cocok: {file['name']}")
                    result_files.append((file['id'], file['name']))
            elif suffix in name_upper:
                logger.info(f"[DEBUG] Cocok fallback: {file['name']}")
                result_files.append((file['id'], file['name']))

        return result_files

    except Exception as e:
        logger.error(f"[find_drawio_files] Gagal: {e}", exc_info=True)
        return []




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


def dms_to_decimal(dms_str: str) -> float:
    """
    Konversi koordinat dari format DMS ke desimal.
    Contoh input: 0°14'0.62"S
    """
    match = re.match(r"(\d+)[°º](\d+)'(\d+(?:\.\d+)?)\"?([NSEW])", dms_str.strip().upper())
    if not match:
        return None
    degrees, minutes, seconds, direction = match.groups()
    decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    if direction in ['S', 'W']:
        decimal *= -1
    return decimal

def parse_coordinate(coord_str: str) -> float:
    """
    Deteksi dan konversi koordinat DMS atau desimal dengan simbol derajat (°).
    Return float atau None.
    """
    coord_str = coord_str.strip().replace("°", "")
    # Jika sudah dalam desimal, coba langsung parsing
    try:
        return float(coord_str)
    except ValueError:
        pass

    # Coba format DMS (misalnya: 0°14'0.62"S)
    match = re.match(r"(\d+)[°º](\d+)'(\d+(?:\.\d+)?)\"?([NSEW])", coord_str.upper())
    if not match:
        return None
    degrees, minutes, seconds, direction = match.groups()
    decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    if direction in ['S', 'W']:
        decimal *= -1
    return decimal

def download_file_as_bytes(file_id: str) -> bytes:
    """
    Mengunduh file dari Google Drive sebagai bytes.
    """
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read()

def extract_kml_distribution(kml_bytes: bytes, target_folder_name: str) -> bytes:
    """
    Mengambil folder DISTRIBUSI dan folder TIANG dari file KML serta semua Style/StyleMap yang relevan.
    """
    ET.register_namespace("", "http://www.opengis.net/kml/2.2")
    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    normalized_target = target_folder_name.lower().replace(" ", "").replace("0", "")

    root = ET.fromstring(kml_bytes)
    doc_root = root.find("kml:Document", ns)
    if doc_root is None:
        raise ValueError("Dokumen KML tidak memiliki elemen <Document>.")

    # Buat root baru untuk KML hasil
    kml_new = ET.Element("{http://www.opengis.net/kml/2.2}kml")
    doc_new = ET.SubElement(kml_new, "Document")

    # Salin semua <Style> dan <StyleMap>
    for elem in doc_root:
        if elem.tag in [
            f"{{{ns['kml']}}}Style",
            f"{{{ns['kml']}}}StyleMap"
        ]:
            doc_new.append(elem)

    # Temukan folder target distribusi & folder TIANG
    distrib_folder = None
    tiang_folder = None
    for folder in doc_root.findall("kml:Folder", ns):
        name_elem = folder.find("kml:name", ns)
        if name_elem is not None:
            folder_name_raw = name_elem.text.strip()
            folder_name_norm = folder_name_raw.lower().replace(" ", "").replace("0", "")
            if folder_name_norm == normalized_target:
                distrib_folder = folder
            elif folder_name_raw.strip().lower() == "tiang":
                tiang_folder = folder

    if distrib_folder is None:
        raise ValueError(f"Folder '{target_folder_name}' tidak ditemukan dalam file KML.")

    # Tambahkan folder distribusi dan TIANG jika ditemukan
    doc_new.append(distrib_folder)
    if tiang_folder is not None:
        doc_new.append(tiang_folder)

    return ET.tostring(kml_new, encoding="utf-8", xml_declaration=True)




def find_feeder_kml_file(done_masterplan_folder_id: str, sto_code: str):
    service = get_drive_service()

    # Step 1: Cari semua folder di dalam Done Masterplan
    query_sto_folders = (
        f"'{done_masterplan_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    sto_folders = service.files().list(q=query_sto_folders, fields="files(id, name)").execute().get("files", [])

    for folder in sto_folders:
        folder_name = folder["name"].upper()
        if folder_name.endswith(sto_code.upper()):
            logger.info(f"[FEEDER] Cocok folder STO: {folder['name']}")
            sto_folder_id = folder["id"]

            # Step 2: Masuk ke folder FEEDER
            query_feeder = (
                f"'{sto_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' "
                f"and name = 'FEEDER' and trashed = false"
            )
            feeder_folders = service.files().list(q=query_feeder, fields="files(id, name)").execute().get("files", [])
            if not feeder_folders:
                logger.warning(f"[FEEDER] Folder FEEDER tidak ditemukan dalam folder STO: {folder['name']}")
                return None

            feeder_folder_id = feeder_folders[0]["id"]

            # Step 3: Cari file .kml di dalam folder FEEDER
            query_file = (
                f"'{feeder_folder_id}' in parents and trashed = false and "
                f"mimeType != 'application/vnd.google-apps.folder' and "
                f"name contains 'FEEDER' and name contains '{sto_code}'"
            )
            files = service.files().list(q=query_file, fields="files(id, name)").execute().get("files", [])
            if files:
                logger.info(f"[FEEDER] File feeder ditemukan: {files[0]['name']}")
                return files[0]["id"]
            else:
                logger.warning(f"[FEEDER] Tidak ditemukan file feeder .kml untuk STO {sto_code}")
                return None

    logger.warning(f"[FEEDER] Tidak ditemukan folder STO yang berakhiran dengan: {sto_code}")
    return None


def extract_all_kml_folders_by_keyword(kml_bytes: bytes, keyword: str, preserve_full_styles: bool = True) -> bytes:
    """
    Mengekstrak semua folder dalam file .kml yang <name>-nya mengandung keyword.
    Menggabungkan semuanya menjadi satu file .kml baru.

    Params:
    - kml_bytes: isi file .kml dalam bentuk bytes
    - keyword: kata kunci pencarian folder (misal 'FAB')
    - preserve_full_styles: jika True, maka seluruh <Style> dan <StyleMap> akan disalin ke file baru

    Returns:
    - bytes: isi file .kml hasil ekstraksi folder-folder yang cocok
    """
    import xml.etree.ElementTree as ET

    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    root = ET.fromstring(kml_bytes)
    document = root.find("kml:Document", ns)
    if document is None:
        raise ValueError("KML tidak memiliki elemen <Document>.")

    # Ambil semua style/styleMap
    styles = []
    if preserve_full_styles:
        for tag in ["Style", "StyleMap"]:
            styles.extend(document.findall(f"kml:{tag}", ns))

    matched_folders = []
    keyword_upper = keyword.upper().replace(" ", "")
    for folder in document.findall("kml:Folder", ns):
        name_el = folder.find("kml:name", ns)
        if name_el is not None:
            name_text = name_el.text.strip().upper().replace(" ", "")
            if keyword_upper in name_text:
                matched_folders.append(folder)

    if not matched_folders:
        raise ValueError(f"Tidak ditemukan folder yang cocok dengan keyword '{keyword}'.")

    # Buat file .kml baru
    new_kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    new_doc = ET.SubElement(new_kml, "Document")

    if preserve_full_styles:
        for s in styles:
            new_doc.append(s)

    for folder in matched_folders:
        new_doc.append(folder)

    return ET.tostring(new_kml, encoding="utf-8", xml_declaration=True)