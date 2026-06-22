#!/usr/bin/env python3
"""
Aviary Oral History Sync Script

This script syncs Aviary oral history resources with legacy PDF files in three phases:

Phase 1: BUILD RESOURCE LIST
    - Authenticates with Aviary API
    - Fetches all collections
    - Fetches all resources within each collection
    - Extracts metadata (Title, Resourcespace Identifier, media URLs)

Phase 2: MATCH PDFS
    - Loads legacy PDF data from CSV
    - Matches resources by Resourcespace Identifier
    - Reports match statistics

Phase 3: DOWNLOAD FILES
    - Creates folder structure: output_dir/Collection Name/Resource Title/
    - Downloads AV files and PDFs with matching filenames

Usage:
    python aviary_sync.py --output-dir ./downloads
    python aviary_sync.py --output-dir ./downloads --interactive
    python aviary_sync.py --output-dir ./downloads --dry-run
    python aviary_sync.py --output-dir ./downloads --verbose
    python aviary_sync.py --output-dir ./downloads --pdf-only
"""

import argparse
import csv
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

# Configuration
API_BASE_URL = "https://lcdl.aviaryplatform.com/api/v1"
AUTH_URL = "https://www.aviaryplatform.com/api/v1/auth/sign_in"
DEFAULT_API_KEY = ""

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between API requests


@dataclass
class Resource:
    """Represents an Aviary resource with associated metadata."""
    resource_id: int
    title: str
    resourcespace_id: Optional[str]
    media_url: Optional[str]
    collection_id: int
    collection_title: str
    pdf_url: Optional[str] = None

    def get_clean_title(self) -> str:
        """Return a filesystem-safe version of the title."""
        clean = re.sub(r'[<>:"/\\|?*]', '', self.title)
        clean = re.sub(r'\s+', ' ', clean)
        clean = clean.strip()[:100]
        return clean if clean else f"resource_{self.resource_id}"

    def get_clean_collection_title(self) -> str:
        """Return a filesystem-safe version of the collection title."""
        clean = re.sub(r'[<>:"/\\|?*]', '', self.collection_title)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()[:100] or f"collection_{self.collection_id}"


@dataclass
class SyncResult:
    """Tracks results of the sync operation."""
    collections_found: int = 0
    resources_found: int = 0
    resources_with_media: int = 0
    resources_matched_pdf: int = 0
    files_downloaded: int = 0
    errors: list = field(default_factory=list)

    def add_error(self, error_type: str, message: str, details: Optional[dict] = None):
        self.errors.append({
            "type": error_type,
            "message": message,
            "details": details or {},
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        })

    def phase1_summary(self) -> str:
        return (
            f"  Collections found: {self.collections_found}\n"
            f"  Resources found:   {self.resources_found}\n"
            f"  Resources with media URLs: {self.resources_with_media}"
        )

    def phase2_summary(self) -> str:
        return f"  Resources matched to PDFs: {self.resources_matched_pdf}"

    def final_summary(self) -> str:
        lines = [
            "\n" + "=" * 60,
            "SYNC SUMMARY",
            "=" * 60,
            f"Collections found:     {self.collections_found}",
            f"Resources found:       {self.resources_found}",
            f"Resources with media:  {self.resources_with_media}",
            f"Resources with PDFs:   {self.resources_matched_pdf}",
            f"Files downloaded:      {self.files_downloaded}",
            f"Errors encountered:    {len(self.errors)}",
        ]
        if self.errors:
            lines.append("\nERRORS:")
            for err in self.errors:
                lines.append(f"  [{err['type']}] {err['message']}")
                if err['details']:
                    for k, v in err['details'].items():
                        lines.append(f"    {k}: {v}")
        lines.append("=" * 60)
        return "\n".join(lines)


