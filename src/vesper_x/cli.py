import asyncio
import json
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
import httpx
import typer
from rich.console import Console

from vesper_x.config import AppConfig, load_config
from vesper_x.dispatchers.aria2 import Aria2Dispatcher
from vesper_x.extractors.crawler import CategoryCrawler
from vesper_x.extractors.cosplaytele import CosplayteleParser, CosplayteleCrawler
from vesper_x.extractors.gofile import GofileResolver
from vesper_x.extractors.mediafire import MediafireResolver
from vesper_x.extractors.misskon import MisskonParser
from vesper_x.extractors.ouo import OuoBypasser
from vesper_x.fetchers import BrowserFetcher
from vesper_x.models import DownloadMetadata

try:
    import pyperclip
except ImportError:
    pyperclip = None

app = typer.Typer(name="url-resolver", help="Direct Link Extractor & Aria2 Dispatcher CLI")
console = Console()

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

GENRE_TAG_KEYWORDS = [
    "cosplay", "ero", "game", "free style", "nude", "anime", "manga",
    "video", "part", "photos", "ai art", "cheongsam", "hktv", "video cosplay"
]


def extract_tags_from_html_and_url(html_content: str, post_url: str) -> list[str]:
    """Extract all tags as an Array (list) from HTML rel='tag' links and URL."""
    tags = []
    soup = BeautifulSoup(html_content, "html.parser")
    for a in soup.find_all("a", rel="tag"):
        tag_text = a.text.strip()
        if tag_text and tag_text not in tags:
            tags.append(tag_text)

    match = re.search(r"/(?:tag|category)/([^/]+)/", post_url)
    if match and match.group(1) not in tags:
        tags.append(match.group(1))

    return tags


def extract_models_from_tags_and_html(tags: list[str], html_content: str, post_url: str, config_models: list[str]) -> list[str]:
    """Smart auto-extract model names from tags, config, and title."""
    models = []
    for m in config_models:
        if m in post_url or m in html_content:
            if m not in models:
                models.append(m)

    for tag in tags:
        lower_t = tag.lower().strip()
        is_genre = any(kw in lower_t for kw in GENRE_TAG_KEYWORDS)
        if not is_genre and tag not in models:
            models.append(tag)

    return models


