# Photo & Drive Organizer

A smart, multi-tier file organizer designed to process large archives (e.g., Google Takeout) by categorizing, deduplicating, and preserving metadata.

## Features

-   **Smart Categorization**: Automatically separates files into `Media`, `Documents`, `Audio`, and `Other` using MIME types and robust fallbacks.
-   **Deduplication**:
    -   *Exact Duplicates*: Identifies files with identical MD5 hashes and isolates them.
    -   *Quality-Based Deduplication*: Groups similar items and automatically keeps the highest resolution/size version.
-   **Metadata Updates & Injection**:
    -   Fixes and updates **EXIF tags** (DateTimeOriginal) for images.
    -   Adjusts **MP4 creation/modification time atoms** (e.g., `mvhd`, `tkhd`) for videos, with UTC offset compensation for Google Photos uploads.
-   **Intelligent Date Extraction**: Fallback chain extracts creation dates from EXIF, JSON sidecars (`.json`), HTML shortcuts (`ADD_DATE`), filename regex (`YYYY-MM-DD`, Unix timestamps), or file system mtime.
-   **Safe Dry-Run Mode**: Default execution tests the organization structure without moving files.

---

## Installation

Ensure you have Python 3 installed along with the required libraries:

```bash
pip install piexif Pillow
```

---

## Usage

Run the script by supplying source directories and a destination:

```bash
python organize_photos_unified.py --src "C:\Path\To\Source1,C:\Path\To\Source2" --dest "C:\Path\To\Destination"
```

### Options

| Flag | Description |
| :--- | :--- |
| `--src` | **Required**. Source directory paths. Comma-separated for multiples. |
| `--dest` | **Required**. Destination directory path. |
| `--execute` | Enable execution. By default, the script runs in `dry-run` mode to show changes. |
| `--utc-offset` | UTC offset to adjust video timestamps (e.g., `5:30`). Defaults to `5:30`. |

---

## Output Structure

The script creates organized folders under your destination path:

```text
Destination/
├── Media/
│   ├── Organized/
│   │   └── [Year]/
│   │       └── [Month]/
│   │           └── File.jpg
│   └── Duplicates/
│       ├── Exact/
│       └── LowerQuality/
├── Documents/
├── Audio/
└── Other/
```
