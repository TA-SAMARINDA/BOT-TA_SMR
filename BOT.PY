import logging
import io
import re
from telegram import Update, InputFile
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from telegram import Update
from telegram.ext import ContextTypes
import os
import tempfile
from telegram import Update
from drive_helpers import get_drive_service
import subprocess
from googleapiclient.errors import HttpError
from datetime import datetime
from drive_helpers import find_drawio_files, convert_drawio_to_png
from datetime import datetime
from googleapiclient.errors import HttpError
from drive_auth import get_drive_service, get_sheets_service
 
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

     
from drive_helpers import (
    export_pdf,
    find_kml_deep,
    find_file_in_odc,
    list_sto_folders,
    get_drive_service,
    get_sheets_service,
    convert_drawio_to_png,
    parse_coordinate,
    download_file_as_bytes,
    extract_kml_distribution,
    get_drive_service,
    find_feeder_kml_file,
    extract_all_kml_folders_by_keyword,
    MediaIoBaseDownload,
)

# --------------------
# CONFIG
# --------------------
BOT_TOKEN = '7627198915:AAGtXJ0nAhoOSMmm46VIHa3qeLTlesUiCQQ'
CONNECTIVITY_FOLDER_ID = '0BzUWkMAekdkANjFRZTZkWlVvRmc'
KML_ROOT_FOLDER_ID = "1k1rkkvkFE8cqwgBEPTKwfkzp-FqmRrv_"
FS1_FOLDER_ID = '0BzUWkMAekdkAbno3SnV2c2t6cVU'
SCHEMATIC_FOLDER_ID = "0BzUWkMAekdkAdHJwd09LNXQxR2c"  
USER_SHEET_ID = "1QGisQ9gmQf9RHHpETpkiabHmhBKuo-8PSr27t2kl-pw"


logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------
# /start Handler
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
       "```\n"
        "+-----------------------------------------------+\n"
        "|             Selamat Datang di Bot ODP         |\n"
        "+-----------------------------------------------+\n"
        "| 1) Connectivity                               |\n"
        "|    Kirim teks:                                |\n"
        "|    connectivity, ODC-XXX-YYY, DS.ZZ           |\n"
        "|    → Mengirim PDF dari Google Drive DS.ZZ     |\n"
        "+-----------------------------------------------+\n"
        "| 2) KML                                        |\n"
        "|    Kirim perintah:                            |\n"
        "|    - kml ODC-XXX-YYY                          |\n"
        "|      → Mengirim file .kml dari Google Earth   |\n"
        "|    - kml ODC-XXX-YYY DISTRIBUSI X             |\n"
        "|      → Mengirim Sesuai Distribusi             |\n"
        "+-----------------------------------------------+\n"
        "| 3) Informasi ODP                              |\n"
        "|    Kirim teks:                                |\n"
        "|    ODP-SMR-FBV/021                            |\n"
        "|    → Menampilkan informasi ODP dari Sheet     |\n"
        "+-----------------------------------------------+\n"
        "| 4) Informasi Feeder                           |\n"
        "|    Kirim teks:                                |\n"
        "|    - schematic FE-LOB-FAM                     |\n"
        "|      → Menampilkan schematic informasi        |\n"
        "|    - Feeder ODC-LOB-FAM                       |\n"
        "|      → Menampilkan KML informasi              |\n"
        "+-----------------------------------------------+\n"
        "```",
        parse_mode='Markdown'
    )


async def is_user_allowed(user_id: int) -> bool:
    try:
        sheets_svc = get_sheets_service()
        data = sheets_svc.spreadsheets().values().get(
            spreadsheetId=USER_SHEET_ID,
            range='Sheet1!A:A'
        ).execute().get('values', [])

        allowed_ids = {int(row[0]) for row in data if row and row[0].isdigit()}
        return user_id in allowed_ids

    except Exception as e:
        logger.error(f"Gagal cek izin user: {e}")
        return False

async def check_user_permission(update: Update) -> bool:
    user_id = update.effective_user.id
    if not await is_user_allowed(user_id):
        await update.message.reply_text("🚫 Anda tidak diizinkan menggunakan bot ini.")
        logger.warning(f"Unauthorized access by user_id: {user_id}")
        return False
    return True

    

