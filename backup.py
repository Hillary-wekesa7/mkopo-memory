"""
Run this as a PythonAnywhere scheduled task daily.
Requires: pip install pydrive2
Set up credentials.json from Google Cloud Console first.
"""

import os
import shutil
from datetime import datetime

try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False


CHAIN_FILE = "mkopo_chain.jsonl"
INDEX_FILE = "uvi_index.json"
BACKUP_DIR = "backups"


def local_backup():
    """Always make a local timestamped backup first."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for f in [CHAIN_FILE, INDEX_FILE]:
        if os.path.exists(f):
            dest = os.path.join(BACKUP_DIR, f"{timestamp}_{f}")
            shutil.copy2(f, dest)
            print(f"Local backup: {dest}")


def gdrive_backup():
    """Upload chain file to Google Drive."""
    if not GDRIVE_AVAILABLE:
        print("pydrive2 not installed. Skipping Google Drive backup.")
        return

    try:
        gauth = GoogleAuth()
        gauth.LocalWebserverAuth()  # First time only; use saved credentials after
        drive = GoogleDrive(gauth)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for f in [CHAIN_FILE, INDEX_FILE]:
            if os.path.exists(f):
                gfile = drive.CreateFile({
                    "title": f"{timestamp}_{f}"
                })
                gfile.SetContentFile(f)
                gfile.Upload()
                print(f"Uploaded {f} to Google Drive")

    except Exception as e:
        print(f"Google Drive backup failed: {e}")


if __name__ == "__main__":
    local_backup()
    gdrive_backup()