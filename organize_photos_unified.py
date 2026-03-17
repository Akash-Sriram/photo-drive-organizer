import os
import shutil
import hashlib
import re
import sys
import json
import argparse
import mimetypes
import piexif
from PIL import Image
from collections import defaultdict
from datetime import datetime, timedelta
import struct



# Fix for Windows console/redirection Unicode crashes
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
elif hasattr(sys.stdout, 'encoding') and sys.stdout.encoding != 'utf-8':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

SUFFIX_REGEX = re.compile(r"(\s*\(\d+\))|(-edited)|(_edited)|(\s*-\s*edited)|(\(\d+\))", re.IGNORECASE)

def update_exif_date(filepath, target_date):
    """Inject DateTimeOriginal EXIF tag for fallback preservation."""
    try:
        exif_dict = piexif.load(filepath)
        date_str = target_date.strftime("%Y:%m:%d %H:%M:%S")
        # Ensure Exif tag structure exists
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

    # Use original date time if found
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

    # ONLY run Image Open on Media files
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

    # Try JSON sidecar as fallback
    if not exif_date:
        exif_date = get_json_date(filepath)
    
    # Try HTML shortcut fallback
    if not exif_date:
        exif_date = get_html_date(filepath)

    return width, height, file_size, exif_date


def get_date_from_filename(filename):
    try:
        match1 = re.search(r"(\d{4})(\d{2})(\d{2})_\d{6}", filename)
        if match1:
            return datetime(int(match1.group(1)), int(match1.group(2)), int(match1.group(3)))

        match2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", filename)
        if match2:
            return datetime(int(match2.group(1)), int(match2.group(2)), int(match2.group(3)))

        match3 = re.search(r"(201\d|202\d)(\d{2})(\d{2})", filename)
        if match3:
            year = int(match3.group(1))
            part1 = int(match3.group(2))
            part2 = int(match3.group(3))
            if 1 <= part1 <= 12 and 1 <= part2 <= 31:
                return datetime(year, part1, part2)
            elif 1 <= part2 <= 12 and 1 <= part1 <= 31:
                return datetime(year, part2, part1)

        # Match 13-digit Unix Millisecond timestamps (Common for Messenger hubs)
        match_unix = re.search(r"(\d{13})", filename)
        if match_unix:
            ms = int(match_unix.group(1))
            # 2000-01-01 to 2030-01-01 safety thresholds
            if 946684800000 < ms < 1893456000000:
                return datetime.fromtimestamp(ms / 1000.0)

        # 5. Smart General Fallback for any digit sequence
        digits_list = re.findall(r'\d+', filename)
        for digits in digits_list:
            if len(digits) >= 7:
                # Try 8 digit standard YYYYMMDD
                if len(digits) >= 8:
                    try:
                        year = int(digits[:4])
                        month = int(digits[4:6])
                        day = int(digits[6:8])
                        if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                             return datetime(year, month, day)
                    except ValueError:
                        pass
                
                # Try 7 digit YYYYMDD (Single digit month)
                try:
                    year = int(digits[:4])
                    month = int(digits[4:5])
                    day = int(digits[5:7])
                    if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                         return datetime(year, month, day)
                except ValueError:
                    pass
                    
                # Try 7 digit YYYYMMD (Single digit day)
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