# -----------------------------------
# Handle Pesan Text (connectivity)
# -----------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_permission(update):
        return
    text = update.message.text.strip()
    logger.info(f"Pesan masuk: {text}")

    # 1) Validasi format dasar
    parts = [p.strip() for p in text.split(',')]
    if len(parts) != 3 or parts[0].lower() != 'connectivity':
        logger.warning("Format input salah.")
        return await update.message.reply_text(
            "❌ Format salah.\nGunakan:\n"
            "`connectivity, ODC-XXX-YYY, DS.ZZ`",
            parse_mode='Markdown'
        )

    _, odc_full, ds_input = parts
    logger.info(f"ODC: {odc_full} | DS raw: {ds_input}")

    # 2) Ambil kode STO (tiga karakter di tengah)
    try:
        sto_code = odc_full.split('-')[1].upper()
        logger.info(f"Kode STO: {sto_code}")
    except Exception as e:
        logger.error("Gagal parsing kode STO: %s", e)
        return await update.message.reply_text(
            "❌ Format ODC salah. Contoh: ODC-LMP-FAA",
            parse_mode='Markdown'
        )

    # 3) Ekstrak nomor DS (angka) dan siapkan regex
    m = re.search(r'\d+', ds_input)
    if not m:
        logger.warning("Tidak ada nomor DS di input.")
        return await update.message.reply_text(
            "❌ Format DS salah. Contoh: DS.01 atau DS01",
            parse_mode='Markdown'
        )
    ds_number = m.group(0)
    ds_pattern = re.compile(rf'\bDS\.?\s*{ds_number}\b', re.IGNORECASE)
    logger.info(f"Regex untuk DS: {ds_pattern.pattern}")

    # 4) Daftar folder STO dalam folder CONNECTIVITY
    try:
        sto_list = list_sto_folders(CONNECTIVITY_FOLDER_ID)
        logger.info("Jumlah folder STO: %d", len(sto_list))
    except Exception as e:
        logger.error("Gagal list STO: %s", e)
        return await update.message.reply_text(
            "❌ Gagal mengambil daftar STO. Cek koneksi ke Google Drive."
        )

    # 5) Matching STO berdasarkan 3 karakter terakhir
    sto_folder = None
    for s in sto_list:
        name_clean = re.sub(r'[^A-Z0-9]', '', s['name'].upper())
        if name_clean[-3:] == sto_code:
            sto_folder = s
            logger.info("Matched STO: %s (ID:%s)", s['name'], s['id'])
            break

    if not sto_folder:
        logger.warning("STO kode %s tidak ditemukan.", sto_code)
        return await update.message.reply_text(
            f"❌ STO dengan kode *{sto_code}* tidak ditemukan.",
            parse_mode='Markdown'
        )

    # 6) Coba cari file lewat helper find_file_in_odc
    file_id = None
    try:
        file_id = find_file_in_odc(sto_folder['id'], odc_full, f"DS {ds_number}")
        logger.info("find_file_in_odc returned: %s", file_id)
    except Exception as e:
        logger.error("Error find_file_in_odc: %s", e)

    # 7) Fallback listing Drive jika helper gagal
    svc = get_drive_service()
    if not file_id:
        logger.info("Masuk fallback: list semua file di ODC %s", odc_full)
        odc_q = (
            f"'{sto_folder['id']}' in parents and "
            f"name = '{odc_full}' and mimeType='application/vnd.google-apps.folder'"
        )
        odc_list = svc.files().list(q=odc_q, fields="files(id)").execute().get('files', [])
        if odc_list:
            odc_folder_id = odc_list[0]['id']
            files = svc.files().list(
                q=f"'{odc_folder_id}' in parents and mimeType!='application/vnd.google-apps.folder'",
                fields="files(id,name,mimeType)"
            ).execute().get('files', [])
            for f in files:
                if ds_pattern.search(f['name']):
                    file_id = f['id']
                    logger.info("Matched file by regex: %s", f['name'])
                    break

    if not file_id:
        logger.warning("File DS %s tidak ditemukan di ODC %s", ds_number, odc_full)
        return await update.message.reply_text(
            f"❌ File DS {ds_number} tidak ditemukan di ODC *{odc_full}*.",
            parse_mode='Markdown'
        )

    # 8) Download / export dan kirim sebagai PDF
    try:
        # Cek metadata untuk tahu tipe file
        meta = svc.files().get(fileId=file_id, fields="name,mimeType").execute()
        name = meta['name']
        mime = meta['mimeType']
        logger.info("Metadata file: name=%s, mimeType=%s", name, mime)

        fh = io.BytesIO()
        if mime == 'application/vnd.google-apps.spreadsheet':
                logger.info("Exporting Google Spreadsheet to PDF")
                request = svc.files().export_media(fileId=file_id, mimeType='application/pdf')
                file_name = name + '.pdf'
        else:
            logger.info("Downloading file directly")
            request = svc.files().get_media(fileId=file_id)
            file_name = name

        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        await update.message.reply_document(document=InputFile(fh, filename=file_name))
        logger.info(f"Berhasil mengirim file {file_name}")

        # Tentukan nama file PDF
        pdf_name = re.sub(r'\.xlsx?$', '.pdf', name, flags=re.IGNORECASE) if mime != 'application/pdf' else name

        await update.message.reply_document(
            document=InputFile(fh, filename=pdf_name)
        )
        logger.info("Berhasil mengirim file %s", pdf_name)

    except Exception as e:
        logger.exception("Gagal download/export/send PDF: %s", e)
        await update.message.reply_text(
            
        )

