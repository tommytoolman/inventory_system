# tests/unit/services/vintageandrare/test_vr_client_errors.py
"""
Tests for VintageAndRareClient error handling.
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests
from app.services.vintageandrare.client import VintageAndRareClient


class TestVintageAndRareClientErrors:

    @pytest.mark.asyncio
    async def test_authenticate_network_error(self, mocker):
        """Test authentication handles network error gracefully."""
        client = VintageAndRareClient(username="testuser", password="testpass")

        mocker.patch.object(client.session, "get", side_effect=requests.ConnectionError("Failed to connect"))
        mocker.patch.object(client.session, "post", side_effect=requests.ConnectionError("Failed to connect"))

        if client.cf_session is not None:
            mocker.patch.object(client.cf_session, "get", side_effect=Exception("Connection failed"))
            mocker.patch.object(client.cf_session, "post", side_effect=Exception("Connection failed"))

        result = await client.authenticate()

        assert result is False
        assert client.authenticated is False

    @pytest.mark.asyncio
    async def test_authenticate_http_error(self, mocker):
        """Test authentication handles HTTP error (500) gracefully."""
        client = VintageAndRareClient(username="testuser", password="testpass")

        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.text = "<html>Login page</html>"
        mock_get_response.headers = {}

        mock_post_response = MagicMock()
        mock_post_response.status_code = 500
        mock_post_response.text = "Internal Server Error"
        mock_post_response.url = "https://www.vintageandrare.com/error"
        mock_post_response.headers = {}

        mocker.patch.object(client.session, "get", return_value=mock_get_response)
        mocker.patch.object(client.session, "post", return_value=mock_post_response)

        if client.cf_session is not None:
            mocker.patch.object(client.cf_session, "get", return_value=mock_get_response)
            mocker.patch.object(client.cf_session, "post", return_value=mock_post_response)

        result = await client.authenticate()

        assert result is False
        assert client.authenticated is False

    @pytest.mark.asyncio
    async def test_authenticate_unexpected_response(self, mocker):
        """Test authentication returns False when login markers aren't found."""
        client = VintageAndRareClient(username="testuser", password="testpass")

        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.text = "<html>Please enter your credentials</html>"
        mock_get_response.headers = {}

        mock_post_response = MagicMock()
        mock_post_response.status_code = 200
        mock_post_response.text = "<html>Invalid credentials. Please try again.</html>"
        mock_post_response.url = "https://www.vintageandrare.com/do_login"
        mock_post_response.headers = {}

        mocker.patch.object(client.session, "get", return_value=mock_get_response)
        mocker.patch.object(client.session, "post", return_value=mock_post_response)

        if client.cf_session is not None:
            mocker.patch.object(client.cf_session, "get", return_value=mock_get_response)
            mocker.patch.object(client.cf_session, "post", return_value=mock_post_response)

        result = await client.authenticate()

        assert result is False
        assert client.authenticated is False

    @pytest.mark.asyncio
    async def test_download_inventory_csv_without_auth(self, mocker):
        client = VintageAndRareClient(username="testuser", password="testpass")
        client.authenticated = False
        mocker.patch.object(client, "authenticate", return_value=False)
        result = await client.download_inventory_dataframe()
        assert result is None

    @pytest.mark.asyncio
    async def test_download_inventory_csv_network_error(self, mocker):
        client = VintageAndRareClient(username="testuser", password="testpass")
        client.authenticated = True

        mocker.patch.object(client.session, "get", side_effect=requests.ConnectionError("Network error"))
        if client.cf_session is not None:
            mocker.patch.object(client.cf_session, "get", side_effect=Exception("Network error"))

        result = await client.download_inventory_dataframe()
        assert result is None

    @pytest.mark.asyncio
    async def test_download_inventory_csv_http_error(self, mocker):
        client = VintageAndRareClient(username="testuser", password="testpass")
        client.authenticated = True

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_response.headers = {}

        mocker.patch.object(client.session, "get", return_value=mock_response)
        if client.cf_session is not None:
            mocker.patch.object(client.cf_session, "get", return_value=mock_response)

        result = await client.download_inventory_dataframe()
        assert result is None

    @pytest.mark.asyncio
    async def test_download_inventory_csv_empty_response(self, mocker):
        client = VintageAndRareClient(username="testuser", password="testpass")
        client.authenticated = True

        mock_page_response = MagicMock()
        mock_page_response.status_code = 200
        mock_page_response.headers = {}
        mock_page_response.text = ""
        mock_page_response.iter_content.return_value = []

        mock_csv_response = MagicMock()
        mock_csv_response.status_code = 200
        mock_csv_response.content = b""
        mock_csv_response.headers = {"content-type": "text/csv"}
        mock_csv_response.text = ""
        mock_csv_response.iter_content.return_value = []

        call_count = [0]

        def get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_page_response
            return mock_csv_response

        mocker.patch.object(client.session, "get", side_effect=get_side_effect)
        if client.cf_session is not None:
            cf_call_count = [0]

            def cf_get_side_effect(*args, **kwargs):
                cf_call_count[0] += 1
                if cf_call_count[0] == 1:
                    return mock_page_response
                return mock_csv_response

            mocker.patch.object(client.cf_session, "get", side_effect=cf_get_side_effect)

        result = await client.download_inventory_dataframe()
        assert result is None

    @pytest.mark.asyncio
    async def test_download_inventory_dataframe_csv_parsing_error(self, mocker):
        client = VintageAndRareClient(username="testuser", password="testpass")
        client.authenticated = True

        csv_data = b"not,valid\ncsv\xff\x00data"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = csv_data
        mock_response.headers = {"content-type": "text/csv"}
        mock_response.iter_content.return_value = [csv_data]

        mocker.patch.object(client.session, "get", return_value=mock_response)
        if client.cf_session is not None:
            mocker.patch.object(client.cf_session, "get", return_value=mock_response)

        mocker.patch("pandas.read_csv", side_effect=pd.errors.ParserError("CSV parsing error"))

        result = await client.download_inventory_dataframe()
        assert result is None

    @pytest.mark.asyncio
    async def test_download_inventory_dataframe_file_write_error(self, mocker):
        client = VintageAndRareClient(username="testuser", password="testpass")
        client.authenticated = True

        csv_data = b"brand name,product model name,product price\nFender,Strat,1500"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = csv_data
        mock_response.headers = {"content-type": "text/csv"}
        mock_response.iter_content.return_value = [csv_data]

        mocker.patch.object(client.session, "get", return_value=mock_response)
        if client.cf_session is not None:
            mocker.patch.object(client.cf_session, "get", return_value=mock_response)

        mock_df = pd.DataFrame({"brand name": ["Fender"], "product model name": ["Strat"], "product price": [1500]})
        mocker.patch("pandas.read_csv", return_value=mock_df)
        mocker.patch("builtins.open", side_effect=PermissionError("Permission denied"))

        try:
            await client.download_inventory_dataframe(save_to_file=True)
        except PermissionError:
            pytest.fail("Should not propagate PermissionError to caller")
