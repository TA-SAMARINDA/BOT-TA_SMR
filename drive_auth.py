# # drive_auth.py - versi akhir dengan prompt='consent' dan dua scope aktif

# import os.path
# from google.oauth2.credentials import Credentials
# from google_auth_oauthlib.flow import InstalledAppFlow
# from google.auth.transport.requests import Request
# from googleapiclient.discovery import build

# # ✅ Gunakan kedua scope ini untuk akses Google Drive (.kml) dan Google Sheets
# SCOPES = [
#     "https://www.googleapis.com/auth/drive.readonly",
#     "https://www.googleapis.com/auth/spreadsheets.readonly"
# ]

# def get_drive_service():
#     creds = None
#     if os.path.exists("token.json"):
#         creds = Credentials.from_authorized_user_file("token.json", SCOPES)

#     if not creds or not creds.valid:
#         if creds and creds.expired and creds.refresh_token:
#             creds.refresh(Request())
#             with open("token.json", "w") as token:
#                 token.write(creds.to_json())
#         else:
#             flow = InstalledAppFlow.from_client_secrets_file(
#                 "credentials.json", SCOPES
#             )
#             creds = flow.run_local_server(port=0, access_type='offline', prompt='consent')
#             with open("token.json", "w") as token:
#                 token.write(creds.to_json())

#     return build("drive", "v3", credentials=creds)

# def get_sheets_service():
#     creds = None
#     if os.path.exists("token.json"):
#         creds = Credentials.from_authorized_user_file("token.json", SCOPES)

#     if not creds or not creds.valid:
#         if creds and creds.expired and creds.refresh_token:
#             creds.refresh(Request())
#             with open("token.json", "w") as token:
#                 token.write(creds.to_json())
#         else:
#             flow = InstalledAppFlow.from_client_secrets_file(
#                 "credentials.json", SCOPES
#             )
#             creds = flow.run_local_server(port=0, access_type='offline', prompt='consent')
#             with open("token.json", "w") as token:
#                 token.write(creds.to_json())

#     return build("sheets", "v4", credentials=creds)

# if __name__ == '__main__':
#     # ⬇️ Paksa login agar scope Drive & Sheets aktif
#     _ = get_drive_service()
#     _ = get_sheets_service()
#     print("✅ Login berhasil. Token berisi akses Google Drive & Sheets.")


import os
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# SCOPES yang digunakan oleh bot
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]

def get_credentials():
    # Tulis ulang token.json dari environment variable jika belum ada
    if not os.path.exists("token.json") and 'CREDENTIALS' in os.environ:
        with open("token.json", "w") as f:
            f.write(os.environ['CREDENTIALS'])

    # Buat objek credentials dari file token.json
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    return creds

def get_drive_service():
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)
    return service

def get_sheets_service():
    creds = get_credentials()
    service = build('sheets', 'v4', credentials=creds)
    return service