class AviaryClient:
    """Client for interacting with the Aviary API."""

    def __init__(self, api_key: str, logger: logging.Logger):
        self.api_key = api_key
        self.logger = logger
        self.session = requests.Session()
        self.org_id: Optional[int] = None

    def authenticate(self) -> bool:
        """Authenticate with Aviary and get organization ID."""
        self.logger.info("Authenticating with Aviary API...")

        headers = {
            "Accept": "application/json",
            "AUTHORIZATION": self.api_key
        }

        try:
            response = self.session.post(AUTH_URL, headers=headers)
            response.raise_for_status()
            data = response.json()

            if "data" in data and "organizations" in data["data"]:
                orgs = data["data"]["organizations"]
                if orgs:
                    self.org_id = orgs[0]["id"]
                    self.logger.info(f"Authenticated successfully. Organization ID: {self.org_id}")
                    return True

            self.logger.error("No organizations found in auth response")
            return False

        except requests.RequestException as e:
            self.logger.error(f"Authentication failed: {e}")
            return False

    def _get_headers(self) -> dict:
        """Get headers for authenticated API requests."""
        return {
            "Accept": "application/json",
            "AUTHORIZATION": self.api_key,
            "organization-id": str(self.org_id) if self.org_id else ""
        }

    def _api_get(self, endpoint: str) -> Optional[dict]:
        """Make an authenticated GET request to the API."""
        url = f"{API_BASE_URL}/{endpoint}"
        self.logger.debug(f"GET {url}")

        try:
            time.sleep(REQUEST_DELAY)  # Rate limiting
            response = self.session.get(url, headers=self._get_headers())
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            self.logger.error(f"API request failed for {endpoint}: {e}")
            return None

    def get_collections(self) -> list[dict]:
        """Fetch all collections."""
        self.logger.info("Fetching collections...")
        data = self._api_get("collections")
        if data and "data" in data:
            collections = data["data"]
            self.logger.info(f"Found {len(collections)} collections")
            return collections
        return []

    def get_collection_resources(self, collection_id: int, limit: Optional[int] = None) -> list[dict]:
        """Fetch resources in a collection, optionally limited to a maximum count."""
        self.logger.debug(f"Fetching resources for collection {collection_id}")

        resources = []
        page = 1
        per_page = 100

        while True:
            data = self._api_get(f"collections/{collection_id}/resources?page={page}&per_page={per_page}")
            if not data or "data" not in data:
                break

            page_resources = data["data"]
            if not page_resources:
                break

            resources.extend(page_resources)
            self.logger.debug(f"  Page {page}: {len(page_resources)} resources")

            # Check if we've fetched enough for the limit
            if limit is not None and len(resources) >= limit:
                self.logger.debug(f"  Reached fetch limit of {limit}, stopping pagination")
                break

            # Check if there are more pages
            if len(page_resources) < per_page:
                break
            page += 1

        return resources

    def get_resource_details(self, resource_id: int) -> Optional[dict]:
        """Fetch detailed information about a resource."""
        data = self._api_get(f"resources/{resource_id}")
        if data and "data" in data:
            return data["data"]
        return None

    def get_media_file(self, media_id: int) -> Optional[dict]:
        """Fetch media file information."""
        data = self._api_get(f"media_files/{media_id}")
        if data and "data" in data:
            return data["data"]
        return None


def load_legacy_pdf_csv(csv_path: Path, logger: logging.Logger) -> dict[str, dict]:
    """
    Load legacy PDF data from CSV.
    Returns a dict mapping rspace-id to {collectiontitle, filepath}.
    """
    logger.info(f"Loading legacy PDF data from {csv_path}")

    pdf_data = {}

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rspace_id = row.get('rspace-id', '').strip()
                if rspace_id:
                    pdf_data[rspace_id] = {
                        'collectiontitle': row.get('collectiontitle', ''),
                        'filepath': row.get('filepath', '')
                    }

        logger.info(f"Loaded {len(pdf_data)} PDF records")
        return pdf_data

    except FileNotFoundError:
        logger.error(f"CSV file not found: {csv_path}")
        return {}
    except Exception as e:
        logger.error(f"Error reading CSV: {e}")
        return {}


