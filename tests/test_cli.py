from unittest.mock import patch
from typer.testing import CliRunner
from vesper_x.cli import app

runner = CliRunner()

def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "direct link extractor" in result.output.lower() or "usage" in result.output.lower()

def test_parse_command_extract_only():
    with patch("vesper_x.extractors.ouo.OuoBypasser.resolve", return_value="https://mediafire.com/file/123"):
        result = runner.invoke(app, ["parse", "https://ouo.io/test123", "--extract-only"])
        assert result.exit_code == 0

def test_parse_command_json_output():
    with patch("vesper_x.extractors.ouo.OuoBypasser.resolve", return_value="https://mediafire.com/file/123"), \
         patch("vesper_x.extractors.mediafire.MediafireResolver.extract_direct_url", return_value="https://download.mediafire.com/123.zip"):
        result = runner.invoke(app, ["parse", "https://ouo.io/test123", "--extract-only", "--json"])
        assert result.exit_code == 0
        assert "direct_url" in result.output
        assert "tags" in result.output
        assert "models" in result.output