# --------------------
# Handle Perintah /kml
# --------------------
async def kml(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_permission(update):
        return

    if not context.args:
        return await update.message.reply_text("❌ Format salah. Gunakan:\n/kml ODC-XXX-YYY\natau\n/kml ODC-XXX-YYY DISTRIBUSI X")

    odc_full = context.args[0].upper()
    distrib = " ".join(context.args[1:]).upper() if len(context.args) > 1 else None

    logger.info(f"[KML] odc: {odc_full}, distrib: {distrib}")

    file_id = find_kml_deep(KML_ROOT_FOLDER_ID, odc_full)
    if not file_id:
        return await update.message.reply_text(
            f"❌ File KML '{odc_full}.kml' tidak ditemukan.",
            parse_mode='Markdown'
        )

    try:
        kml_bytes = download_file_as_bytes(file_id)

        if distrib:
            try:
                filtered_kml = extract_kml_distribution(kml_bytes, distrib)
            except Exception as e:
                return await update.message.reply_text(f"⚠️ {e}")

            filename = f"{odc_full}_{distrib}.kml"
            content = filtered_kml
        else:
            filename = f"{odc_full}.kml"
            content = kml_bytes

        import os
        import tempfile
        from telegram import InputFile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".kml") as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        with open(tmp_path, "rb") as f:
            await update.message.reply_document(
                document=InputFile(f, filename=filename)
            )

        os.remove(tmp_path)

    except Exception as e:
        logger.exception("Gagal kirim file KML: %s", e)
        await update.message.reply_text("❌ Terjadi kesalahan saat memproses file.")

def parse_coordinate(coord_str: str) -> float:
    """
    Konversi koordinat:
    - desimal biasa (dengan atau tanpa simbol °)
    - DMS seperti 0°14'0.62"S
    """
    coord_str = coord_str.strip().replace("°", "").replace(",", ".")
    # Jika bentuknya sudah desimal biasa
    try:
        return float(coord_str)
    except ValueError:
        pass

    # Coba parsing DMS
    match = re.match(r"(\d+)[°º]?\s*(\d+)'(\d+(?:\.\d+)?)\"?([NSEW])", coord_str.upper())
    if not match:
        return None
    degrees, minutes, seconds, direction = match.groups()
    decimal = float(degrees) + float(minutes)/60 + float(seconds)/3600
    if direction in ['S', 'W']:
        decimal *= -1
    return decimal



