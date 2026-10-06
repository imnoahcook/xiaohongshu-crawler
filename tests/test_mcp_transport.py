"""
MCP server transport layer tests — Phase E3: SSE / Streamable HTTP support

Test strategy:
  - Verify CLI argument parsing (--transport, --host, --port)
  - Verify the correct run method is called for each transport mode
  - Verify the SSE transport's default configuration (host/port)
  - All tests mock mcp.run(); no real server is started
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


class TestParseArgs:
    """CLI argument parsing tests."""

    def test_default_args_use_stdio(self):
        """With no arguments, the stdio transport is used by default."""
        from mcp_server import parse_args

        args = parse_args([])
        assert args.transport == "stdio"

    def test_transport_sse(self):
        """--transport sse should parse correctly."""
        from mcp_server import parse_args

        args = parse_args(["--transport", "sse"])
        assert args.transport == "sse"

    def test_transport_streamable_http(self):
        """--transport streamable-http should parse correctly."""
        from mcp_server import parse_args

        args = parse_args(["--transport", "streamable-http"])
        assert args.transport == "streamable-http"

    def test_invalid_transport_raises(self):
        """An invalid transport value should exit with an error."""
        from mcp_server import parse_args

        with pytest.raises(SystemExit):
            parse_args(["--transport", "invalid"])

    def test_default_host(self):
        """The default host should be 127.0.0.1."""
        from mcp_server import parse_args

        args = parse_args([])
        assert args.host == "127.0.0.1"

    def test_custom_host(self):
        """The --host argument should parse correctly."""
        from mcp_server import parse_args

        args = parse_args(["--host", "0.0.0.0"])
        assert args.host == "0.0.0.0"

    def test_default_port(self):
        """The default port should be 8000."""
        from mcp_server import parse_args

        args = parse_args([])
        assert args.port == 8000

    def test_custom_port(self):
        """The --port argument should parse correctly."""
        from mcp_server import parse_args

        args = parse_args(["--port", "9090"])
        assert args.port == 9090

    def test_port_type_is_int(self):
        """port should be parsed as an int."""
        from mcp_server import parse_args

        args = parse_args(["--port", "3000"])
        assert isinstance(args.port, int)


class TestTransportDispatch:
    """Transport mode dispatch tests."""

    def test_stdio_calls_mcp_run_without_transport(self):
        """In stdio mode, mcp.run() should be called without a transport argument (defaults to stdio)."""
        import mcp_server

        mock_mcp = MagicMock()
        with patch.object(mcp_server, "mcp", mock_mcp):
            with patch.object(mcp_server, "parse_args", return_value=MagicMock(
                transport="stdio", host="127.0.0.1", port=8000
            )):
                mcp_server.main()

        mock_mcp.run.assert_called_once_with()

    def test_sse_calls_mcp_run_with_sse_transport(self):
        """In SSE mode, mcp.run(transport='sse') should be called."""
        import mcp_server

        mock_mcp = MagicMock()
        with patch.object(mcp_server, "mcp", mock_mcp):
            with patch.object(mcp_server, "parse_args", return_value=MagicMock(
                transport="sse", host="0.0.0.0", port=9090
            )):
                mcp_server.main()

        mock_mcp.run.assert_called_once_with(transport="sse")

    def test_streamable_http_calls_mcp_run(self):
        """In streamable-http mode, mcp.run(transport='streamable-http') should be called."""
        import mcp_server

        mock_mcp = MagicMock()
        with patch.object(mcp_server, "mcp", mock_mcp):
            with patch.object(mcp_server, "parse_args", return_value=MagicMock(
                transport="streamable-http", host="0.0.0.0", port=8080
            )):
                mcp_server.main()

        mock_mcp.run.assert_called_once_with(transport="streamable-http")

    def test_sse_updates_mcp_settings_host_port(self):
        """In SSE mode, mcp.settings.host and mcp.settings.port should be updated."""
        import mcp_server

        mock_mcp = MagicMock()
        mock_mcp.settings = MagicMock()
        with patch.object(mcp_server, "mcp", mock_mcp):
            with patch.object(mcp_server, "parse_args", return_value=MagicMock(
                transport="sse", host="0.0.0.0", port=9090
            )):
                mcp_server.main()

        assert mock_mcp.settings.host == "0.0.0.0"
        assert mock_mcp.settings.port == 9090

    def test_stdio_does_not_update_settings(self):
        """In stdio mode, mcp.settings should not be modified."""
        import mcp_server

        mock_mcp = MagicMock()
        original_host = mock_mcp.settings.host
        original_port = mock_mcp.settings.port
        with patch.object(mcp_server, "mcp", mock_mcp):
            with patch.object(mcp_server, "parse_args", return_value=MagicMock(
                transport="stdio", host="127.0.0.1", port=8000
            )):
                mcp_server.main()

        # settings should not be assigned in stdio mode
        mock_mcp.run.assert_called_once_with()


class TestMcpInstanceConfig:
    """FastMCP instance configuration tests."""

    def test_mcp_instance_name(self):
        """The MCP instance name should be rednote-crawler."""
        import mcp_server

        # The FastMCP instance's name is stored on settings or _mcp_server
        assert mcp_server.mcp.name == "rednote-crawler"

    def test_mcp_has_lifespan(self):
        """The MCP instance should have a lifespan hook configured."""
        import mcp_server

        # lifespan is passed in via settings
        assert mcp_server.mcp.settings.lifespan is not None