def main():
    parser = argparse.ArgumentParser(description="Multi-tier Photo and Drive Organizer")
    parser.add_argument("--src", required=True, help="Source directories (comma-separated if multiple)")
    parser.add_argument("--dest", required=True, help="Destination directory where output folders will be placed")
    parser.add_argument("--execute", action="store_true", help="Enable to execute copy, defaults to dry-run")
    parser.add_argument("--utc-offset", default="5:30", help="UTC offset to subtract for videos (e.g., 5:30 or 0:00)")
    
    args = parser.parse_args()
    
    # Support Comma-Separated Multiple Paths
    src_dirs = [os.path.abspath(s.strip()) for s in args.src.split(',')]
    dest_dir = os.path.abspath(args.dest)
    dry_run = not args.execute
    
    # Parse UTC offset
    offset_hours, offset_minutes = 0, 0
    if args.utc_offset:
        try:
            parts = args.utc_offset.split(':')
            offset_hours = int(parts[0])
            offset_minutes = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            print(f"Warning: Invalid utc-offset format {args.utc_offset}. Using 0:00.")

    print(f"--- Starting Category-First Unified Layout (Dry Run: {dry_run}) ---")
    print(f"Sources: {', '.join(src_dirs)}")
    print(f"Destination: {dest_dir}")

    files = []
    for src_dir in src_dirs:
        if not os.path.exists(src_dir):
            print(f"Warning: Source path {src_dir} does not exist. Skipping.")
            continue
        for root, dirs, filenames in os.walk(src_dir):
            for f in filenames:
                if f.lower().endswith('.json'):
                    continue
                files.append(os.path.join(root, f))

    print(f"Found {len(files)} items to process recursively.")

    # 1. Group by Hash (Exact Duplicates)
    hash_groups = defaultdict(list)
    for f in files:
        h = get_file_hash(f)
        if h:
            hash_groups[h].append(f)

    exact_duplicates_moved = 0
    remaining_files = []

    for h, file_list in hash_groups.items():
        if len(file_list) > 1:
            sorted_by_name = sorted(file_list, key=lambda x: len(os.path.basename(x)))
            winner = sorted_by_name[0]
            losers = sorted_by_name[1:]
            
            remaining_files.append(winner)
            print(f"[Exact Duplicate] Keeping: {os.path.basename(winner)}")
            for l in losers:
                cat = get_file_category(l)
                if cat == 'Media':
                    target_dir_dup = os.path.join(dest_dir, "Media", "Duplicates", "Exact")
                else:
                    target_dir_dup = os.path.join(dest_dir, cat, "Duplicates") # Flat
                
                print(f"  -> Copying Duplicate: {os.path.basename(l)} to {os.path.relpath(target_dir_dup, dest_dir)}")
                exact_duplicates_moved += 1
                if not dry_run:
                    try:
                        os.makedirs(target_dir_dup, exist_ok=True)
                        shutil.copy2(l, os.path.join(target_dir_dup, os.path.basename(l)))
                    except Exception:
                        pass
        else:
            remaining_files.append(file_list[0])

    print(f"Exact duplicates found: {exact_duplicates_moved}")

    # 2. Group by Base Name (Near Duplicates)
    base_groups = defaultdict(list)
    for f in remaining_files:
        filename = os.path.basename(f)
        basename, ext = get_base_name(filename)
        base_groups[(basename, ext)].append(f)

    quality_duplicates_moved = 0
    final_files = []

    for (basename, ext), file_list in base_groups.items():
        if len(file_list) > 1:
            infos = []
            for f in file_list:
                w, h, sz, exif_d = get_image_info(f)
                res = w * h
                infos.append({'path': f, 'res': res, 'size': sz, 'name': os.path.basename(f)})
            
            sorted_infos = sorted(infos, key=lambda x: (x['res'], x['size']), reverse=True)
            winner_info = sorted_infos[0]
            loser_infos = sorted_infos[1:]

            final_files.append(winner_info['path'])
            print(f"[Quality Group] Keeping: {winner_info['name']}")
            
            for l_info in loser_infos:
                cat = get_file_category(l_info['path'])
                if cat == 'Media':
                     target_dir_dup = os.path.join(dest_dir, "Media", "Duplicates", "LowerQuality")
                else:
                     target_dir_dup = os.path.join(dest_dir, cat) # Just route back to flat cat folder
                     
                print(f"  -> Copying Lower Quality: {l_info['name']} to {os.path.relpath(target_dir_dup, dest_dir)}")
                quality_duplicates_moved += 1
                if not dry_run:
                    try:
                         os.makedirs(target_dir_dup, exist_ok=True)
                         shutil.copy2(l_info['path'], os.path.join(target_dir_dup, l_info['name']))
                    except Exception:
                         pass
        else:
            final_files.append(file_list[0])

    print(f"Lower quality items separated: {quality_duplicates_moved}")

    # 3. Organize by Date/Type
    organized_count = 0
    for f in final_files:
        filename = os.path.basename(f)
        _, _, _, exif_date = get_image_info(f)
        category = get_file_category(f)
        
        target_date = exif_date
        method = "EXIF/JSON" if exif_date else None

        if not target_date:
            target_date = get_date_from_filename(filename)
            if target_date:
                method = "Filename"

        if not target_date:
            # File mtime fallback
            try:
                mtime = os.path.getmtime(f)
                target_date = datetime.fromtimestamp(mtime)
                method = "File MTime"
            except Exception:
                target_date = datetime.now() # Safety Absolute fallback
                method = "Now (Error)"

        year_str = target_date.strftime("%Y")
        month_str = target_date.strftime("%m-%B")
        
        # Category-First Destination Layout
        if category == 'Media':
            target_dir = os.path.join(dest_dir, "Media", "Organized", year_str, month_str)
        else:
            target_dir = os.path.join(dest_dir, category) # Flattened

        print(f"[Organize] {filename} -> {os.path.relpath(target_dir, dest_dir)} (via {method})")
        organized_count += 1
        
        if not dry_run:
            os.makedirs(target_dir, exist_ok=True)
            try:
                dest_path = os.path.join(target_dir, filename)
                shutil.copy2(f, dest_path)
                
                # Write back "strategically gathered" date into File MTime
                t_stamp = target_date.timestamp()
                os.utime(dest_path, (t_stamp, t_stamp))

                # Inject EXIF update for JPEG formats
                if filename.lower().endswith(('.jpg', '.jpeg')):
                    update_exif_date(dest_path, target_date)

                # Inject MP4 updates for videos
                if filename.lower().endswith(('.mp4', '.mov')):
                    update_mp4_metadata(dest_path, target_date, offset_hours, offset_minutes)

            except Exception as e:
                print(f"Error copying {filename}: {e}")

    print(f"Total items remaining and organized: {organized_count}")
    print("--- Done ---")

if __name__ == "__main__":
    main()