async def handle_odp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_permission(update):
        return
    raw_text = update.message.text.strip()
    text = raw_text.upper()  # normalisasi ke uppercase
    logger.info(f"[ODP] Pesan masuk: {raw_text}")

    # 1) Validasi prefix ODP
    if not text.startswith('ODP-'):
        return  # bukan permintaan ODP

    # 2) Parse sto_code, odc_full, odp_number
    try:
        body = text.split('ODP-', 1)[1]            # e.g. "SMR-FBV/021"
        odc_part, odp_number = body.split('/', 1)  # ["SMR-FBV", "021"]
        sto_code = odc_part.split('-', 1)[0]       # "SMR"
        odc_full = 'ODC-' + odc_part               # "ODC-SMR-FBV"
    except Exception as e:
        logger.error("Gagal parsing ODP: %s", e)
        return await update.message.reply_text(
            "❌ Format ODP salah. Contoh: `ODP-SMR-FBV/021`",
            parse_mode='Markdown'
        )

    # 3) List folder FS-1
    try:
        fs1_list = list_sto_folders(FS1_FOLDER_ID)
    except Exception as e:
        logger.error("Gagal akses FS-1: %s", e)
        return await update.message.reply_text("❌ Gagal mengakses folder FS-1 di Drive.")

    # 4) Cari folder STO (case-insensitive)
    fs1_folder = next(
        (f for f in fs1_list if f['name'].upper().endswith(sto_code)),
        None
    )
    if not fs1_folder:
        return await update.message.reply_text(
            f"❌ Folder data untuk STO *{sto_code}* tidak ditemukan.",
            parse_mode='Markdown'
        )

    # 5) List spreadsheets di folder itu
    svc = get_drive_service()
    q = (
        f"'{fs1_folder['id']}' in parents and "
        "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    )
    try:
        resp = svc.files().list(q=q, fields="files(id,name)").execute()
        sheets = resp.get('files', [])
    except Exception as e:
        logger.error("Gagal list spreadsheet: %s", e)
        return await update.message.reply_text("❌ Gagal mengambil daftar spreadsheet.")

    # 6) Pilih spreadsheet berdasarkan odc_full (case-insensitive)
    sheet = next(
        (f for f in sheets if f['name'].upper().startswith(odc_full)),
        None
    )
    if not sheet:
        return await update.message.reply_text(
            f"❌ Spreadsheet *{odc_full}* tidak ditemukan.",
            parse_mode='Markdown'
        )
    await update.message.reply_text(f"✅ Ditemukan file: *{sheet['name']}*", parse_mode='Markdown')

    # 7) Baca data dari Sheet1
        # 7) Baca data dari FS-1 atau Sheet1
    try:
        sheets_svc = get_sheets_service()
        try:
            data = sheets_svc.spreadsheets().values().get(
                spreadsheetId=sheet['id'],
                range='FS-1'
            ).execute().get('values', [])
            logger.info("Berhasil membaca dari sheet: FS-1")
        except Exception:
            logger.warning("Sheet 'FS-1' tidak ditemukan, coba baca 'Sheet1'")
            data = sheets_svc.spreadsheets().values().get(
                spreadsheetId=sheet['id'],
                range='Sheet1'
            ).execute().get('values', [])
            logger.info("Berhasil membaca dari sheet: Sheet1")

    except Exception as e:
        logger.error("Gagal membaca sheet: %s", e)
        return await update.message.reply_text("❌ Gagal membaca isi spreadsheet.")


    # 8) Temukan indeks header (kolom W, index=22)
    header_idx = None
    for i, row in enumerate(data):
        if len(row) > 21 and row[21].strip().upper() == 'NAMA LOCATION ODP':
            header_idx = i
            break
    if header_idx is None:
        return await update.message.reply_text("❌ Struktur sheet tidak sesuai (header ODP tidak ditemukan).")

    # 9) Ambil baris data setelah header
    rows = data[header_idx + 1:]

    # 10) Cari baris ODP: match full-text ODP di kolom W (case-insensitive)
    odp_row = next(
        (r for r in rows
         if len(r) > 21 and r[21].strip().upper() == text),
        None
    )
    if not odp_row:
        return await update.message.reply_text(
            f"❌ ODP *{raw_text}* tidak ditemukan di spreadsheet.",
            parse_mode='Markdown'
        )

    # 11) Fungsi safe_get untuk menghindari IndexError/empty
    def safe_get(r, idx):
        return r[idx].strip() if idx < len(r) and r[idx].strip() else '-'

    # 12) Mapping kolom ke field
    info = {
        'ODP':            safe_get(odp_row, 21),  # V
        'QR Code':        safe_get(odp_row, 20),  # U
        'Panel IN':       safe_get(odp_row, 8),   # I
        'Panel IN Port':  safe_get(odp_row, 9),   # J
        'Panel OUT':      safe_get(odp_row, 14),  # O
        'Panel OUT Port': safe_get(odp_row, 15),  # P
        'Distribusi':     safe_get(odp_row, 17),  # R
        'Kapasitas':      safe_get(odp_row, 18),  # S
        'Alamat':         safe_get(odp_row, 28),  # AC
        'Latitude':       safe_get(odp_row, 31),  # AF
        'Longitude':      safe_get(odp_row, 32),  # AG
    }


    lat_raw = info['Latitude']
    lon_raw = info['Longitude']

    lat = parse_coordinate(lat_raw)
    lon = parse_coordinate(lon_raw)

    if lat is None or lon is None:
        map_url = "https://www.google.com/maps"
        coord_display = f"{lat_raw}, {lon_raw}"
    else:
        map_url = f"https://www.google.com/maps?q={lat},{lon}"
        coord_display = f"[{lat:.6f}, {lon:.6f}]({map_url})"
        
    msg = (
        f"*📡 Informasi ODP: {info['ODP']}*\n\n"
        f"🔗 *QR Code*: {info['QR Code']}\n"
        f"📍 *Alamat*: {info['Alamat']}\n"
        f"🔌 *Panel IN*: {info['Panel IN']} (Port {info['Panel IN Port']})\n"
        f"🔌 *Panel OUT*: {info['Panel OUT']} (Port {info['Panel OUT Port']})\n"
        f"🔀 *Distribusi*: {info['Distribusi']}\n"
        f"📦 *Kapasitas*: {info['Kapasitas']}\n"
        f"🌐 *Koordinat*: {coord_display}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def schematic_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_permission(update):
        return
    """Handle command /schematic FE-XXX-YYY (mendukung banyak file termasuk RESILIENCY)"""
    try:
        if not context.args or len(context.args) < 1:
            await update.message.reply_text(
                "⚠️ Format perintah salah\n"
                "Gunakan: /schematic FE-XXX-YYY\n"
                "Contoh: /schematic FE-SSTT-FAB\n"
                "        /schematic FE-MLA-001"
            )
            return

        keyword = context.args[0].strip().upper()
        logger.info(f"Memproses schematic untuk: {keyword}")

        if len(keyword.split('-')) != 3:
            await update.message.reply_text(
                "❌ Format keyword salah\n"
                "Format harus: FE-KODE_STO-KODE_ODP\n"
                "Contoh: FE-SSTT-FAB"
            )
            return

        try:
            file_list = find_drawio_files(keyword, SCHEMATIC_FOLDER_ID)
            if not file_list:
                logger.warning(f"File tidak ditemukan untuk keyword: {keyword}")
                await update.message.reply_text(
                    f"⚠️ Schematic untuk {keyword} tidak ditemukan\n"
                    "Pastikan:\n"
                    "1. Format FE-XXX-YYY benar\n"
                    "2. File tersedia di Google Drive"
                )
                return
        except HttpError as e:
            logger.error(f"Google Drive Error: {str(e)}")
            await update.message.reply_text("🔧 Sedang ada masalah ke Google Drive, coba lagi nanti")
            return

        for file_id, file_name in file_list:
            input_path = None
            output_path = None
            logger.info(f"File ditemukan: {file_name} ({file_id})")

            try:
                # [Download file]
                with tempfile.NamedTemporaryFile(delete=False, suffix=".drawio") as tmp_file:
                    service = get_drive_service()
                    request = service.files().get_media(fileId=file_id)
                    with open(tmp_file.name, "wb") as f:
                        downloader = MediaIoBaseDownload(f, request)
                        done = False
                        while not done:
                            status, done = downloader.next_chunk()
                            logger.info(f"Downloaded {int(status.progress() * 100)}%")

                    input_path = tmp_file.name
                    logger.info(f"File tersimpan di: {input_path}")

                # [Konversi ke PNG]
                output_path = f"{input_path}.png"
                try:
                    if not convert_drawio_to_png(input_path, output_path):
                        raise Exception("Konversi gagal")
                    logger.info(f"File PNG dibuat: {output_path}")
                except subprocess.TimeoutExpired:
                    logger.error("Konversi timeout (30 detik)")
                    await update.message.reply_text(f"⚠️ Konversi timeout untuk: {file_name}")
                    continue
                except Exception as e:
                    logger.error(f"Konversi error: {str(e)}")
                    await update.message.reply_text(f"⚠️ Gagal mengonversi file: {file_name}")
                    continue

                # [Kirim ke user]
                try:
                    with open(output_path, "rb") as photo:
                        await update.message.reply_photo(
                            photo=photo,
                            caption=f"✅ **{file_name}**\n"
                                    f"📆 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                            parse_mode="Markdown"
                        )
                    logger.info("Schematic berhasil dikirim")
                except Exception as e:
                    logger.error(f"Gagal mengirim foto: {str(e)}")
                    await update.message.reply_text(f"⚠️ Gagal mengirim hasil file: {file_name}")

            finally:
                # Bersihkan file sementara
                for path in [input_path, output_path]:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                            logger.debug(f"File sementara dihapus: {path}")
                        except Exception as e:
                            logger.warning(f"Gagal menghapus {path}: {str(e)}")

    except Exception as e:
        logger.error(f"Error tidak terduga: {str(e)}", exc_info=True)
        await update.message.reply_text("🔧 Terjadi masalah tak terduga. Silakan coba lagi nanti.")



async def schematic_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_permission(update):
        return
    if not await check_user_permission(update):
        return
    try:
        parts = update.message.text.strip().split()
        if len(parts) >= 2:
            context.args = [parts[1]]
            await schematic_handler(update, context)
        else:
            await update.message.reply_text("⚠️ Gunakan format: schematic FE-XXX-YYY")
    except Exception as e:
        logger.error(f"Error di schematic_text_handler: {e}")
        await update.message.reply_text("⚠️ Terjadi kesalahan saat memproses schematic")


async def kml_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_permission(update):
        return
    try:
        parts = update.message.text.strip().split()
        if len(parts) >= 2:
            context.args = parts[1:]
            logger.info(f"[TEXT_HANDLER] args: {context.args}")
            await kml(update, context)
        else:
            await update.message.reply_text("⚠️ Gunakan format: kml ODC-NAMA [DISTRIBUSI X]")
    except Exception as e:
        logger.error(f"Error di kml_text_handler: {e}")
        await update.message.reply_text("⚠️ Terjadi kesalahan saat memproses perintah KML")

async def feeder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_permission(update):
        return
    try:
        odc_full = context.args[0].strip().upper()
        parts = odc_full.split("-")
        if len(parts) < 3:
            return await update.message.reply_text("⚠️ Format: Feeder ODC-XXX-YYY")

        sto = parts[1]
        keyword = parts[2]

        logger.info(f"[FEEDER] User request: {odc_full}, STO={sto}, keyword={keyword}")

        file_id = find_feeder_kml_file(KML_ROOT_FOLDER_ID, sto)
        if not file_id:
            logger.warning(f"[FEEDER] File feeder tidak ditemukan untuk STO {sto}")
            return await update.message.reply_text("❌ File feeder tidak ditemukan di Google Drive.")

        kml_bytes = download_file_as_bytes(file_id)
        filtered_kml = extract_all_kml_folders_by_keyword(kml_bytes, keyword)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".kml") as tmp:
            tmp.write(filtered_kml)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            await update.message.reply_document(InputFile(f, filename=f"{keyword}.kml"))

        os.remove(tmp_path)
        logger.info(f"[FEEDER] File {keyword}.kml berhasil dikirim")

    except Exception as e:
        logger.exception(f"[FEEDER] ERROR: {e}")
        await update.message.reply_text("❌ Terjadi kesalahan saat memproses Feeder")

async def feeder_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_permission(update):
        return

    try:
        text = update.message.text.strip()
        logger.info(f"[FEEDER_TEXT_HANDLER] Pesan user: {text}")
        parts = text.split()
        if len(parts) < 2:
            return await update.message.reply_text("⚠️ Format: Feeder ODC-XXX-YYY")

        full_code = parts[1].upper().replace("/", "-")
        sto_code = full_code.split("-")[1].strip()
        keyword = full_code.split("-")[-1].strip()

        logger.info(f"[FEEDER] User request: {full_code}, STO={sto_code}, keyword={keyword}")
        file_id = find_feeder_kml_file(KML_ROOT_FOLDER_ID, sto_code)

        if not file_id:
            return await update.message.reply_text(f"❌ File KML feeder untuk STO {sto_code} tidak ditemukan.")

        kml_bytes = download_file_as_bytes(file_id)
        filtered_kml = extract_all_kml_folders_by_keyword(kml_bytes, keyword, preserve_full_styles=True)

        if not filtered_kml:
            return await update.message.reply_text(f"⚠️ Feeder {keyword} tidak ditemukan dalam file.")

        filename = f"FEEDER-{sto_code}-{keyword}.kml"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".kml") as tmp:
            tmp.write(filtered_kml)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            await update.message.reply_document(InputFile(f, filename=filename))

        os.remove(tmp_path)

    except Exception as e:
        logger.exception(f"[FEEDER] Error: {e}")
        await update.message.reply_text("❌ Terjadi kesalahan saat memproses permintaan feeder.")