def run_async(coro):
    """Playwright sync 세션 중에는 main thread에 running loop가 남아 asyncio.run()이 실패한다 - worker thread에서 실행."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def _select_crawler(url: str, config: AppConfig):
    """config [sites]의 도메인 매칭으로 crawler를 고른다 - 미등록 도메인은 category 기본."""
    crawlers = {
        "category": CategoryCrawler,
        "cosplaytele": CosplayteleCrawler,
    }
    host = urllib.parse.urlparse(url).hostname or ""
    for domain, site in config.sites.items():
        if host == domain or host.endswith("." + domain):
            return crawlers[site.crawler]()
    return crawlers["category"]()


def resolve_post(post_url: str, config: Optional[AppConfig] = None, current_tag: Optional[str] = None, fetcher: Optional[BrowserFetcher] = None) -> list[DownloadMetadata]:
    if config is None:
        config = load_config()

    headers = {"User-Agent": DEFAULT_USER_AGENT}
    try:
        if fetcher is not None:
            html_content = fetcher.fetch(post_url)
        else:
            resp = httpx.get(post_url, headers=headers, follow_redirects=True, timeout=30.0, proxy=config.proxy)
            html_content = resp.text
    except Exception as e:
        console.print(f"[bold red]Failed to fetch post URL {post_url}: {e}[/bold red]")
        return []

    if "cosplaytele.com" in post_url:
        parser = CosplayteleParser()
    else:
        parser = MisskonParser()

    links = parser.extract_download_links(html_content)
    if not links:
        if any(domain in post_url for domain in ["ouo.io", "ouo.press", "mediafire.com", "mega.nz", "gofile.io"]):
            links = [post_url]

    tags = extract_tags_from_html_and_url(html_content, post_url)
    if current_tag and current_tag not in tags:
        tags.append(current_tag)

    matched_models = extract_models_from_tags_and_html(tags, html_content, post_url, config.models)

    results: list[DownloadMetadata] = []
    # ouo는 한국 미차단 + Cloudflare challenge에 데이터센터 IP가 불리해 직접 경로,
    # gofile은 프록시 경유
    ouo_bypasser = OuoBypasser()
    mediafire_resolver = MediafireResolver()
    gofile_resolver = GofileResolver(proxy=config.proxy)

    for link in links:
        current_url = link
        if "ouo.io" in current_url or "ouo.press" in current_url:
            # ouo는 연속 요청 시 throttling 한다 - backoff 재시도
            bypassed = None
            for attempt in range(3):
                try:
                    bypassed = run_async(ouo_bypasser.resolve(current_url))
                except Exception as e:
                    console.print(f"[bold red]Failed to bypass shortener link {link}: {e}[/bold red]")
                    break
                # ouo 우회는 간헐 실패 시 입력 URL을 그대로 반환한다
                if "ouo.io" not in bypassed and "ouo.press" not in bypassed:
                    break
                if attempt < 2:
                    time.sleep(8 * (attempt + 1))
            if bypassed is None or "ouo.io" in bypassed or "ouo.press" in bypassed:
                console.print(f"[yellow]Bypass failed after retry, skipping: {link}[/yellow]")
                continue
            current_url = bypassed

        # gofile 폴더 링크는 파일 여러 개로 확장된다 - 파일별 직링크+인증 쿠키로 dispatch
        if "gofile.io" in current_url:
            try:
                gf_downloads = run_async(gofile_resolver.resolve(current_url))
            except Exception as e:
                console.print(f"[yellow]Warning resolving gofile {current_url}: {e}[/yellow]")
                continue
            if not gf_downloads:
                console.print(f"[yellow]No gofile downloads resolved, skipping: {current_url}[/yellow]")
                continue
            for gf in gf_downloads:
                results.append(
                    DownloadMetadata(
                        direct_url=gf.direct_url,
                        referer=post_url,
                        user_agent=DEFAULT_USER_AGENT,
                        filename=gf.filename,
                        source_page=post_url,
                        tags=list(tags),
                        models=list(matched_models),
                        cookies=gf.cookies,
                    )
                )
            continue

        direct_url = current_url
        if "mediafire.com" in current_url:
            try:
                mf_resp = httpx.get(current_url, headers=headers, follow_redirects=True, timeout=30.0, proxy=config.proxy)
                extracted_direct = mediafire_resolver.extract_direct_url(mf_resp.text)
                if extracted_direct:
                    direct_url = extracted_direct
                else:
                    # Ignore Mediafire pages that failed to yield a direct CDN download link
                    continue
            except Exception as e:
                console.print(f"[yellow]Warning fetching Mediafire page {current_url}: {e}[/yellow]")
                continue

        # Ignore non-downloadable auxiliary links like blog.mediafire.com or repair scripts
        if any(bad in direct_url for bad in ["blog.mediafire.com", "download_repair.php", "af_link.php"]):
            continue

        filename = direct_url.split("/")[-1].split("?")[0] if "/" in direct_url else None
        if not filename or filename == direct_url:
            filename = None
        else:
            # mediafire direct URL의 filename은 percent-encoding + '+'(space) 그대로 aria2에 전달된다
            filename = urllib.parse.unquote(filename).replace("+", " ")

        meta = DownloadMetadata(
            direct_url=direct_url,
            referer=post_url,
            user_agent=DEFAULT_USER_AGENT,
            filename=filename,
            source_page=post_url,
            tags=list(tags),
            models=list(matched_models),
        )
        results.append(meta)

    return results


def handle_results(
    metadata_list: list[DownloadMetadata],
    extract_only: bool,
    output: Optional[str],
    copy: bool,
    json_output: bool,
    config: Optional[AppConfig] = None,
):
    if not metadata_list:
        console.print("[yellow]No download metadata resolved.[/yellow]")
        return

    if json_output:
        json_data = [
            {
                "direct_url": m.direct_url,
                "referer": m.referer,
                "user_agent": m.user_agent,
                "filename": m.filename,
                "source_page": m.source_page,
                "tags": m.tags,
                "models": m.models,
            }
            for m in metadata_list
        ]
        print(json.dumps(json_data, indent=2))
    else:
        for m in metadata_list:
            console.print(f"[bold green]Direct URL:[/bold green] {m.direct_url}")
            if m.tags:
                console.print(f"  [bold yellow]Tags:[/bold yellow] {', '.join(m.tags)}")
            if m.models:
                console.print(f"  [bold magenta]Models:[/bold magenta] {', '.join(m.models)}")
            if m.filename:
                console.print(f"  [bold cyan]Filename:[/bold cyan] {m.filename}")

    if copy:
        urls_str = "\n".join(m.direct_url for m in metadata_list)
        if pyperclip is not None:
            try:
                pyperclip.copy(urls_str)
                console.print("[green]Copied direct URL(s) to clipboard.[/green]")
            except Exception as e:
                console.print(f"[yellow]Failed to copy to clipboard: {e}[/yellow]")
        else:
            console.print("[yellow]pyperclip module not available for copying.[/yellow]")

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if json_output:
            out_path.write_text(
                json.dumps(
                    [
                        {
                            "direct_url": m.direct_url,
                            "referer": m.referer,
                            "user_agent": m.user_agent,
                            "filename": m.filename,
                            "source_page": m.source_page,
                            "tags": m.tags,
                            "models": m.models,
                        }
                        for m in metadata_list
                    ],
                    indent=2,
                )
            )
        else:
            out_path.write_text("\n".join(m.direct_url for m in metadata_list) + "\n")
        console.print(f"[green]Saved extracted output to {output}[/green]")

    if not extract_only:
        if config is None:
            config = load_config()
        dispatcher = Aria2Dispatcher(config)
        for m in metadata_list:
            try:
                gid = dispatcher.dispatch(m)
                console.print(f"[bold green]Dispatched to aria2[/bold green] (GID: [cyan]{gid}[/cyan]) - {m.direct_url}")
            except Exception as e:
                console.print(f"[bold red]Failed to dispatch to aria2: {e}[/bold red]")


@app.command()
def parse(
    url: str = typer.Argument(..., help="Target post URL"),
    extract_only: bool = typer.Option(False, "--extract-only", help="Extract direct URL without dispatching to aria2"),
    output: Optional[str] = typer.Option(None, "-o", "--output", help="Save extracted URLs to file"),
    copy: bool = typer.Option(False, "-c", "--copy", help="Copy extracted direct URL(s) to clipboard"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON format"),
):
    """Parse single post page, extract direct download link, and dispatch to aria2."""
    metadata_list = resolve_post(url)
    handle_results(metadata_list, extract_only=extract_only, output=output, copy=copy, json_output=json_output)


@app.command()
def crawl(
    url: str = typer.Argument(..., help="Category or Tag list URL"),
    pages: int = typer.Option(1, "--pages", help="Max pages to crawl (0 for all)"),
    limit: int = typer.Option(0, "--limit", help="Max posts to process (0 for all)"),
    extract_only: bool = typer.Option(False, "--extract-only", help="Extract direct URL without dispatching to aria2"),
    output: Optional[str] = typer.Option(None, "-o", "--output", help="Save extracted URLs to file"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON format"),
):
    """Crawl category or tag listing across multiple pages and process all posts.

    페이지를 페치할 때마다 해당 post를 즉시 resolve+dispatch 한다 (최신 페이지 우선, 스트리밍)."""
    tag_match = re.search(r"/(?:tag|category)/([^/]+)/", url)
    tag_slug = tag_match.group(1) if tag_match else None

    config = load_config()
    # 사이트별 crawler는 config [sites]가 결정한다
    crawler = _select_crawler(url, config)
    dispatcher = None if extract_only else Aria2Dispatcher(config)

    visited_pages = set()
    visited_posts: set[str] = set()
    to_visit = [url]
    all_metadata: list[DownloadMetadata] = []

    with BrowserFetcher(proxy=config.proxy) as fetcher:
        page_count = 0
        post_count = 0
        while to_visit:
            if pages > 0 and page_count >= pages:
                break
            current_page_url = to_visit.pop(0)
            if current_page_url in visited_pages:
                continue
            visited_pages.add(current_page_url)
            page_count += 1

            try:
                page_html = fetcher.fetch(current_page_url)
            except Exception as e:
                console.print(f"[bold red]Failed to fetch category page {current_page_url}: {e}[/bold red]")
                continue

            for post_url in crawler.extract_post_urls(page_html):
                if post_url in visited_posts:
                    continue
                visited_posts.add(post_url)
                post_count += 1
                console.print(f"[bold cyan]({post_count})[/bold cyan] {post_url}")

                metadata = resolve_post(post_url, config=config, current_tag=tag_slug, fetcher=fetcher)
                all_metadata.extend(metadata)

                if dispatcher:
                    for m in metadata:
                        try:
                            gid = dispatcher.dispatch(m)
                            console.print(f"[bold green]Dispatched to aria2[/bold green] (GID: [cyan]{gid}[/cyan]) - {m.filename or m.direct_url[:60]}")
                        except Exception as e:
                            console.print(f"[bold red]Failed to dispatch to aria2: {e}[/bold red]")

                if limit > 0 and post_count >= limit:
                    to_visit.clear()
                    break

            for p in crawler.extract_pagination_urls(page_html):
                if p not in visited_pages and p not in to_visit:
                    to_visit.append(p)

    # dispatch는 위에서 이미 처리 - 출력/저장만
    handle_results(all_metadata, extract_only=True, output=output, copy=False, json_output=json_output, config=config)


@app.command()
def clip(
    extract_only: bool = typer.Option(False, "--extract-only", help="Extract direct URL without dispatching to aria2"),
    output: Optional[str] = typer.Option(None, "-o", "--output", help="Save extracted URLs to file"),
    copy: bool = typer.Option(False, "-c", "--copy", help="Copy extracted direct URL(s) to clipboard"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON format"),
):
    """Read URL from clipboard and parse it."""
    if pyperclip is None:
        console.print("[bold red]pyperclip module is not installed.[/bold red]")
        raise typer.Exit(1)

    url = pyperclip.paste().strip()
    if not url:
        console.print("[bold red]Clipboard is empty.[/bold red]")
        raise typer.Exit(1)

    console.print(f"[bold green]Read URL from clipboard:[/bold green] {url}")
    metadata_list = resolve_post(url)
    handle_results(metadata_list, extract_only=extract_only, output=output, copy=copy, json_output=json_output)


@app.command()
def batch(
    file_path: str = typer.Argument(..., help="Path to file containing URLs (one per line)"),
    extract_only: bool = typer.Option(False, "--extract-only", help="Extract direct URL without dispatching to aria2"),
    output: Optional[str] = typer.Option(None, "-o", "--output", help="Save extracted URLs to file"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON format"),
):
    """Batch process list of URLs from text file."""
    path = Path(file_path)
    if not path.exists():
        console.print(f"[bold red]File not found: {file_path}[/bold red]")
        raise typer.Exit(1)

    lines = path.read_text().splitlines()
    urls = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]

    config = load_config()
    all_metadata: list[DownloadMetadata] = []
    for url in urls:
        metadata = resolve_post(url, config=config)
        all_metadata.extend(metadata)

    handle_results(all_metadata, extract_only=extract_only, output=output, copy=False, json_output=json_output, config=config)


if __name__ == "__main__":
    app()
