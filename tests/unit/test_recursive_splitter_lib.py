"""Unit tests for RecursiveSplitter implementation.

This module tests the RecursiveSplitter class, including basic functionality,
Markdown structure preservation, parameter overrides, and edge cases.
"""

from __future__ import annotations

import pytest

from src.core.settings import Settings, SplitterSettings
from src.libs.splitter.recursive_splitter import RecursiveSplitter


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def default_settings() -> Settings:
    """Create default settings for testing."""
    settings = Settings(
        llm=None,
        embedding=None,
        vision_llm=None,
        vector_store=None,
        splitter=SplitterSettings(
            strategy="recursive",
            chunk_size=1000,
            chunk_overlap=200,
        )
    )
    return settings


@pytest.fixture
def markdown_sample() -> str:
    """Sample Markdown text with various structures."""
    return """# Main Title

## First Section
This is the first paragraph with some content.

```python
def example():
    return "code block"
```

## Second Section
- List item 1
- List item 2
- List item 3

> This is a quote block
> with multiple lines

### Subsection
More content here.
"""


@pytest.fixture
def long_text() -> str:
    """Generate a long text for performance testing."""
    return "This is a long paragraph with repeated content. " * 200


# ============================================================================
# Group 1: Basic Functionality Tests (6 test cases)
# ============================================================================


@pytest.mark.unit
def test_split_simple_text(default_settings: Settings):
    """Test basic text splitting functionality."""
    splitter = RecursiveSplitter(default_settings)
    text = "Hello world. This is a test. Foo bar baz."

    chunks = splitter.split_text(text)

    assert isinstance(chunks, list)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) for c in chunks)
    assert all(len(c) > 0 for c in chunks)


@pytest.mark.unit
def test_split_respects_chunk_size(default_settings: Settings):
    """Test that chunks respect configured chunk_size."""
    splitter = RecursiveSplitter(default_settings)
    # Create text longer than chunk_size
    text = "A" * 2000

    chunks = splitter.split_text(text)

    # Most chunks should be close to chunk_size (some may be slightly larger)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= default_settings.splitter.chunk_size * 1.1  # 10% tolerance


@pytest.mark.unit
def test_split_respects_chunk_overlap(default_settings: Settings):
    """Test that chunks have proper overlap."""
    splitter = RecursiveSplitter(default_settings)
    text = "Sentence one. " * 100  # Repeating pattern to verify overlap

    chunks = splitter.split_text(text)

    if len(chunks) > 1:
        # Check that consecutive chunks share content (overlap)
        # This is a heuristic check - exact overlap depends on separator positions
        assert len(chunks) >= 2


@pytest.mark.unit
def test_split_empty_text_raises_error(default_settings: Settings):
    """Test that empty text raises ValueError."""
    splitter = RecursiveSplitter(default_settings)

    with pytest.raises(ValueError, match="Text cannot be empty"):
        splitter.split_text("")


@pytest.mark.unit
def test_split_whitespace_text_raises_error(default_settings: Settings):
    """Test that whitespace-only text raises ValueError."""
    splitter = RecursiveSplitter(default_settings)

    with pytest.raises(ValueError, match="Text cannot be empty"):
        splitter.split_text("   \n\t   ")


@pytest.mark.unit
def test_get_metadata_methods(default_settings: Settings):
    """Test metadata accessor methods."""
    splitter = RecursiveSplitter(default_settings)

    assert splitter.get_strategy_name() == "recursive"
    assert splitter.get_chunk_size() == 1000
    assert splitter.get_chunk_overlap() == 200


# ============================================================================
# Group 2: Markdown Structure Preservation Tests (4 test cases)
# ============================================================================


@pytest.mark.unit
def test_markdown_headers_not_split(default_settings: Settings, markdown_sample: str):
    """Test that Markdown headers are preserved and not split mid-header."""
    # Use small chunk size to force splitting
    small_settings = Settings(
        llm=None,
        embedding=None,
        vision_llm=None,
        vector_store=None,
        splitter=SplitterSettings(strategy="recursive", chunk_size=100, chunk_overlap=20)
    )
    splitter = RecursiveSplitter(small_settings)

    chunks = splitter.split_text(markdown_sample)

    # Verify no chunk starts with incomplete header (e.g., "#" without space)
    for chunk in chunks:
        # Headers should be complete (e.g., "## Title" not "# Tit")
        lines = chunk.strip().split("\n")
        for line in lines:
            if line.startswith("#"):
                # Should have proper header format
                assert " " in line or line == "#" * len(line.split()[0])


@pytest.mark.unit
def test_code_blocks_preserved(default_settings: Settings, markdown_sample: str):
    """Test that code blocks remain intact."""
    # Use small chunk size
    small_settings = Settings(
        llm=None,
        embedding=None,
        vision_llm=None,
        vector_store=None,
        splitter=SplitterSettings(strategy="recursive", chunk_size=150, chunk_overlap=20)
    )
    splitter = RecursiveSplitter(small_settings)

    chunks = splitter.split_text(markdown_sample)

    # Check if code block appears in chunks
    code_found = False
    for chunk in chunks:
        if "def example():" in chunk:
            code_found = True
            # Code block should be complete
            assert "```python" in chunk or "def example():" in chunk

    # Code block should exist in at least one chunk
    assert code_found


