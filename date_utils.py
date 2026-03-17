import os
import re
import json
import struct
import piexif
from PIL import Image
from datetime import datetime, timedelta
from file_utils import get_file_category

# Fix for Windows console/redirection Unicode crashes
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def update_exif_date(filepath, target_date):
    """Inject DateTimeOriginal EXIF tag for fallback preservation."""
    try:
        exif_dict = piexif.load(filepath)
        date_str = target_date.strftime("%Y:%m:%d %H:%M:%S")
        if 'Exif' not in exif_dict:
            exif_dict['Exif'] = {}
        exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = date_str
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, filepath)
    except Exception:
        pass

def get_seconds_since_1904(dt):
    epoch = datetime(1904, 1, 1)
    return int((dt - epoch).total_seconds())

def get_datetime_from_seconds(sec):
    epoch = datetime(1904, 1, 1)
    try:
        return epoch + timedelta(seconds=sec)
    except Exception:
        return None

def parse_atoms(f, atom_start, atom_end, depth=0, new_seconds=None):
    f.seek(atom_start)
    while f.tell() < atom_end:
        pos = f.tell()
        header = f.read(8)
        if len(header) < 8: break
        size, name = struct.unpack('>I4s', header)
        if size == 0:
            f.seek(0, 2)
            inner_end = f.tell()
            size = inner_end - pos
            f.seek(pos + 8)
        elif size == 1:
            size_ext = f.read(8)
            if len(size_ext) < 8: break
            size = struct.unpack('>Q', size_ext)[0]
            header_size = 16
        else:
            header_size = 8
        inner_start = pos + header_size
        inner_end = pos + size
        if name in {b'moov', b'trak', b'mdia'}:
            res = parse_atoms(f, inner_start, inner_end, depth + 1, new_seconds)
            if res is not None and new_seconds is None:
                return res
        elif name in {b'mvhd', b'tkhd', b'mdhd'}:
            f.seek(inner_start)
            version_flags = f.read(4)
            if len(version_flags) < 4: break
            version = version_flags[0]
            if version == 1:
                orig_sec_bytes = f.read(8)
                if len(orig_sec_bytes) < 8: break
                orig_seconds = struct.unpack('>Q', orig_sec_bytes)[0]
                has_64 = True
            else:
                orig_sec_bytes = f.read(4)
                if len(orig_sec_bytes) < 4: break
                orig_seconds = struct.unpack('>I', orig_sec_bytes)[0]
                has_64 = False
            orig_dt = get_datetime_from_seconds(orig_seconds)
            if new_seconds is not None:
                f.seek(inner_start + 4)
                if has_64:
                    f.write(struct.pack('>Q', new_seconds))
                    f.write(struct.pack('>Q', new_seconds))
                else:
                    f.write(struct.pack('>I', new_seconds))
                    f.write(struct.pack('>I', new_seconds))
            else:
                if orig_dt:
                    return orig_dt
        f.seek(inner_end)
    return None

def update_mp4_metadata(filepath, target_date_obj, offset_hours=5, offset_minutes=30):
    """Updates MP4 creation time with UTC adjustment for Google Photos."""
    orig_dt = None
    try:
        with open(filepath, 'rb') as f:
            f.seek(0, 2)
            full_size = f.tell()
            orig_dt = parse_atoms(f, 0, full_size)
    except Exception:
        pass

    target_dt = target_date_obj
    if orig_dt:
        try:
             target_dt = target_date_obj.replace(
                  hour=orig_dt.hour,
                  minute=orig_dt.minute,
                  second=orig_dt.second,
                  microsecond=0
             )
        except ValueError:
             pass

    target_dt_utc = target_dt - timedelta(hours=offset_hours, minutes=offset_minutes)
    new_seconds = get_seconds_since_1904(target_dt_utc)

    try:
        with open(filepath, 'r+b') as f:
            f.seek(0, 2)
            full_size = f.tell()
            parse_atoms(f, 0, full_size, new_seconds=new_seconds)
    except Exception:
         pass