# async def feeder_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if not await check_user_permission(update):
#         return

#     try:
#         text = update.message.text.strip()
#         parts = text.split()
#         if len(parts) < 2:
#             return await update.message.reply_text("⚠️ Format: Feeder ODC-XXX-YYY")

#         full_code = parts[1].upper().replace("/", "-")
#         sto_code = full_code.split("-")[1].strip()
#         keyword = full_code.split("-")[-1].strip()

#         logger.info(f"[FEEDER] Request: {full_code} | STO={sto_code} | keyword={keyword}")

#         file_id, file_name = find_feeder_kml_file(sto_code, keyword)
#         if not file_id:
#             return await update.message.reply_text(
#                 f"❌ File feeder .kml untuk keyword '{keyword}' tidak ditemukan."
#             )

#         kml_bytes = download_file_as_bytes(file_id)
#         filtered_kml = extract_all_kml_folders_by_keyword(kml_bytes, keyword)

#         filename = f"{file_name.replace('.kml','')}_{keyword}.kml"
#         with tempfile.NamedTemporaryFile(delete=False, suffix=".kml") as tmp:
#             tmp.write(filtered_kml)
#             tmp_path = tmp.name

#         with open(tmp_path, "rb") as f:
#             await update.message.reply_document(InputFile(f, filename=filename))

