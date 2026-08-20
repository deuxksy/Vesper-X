from unittest.mock import AsyncMock, patch
import pytest
from vesper_x.extractors.ouo import OuoBypasser

@pytest.mark.asyncio
async def test_ouo_resolve_destination():
    bypasser = OuoBypasser()
    with patch.object(bypasser, "_run_playwright_bypass", new_callable=AsyncMock) as mock_bypass:
        mock_bypass.return_value = "https://www.mediafire.com/file/sample/file.rar/file"
        result = await bypasser.resolve("https://ouo.io/hHzh1N")
        assert result == "https://www.mediafire.com/file/sample/file.rar/file"