def get_json_date(filepath):
    """Check for Google Takeout Sidecar JSON and extract date."""
    possible_jsons = [filepath + ".json", os.path.splitext(filepath)[0] + ".json"]
    for j_path in possible_jsons:
        if os.path.exists(j_path):
            try:
                with open(j_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    timestamp = data.get('photoTakenTime', {}).get('timestamp')
                    if timestamp:
                        return datetime.fromtimestamp(int(timestamp))
            except Exception:
                pass
    return None

def get_html_date(filepath):
    """Check for Google Drive Shortcut HTML and extract ADD_DATE."""
    possible_htmls = [filepath + ".html", os.path.splitext(filepath)[0] + ".html"]
    for h_path in possible_htmls:
        if os.path.exists(h_path):
            try:
                with open(h_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    match = re.search(r'ADD_DATE="(\d+)"', content)
                    if match:
                        return datetime.fromtimestamp(int(match.group(1)))
            except Exception:
                pass
    return None

def get_image_info(filepath):
    """Returns (width, height, file_size, exif_date)"""
    file_size = os.path.getsize(filepath)
    width = 0
    height = 0
    exif_date = None
    category = get_file_category(filepath)

    if category == 'Media':
        try:
            with Image.open(filepath) as img:
                width, height = img.size
                if hasattr(img, '_getexif'):
                    exif = img._getexif()
                    if exif:
                        exif_date_str = exif.get(36867) or exif.get(306)
                        if exif_date_str:
                            try:
                                exif_date = datetime.strptime(exif_date_str[:10], '%Y:%m:%d')
                            except ValueError:
                                pass
        except Exception:
            pass

    if not exif_date:
        exif_date = get_json_date(filepath)
    if not exif_date:
        exif_date = get_html_date(filepath)

    return width, height, file_size, exif_date

def get_date_from_filename(filename):
    """
    Expandable Date Extraction Logic
    Add new regex patterns here to support more filename formats.
    """
    try:
        # Pattern 1: YYYYMMDD_HHMMSS
        match1 = re.search(r"(\d{4})(\d{2})(\d{2})_\d{6}", filename)
        if match1:
            return datetime(int(match1.group(1)), int(match1.group(2)), int(match1.group(3)))

        # Pattern 2: YYYY-MM-DD
        match2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", filename)
        if match2:
            return datetime(int(match2.group(1)), int(match2.group(2)), int(match2.group(3)))

        # Pattern 3: general 201x/202x sequence
        match3 = re.search(r"(201\d|202\d)(\d{2})(\d{2})", filename)
        if match3:
            year = int(match3.group(1))
            part1 = int(match3.group(2))
            part2 = int(match3.group(3))
            if 1 <= part1 <= 12 and 1 <= part2 <= 31:
                return datetime(year, part1, part2)
            elif 1 <= part2 <= 12 and 1 <= part1 <= 31:
                return datetime(year, part2, part1)

        # Pattern 4: 13-digit Unix Millisecond timestamps
        match_unix = re.search(r"(\d{13})", filename)
        if match_unix:
            ms = int(match_unix.group(1))
            if 946684800000 < ms < 1893456000000:
                return datetime.fromtimestamp(ms / 1000.0)

        # Pattern 5: Smart General Fallback
        digits_list = re.findall(r'\d+', filename)
        for digits in digits_list:
            if len(digits) >= 7:
                if len(digits) >= 8:
                    try:
                        year = int(digits[:4])
                        month = int(digits[4:6])
                        day = int(digits[6:8])
                        if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                             return datetime(year, month, day)
                    except ValueError:
                        pass
                
                try:
                    year = int(digits[:4])
                    month = int(digits[4:5])
                    day = int(digits[5:7])
                    if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                          return datetime(year, month, day)
                except ValueError:
                    pass
                    
                try:
                    year = int(digits[:4])
                    month = int(digits[4:6])
                    day = int(digits[6:7])
                    if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                          return datetime(year, month, day)
                except ValueError:
                    pass
    except ValueError:
        pass

    return None
