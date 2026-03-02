"""Unit tests for ImageCaptioner with fallback modes.

Tests cover:
1. Disabled mode - config disabled, no Vision LLM calls
2. No Vision LLM - enabled but no LLM instance, graceful degradation
3. Success case - normal caption generation
4. Single image failure - one image fails, others succeed
5. Image file not found - missing file handled gracefully
6. Custom prompt - custom prompt loaded correctly
"""

import pytest
from pathlib import Path
from typing import List, Optional, Dict, Any
from unittest.mock import Mock, patch
import tempfile
import os

from src.core.types import Chunk, ImageReference
from src.core.trace.trace_context import TraceContext
from src.core.settings import Settings, IngestionSettings, ImageCaptionerSettings
from src.ingestion.transform.image_captioner import ImageCaptioner
from src.libs.llm.base_vision_llm import BaseVisionLLM


class MockVisionLLM(BaseVisionLLM):
    """Mock Vision LLM for testing.

    Attributes:
        fail_on_image_ids: List of image IDs that should trigger failures
        call_count: Number of times chat_with_image was called
    """

    def __init__(self, fail_on_image_ids: Optional[List[str]] = None):
        self.fail_on_image_ids = fail_on_image_ids or []
        self.call_count = 0
        self.calls: List[Dict[str, Any]] = []

    def chat_with_image(
        self,
        text: str,
        image: str | bytes,
        trace: Optional[Any] = None,
        **kwargs: Any
    ) -> str:
        """Mock chat_with_image implementation."""
        self.call_count += 1
        self.calls.append({
            "text": text,
            "image": image,
            "trace": trace,
            "kwargs": kwargs
        })

        # Extract image ID from path
        if isinstance(image, str):
            image_id = Path(image).stem
            if image_id in self.fail_on_image_ids:
                raise RuntimeError(f"Mock failure for image {image_id}")
            return f"Caption for {image_id}"
        else:
            return "Caption for image bytes"

    def get_model_name(self) -> str:
        return "mock-vision-llm"

    def get_backend_name(self) -> str:
        return "mock"


@pytest.fixture
def base_settings():
    """Create base settings with minimal config."""
    settings = Mock(spec=Settings)
    settings.ingestion = Mock(spec=IngestionSettings)
    settings.ingestion.image_captioner = Mock(spec=ImageCaptionerSettings)
    settings.ingestion.image_captioner.enabled = True
    settings.ingestion.image_captioner.use_fallback = True
    return settings


