"""vesper models 명령 — DB 이름 사전 + 실시간 카운트 + 보유 현황 조회."""
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from vesper_x.cli import app

runner = CliRunner()

INFO = {
    "canonical": "ZinieQ",
    "slug": "zinieq",
    "misskon_slug": "https://misskon.com/tag/zinieq/",
    "snapshot": {"misskon": 32, "cosplaytele": 86},
    "archive": {"albums": 12, "size_kb": 28_000_000, "region": "SEA",
                "folders": ["ZinieQ (ジニCosplayer)"]},
}


def test_models_command_shows_live_counts_and_recommendation():
    registry = MagicMock()
    registry.lookup.return_value = INFO
    with patch("vesper_x.cli.ModelRegistry", return_value=registry), \
         patch("vesper_x.cli._live_misskon_count", return_value=34), \
         patch("vesper_x.cli._live_cosplaytele_count", return_value=90), \
         patch("vesper_x.cli._live_heritage_counts",
               return_value={"albums": 13, "size_kb": 28_500_000}):
        result = runner.invoke(app, ["models", "zinieq"])
    assert result.exit_code == 0
    assert "ZinieQ" in result.output
    assert "34" in result.output      # misskon 실시간
    assert "90" in result.output      # cosplaytele 실시간
    assert "13" in result.output      # heritage 실시간 앨범
    assert "cosplaytele" in result.output.lower()


def test_models_command_unknown_model_exits_nonzero():
    registry = MagicMock()
    registry.lookup.return_value = None
    with patch("vesper_x.cli.ModelRegistry", return_value=registry):
        result = runner.invoke(app, ["models", "없는모델"])
    assert result.exit_code == 1


def test_models_command_recommends_site_with_more_posts():
    """misskon이 더 많으면 misskon 추천 + 태그 URL 안내."""
    registry = MagicMock()
    registry.lookup.return_value = INFO
    with patch("vesper_x.cli.ModelRegistry", return_value=registry), \
         patch("vesper_x.cli._live_misskon_count", return_value=95), \
         patch("vesper_x.cli._live_cosplaytele_count", return_value=40), \
         patch("vesper_x.cli._live_heritage_counts",
               return_value={"albums": 12, "size_kb": 28_000_000}):
        result = runner.invoke(app, ["models", "zinieq"])
    assert result.exit_code == 0
    assert "misskon" in result.output
    assert "https://misskon.com/tag/zinieq/" in result.output


def test_resolve_post_canonicalizes_model_variants():
    """(B) 사이트 표기 변형('Umeko J')이 캐노니컬명('UmekoJ')으로 metadata.models에 기록된다."""
    from types import SimpleNamespace

    from vesper_x.cli import resolve_post

    post_html = """
    <html><body>
    <a href="https://ouo.io/abc123" rel="nofollow">download</a>
    <a href="https://cosplaytele.com/tag/x/" rel="tag">Umeko J</a>
    </body></html>
    """
    fetcher = MagicMock()
    fetcher.fetch.return_value = post_html
    stub_registry = SimpleNamespace(canonicalize=lambda n: {"Umeko J": "UmekoJ"}.get(n))
    with patch("vesper_x.cli.ModelRegistry", return_value=stub_registry), \
         patch("vesper_x.extractors.ouo.OuoBypasser.resolve", return_value="https://www.mediafire.com/file/x/u.rar"), \
         patch("vesper_x.extractors.mediafire.MediafireResolver.extract_direct_url", return_value="https://download.mediafire.net/x/u.rar"):
        results = resolve_post("https://cosplaytele.com/umeko-post/", fetcher=fetcher)
    assert results[0].models == ["UmekoJ"]
