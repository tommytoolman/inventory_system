# tests/unit/services/vintageandrare/test_vr_client_errors.py

import pytest
import pandas as pd
import requests
import os
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from io import StringIO, BytesIO
from pathlib import Path
from dotenv import load_dotenv

from app.services.vintageandrare.client import VintageAndRareClient

# Load environment variables at module level
load_dotenv()

class TestVintageAndRareClientErrors:
    """Tests focused on error handling in VintageAndRareClient."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test credentials from environment variables."""
        self.username = os.environ.get("VINTAGE_AND_RARE_USERNAME", "test_user")
        self.password = os.environ.get("VINTAGE_AND_RARE_PASSWORD", "test_pass")
        
        # If environment variables aren't set and we're not in CI, warn
        if (not self.username or not self.password) and not os.environ.get("CI"):
            print("\nWARNING: VintageAndRare credentials not found in environment variables.")
            print("Tests will use placeholder credentials.")
    
    # === Authentication Error Tests ===
    
    @pytest.mark.asyncio
    async def test_authenticate_network_error(self, mocker):
        """Test authentication handling when network error occurs."""
        # Mock requests.Session to raise ConnectionError
        mock_session = mocker.patch('requests.Session')
        mock_session_instance = mock_session.return_value
        mock_session_instance.post.side_effect = requests.ConnectionError("Failed to connect")
        
        client = VintageAndRareClient()
        
        # Act: Try to authenticate with credentials from env
        result = await client.authenticate(self.username, self.password)
        
        # Assert: Should return False and not raise the exception
        assert result is False
        assert client._authenticated is False
    
    @pytest.mark.asyncio
    async def test_authenticate_http_error(self, mocker):
        """Test authentication handling when HTTP error occurs."""
        # Mock requests.Session to return 500 error
        mock_session = mocker.patch('requests.Session')
        mock_session_instance = mock_session.return_value
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_session_instance.post.return_value = mock_response
        
        client = VintageAndRareClient()
        
        # Act: Try to authenticate with credentials from env
        result = await client.authenticate(self.username, self.password)
        
        # Assert: Should return False and log error
        assert result is False
        assert client._authenticated is False
    
    @pytest.mark.asyncio
    async def test_authenticate_unexpected_response(self, mocker):
        """Test authentication handling when response is unexpected."""
        # Mock requests.Session to return 200 but with unexpected content
        mock_session = mocker.patch('requests.Session')
        mock_session_instance = mock_session.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>Unexpected login response</html>"
        mock_session_instance.post.return_value = mock_response
        
        client = VintageAndRareClient()
        
        # Act: Try to authenticate with credentials from env
        result = await client.authenticate(self.username, self.password)
        
        # Assert: Should return False if login markers not found
        assert result is False
        assert client._authenticated is False
    
    # === Download Error Tests ===
    
    @pytest.mark.asyncio
    async def test_download_inventory_csv_without_auth(self, mocker):
        """Test download fails appropriately when not authenticated."""
        client = VintageAndRareClient(username=self.username, password=self.password)
        client._authenticated = False
        
        # Act & Assert: Should raise an exception
        with pytest.raises(Exception) as exc_info:
            await client.download_inventory_csv()
        
        assert "not authenticated" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_download_inventory_csv_network_error(self, mocker):
        """Test download handling when network error occurs."""
        # Mock requests.Session
        mock_session = mocker.patch('requests.Session')
        mock_session_instance = mock_session.return_value
        mock_session_instance.get.side_effect = requests.ConnectionError("Failed to connect")
        
        client = VintageAndRareClient(username=self.username, password=self.password)
        client._authenticated = True  # Skip authentication
        client._session = mock_session_instance
        
        # Act & Assert: Should raise an exception with descriptive message
        with pytest.raises(Exception) as exc_info:
            await client.download_inventory_csv()
        
        assert "network error" in str(exc_info.value).lower() or "failed to connect" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_download_inventory_csv_http_error(self, mocker):
        """Test download handling when HTTP error occurs."""
        # Mock requests.Session
        mock_session = mocker.patch('requests.Session')
        mock_session_instance = mock_session.return_value
        mock_response = MagicMock()
        mock_response.status_code = 403  # Forbidden
        mock_response.text = "Access denied"
        mock_session_instance.get.return_value = mock_response
        
        client = VintageAndRareClient(username=self.username, password=self.password)
        client._authenticated = True  # Skip authentication
        client._session = mock_session_instance
        
        # Act & Assert: Should raise an exception with status code
        with pytest.raises(Exception) as exc_info:
            await client.download_inventory_csv()
        
        assert "403" in str(exc_info.value) or "forbidden" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_download_inventory_csv_empty_response(self, mocker):
        """Test download handling when response is empty."""
        # Mock requests.Session
        mock_session = mocker.patch('requests.Session')
        mock_session_instance = mock_session.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b""  # Empty content
        mock_session_instance.get.return_value = mock_response
        
        client = VintageAndRareClient(username=self.username, password=self.password)
        client._authenticated = True  # Skip authentication
        client._session = mock_session_instance
        
        # Act & Assert: Should raise an exception about empty content
        with pytest.raises(Exception) as exc_info:
            await client.download_inventory_csv()
        
        assert "empty" in str(exc_info.value).lower() or "no data" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_download_inventory_dataframe_csv_parsing_error(self, mocker):
        """Test handling of malformed CSV data."""
        # Mock the CSV download to return invalid CSV data
        mock_download = mocker.patch.object(
            VintageAndRareClient, 
            'download_inventory_csv',
            return_value=b"invalid,csv,data\nwithout,proper,structure"
        )
        
        # Mock pandas to raise an exception when reading CSV
        mock_read_csv = mocker.patch('pandas.read_csv', side_effect=pd.errors.ParserError("CSV parsing error"))
        
        # Setup client
        client = VintageAndRareClient(username=self.username, password=self.password)
        client._authenticated = True
        
        # Act & Assert: Should raise an exception about CSV parsing
        with pytest.raises(Exception) as exc_info:
            await client.download_inventory_dataframe()
        
        assert "parsing" in str(exc_info.value).lower() or "csv" in str(exc_info.value).lower()
        mock_read_csv.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_download_inventory_dataframe_file_write_error(self, mocker):
        """Test handling of file write errors."""
        # Mock the CSV download to return some data
        sample_csv = b"brand,model,price\nFender,Stratocaster,1000"
        mock_download = mocker.patch.object(
            VintageAndRareClient, 
            'download_inventory_csv',
            return_value=sample_csv
        )
        
        # Mock pandas read_csv to return a DataFrame
        mock_df = pd.DataFrame({'brand': ['Fender'], 'model': ['Stratocaster'], 'price': [1000]})
        mocker.patch('pandas.read_csv', return_value=mock_df)
        
        # Mock file operations to raise an error
        mock_open = mocker.patch('builtins.open', side_effect=PermissionError("Permission denied"))
        mocker.patch('pathlib.Path.mkdir')
        
        # Setup client
        client = VintageAndRareClient(username=self.username, password=self.password)
        client._authenticated = True
        
        # Act & Assert: Should handle the error but still return DataFrame
        try:
            df = await client.download_inventory_dataframe(save_to_file=True, output_path="inventory.csv")
            # Should have returned DataFrame even though file write failed
            assert isinstance(df, pd.DataFrame)
            mock_open.assert_called_once()
            # Should have logged a warning (harder to test)
        except Exception as e:
            pytest.fail(f"Should not have raised exception but returned DataFrame: {e}")