@pytest.fixture
def sample_chunk_with_images(tmp_path):
    """Create a sample chunk with image references.

    Returns:
        Tuple of (Chunk, List[image_paths])
    """
    # Create temporary image files
    image_paths = []
    for i in range(3):
        img_path = tmp_path / f"test_image_{i}.png"
        # Create a dummy PNG file (1x1 pixel)
        img_path.write_bytes(
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
            b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
            b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        image_paths.append(str(img_path))

    # Create image references
    image_refs = [
        ImageReference(
            id=f"test_image_{i}",
            path=image_paths[i],
            text_offset=i * 50,
            text_length=20
        )
        for i in range(3)
    ]

    # Create chunk
    chunk = Chunk(
        id="test_chunk_001",
        text="This is a test chunk with [IMAGE: test_image_0] and [IMAGE: test_image_1] and [IMAGE: test_image_2].",
        metadata={
            "source_path": "test.pdf",
            "images": image_refs
        }
    )

    return chunk, image_paths


@pytest.mark.unit
def test_image_captioner_disabled(base_settings, sample_chunk_with_images):
    """Test ImageCaptioner when disabled in config.

    Should return chunks unchanged without calling Vision LLM.
    """
    # Arrange
    base_settings.ingestion.image_captioner.enabled = False
    chunk, _ = sample_chunk_with_images

    mock_llm = MockVisionLLM()
    captioner = ImageCaptioner(
        settings=base_settings,
        vision_llm=mock_llm
    )

    # Act
    result = captioner.transform([chunk])

    # Assert
    assert len(result) == 1
    assert result[0] == chunk  # Same object returned
    assert mock_llm.call_count == 0  # Vision LLM not called
    assert "image_captions" not in result[0].metadata


@pytest.mark.unit
def test_image_captioner_no_vision_llm(base_settings, sample_chunk_with_images):
    """Test ImageCaptioner when Vision LLM is not available.

    Should mark images as unprocessed but not block pipeline.
    """
    # Arrange
    chunk, _ = sample_chunk_with_images

    captioner = ImageCaptioner(
        settings=base_settings,
        vision_llm=None  # No Vision LLM provided
    )

    # Act
    result = captioner.transform([chunk])

    # Assert
    assert len(result) == 1
    assert result[0].id == chunk.id
    assert result[0].metadata["has_unprocessed_images"] is True
    assert "image_captions" not in result[0].metadata


@pytest.mark.unit
def test_image_captioner_success(base_settings, sample_chunk_with_images):
    """Test ImageCaptioner with successful caption generation.

    Should generate captions for all images and store in metadata.
    """
    # Arrange
    chunk, image_paths = sample_chunk_with_images

    mock_llm = MockVisionLLM()
    captioner = ImageCaptioner(
        settings=base_settings,
        vision_llm=mock_llm
    )

    trace = TraceContext(trace_type="ingestion")

    # Act
    result = captioner.transform([chunk], trace=trace)

    # Assert
    assert len(result) == 1
    assert result[0].id == chunk.id

    # Check captions were generated
    assert "image_captions" in result[0].metadata
    captions = result[0].metadata["image_captions"]
    assert len(captions) == 3

    for i in range(3):
        image_id = f"test_image_{i}"
        assert image_id in captions
        assert captions[image_id] == f"Caption for test_image_{i}"

    # Check Vision LLM was called 3 times
    assert mock_llm.call_count == 3

    # Check trace was updated
    last_stage = trace.stages[-1]
    assert last_stage.name == "image_caption"
    assert last_stage.data["total_images"] == 3
    assert last_stage.data["captioned"] == 3
    assert last_stage.data["failed"] == 0
    assert last_stage.data["vision_model"] == "mock-vision-llm"


@pytest.mark.unit
def test_image_captioner_single_image_failure(base_settings, sample_chunk_with_images):
    """Test ImageCaptioner when one image fails.

    Should process other images successfully and record error for failed image.
    """
    # Arrange
    chunk, image_paths = sample_chunk_with_images

    # Mock LLM that fails on test_image_1
    mock_llm = MockVisionLLM(fail_on_image_ids=["test_image_1"])
    captioner = ImageCaptioner(
        settings=base_settings,
        vision_llm=mock_llm
    )

    trace = TraceContext(trace_type="ingestion")

    # Act
    result = captioner.transform([chunk], trace=trace)

    # Assert
    assert len(result) == 1
    assert result[0].id == chunk.id

    # Check captions for successful images
    assert "image_captions" in result[0].metadata
    captions = result[0].metadata["image_captions"]
    assert len(captions) == 2  # Only 2 succeeded
    assert "test_image_0" in captions
    assert "test_image_2" in captions
    assert "test_image_1" not in captions

    # Check errors were recorded
    assert "caption_errors" in result[0].metadata
    errors = result[0].metadata["caption_errors"]
    assert "test_image_1" in errors
    assert "Mock failure" in errors["test_image_1"]

    # Check trace statistics
    last_stage = trace.stages[-1]
    assert last_stage.data["total_images"] == 3
    assert last_stage.data["captioned"] == 2
    assert last_stage.data["failed"] == 1


@pytest.mark.unit
def test_image_captioner_image_file_not_found(base_settings):
    """Test ImageCaptioner when image file doesn't exist.

    Should handle missing files gracefully without blocking pipeline.
    """
    # Arrange
    # Create chunk with non-existent image path
    chunk = Chunk(
        id="test_chunk_002",
        text="This chunk has a missing image [IMAGE: missing].",
        metadata={
            "source_path": "test.pdf",
            "images": [
                ImageReference(
                    id="missing_image",
                    path="/nonexistent/path/missing.png",
                    text_offset=30,
                    text_length=15
                )
            ]
        }
    )

    mock_llm = MockVisionLLM()
    captioner = ImageCaptioner(
        settings=base_settings,
        vision_llm=mock_llm
    )

    # Act
    result = captioner.transform([chunk])

    # Assert
    assert len(result) == 1
    assert result[0].id == chunk.id

    # Check that error was recorded
    assert "caption_errors" in result[0].metadata
    errors = result[0].metadata["caption_errors"]
    assert "missing_image" in errors
    assert "File not found" in errors["missing_image"]

    # Vision LLM should not have been called
    assert mock_llm.call_count == 0


@pytest.mark.unit
def test_image_captioner_custom_prompt(base_settings, sample_chunk_with_images, tmp_path):
    """Test ImageCaptioner with custom prompt template.

    Should load and use custom prompt from file.
    """
    # Arrange
    chunk, image_paths = sample_chunk_with_images

    # Create custom prompt file
    custom_prompt = "CUSTOM PROMPT: Describe this image briefly."
    prompt_file = tmp_path / "custom_prompt.txt"
    prompt_file.write_text(custom_prompt, encoding='utf-8')

    mock_llm = MockVisionLLM()
    captioner = ImageCaptioner(
        settings=base_settings,
        vision_llm=mock_llm,
        prompt_path=str(prompt_file)
    )

    # Act
    result = captioner.transform([chunk])

    # Assert
    assert len(result) == 1

    # Check that custom prompt was used
    assert mock_llm.call_count == 3
    for call in mock_llm.calls:
        assert call["text"] == custom_prompt


@pytest.mark.unit
def test_image_captioner_no_images(base_settings):
    """Test ImageCaptioner with chunk containing no images.

    Should return chunk unchanged.
    """
    # Arrange
    chunk = Chunk(
        id="test_chunk_003",
        text="This is a plain text chunk with no images.",
        metadata={"source_path": "test.pdf"}
    )

    mock_llm = MockVisionLLM()
    captioner = ImageCaptioner(
        settings=base_settings,
        vision_llm=mock_llm
    )

    # Act
    result = captioner.transform([chunk])

    # Assert
    assert len(result) == 1
    assert result[0] == chunk
    assert mock_llm.call_count == 0  # No Vision LLM calls
    assert "image_captions" not in result[0].metadata
    assert "has_unprocessed_images" not in result[0].metadata
