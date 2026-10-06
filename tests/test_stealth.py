"""
Unit tests for the stealth module

Test strategy:
  - Use unittest.mock.patch to isolate the external browserforge / playwright_stealth dependencies
  - Cover the three public functions: build_stealth, generate_context_options, apply_stealth_to_page
  - No real browser needed; everything runs in-process
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.stealth import apply_stealth_to_page, build_stealth, generate_context_options


# A valid Chrome UA (the Stealth library needs to parse the version number from it)
_VALID_CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class TestBuildStealth:
    """Tests for the build_stealth function."""

    def test_returns_stealth_instance(self):
        """Should return a Stealth instance."""
        from playwright_stealth import Stealth

        result = build_stealth(_VALID_CHROME_UA)
        assert isinstance(result, Stealth)

    def test_passes_user_agent_to_stealth(self):
        """Should set the given user_agent on the Stealth instance."""
        result = build_stealth(_VALID_CHROME_UA)
        assert result.navigator_user_agent_override == _VALID_CHROME_UA

    def test_sets_platform_to_macintel(self):
        """navigator_platform_override should be 'MacIntel'."""
        result = build_stealth(_VALID_CHROME_UA)
        assert result.navigator_platform_override == "MacIntel"

    def test_sets_vendor_to_google(self):
        """navigator_vendor_override should be 'Google Inc.'."""
        result = build_stealth(_VALID_CHROME_UA)
        assert result.navigator_vendor_override == "Google Inc."

    def test_chrome_runtime_disabled(self):
        """The chrome_runtime patch should be disabled (headed-mode compatibility)."""
        result = build_stealth(_VALID_CHROME_UA)
        assert result.chrome_runtime is False


class TestGenerateContextOptions:
    """Tests for the generate_context_options function."""

    def _make_mock_fingerprint(
        self,
        ua: str = "Mozilla/5.0 Chrome/120",
        width: int = 1920,
        height: int = 1080,
        language: str = "zh-CN",
    ) -> MagicMock:
        """Build a mock fingerprint object."""
        fp = MagicMock()
        fp.navigator.userAgent = ua
        fp.navigator.language = language
        fp.screen.width = width
        fp.screen.height = height
        return fp

    def test_returns_dict(self):
        """Should return a dict."""
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = self._make_mock_fingerprint()
            result = generate_context_options()
        assert isinstance(result, dict)

    def test_contains_user_agent(self):
        """The returned dict should contain the user_agent key."""
        fp = self._make_mock_fingerprint(ua="MockUA/1.0")
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = fp
            result = generate_context_options()
        assert result["user_agent"] == "MockUA/1.0"

    def test_contains_viewport(self):
        """The returned dict should contain viewport (width / height)."""
        fp = self._make_mock_fingerprint(width=1366, height=768)
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = fp
            result = generate_context_options()
        assert result["viewport"]["width"] == 1366
        assert result["viewport"]["height"] == 768

    def test_contains_screen(self):
        """The returned dict should contain screen (width / height)."""
        fp = self._make_mock_fingerprint(width=2560, height=1600)
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = fp
            result = generate_context_options()
        assert result["screen"]["width"] == 2560
        assert result["screen"]["height"] == 1600

    def test_locale_from_fingerprint(self):
        """locale should come from the fingerprint's navigator.language."""
        fp = self._make_mock_fingerprint(language="en-US")
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = fp
            result = generate_context_options()
        assert result["locale"] == "en-US"

    def test_locale_falls_back_to_en_us_when_none(self):
        """locale should fall back to 'en-US' when navigator.language is None."""
        fp = self._make_mock_fingerprint()
        fp.navigator.language = None
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = fp
            result = generate_context_options()
        assert result["locale"] == "en-US"

    def test_timezone_not_overridden(self):
        """The browser keeps the system timezone so it stays consistent with the IP."""
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = self._make_mock_fingerprint()
            result = generate_context_options()
        assert "timezone_id" not in result

    def test_color_scheme_is_light(self):
        """color_scheme should always be 'light'."""
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = self._make_mock_fingerprint()
            result = generate_context_options()
        assert result["color_scheme"] == "light"

    def test_contains_fingerprint_key(self):
        """The returned dict should contain the _fingerprint key (reused when building Stealth)."""
        fp = self._make_mock_fingerprint()
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = fp
            result = generate_context_options()
        assert result["_fingerprint"] is fp

    def test_calls_generate_once_per_invocation(self):
        """Each call should generate a new fingerprint (calling generate() once)."""
        with patch("src.stealth._fingerprint_generator") as mock_gen:
            mock_gen.generate.return_value = self._make_mock_fingerprint()
            generate_context_options()
        mock_gen.generate.assert_called_once()


class TestApplyStealthToPage:
    """Tests for the apply_stealth_to_page function."""

    async def test_calls_apply_stealth_async(self):
        """Should call stealth.apply_stealth_async(page)."""
        mock_page = AsyncMock()
        mock_stealth = MagicMock()
        mock_stealth.apply_stealth_async = AsyncMock()

        await apply_stealth_to_page(mock_page, mock_stealth)

        mock_stealth.apply_stealth_async.assert_called_once_with(mock_page)

    async def test_passes_correct_page_to_stealth(self):
        """Should pass the correct page object to apply_stealth_async."""
        mock_page = AsyncMock()
        mock_stealth = MagicMock()
        mock_stealth.apply_stealth_async = AsyncMock()

        await apply_stealth_to_page(mock_page, mock_stealth)

        call_args = mock_stealth.apply_stealth_async.call_args
        assert call_args[0][0] is mock_page

    async def test_returns_none(self):
        """The function should return None (void semantics)."""
        mock_page = AsyncMock()
        mock_stealth = MagicMock()
        mock_stealth.apply_stealth_async = AsyncMock(return_value=None)

        result = await apply_stealth_to_page(mock_page, mock_stealth)

        assert result is None