def extract_resourcespace_id(metadata: list[dict]) -> Optional[str]:
    """Extract Resourcespace Identifier from resource metadata."""
    for item in metadata:
        label = item.get('label', '').lower()
        if 'resourcespace' in label and 'identifier' in label:
            data = item.get('data', [])
            if data and len(data) > 0:
                return str(data[0].get('value', ''))
    return None


def get_file_extension(url: str, default: str = '') -> str:
    """Extract file extension from URL."""
    parsed = urlparse(url)
    path = parsed.path
    if '.' in path:
        return path.rsplit('.', 1)[-1].lower()
    return default


def download_file(url: str, dest_path: Path, logger: logging.Logger, dry_run: bool = False) -> bool:
    """Download a file from URL to destination path."""
    if dry_run:
        logger.info(f"    [DRY RUN] Would download: {url}")
        logger.info(f"              To: {dest_path}")
        return True

    try:
        logger.info(f"    Downloading: {url}")
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"    Saved to: {dest_path}")
        return True

    except requests.RequestException as e:
        logger.error(f"    Download failed: {e}")
        return False
    except IOError as e:
        logger.error(f"    File write failed: {e}")
        return False


# =============================================================================
# PHASE 1: Build Resource List
# =============================================================================

def phase1_build_resource_list(
    client: AviaryClient,
    logger: logging.Logger,
    result: SyncResult,
    limit: Optional[int] = None,
    collection_filter: Optional[dict] = None
) -> list[Resource]:
    """
    Phase 1: Fetch all collections and resources from Aviary API.

    Args:
        client: The AviaryClient instance
        logger: Logger instance
        result: SyncResult to track progress
        limit: Optional limit on number of resources to fetch
        collection_filter: Optional single collection dict to process (from interactive selection)

    Returns a list of Resource objects with metadata populated.
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 1: Building resource list from Aviary API")
    logger.info("=" * 60)

    all_resources: list[Resource] = []

    # Use filtered collection or get all collections
    if collection_filter:
        collections = [collection_filter]
        logger.info(f"Processing single collection: {collection_filter.get('title')}")
    else:
        collections = client.get_collections()
        if not collections:
            result.add_error("API", "No collections found or API error")
            return all_resources

    result.collections_found = len(collections)
    logger.info(f"Found {len(collections)} collection(s)")

    for collection in collections:
        collection_id = collection.get('id')
        collection_title = collection.get('title', f'Collection_{collection_id}')

        logger.info(f"\n  Collection: {collection_title} (ID: {collection_id})")

        # Calculate remaining limit for this collection
        remaining_limit = None
        if limit is not None:
            remaining_limit = limit - len(all_resources)
            if remaining_limit <= 0:
                logger.info("  Reached resource limit, stopping collection iteration.")
                break

        # Get resources in this collection
        resources_data = client.get_collection_resources(collection_id, limit=remaining_limit)
        logger.info(f"    Found {len(resources_data)} resources in collection")

        if not resources_data:
            logger.info("    No resources returned from API for this collection")
            continue

        for resource_summary in resources_data:
            # Check limit
            if limit is not None and len(all_resources) >= limit:
                logger.info(f"  Reached limit of {limit} resources, stopping.")
                break

            # API returns 'resource_id' not 'id'
            resource_id = resource_summary.get('resource_id') or resource_summary.get('id')
            if not resource_id:
                logger.warning(f"    Skipping resource with no ID: {resource_summary}")
                continue

            # Get detailed resource info
            resource_details = client.get_resource_details(resource_id)
            if not resource_details:
                result.add_error("API", f"Could not fetch details for resource {resource_id}")
                continue

            title = resource_details.get('title', f'Resource_{resource_id}')
            metadata = resource_details.get('metadata', [])

            # Extract Resourcespace Identifier
            rspace_id = extract_resourcespace_id(metadata)

            # Get media file URL
            # The media_files API returns JSON with these URL fields:
            # - media_download_url: direct download URL (preferred)
            # - transcode_url: transcoded version URL
            # - media_embed_code: embed URL for external sources (YouTube, etc.)
            media_url = None
            media_ids = resource_details.get('media_file_id', [])
            if media_ids:
                media_info = client.get_media_file(media_ids[0])
                if media_info:
                    media_url = (
                        media_info.get('media_download_url') or
                        media_info.get('transcode_url') or
                        media_info.get('media_embed_code')
                    )

            # Create Resource object
            resource = Resource(
                resource_id=resource_id,
                title=title,
                resourcespace_id=rspace_id,
                media_url=media_url,
                collection_id=collection_id,
                collection_title=collection_title
            )

            all_resources.append(resource)
            result.resources_found += 1
            if media_url:
                result.resources_with_media += 1

            logger.debug(f"    Added: {title} (RSpace ID: {rspace_id}, Media: {'Yes' if media_url else 'No'})")

        # Check limit after collection
        if limit is not None and len(all_resources) >= limit:
            break

    logger.info("")
    logger.info("Phase 1 complete:")
    logger.info(result.phase1_summary())

    return all_resources


# =============================================================================
# PHASE 2: Match PDFs
# =============================================================================

def phase2_match_pdfs(
    resources: list[Resource],
    pdf_data: dict[str, dict],
    logger: logging.Logger,
    result: SyncResult
) -> list[Resource]:
    """
    Phase 2: Match resources against legacy PDF data.

    Updates resources in-place with pdf_url where matches are found.
    Returns the same list for chaining.
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 2: Matching resources against legacy PDF data")
    logger.info("=" * 60)

    logger.info(f"Checking {len(resources)} resources against {len(pdf_data)} PDF records")

    matched_count = 0
    unmatched_with_rspace = []

    for resource in resources:
        if resource.resourcespace_id and resource.resourcespace_id in pdf_data:
            resource.pdf_url = pdf_data[resource.resourcespace_id].get('filepath')
            matched_count += 1
            result.resources_matched_pdf += 1
            logger.debug(f"  MATCH: {resource.title} -> {resource.pdf_url}")
        elif resource.resourcespace_id:
            unmatched_with_rspace.append(resource)

    logger.info(f"\n  Matched: {matched_count} resources have associated PDFs")
    logger.info(f"  Unmatched: {len(unmatched_with_rspace)} resources have RSpace IDs but no PDF match")

    if unmatched_with_rspace and logger.isEnabledFor(logging.DEBUG):
        logger.debug("\n  Unmatched RSpace IDs:")
        for r in unmatched_with_rspace[:10]:  # Show first 10
            logger.debug(f"    {r.resourcespace_id}: {r.title}")
        if len(unmatched_with_rspace) > 10:
            logger.debug(f"    ... and {len(unmatched_with_rspace) - 10} more")

    logger.info("")
    logger.info("Phase 2 complete:")
    logger.info(result.phase2_summary())

    return resources


