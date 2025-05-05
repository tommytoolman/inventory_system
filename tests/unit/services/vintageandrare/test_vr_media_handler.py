import pytest
import requests
import tempfile
import shutil
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from app.services.vintageandrare.media_handler import MediaHandler

# --- Test Cases ---

def test_media_handler_init_creates_temp_dir():
    """Test that __init__ creates a temporary directory."""
    with patch('tempfile.mkdtemp') as mock_mkdtemp:
        temp_dir_path = "/fake/temp/dir"
        mock_mkdtemp.return_value = temp_dir_path
        handler = MediaHandler()
        mock_mkdtemp.assert_called_once()
        assert handler.temp_dir == Path(temp_dir_path)
        # Clean up mock directory if needed, though handler should do it
        if os.path.exists(temp_dir_path): os.rmdir(temp_dir_path) # Simple cleanup for mock

@patch('requests.get')
@patch('shutil.copyfileobj')
@patch('tempfile.mkdtemp')
@patch('builtins.open', new_callable=mock_open)
def test_download_image_success(mock_open_func, mock_mkdtemp, mock_copyfileobj, mock_requests_get):
    """Test successful image download and saving."""
    # Arrange
    fake_temp_dir = "/fake/temp/media"
    mock_mkdtemp.return_value = fake_temp_dir
    image_url = "http://example.com/image.jpg"
    image_content = b"fake_image_bytes"

    mock_response = MagicMock(spec=requests.Response)
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {'content-type': 'image/jpeg'}
    mock_response.raw = MagicMock() # Simulate the raw stream object
    mock_requests_get.return_value = mock_response

    handler = MediaHandler()
    expected_file_path = handler.temp_dir / "temp_0.jpg"

    # Act
    result_path = handler.download_image(image_url)

    # Assert
    # 1. Check the return value is correct
    assert result_path == expected_file_path

    # 2. Check external calls
    mock_requests_get.assert_called_once_with(image_url, stream=True)
    mock_response.raise_for_status.assert_called_once()

    # 3. Check file operations were attempted correctly
    #    - open was called with the expected path and mode
    mock_open_func.assert_called_once_with(expected_file_path, 'wb')
    #    - copyfileobj was called with the response stream and the mock file handle
    mock_file_handle = mock_open_func() # Get the mock file handle returned by open()
    mock_copyfileobj.assert_called_once_with(mock_response.raw, mock_file_handle)

    # 4. Check internal state
    assert handler._temp_files == [expected_file_path]

    # Manual cleanup for mocks if needed
    if os.path.exists(fake_temp_dir): shutil.rmtree(fake_temp_dir)


@patch('requests.get')
@patch('tempfile.mkdtemp')
def test_download_image_request_error(mock_mkdtemp, mock_requests_get):
    """Test download fails on requests error."""
    mock_mkdtemp.return_value = "/fake/dir"
    image_url = "http://example.com/image.jpg"
    mock_requests_get.side_effect = requests.exceptions.RequestException("Connection failed")

    handler = MediaHandler()
    result_path = handler.download_image(image_url)

    assert result_path is None
    assert not handler._temp_files # No file should be tracked

@patch('requests.get')
@patch('tempfile.mkdtemp')
def test_download_image_bad_status(mock_mkdtemp, mock_requests_get):
    """Test download fails on bad HTTP status."""
    mock_mkdtemp.return_value = "/fake/dir"
    image_url = "http://example.com/image.jpg"

    mock_response = MagicMock(spec=requests.Response)
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
    mock_requests_get.return_value = mock_response

    handler = MediaHandler()
    result_path = handler.download_image(image_url)

    assert result_path is None

@patch('requests.get')
@patch('tempfile.mkdtemp')
def test_download_image_not_image_content(mock_mkdtemp, mock_requests_get):
    """Test download fails if content-type is not image."""
    mock_mkdtemp.return_value = "/fake/dir"
    image_url = "http://example.com/not_an_image.html"

    mock_response = MagicMock(spec=requests.Response)
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {'content-type': 'text/html'} # Wrong content type
    mock_requests_get.return_value = mock_response

    handler = MediaHandler()
    result_path = handler.download_image(image_url)

    assert result_path is None

def test_media_handler_cleanup():
    """Test the cleanup method removes the temp directory."""
    handler = MediaHandler()
    temp_dir_path_str = str(handler.temp_dir)
    # Create a dummy file inside to ensure rmtree works
    Path(temp_dir_path_str, "dummy.txt").touch()

    assert os.path.exists(temp_dir_path_str)
    handler.clean_up()
    assert not os.path.exists(temp_dir_path_str)

def test_media_handler_context_manager():
    """Test using the handler as a context manager triggers cleanup."""
    temp_dir_path_str = None
    with patch('shutil.rmtree') as mock_rmtree:
        with MediaHandler() as handler:
            temp_dir_path_str = str(handler.temp_dir)
            assert os.path.exists(temp_dir_path_str)
        # After exiting 'with' block:
        mock_rmtree.assert_called_once_with(Path(temp_dir_path_str))