#         os.remove(tmp_path)

#     except Exception as e:
#         logger.exception(f"[FEEDER] Error: {e}")
#         await update.message.reply_text("❌ Terjadi kesalahan saat memproses file feeder.")




# Sebuah handler sederhana untuk pesan-pesan yang tidak dikenali:
async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kita tidak kirim apa-apa atau bisa kirim "Command tidak dikenali"
    logger.info(f"Pesan tidak ditangani: {update.message.text}")



def main():
    # 1) Buat instance bot
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 2) Handler /start masih menggunakan CommandHandler
    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^kml "), kml_text_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("(?i)^feeder "), feeder_text_handler))


    # 3) Handler "kml ..." tanpa slash
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r'(?i)^kml\s+'),
            kml_text_handler
        )
    )

    # 4) Handler "schematic ..." tanpa slash
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r'(?i)^schematic\s+'),
            schematic_text_handler
        )
    )

    # 5) Handler ODP: hanya pesan yang diawali “ODP-”
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r'(?i)^ODP-'),
            handle_odp
        )
    )

    # 6) Handler Connectivity: hanya pesan yang diawali “connectivity,”
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r'(?i)^connectivity,'),
            handle_message
        )
    )

    # 7) Fallback untuk semua pesan teks lainnya
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.Regex(r'(?i)^(connectivity,|ODP-|kml\s+|schematic\s+)'),
            unknown_text
        )
    )

    logger.info("Bot started, polling...")
    app.run_polling()

if __name__ == "__main__":
    main()

