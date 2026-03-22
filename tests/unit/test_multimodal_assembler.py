"""Unit tests for MultimodalAssembler."""

import base64
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp.types import TextContent, ImageContent

from src.core.response.multimodal_assembler import MultimodalAssembler
from src.core.types import RetrievalResult
from src.ingestion.storage.image_storage import SQLiteImageStorage


class TestMultimodalAssembler:
    """Test MultimodalAssembler functionality."""

    @pytest.fixture
    def sample_image_data(self) -> bytes:
        """Create a sample PNG image data (1x1 pixel transparent PNG)."""
        # 1x1 pixel transparent PNG
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        )

    @pytest.fixture
    def temp_image_file(self, sample_image_data: bytes) -> str:
        """Create a temporary image file."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(sample_image_data)
            temp_path = f.name
        yield temp_path
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)

    @pytest.fixture
    def mock_image_storage(self, temp_image_file: str) -> MagicMock:
        """Create a mock ImageStorage."""
        storage = MagicMock(spec=SQLiteImageStorage)

        def get_image_path_side_effect(image_id: str) -> str | None:
            if image_id == "test_img_1":
                return temp_image_file
            elif image_id == "test_img_2":
                return temp_image_file  # Reuse same image for both
            return None

        storage.get_image_path.side_effect = get_image_path_side_effect
        return storage

    def test_init_with_default_storage(self):
        """Test MultimodalAssembler initializes with default storage."""
        assembler = MultimodalAssembler()
        assert assembler._image_storage is not None
        assert isinstance(assembler._image_storage, SQLiteImageStorage)

    def test_init_with_custom_storage(self, mock_image_storage: MagicMock):
        """Test MultimodalAssembler initializes with custom storage."""
        assembler = MultimodalAssembler(mock_image_storage)
        assert assembler._image_storage == mock_image_storage

    def test_assemble_without_images(self):
        """Test assemble returns only text when no images present."""
        assembler = MultimodalAssembler()
        markdown = "This is a test response without images."

        results: list[RetrievalResult] = []

        contents = assembler.assemble(markdown, results)

        assert len(contents) == 2
        assert isinstance(contents[0], TextContent)
        assert contents[0].text == markdown
        assert isinstance(contents[1], dict)
        assert "images" in contents[1]
        assert contents[1]["images"] == []

    def test_assemble_with_images(self, mock_image_storage: MagicMock):
        """Test assemble returns text and images when images present."""
        assembler = MultimodalAssembler(mock_image_storage)

        markdown = "This is a response with [IMAGE: test_img_1] an image."

        results: list[RetrievalResult] = [
            RetrievalResult(
                chunk_id="chunk_1",
                score=0.95,
                text="Sample text",
                metadata={
                    "images": [
                        {
                            "id": "test_img_1",
                            "path": "/fake/path/image1.png",
                            "text_offset": 32,
                            "text_length": 15,
                        }
                    ]
                },
            )
        ]

        contents = assembler.assemble(markdown, results)

        # Should have: TextContent, ImageContent, images dict
        assert len(contents) == 3
        assert isinstance(contents[0], TextContent)
        assert isinstance(contents[1], ImageContent)
        assert isinstance(contents[2], dict)

        # Verify image content
        image_content = contents[1]
        assert image_content.type == "image"
        assert image_content.mimeType == "image/png"
        assert image_content.data is not None
        assert len(image_content.data) > 0

        # Verify images dict
        assert "images" in contents[2]
        assert len(contents[2]["images"]) == 1

    def test_extract_image_refs_from_results(self, mock_image_storage: MagicMock):
        """Test extracting image references from retrieval results."""
        assembler = MultimodalAssembler(mock_image_storage)

        results: list[RetrievalResult] = [
            RetrievalResult(
                chunk_id="chunk_1",
                score=0.95,
                text="Text with image",
                metadata={
                    "images": [
                        {"id": "img_1", "path": "path1.png", "text_offset": 10, "text_length": 15},
                        {"id": "img_2", "path": "path2.png", "text_offset": 30, "text_length": 15},
                    ]
                },
            ),
            RetrievalResult(
                chunk_id="chunk_2",
                score=0.90,
                text="More text",
                metadata={
                    "images": [
                        {"id": "img_3", "path": "path3.png", "text_offset": 5, "text_length": 15},
                        # Duplicate id should be deduplicated
                        {"id": "img_1", "path": "path1.png", "text_offset": 20, "text_length": 15},
                    ]
                },
            ),
        ]

        image_refs = assembler._extract_image_refs(results)

        assert len(image_refs) == 3  # Duplicates removed
        ids = [ref["id"] for ref in image_refs]
        assert "img_1" in ids
        assert "img_2" in ids
        assert "img_3" in ids

    def test_extract_image_refs_sorts_by_offset(self):
        """Test that image refs are sorted by text offset."""
        assembler = MultimodalAssembler()

        results: list[RetrievalResult] = [
            RetrievalResult(
                chunk_id="chunk_1",
                score=0.95,
                text="Text",
                metadata={
                    "images": [
                        {"id": "img_2", "text_offset": 100, "text_length": 15},
                        {"id": "img_1", "text_offset": 10, "text_length": 15},
                        {"id": "img_3", "text_offset": 50, "text_length": 15},
                    ]
                },
            )
        ]

        image_refs = assembler._extract_image_refs(results)

        assert len(image_refs) == 3
        assert image_refs[0]["id"] == "img_1"  # Offset 10
        assert image_refs[1]["id"] == "img_3"  # Offset 50
        assert image_refs[2]["id"] == "img_2"  # Offset 100

    def test_load_image_success(self, mock_image_storage: MagicMock, temp_image_file: str):
        """Test successful image loading."""
        assembler = MultimodalAssembler(mock_image_storage)

        ref = {"id": "test_img_1", "path": temp_image_file}
        image_content = assembler._load_image(ref)

        assert image_content is not None
        assert image_content.type == "image"
        assert image_content.mimeType == "image/png"
        assert isinstance(image_content.data, str)
        assert len(image_content.data) > 0

    def test_load_image_not_found(self, mock_image_storage: MagicMock):
        """Test image loading when image is not in storage."""
        assembler = MultimodalAssembler(mock_image_storage)

        ref = {"id": "nonexistent", "path": "/fake/path"}
        image_content = assembler._load_image(ref)

        assert image_content is None

    def test_load_image_file_not_exists(self):
        """Test image loading when file does not exist."""
        mock_storage = MagicMock()
        mock_storage.get_image_path.return_value = "/nonexistent/path.png"

        assembler = MultimodalAssembler(mock_storage)

        ref = {"id": "test", "path": "/nonexistent/path.png"}
        image_content = assembler._load_image(ref)

        assert image_content is None

    def test_detect_mime_type(self):
        """Test MIME type detection."""
        assert MultimodalAssembler.detect_mime_type("test.png") == "image/png"
        assert MultimodalAssembler.detect_mime_type("test.jpg") == "image/jpeg"
        assert MultimodalAssembler.detect_mime_type("test.jpeg") == "image/jpeg"
        assert MultimodalAssembler.detect_mime_type("test.gif") == "image/gif"
        assert MultimodalAssembler.detect_mime_type("test.webp") == "image/webp"
        assert MultimodalAssembler.detect_mime_type("test.unknown") == "image/png"

    def test_sort_by_text_offset(self, sample_image_data: bytes):
        """Test sorting images by their position in markdown."""
        assembler = MultimodalAssembler()

        markdown = "Text [IMAGE: img2] middle [IMAGE: img1] end"

        # Create mock image contents with IDs
        base64_data = base64.b64encode(sample_image_data).decode("utf-8")
        image1 = ("img1", ImageContent(type="image", data=base64_data, mimeType="image/png"))
        image2 = ("img2", ImageContent(type="image", data=base64_data, mimeType="image/png"))
        image3 = ("img3", ImageContent(type="image", data=base64_data, mimeType="image/png"))

        # Shuffle the order
        unsorted = [image3, image1, image2]

        sorted_images = assembler._sort_by_text_offset(unsorted, markdown)

        # img2 appears before img1 in markdown
        assert len(sorted_images) == 3
        assert sorted_images[0][0] == "img2"  # First in markdown
        assert sorted_images[1][0] == "img1"  # Second in markdown
        assert sorted_images[2][0] == "img3"  # Not in markdown, appended at end

        # Verify the ImageContent objects are correct
        assert isinstance(sorted_images[0][1], ImageContent)
        assert isinstance(sorted_images[1][1], ImageContent)
        assert isinstance(sorted_images[2][1], ImageContent)

    def test_graceful_degradation_on_image_error(self):
        """Test that image errors don't break the whole response."""
        mock_storage = MagicMock()
        mock_storage.get_image_path.return_value = "/nonexistent/path.png"

        assembler = MultimodalAssembler(mock_storage)

        markdown = "Response with [IMAGE: missing_img] image."

        results: list[RetrievalResult] = [
            RetrievalResult(
                chunk_id="chunk_1",
                score=0.95,
                text="Text",
                metadata={
                    "images": [
                        {"id": "missing_img", "path": "/nonexistent/path.png", "text_offset": 15, "text_length": 15},
                    ]
                },
            )
        ]

        # Should not raise exception, but return text only
        contents = assembler.assemble(markdown, results)

        assert len(contents) >= 2
        assert isinstance(contents[0], TextContent)
        assert contents[0].text == markdown

    def test_multiple_images_sorting(self, mock_image_storage: MagicMock):
        """Test multiple images are correctly sorted by position in text."""
        assembler = MultimodalAssembler(mock_image_storage)

        markdown = "Start [IMAGE: test_img_1] middle [IMAGE: test_img_2] end"

        results: list[RetrievalResult] = [
            RetrievalResult(
                chunk_id="chunk_1",
                score=0.95,
                text="Text",
                metadata={
                    "images": [
                        {"id": "test_img_2", "path": "/fake/path2.png", "text_offset": 33, "text_length": 15},
                        {"id": "test_img_1", "path": "/fake/path1.png", "text_offset": 6, "text_length": 15},
                    ]
                },
            )
        ]

        contents = assembler.assemble(markdown, results)

        # Should have: TextContent + 2 ImageContents + images dict = 4 items
        assert len(contents) == 4
        assert isinstance(contents[0], TextContent)
        assert isinstance(contents[1], ImageContent)
        assert isinstance(contents[2], ImageContent)
        assert isinstance(contents[3], dict)

        # Verify images dict contains 2 images
        assert "images" in contents[3]
        assert len(contents[3]["images"]) == 2