# =============================================================================
# PHASE 3: Download Files
# =============================================================================

def phase3_download_files(
    resources: list[Resource],
    output_dir: Path,
    logger: logging.Logger,
    result: SyncResult,
    dry_run: bool = False,
    pdf_only: bool = False
) -> None:
    """
    Phase 3: Download AV and PDF files to organized folder structure.

    Structure: output_dir/Collection Name/Resource Title/filename.ext

    Args:
        resources: List of Resource objects to download
        output_dir: Base directory for downloads
        logger: Logger instance
        result: SyncResult to track progress
        dry_run: If True, simulate downloads without actually downloading
        pdf_only: If True, skip AV files and only download PDFs
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 3: Downloading files")
    logger.info("=" * 60)

    if dry_run:
        logger.info("[DRY RUN MODE - No files will be created or downloaded]")

    if pdf_only:
        logger.info("[PDF-ONLY MODE - Skipping AV file downloads]")

    # Filter to resources that have something to download
    if pdf_only:
        downloadable = [r for r in resources if r.pdf_url]
    else:
        downloadable = [r for r in resources if r.media_url or r.pdf_url]
    logger.info(f"Resources with files to download: {len(downloadable)}")

    for i, resource in enumerate(downloadable, 1):
        logger.info(f"\n[{i}/{len(downloadable)}] {resource.title}")

        # Build folder path
        collection_folder = output_dir / resource.get_clean_collection_title()
        item_folder = collection_folder / resource.get_clean_title()
        base_filename = resource.get_clean_title()

        if not dry_run:
            item_folder.mkdir(parents=True, exist_ok=True)
        else:
            logger.info(f"  [DRY RUN] Would create folder: {item_folder}")

        # Download media file (AV) - skip if pdf_only mode
        if resource.media_url and not pdf_only:
            media_ext = get_file_extension(resource.media_url, 'mp4')
            media_dest = item_folder / f"{base_filename}.{media_ext}"
            if download_file(resource.media_url, media_dest, logger, dry_run):
                result.files_downloaded += 1
            else:
                result.add_error("Download", f"Media download failed for {resource.title}",
                                {"url": resource.media_url})

        # Download PDF
        if resource.pdf_url:
            pdf_ext = get_file_extension(resource.pdf_url, 'pdf')
            pdf_dest = item_folder / f"{base_filename}.{pdf_ext}"
            if download_file(resource.pdf_url, pdf_dest, logger, dry_run):
                result.files_downloaded += 1
            else:
                result.add_error("Download", f"PDF download failed for {resource.title}",
                                {"url": resource.pdf_url})

    logger.info("")
    logger.info(f"Phase 3 complete: {result.files_downloaded} files downloaded")


def select_collection_interactive(collections: list[dict], logger: logging.Logger) -> Optional[dict]:
    """
    Display a numbered list of collections and prompt the user to select one.

    Returns the selected collection dict, or None if the user cancels.
    """
    if not collections:
        logger.error("No collections available to select from.")
        return None

    print("\n" + "=" * 60)
    print("AVAILABLE COLLECTIONS")
    print("=" * 60)
    print()

    for i, collection in enumerate(collections, 1):
        collection_id = collection.get('id', 'N/A')
        title = collection.get('title', f'Collection_{collection_id}')
        resource_count = collection.get('resources_count', '?')
        print(f"  [{i:2d}] {title}")
        print(f"       ID: {collection_id} | Resources: {resource_count}")
        print()

    print("  [0]  Cancel / Exit")
    print()
    print("=" * 60)

    while True:
        try:
            choice = input("\nEnter the number of the collection to process: ").strip()

            if not choice:
                continue

            choice_num = int(choice)

            if choice_num == 0:
                logger.info("User cancelled collection selection.")
                return None

            if 1 <= choice_num <= len(collections):
                selected = collections[choice_num - 1]
                logger.info(f"Selected collection: {selected.get('title')} (ID: {selected.get('id')})")
                return selected
            else:
                print(f"Please enter a number between 0 and {len(collections)}")

        except ValueError:
            print("Please enter a valid number.")
        except KeyboardInterrupt:
            print("\n")
            logger.info("User interrupted collection selection.")
            return None


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO

    logger = logging.getLogger("aviary_sync")
    logger.setLevel(level)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                   datefmt='%Y-%m-%d %H:%M:%S')
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


def generate_report(resources: list[Resource], output_path: Path, logger: logging.Logger):
    """Generate a CSV report of all resources and their matches."""
    logger.info(f"Generating report: {output_path}")

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'resource_id', 'title', 'resourcespace_id',
            'collection_id', 'collection_title',
            'media_url', 'pdf_url', 'matched'
        ])

        for r in resources:
            writer.writerow([
                r.resource_id, r.title, r.resourcespace_id or '',
                r.collection_id, r.collection_title,
                r.media_url or '', r.pdf_url or '',
                'yes' if r.pdf_url else 'no'
            ])


def main():
    parser = argparse.ArgumentParser(
        description='Sync Aviary oral history resources with legacy PDF files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --output-dir ./downloads
  %(prog)s --output-dir ./downloads --dry-run
  %(prog)s --output-dir ./downloads --dry-run --limit 3
  %(prog)s --output-dir ./downloads --verbose --report report.csv
        """
    )

    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        default=Path('./aviary_downloads'),
        help='Output directory for downloaded files (default: ./aviary_downloads)'
    )

    parser.add_argument(
        '--csv-file', '-c',
        type=Path,
        default=Path(__file__).parent / 'legacy-lcdl-pdf' / 'legacy-pdf-solr.csv',
        help='Path to legacy PDF CSV file'
    )

    parser.add_argument(
        '--api-key', '-k',
        type=str,
        default=DEFAULT_API_KEY,
        help='Aviary API authorization key'
    )

    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Show what would be done without making changes'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )

    parser.add_argument(
        '--report', '-r',
        type=Path,
        help='Generate a CSV report of all resources'
    )

    parser.add_argument(
        '--collection',
        type=int,
        help='Process only a specific collection ID'
    )

    parser.add_argument(
        '--interactive', '-i',
        action='store_true',
        help='Interactively select a collection from a list'
    )

    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=None,
        help='Limit processing to first N resources (useful for testing)'
    )

    parser.add_argument(
        '--pdf-only',
        action='store_true',
        help='Only download PDF files, skip AV media files'
    )

    args = parser.parse_args()

    # Setup
    logger = setup_logging(args.verbose)

    if args.dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE - No files will be downloaded or created")
        logger.info("=" * 60)

    if args.limit:
        logger.info(f"LIMIT MODE - Processing only first {args.limit} resources")

    # Initialize result tracker
    result = SyncResult()

    # Initialize API client
    client = AviaryClient(args.api_key, logger)

    if not client.authenticate():
        logger.error("Authentication failed. Exiting.")
        sys.exit(1)

    # =========================================================================
    # Collection Selection (Interactive or via --collection flag)
    # =========================================================================
    selected_collection = None

    if args.interactive:
        # Fetch collections and let user select one
        logger.info("Fetching collections for interactive selection...")
        all_collections = client.get_collections()

        if not all_collections:
            logger.error("No collections found. Exiting.")
            sys.exit(1)

        selected_collection = select_collection_interactive(all_collections, logger)

        if selected_collection is None:
            logger.info("No collection selected. Exiting.")
            sys.exit(0)

    elif args.collection:
        # Fetch the specific collection by ID
        logger.info(f"Fetching collection ID {args.collection}...")
        all_collections = client.get_collections()
        for col in all_collections:
            if col.get('id') == args.collection:
                selected_collection = col
                break

        if selected_collection is None:
            logger.error(f"Collection ID {args.collection} not found. Exiting.")
            sys.exit(1)

    # =========================================================================
    # PHASE 1: Build resource list from Aviary API
    # =========================================================================
    resources = phase1_build_resource_list(
        client=client,
        logger=logger,
        result=result,
        limit=args.limit,
        collection_filter=selected_collection
    )

    if not resources:
        logger.error("No resources found. Exiting.")
        print(result.final_summary())
        sys.exit(1)

    # =========================================================================
    # PHASE 2: Match resources against legacy PDF data
    # =========================================================================
    pdf_data = load_legacy_pdf_csv(args.csv_file, logger)
    if not pdf_data:
        logger.warning("No PDF data loaded. Continuing without PDF matching.")
    else:
        phase2_match_pdfs(resources, pdf_data, logger, result)

    # =========================================================================
    # PHASE 3: Download files
    # =========================================================================
    phase3_download_files(
        resources=resources,
        output_dir=args.output_dir,
        logger=logger,
        result=result,
        dry_run=args.dry_run,
        pdf_only=args.pdf_only
    )

    # Generate report if requested
    if args.report:
        generate_report(resources, args.report, logger)

    # Print final summary
    print(result.final_summary())

    # Exit with appropriate code
    if result.errors:
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