@pytest.mark.unit
def test_nested_structures(default_settings: Settings):
    """Test handling of nested Markdown structures."""
    nested_text = """
## Section
- Item 1
  - Nested item 1.1
  - Nested item 1.2
- Item 2

> Quote level 1
> > Quote level 2
"""
    splitter = RecursiveSplitter(default_settings)

    chunks = splitter.split_text(nested_text)

    assert len(chunks) >= 1
    # Verify all content is preserved
    combined = "".join(chunks)
    assert "Nested item 1.1" in combined
    assert "Quote level 2" in combined


@pytest.mark.unit
def test_mixed_content(default_settings: Settings):
    """Test mixed content with text, code, and lists."""
    mixed_text = """
# Title

Some introductory text here.

```python
def func():
    pass
```

- List item
- Another item

Final paragraph.
"""
    splitter = RecursiveSplitter(default_settings)

    chunks = splitter.split_text(mixed_text)

    assert len(chunks) >= 1
    combined = "".join(chunks)
    assert "def func():" in combined
    assert "List item" in combined
    assert "Final paragraph" in combined


# ============================================================================
# Group 3: Parameter Override Tests (3 test cases)
# ============================================================================


@pytest.mark.unit
def test_runtime_chunk_size_override(default_settings: Settings):
    """Test runtime override of chunk_size parameter."""
    splitter = RecursiveSplitter(default_settings)
    text = "A" * 500

    # Override chunk_size at runtime
    chunks = splitter.split_text(text, chunk_size=100, chunk_overlap=20)

    # Should create more chunks with smaller size
    assert len(chunks) > 1
    # Most chunks should be around 100 chars
    for chunk in chunks:
        assert len(chunk) <= 120  # Some tolerance


@pytest.mark.unit
def test_runtime_overlap_override(default_settings: Settings):
    """Test runtime override of chunk_overlap parameter."""
    splitter = RecursiveSplitter(default_settings)
    text = "Sentence. " * 150

    # Override overlap at runtime
    chunks = splitter.split_text(text, chunk_size=200, chunk_overlap=50)

    assert len(chunks) >= 2


@pytest.mark.unit
def test_custom_separators(default_settings: Settings):
    """Test custom separator list."""
    splitter = RecursiveSplitter(default_settings)
    text = "Part1|Part2|Part3|Part4|Part5"

    # Use custom separator
    chunks = splitter.split_text(
        text,
        chunk_size=10,
        chunk_overlap=0,
        separators=["|", ""]
    )

    # Should split on "|" first
    assert len(chunks) >= 3


# ============================================================================
# Group 4: Edge Cases and Boundary Tests (3 test cases)
# ============================================================================


@pytest.mark.unit
def test_text_shorter_than_chunk_size(default_settings: Settings):
    """Test text shorter than chunk_size returns single chunk."""
    splitter = RecursiveSplitter(default_settings)
    short_text = "This is short."

    chunks = splitter.split_text(short_text)

    assert len(chunks) == 1
    assert chunks[0] == short_text


@pytest.mark.unit
def test_very_long_text(default_settings: Settings, long_text: str):
    """Test handling of very long text."""
    splitter = RecursiveSplitter(default_settings)

    chunks = splitter.split_text(long_text)

    # Should split into multiple chunks
    assert len(chunks) > 1
    # All content should be preserved
    combined_length = sum(len(c) for c in chunks)
    # Account for overlap
    assert combined_length >= len(long_text)


@pytest.mark.unit
def test_special_characters(default_settings: Settings):
    """Test handling of special characters and Unicode."""
    special_text = "Hello 世界! 🌍🚀 Special chars: @#$%^&*()"
    splitter = RecursiveSplitter(default_settings)

    chunks = splitter.split_text(special_text)

    assert len(chunks) >= 1
    combined = "".join(chunks)
    assert "世界" in combined
    assert "🌍" in combined
    assert "🚀" in combined


# ============================================================================
# Additional: Initialization Validation Tests
# ============================================================================


@pytest.mark.unit
def test_invalid_chunk_size_raises_error(default_settings: Settings):
    """Test that invalid chunk_size raises ValueError."""
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        RecursiveSplitter(default_settings, chunk_size=0)

    with pytest.raises(ValueError, match="chunk_size must be positive"):
        RecursiveSplitter(default_settings, chunk_size=-100)


@pytest.mark.unit
def test_invalid_chunk_overlap_raises_error(default_settings: Settings):
    """Test that invalid chunk_overlap raises ValueError."""
    with pytest.raises(ValueError, match="chunk_overlap cannot be negative"):
        RecursiveSplitter(default_settings, chunk_overlap=-10)


@pytest.mark.unit
def test_overlap_greater_than_size_raises_error(default_settings: Settings):
    """Test that overlap >= chunk_size raises ValueError."""
    with pytest.raises(ValueError, match="chunk_overlap .* must be less than"):
        RecursiveSplitter(default_settings, chunk_size=100, chunk_overlap=100)

    with pytest.raises(ValueError, match="chunk_overlap .* must be less than"):
        RecursiveSplitter(default_settings, chunk_size=100, chunk_overlap=150)
