import os
import mimetypes
import hashlib
import re

# Fix for Windows console/redirection Unicode crashes
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SUFFIX_REGEX = re.compile(r"(\s*\(\d+\))|(-edited)|(_edited)|(\s*-\s*edited)|(\(\d+\))", re.IGNORECASE)

# Hardcoded Fallbacks for robustness (e.g., if OS mime mappings are scarce)
MEDIA_EXT = {'.jpg', '.jpeg', '.png', '.heic', '.gif', '.bmp', '.webp', '.dng', '.cr2', '.nef', '.arw', '.raw', '.tif', '.tiff', '.mp4', '.mov', '.avi', '.mkv', '.m4v', '.3gp', '.wmv'}
DOCS_EXT = {'.pdf', '.docx', '.xlsx', '.pptx', '.txt', '.csv', '.rtf', '.pages', '.numbers'}
AUDIO_EXT = {'.mp3', '.m4a', '.wav', '.flac'}

def get_file_category(filepath):
    """Categorize file using mimetypes + robust fallbacks."""
    mime, _ = mimetypes.guess_type(filepath)
    if mime:
        mime = mime.lower()
        if mime.startswith('image/') or mime.startswith('video/'):
            return 'Media'
        if mime.startswith('audio/'):
            return 'Audio'
        if mime.startswith('application/pdf') or 'document' in mime or 'sheet' in mime:
            return 'Documents'

    _, ext = os.path.splitext(filepath)
    ext = ext.lower()
    if ext in MEDIA_EXT:
        return 'Media'
    if ext in DOCS_EXT:
        return 'Documents'
    if ext in AUDIO_EXT:
        return 'Audio'
    return 'Other'

def get_file_hash(filepath):
    """Calculate MD5 hash of a file."""
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None

def get_base_name(filename):
    name, ext = os.path.splitext(filename)
    cleaned_name = SUFFIX_REGEX.sub("", name).strip()
    return cleaned_name.lower(), ext.lower()
