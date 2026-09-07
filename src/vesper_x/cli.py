import asyncio
import json
import re
import subprocess
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
from vesper_x.models_db import ModelRegistry

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


def extract_models_from_tags_and_html(tags: list[str], html_content: str, post_url: str, config_models: list[str], canonicalize=None) -> list[str]:
    """Smart auto-extract model names from tags, config, and title.

    canonicalize를 넘기면 사이트 표기 변형을 캐노니컬명(models.db)으로 통일해 기록한다.
    """
    models = []
    for m in config_models:
        if m in post_url or m in html_content:
            name = canonicalize(m) or m if canonicalize else m
            if name not in models:
                models.append(name)

    for tag in tags:
        lower_t = tag.lower().strip()
        is_genre = any(kw in lower_t for kw in GENRE_TAG_KEYWORDS)
        if not is_genre:
            name = canonicalize(tag) or tag if canonicalize else tag
            if name not in models:
                models.append(name)

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

    def _fetch(url: str) -> str:
        if fetcher is not None:
            return fetcher.fetch(url)
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=30.0, proxy=config.proxy)
        return resp.text

    try:
        html_content = _fetch(post_url)
    except Exception as e:
        console.print(f"[bold red]Failed to fetch post URL {post_url}: {e}[/bold red]")
        return []

    # misskon 멀티페이지 포스트: 다운로드 링크가 뒷 페이지(/N/)에 있기도 하다 -
    # 전 페이지를 병합해 파싱한다 (baegjm06 실측: 링크가 2페이지 이후에만 존재)
    if "misskon.com" in post_url:
        page_soup = BeautifulSoup(html_content, "html.parser")
        base = post_url.rstrip("/") + "/"
        page_urls = {post_url}
        for a in page_soup.find_all("a", class_="post-page-numbers", href=True):
            href = a["href"].strip()
            if href.startswith(base) and href not in page_urls:
                page_urls.add(href)
        for p_url in sorted(page_urls - {post_url})[:40]:
            try:
                html_content += _fetch(p_url)
            except Exception:
                pass

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

    matched_models = extract_models_from_tags_and_html(
        tags, html_content, post_url, config.models, canonicalize=ModelRegistry().canonicalize)

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
                # mediafire 직링크는 요청 IP에 묶인다 - 프록시(SG)로 resolve하면
                # heritage가 홈페이지 HTML을 받는다(2026-09-07 실측). 직접 경로 필수.
                mf_resp = httpx.get(current_url, headers=headers, follow_redirects=True, timeout=30.0, proxy=None)
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


def _live_misskon_count(info: dict, proxy: Optional[str] = None) -> Optional[int]:
    """misskon 태그 리스팅을 순차 페치해 실시간 포스트 수를 센다 (페이지당 20)."""
    slug_url = info.get("misskon_slug") or f"https://misskon.com/tag/{info['slug']}/"
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    total = 0
    url = slug_url
    for _page in range(60):
        try:
            resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=20.0, proxy=proxy)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            break
        n = resp.text.count("post-box-title")
        if n == 0:
            break
        total += n
        if n < 20:
            break
        url = f"{slug_url.rstrip('/')}/page/{_page + 2}/"
    return total


def _live_cosplaytele_count(info: dict, proxy: Optional[str] = None) -> Optional[int]:
    """cosplaytele WP REST 검색에서 제목에 모델명이 든 포스트 수를 센다."""
    names = [info["canonical"].lower(), info["slug"].lower()]
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    query = urllib.parse.quote(info["canonical"])
    total = 0
    for page in range(1, 16):
        try:
            resp = httpx.get(
                f"https://cosplaytele.com/wp-json/wp/v2/posts?per_page=100&page={page}&search={query}",
                headers=headers, timeout=20.0, proxy=proxy)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            break
        try:
            posts = resp.json()
        except ValueError:
            break
        if not isinstance(posts, list) or not posts:
            break
        for p in posts:
            title = (p.get("title") or {}).get("rendered", "").lower()
            if any(n in title for n in names if n):
                total += 1
        if len(posts) < 100:
            break
    return total


def _live_heritage_counts(info: dict) -> dict:
    """heritage 아카이브의 실시간 앨범 수/용량 (SSH)."""
    total_albums, total_kb = 0, 0
    for folder in info["archive"]["folders"]:
        try:
            import shlex
            r = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=10", "media@heritage",
                 f"p=$(find /mnt/data2/torrent/downloads/aria -maxdepth 2 -type d -name {shlex.quote(folder)} | head -1); "
                 f"[ -n \"$p\" ] && find \"$p\" -mindepth 1 -maxdepth 1 -type d | wc -l && du -sk \"$p\" | cut -f1"],
                capture_output=True, text=True, timeout=30)
            out = r.stdout.split()
            if len(out) >= 2:
                total_albums += int(out[0])
                total_kb += int(out[1])
        except (subprocess.SubprocessError, ValueError):
            continue
    return {"albums": total_albums, "size_kb": total_kb}


