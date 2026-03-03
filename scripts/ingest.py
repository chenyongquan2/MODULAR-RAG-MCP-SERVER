"""Offline data ingestion script entry point.

This script provides a command-line interface for ingesting documents into the RAG system.

Usage:
    python scripts/ingest.py --path <file_or_directory> [--collection <name>] [--force]

Examples:
    # Ingest a single PDF file
    python scripts/ingest.py --path ./tests/fixtures/sample_documents/complex_technical_doc.pdf

    # Ingest all PDFs in a directory
    python scripts/ingest.py --path ./tests/fixtures/sample_documents/ --collection my_docs

    # Force reprocess even if file hasn't changed
    python scripts/ingest.py --path ./tests/fixtures/sample_documents/complex_technical_doc.pdf --force
"""

import argparse
import sys
from pathlib import Path

from src.core.settings import load_settings
from src.ingestion.pipeline import IngestionPipeline
from src.observability.logger import get_logger

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Ingest documents into the RAG system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--path",
        type=str,
        required=True,
        help="Path to a PDF file or directory containing PDF files",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="default",
        help="Target collection name (default: default)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocess even if file hasn't changed",
    )
    return parser.parse_args()


def get_pdf_files(path: str) -> list[Path]:
    """Get all PDF files from a path.

    Args:
        path: File or directory path

    Returns:
        list[Path]: List of PDF file paths
    """
    p = Path(path)
    if p.is_file():
        if p.suffix.lower() == ".pdf":
            return [p]
        else:
            logger.warning(f"Skipping non-PDF file: {p}")
            return []
    elif p.is_dir():
        pdf_files = sorted(p.rglob("*.pdf"))
        if not pdf_files:
            logger.warning(f"No PDF files found in directory: {p}")
        return pdf_files
    else:
        logger.error(f"Path does not exist: {p}")
        return []


def main() -> int:
    """Main entry point for ingestion script.

    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    args = parse_args()

    logger.info(f"Starting ingestion with collection: {args.collection}")
    logger.info(f"Source path: {args.path}")
    logger.info(f"Force reprocess: {args.force}")

    try:
        settings = load_settings()
        logger.info("Settings loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        return 1

    pdf_files = get_pdf_files(args.path)
    if not pdf_files:
        logger.error("No PDF files to process")
        return 1

    logger.info(f"Found {len(pdf_files)} PDF file(s) to process")

    pipeline = IngestionPipeline(settings, collection=args.collection)

    success_count = 0
    skip_count = 0
    fail_count = 0

    for pdf_file in pdf_files:
        try:
            logger.info(f"Processing: {pdf_file}")
            result = pipeline.run(str(pdf_file), force=args.force)

            if result.get("status") == "skipped":
                skip_count += 1
                logger.info(f"Skipped (already processed): {pdf_file}")
            elif result.get("status") == "success":
                success_count += 1
                chunk_count = result.get("stages", {}).get("store", {}).get("chunk_count", 0)
                logger.info(f"Successfully ingested: {pdf_file} -> {chunk_count} chunks")
            else:
                fail_count += 1
                error = result.get("error", "Unknown error")
                logger.error(f"Failed to ingest {pdf_file}: {error}")

        except RuntimeError as e:
            if "SKIP" in str(e):
                skip_count += 1
                logger.info(f"Skipped (already processed): {pdf_file}")
            else:
                fail_count += 1
                logger.error(f"Failed to ingest {pdf_file}: {e}")
        except Exception as e:
            fail_count += 1
            logger.error(f"Unexpected error processing {pdf_file}: {e}")

    logger.info(f"Ingestion complete: {success_count} succeeded, {skip_count} skipped, {fail_count} failed")

    if fail_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
