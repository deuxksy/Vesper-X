from unittest.mock import MagicMock, patch

from vesper_x.fetchers import BrowserFetcher, ECH_LAUNCH_ARGS


def _mock_playwright():
    """sync_playwright를 MagicMock으로 대체하고 내부 handle들을 반환한다."""
    with_patch_target = patch("vesper_x.fetchers.sync_playwright")
    mock_factory = with_patch_target.start()
    pw = mock_factory.return_value.start.return_value
    launch = pw.chromium.launch
    browser = launch.return_value
    page = browser.new_context.return_value.new_page.return_value
    return with_patch_target, launch, browser, page


def test_browser_fetcher_launches_chrome_with_ech_args():
    patcher, launch, browser, page = _mock_playwright()
    try:
        page.content.return_value = "<html>ok</html>"
        with BrowserFetcher() as fetcher:
            html = fetcher.fetch("https://example.com")
    finally:
        patcher.stop()

    kwargs = launch.call_args.kwargs
    assert kwargs["channel"] == "chrome"
    assert kwargs["args"] == ECH_LAUNCH_ARGS
    assert "--enable-features=EncryptedClientHello" in kwargs["args"]
    assert html == "<html>ok</html>"
    browser.close.assert_called_once()


def test_browser_fetcher_passes_proxy_to_launch():
    patcher, launch, browser, page = _mock_playwright()
    try:
        with BrowserFetcher(proxy="http://127.0.0.1:7890"):
            pass
    finally:
        patcher.stop()

    assert launch.call_args.kwargs["proxy"] == {"server": "http://127.0.0.1:7890"}


def test_browser_fetcher_no_proxy_by_default():
    patcher, launch, browser, page = _mock_playwright()
    try:
        with BrowserFetcher():
            pass
    finally:
        patcher.stop()

    assert "proxy" not in launch.call_args.kwargs


def test_browser_fetcher_launch_failure_propagates():
    with patch("vesper_x.fetchers.sync_playwright") as failing:
        failing.return_value.start.return_value.chromium.launch.side_effect = RuntimeError("no chrome")
        fetcher = BrowserFetcher()
        try:
            fetcher.__enter__()
            raised = False
        except RuntimeError:
            raised = True
        assert raised