@app.command()
def models(
    query: str = typer.Argument(..., help="모델 이름/slug (예: zinieq, Byoru)"),
):
    """모델 조회: 사이트별 실시간 보유수 + heritage 보유 + 크롤 사이트 추천."""
    registry = ModelRegistry()
    info = registry.lookup(query)
    if info is None:
        console.print(f"[yellow]'{query}' 을(를) models.db에서 찾을 수 없습니다. "
                      f"(data/models.db 필요 - scripts/build_models_db.py)[/yellow]")
        raise typer.Exit(1)

    config = load_config()
    mk_live = _live_misskon_count(info, proxy=config.proxy)
    ct_live = _live_cosplaytele_count(info, proxy=config.proxy)
    heritage_live = _live_heritage_counts(info)

    grade = info.get("grade") or "-"
    console.print(f"[bold]{info['canonical']}[/bold]  [grade {grade}]  (slug: {info['slug']})")
    snap = info["snapshot"]
    mk_str = f"{mk_live}편 (실시간)" if mk_live is not None else "조회 실패"
    ct_str = f"{ct_live}편 (실시간)" if ct_live is not None else "조회 실패"
    console.print(f"  misskon       [cyan]{mk_str}[/cyan]  (스냅샷 {snap['misskon']})")
    console.print(f"  cosplaytele   [cyan]{ct_str}[/cyan]  (스냅샷 {snap['cosplaytele']})")
    gb = heritage_live["size_kb"] / 1024 / 1024
    console.print(f"  heritage      [magenta]{heritage_live['albums']}앨범 / {gb:.1f}GB[/magenta]  [{info['archive']['region'] or '-'}]")

    # 추천: 실시간 수가 많은 쪽 (실패 시 스냅샷으로)
    mk_n = mk_live if mk_live is not None else snap["misskon"]
    ct_n = ct_live if ct_live is not None else snap["cosplaytele"]
    if mk_n == 0 and ct_n == 0:
        console.print("  [yellow]두 사이트 모두 보유 없음[/yellow]")
    elif mk_n >= ct_n:
        entry = info.get("misskon_slug") or f"https://misskon.com/tag/{info['slug']}/"
        console.print(f"  [green]→ 추천: misskon ({mk_n}편)[/green]  진입: {entry}")
    else:
        entry = f"https://cosplaytele.com/?s={urllib.parse.quote(info['canonical'])}"
        console.print(f"  [green]→ 추천: cosplaytele ({ct_n}편)[/green]  진입: {entry}")


@app.command()
def status():
    """aria2 상태 조회: 전체/진행/대기/완료/오류 + 진행 중 상세."""
    dispatcher = Aria2Dispatcher(load_config())
    summary = dispatcher.status_summary()
    console.print(f"[bold][aria2] {dispatcher.format_status(summary)}[/bold]")
    actives = dispatcher.active_downloads()
    if actives:
        console.print("\n[bold]진행 중:[/bold]")
        for d in actives:
            pct = d["done_mb"] * 100 / d["total_mb"] if d["total_mb"] else 0
            console.print(f"  {pct:5.1f}%  {d['done_mb']:8.1f}/{d['total_mb']:.0f}MB  "
                          f"{d['speed_mb']:5.1f}MB/s  {d['name'][:60]}")


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
    registry = ModelRegistry()
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
                if registry.is_dispatched(post_url):
                    console.print(f"[dim]({post_count}) SKIP (이미 전송됨): {post_url}[/dim]")
                    continue
                console.print(f"[bold cyan]({post_count})[/bold cyan] {post_url}")

                # 대역 게이트: aria2 waiting 큐가 비어 있을 때만 진행한다.
                # active는 정상 동시성이지만 waiting 적체는 대역 포화를 뜻한다
                # (heritage 링크는 Meridian-X transmission과 공유).
                while dispatcher and int(dispatcher.waiting_count()) > 0:
                    console.print(f"[dim]aria2 대기 있음 [{dispatcher.format_status(dispatcher.status_summary())}] - 30초 대기...[/dim]")
                    time.sleep(30)

                metadata = resolve_post(post_url, config=config, current_tag=tag_slug, fetcher=fetcher)
                all_metadata.extend(metadata)

                if dispatcher:
                    for m in metadata:
                        # dispatch 직전 재확인 - resolve(ouo bypass 수 분) 사이 waiting이 찰 수 있다
                        while int(dispatcher.waiting_count()) > 0:
                            console.print(f"[dim]aria2 대기 있음 [{dispatcher.format_status(dispatcher.status_summary())}] - 30초 대기...[/dim]")
                            time.sleep(30)
                        try:
                            gid = dispatcher.dispatch(m)
                            console.print(f"[bold green]Dispatched to aria2[/bold green] (GID: [cyan]{gid}[/cyan]) - {m.filename or m.direct_url[:60]}")
                            console.print(f"[dim]  [aria2] {dispatcher.format_status(dispatcher.status_summary())}[/dim]")
                            registry.record_dispatch(post_url, note=m.filename)
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
