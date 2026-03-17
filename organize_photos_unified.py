import os
import shutil
import sys
import argparse
from collections import defaultdict
from datetime import datetime

# Fix for Windows console/redirection Unicode crashes
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
elif hasattr(sys.stdout, 'encoding') and sys.stdout.encoding != 'utf-8':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

# Import modularized helpers
from file_utils import get_file_category, get_file_hash, get_base_name
from date_utils import get_image_info, get_date_from_filename, update_exif_date, update_mp4_metadata

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

    print(f"--- Starting Category-First Modular Layout (Dry Run: {dry_run}) ---")
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
    
    
