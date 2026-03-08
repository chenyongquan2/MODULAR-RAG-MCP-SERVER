"""Online query script entry point.

This script provides a command-line interface for querying the RAG system.

Usage:
    python scripts/query.py --query <query_text> [--top-k <number>] [--collection <name>]

Examples:
    # Query with default settings
    python scripts/query.py --query "How to configure LLM?"

    # Query with custom top-k
    python scripts/query.py --query "What is RAG?" --top-k 10

    # Query specific collection
    python scripts/query.py --query "Tell me about embeddings" --collection my_docs
"""

import argparse
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.core.settings import load_settings
from src.core.query_engine.fusion import HybridSearch
from src.observability.logger import get_logger

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Query the RAG system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="Query text to search for",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results to return (default: 5)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Filter by collection name (optional)",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point for the query script.

    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    args = parse_args()

    try:
        settings = load_settings()
        logger.info("Settings loaded successfully")

        filters = None
        if args.collection:
            filters = {"collection": args.collection}
            logger.info("Using collection filter: %s", args.collection)

        hybrid_search = HybridSearch(settings)
        logger.info("HybridSearch initialized")

        logger.info("Executing query: %s", args.query)
        results = hybrid_search.search(
            query=args.query,
            top_k=args.top_k,
            filters=filters,
        )

        if not results:
            print("\nNo results found for query.")
            return 0

        print(f"\n{'=' * 60}")
        print(f"Query: {args.query}")
        print(f"Results: {len(results)} found")
        print(f"{'=' * 60}\n")

        for i, result in enumerate(results, 1):
            print(f"[{i}] Score: {result.score:.4f}")
            print(f"    Chunk ID: {result.chunk_id}")
            if result.metadata.get("collection"):
                print(f"    Collection: {result.metadata.get('collection')}")
            text_preview = result.text[:200] + "..." if len(result.text) > 200 else result.text
            print(f"    Text: {text_preview}")
            print()

        return 0

    except ValueError as e:
        logger.error("Validation error: %s", e)
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.error("Query failed: %s", e)
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
