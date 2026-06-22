# Aviary Oral History Sync Script

A Python script for synchronizing resources from the [Aviary](https://aviaryplatform.com) oral history platform with legacy PDF files. The script fetches collection and resource metadata via the Aviary API, matches resources against a CSV of legacy PDFs, and downloads files into an organized folder structure.

## Features

- Authenticates with Aviary API using an API key
- Fetches all collections and resources with pagination support
- Extracts metadata including Resourcespace Identifiers
- Matches resources against legacy PDF records from a CSV file
- Downloads AV media files and/or PDFs to organized folders
- Supports dry-run mode for testing without downloading
- Interactive collection selection
- Progress tracking and error reporting
- CSV report generation

## Requirements

- Python 3.9+
- `requests` library

Install dependencies:

```bash
pip install requests
```

## Usage

### Basic Usage

Download all files to the default output directory:

```bash
python aviary_sync.py
```

Specify a custom output directory:

```bash
python aviary_sync.py --output-dir ./downloads
```

### Command-Line Options

| Option | Short | Description |
|--------|-------|-------------|
| `--output-dir PATH` | `-o` | Output directory for downloaded files (default: `./aviary_downloads`) |
| `--csv-file PATH` | `-c` | Path to legacy PDF CSV file (default: `legacy-lcdl-pdf/legacy-pdf-solr.csv`) |
| `--api-key KEY` | `-k` | Aviary API authorization key |
| `--dry-run` | `-n` | Show what would be done without making changes |
| `--verbose` | `-v` | Enable verbose/debug output |
| `--report PATH` | `-r` | Generate a CSV report of all resources |
| `--collection ID` | | Process only a specific collection by ID |
| `--interactive` | `-i` | Interactively select a collection from a list |
| `--limit N` | `-l` | Limit processing to first N resources (useful for testing) |
| `--pdf-only` | | Only download PDF files, skip AV media files |

### Examples

**Dry run to preview what would be downloaded:**

```bash
python aviary_sync.py --output-dir ./downloads --dry-run
```

**Download only PDFs (skip AV files):**

```bash
python aviary_sync.py --output-dir ./downloads --pdf-only
```

**Test with a small number of resources:**

```bash
python aviary_sync.py --output-dir ./downloads --dry-run --limit 5
```

**Interactive collection selection:**

```bash
python aviary_sync.py --output-dir ./downloads --interactive
```

**Process a specific collection:**

```bash
python aviary_sync.py --output-dir ./downloads --collection 42
```

**Generate a report without downloading:**

```bash
python aviary_sync.py --dry-run --report resources.csv
```

**Verbose output for debugging:**

```bash
python aviary_sync.py --output-dir ./downloads --verbose
```

**Combine options:**

```bash
python aviary_sync.py --output-dir ./downloads --pdf-only --collection 42 --verbose
```

## How It Works

The script operates in three phases:

### Phase 1: Build Resource List

1. Authenticates with the Aviary API
2. Fetches all collections (or a selected collection)
3. Iterates through resources in each collection
4. Extracts metadata including:
   - Resource ID and title
   - Resourcespace Identifier (for PDF matching)
   - Media file URLs

### Phase 2: Match PDFs

1. Loads legacy PDF data from the CSV file
2. Matches resources by their Resourcespace Identifier
3. Associates PDF URLs with matched resources
4. Reports match statistics

### Phase 3: Download Files

1. Creates folder structure: `output_dir/Collection Name/Resource Title/`
2. Downloads AV media files (unless `--pdf-only` is set)
3. Downloads matched PDF files
4. Tracks download progress and errors

## Output Structure

Downloaded files are organized as:

```
output_dir/
  Collection Name/
    Resource Title/
      Resource Title.mp4    (AV file)
      Resource Title.pdf    (PDF file)
    Another Resource/
      Another Resource.mp3
      Another Resource.pdf
  Another Collection/
    ...
```

File and folder names are sanitized to remove characters not allowed in file paths.

## CSV File Format

The legacy PDF CSV file should have the following columns:

| Column | Description |
|--------|-------------|
| `rspace-id` | Resourcespace Identifier (used for matching) |
| `collectiontitle` | Collection title |
| `filepath` | URL or path to the PDF file |

## API Authentication

The script requires an Aviary API key for authentication. You can:

1. Use the default key (if configured in the script)
2. Pass a key via the `--api-key` option
3. Set up environment-based configuration (modify the script as needed)

For information on generating an API key, see the [Aviary documentation on creating an API key](https://coda.aviaryplatform.com/edit-user-profile-83#_luHGN).

## Rate Limiting

The script includes built-in rate limiting (0.5 second delay between API requests) to avoid overwhelming the Aviary API.

## Error Handling

- Authentication failures cause immediate exit
- Individual resource/download failures are logged and reported in the final summary
- The script exits with code 1 if any errors occurred, 0 otherwise

## Report Output

When using `--report`, a CSV file is generated with:

- `resource_id`: Aviary resource ID
- `title`: Resource title
- `resourcespace_id`: Resourcespace Identifier
- `collection_id`: Collection ID
- `collection_title`: Collection title
- `media_url`: URL of the AV media file
- `pdf_url`: URL of the matched PDF
- `matched`: "yes" or "no" indicating PDF match status
