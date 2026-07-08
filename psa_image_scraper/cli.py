from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Callable

from .scraper import (
    DEFAULT_USER_AGENT,
    cert_url,
    download_cert_images,
    extract_cert_number,
    extract_cloudfront_image_urls,
    fetch_reader_markdown,
    make_session,
    reader_url,
)

SECURITY_VERIFICATION_MARKERS = (
    "verify you are human",
    "performing security verification",
    "checking if the site connection is secure",
    "just a moment",
    "cf-turnstile",
    "cf_chl",
    "challenges.cloudflare.com",
)


def _read_items(args: argparse.Namespace) -> list[str]:
    items = list(args.items)
    if args.input:
        for line in Path(args.input).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                items.append(line)
    for value in args.html or []:
        cert, _path = _parse_html_override(value)
        items.append(cert)

    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        cert = extract_cert_number(item)
        if cert not in seen:
            unique.append(item)
            seen.add(cert)
    return unique


def _parse_html_override(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--html must use CERT=path/to/page.html")
    cert_value, path_value = value.split("=", 1)
    return extract_cert_number(cert_value), Path(path_value).expanduser()


def _read_html_overrides(values: list[str] | None) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values or []:
        cert, path = _parse_html_override(value)
        overrides[cert] = path.read_text(encoding="utf-8")
    return overrides


def _write_zip(zip_path: Path, out_dir: Path, manifest_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if manifest_path.exists():
            archive.write(manifest_path, manifest_path.name)
        for path in sorted(out_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(out_dir.parent))


def _looks_like_security_verification(html: str) -> bool:
    normalized = html.lower()
    return any(marker in normalized for marker in SECURITY_VERIFICATION_MARKERS)


def _fetcher_plan(args: argparse.Namespace) -> list[str]:
    if args.fetcher == "auto":
        plan = ["reader", "direct"]
        if _should_use_browser(args):
            plan.append("browser")
        return plan
    return [args.fetcher]


def _reader_fetcher(session, timeout: float, retries: int = 3, retry_delay: float = 2) -> Callable[[str], str]:
    def fetch(url: str) -> str:
        last_text = ""
        for attempt in range(1, max(retries, 1) + 1):
            last_text = fetch_reader_markdown(url, session=session, timeout=timeout)
            if extract_cloudfront_image_urls(last_text):
                return last_text
            if attempt < retries and retry_delay > 0:
                time.sleep(retry_delay)
        return last_text

    return fetch


def _make_browser_fetcher(
    timeout: float,
    *,
    headless: bool = True,
    user_data_dir: str | None = None,
    wait_for_images: float = 0,
    verification_timeout: float = 0,
    channel: str | None = None,
) -> tuple[Callable[[str], str], Callable[[], None]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError('browser mode needs: pip install -e ".[browser]" && python -m playwright install chromium') from exc

    manager = sync_playwright().start()
    launch_options = {"headless": headless}
    if channel:
        launch_options["channel"] = channel
    if user_data_dir:
        browser = None
        context = manager.chromium.launch_persistent_context(
            str(Path(user_data_dir).expanduser()),
            user_agent=DEFAULT_USER_AGENT,
            **launch_options,
        )
    else:
        browser = manager.chromium.launch(**launch_options)
        context = browser.new_context(user_agent=DEFAULT_USER_AGENT)

    def fetch(url: str) -> str:
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            try:
                page.wait_for_load_state("networkidle", timeout=min(int(timeout * 1000), 15_000))
            except Exception:
                pass

            deadline = time.monotonic() + max(wait_for_images, 0)
            verification_deadline = time.monotonic() + max(verification_timeout, 0)
            verification_notice_shown = False
            while True:
                html = page.content()
                if extract_cloudfront_image_urls(html):
                    return html
                now = time.monotonic()
                if _looks_like_security_verification(html):
                    if headless:
                        raise RuntimeError(
                            "PSA security verification is showing. Rerun with "
                            "--browser-headful --browser-user-data-dir .psa-browser-profile."
                        )
                    if verification_timeout <= 0 or now >= verification_deadline:
                        raise RuntimeError(
                            "PSA security verification was not completed before timeout. "
                            "Rerun with a larger --browser-verification-timeout and finish "
                            "the Verify you are human check in the opened browser."
                        )
                    if not verification_notice_shown:
                        print(
                            "PSA security verification is showing in the browser. "
                            "Complete the Verify you are human check there; scraper is waiting.",
                            file=sys.stderr,
                        )
                        verification_notice_shown = True
                    deadline = max(deadline, now + max(wait_for_images, 15))
                    page.wait_for_timeout(1000)
                    continue
                if now >= deadline:
                    return html
                page.wait_for_timeout(1000)
        finally:
            page.close()

    def close() -> None:
        context.close()
        if browser:
            browser.close()
        manager.stop()

    return fetch, close


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download public front/back images from PSA cert pages.")
    parser.add_argument("items", nargs="*", help="PSA cert numbers or PSA cert URLs.")
    parser.add_argument("-i", "--input", help="Text file with one PSA cert number or URL per line.")
    parser.add_argument("-o", "--out", default="downloads", help="Output directory. Default: downloads")
    parser.add_argument("--manifest", default="manifest.json", help="Manifest JSON path. Default: manifest.json")
    parser.add_argument("--zip", dest="zip_path", help="Optional zip output path.")
    parser.add_argument("--size", default="large", help="Image size path to request. Default: large")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between certs, in seconds. Default: 0.5")
    parser.add_argument("--timeout", type=float, default=45, help="HTTP timeout in seconds. Default: 45")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="HTTP User-Agent header.")
    parser.add_argument(
        "--fetcher",
        choices=["auto", "reader", "direct", "browser"],
        default="auto",
        help=(
            "Page fetch route. Default: auto, which tries the public reader route first, "
            "then direct PSA, then browser only when browser options are supplied."
        ),
    )
    parser.add_argument("--reader-retries", type=int, default=3, help="Reader fetch retries when no image URL is found. Default: 3")
    parser.add_argument("--reader-retry-delay", type=float, default=2, help="Delay between reader retries, in seconds. Default: 2")
    parser.add_argument("--browser", action="store_true", help="Render cert pages with Playwright before extraction.")
    parser.add_argument("--browser-headful", action="store_true", help="Open a visible browser window in browser mode.")
    parser.add_argument("--browser-channel", help='Playwright browser channel, for example "chrome".')
    parser.add_argument("--browser-user-data-dir", help="Persistent browser profile directory for cookies/session reuse.")
    parser.add_argument(
        "--browser-wait-for-images",
        type=float,
        default=0,
        help="In browser mode, wait up to N seconds for PSA image URLs to appear after page load.",
    )
    parser.add_argument(
        "--browser-verification-timeout",
        type=float,
        default=None,
        help=(
            "In visible browser mode, wait up to N seconds for manual PSA/Cloudflare "
            "human verification. Default: 300 when --browser-headful is used, else 0."
        ),
    )
    parser.add_argument("--html", action="append", help="Use saved HTML for one cert, format CERT=path.html. Repeatable.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero unless every cert has front and back images.")
    return parser


def _should_use_browser(args: argparse.Namespace) -> bool:
    return bool(
        args.fetcher == "browser"
        or args.browser
        or args.browser_headful
        or args.browser_channel
        or args.browser_user_data_dir
        or args.browser_wait_for_images
        or args.browser_verification_timeout
    )


def _attempt_summary(result) -> dict[str, object]:
    data: dict[str, object] = {
        "fetcher": result.fetcher,
        "status": result.status,
        "images": len(result.images),
    }
    if result.fetch_url:
        data["fetch_url"] = result.fetch_url
    if result.errors:
        data["errors"] = result.errors
    return data


def _download_with_fetcher(
    fetcher: str,
    item: str,
    out_dir: Path,
    *,
    size: str,
    session,
    page_html: str | None,
    reader_html_fetcher: Callable[[str], str],
    browser_html_fetcher: Callable[[str], str] | None,
    timeout: float,
):
    cert = extract_cert_number(item)
    if fetcher == "saved-html":
        result = download_cert_images(
            item,
            out_dir,
            size=size,
            session=session,
            page_html=page_html,
            timeout=timeout,
        )
        result.fetch_url = cert_url(cert)
    elif fetcher == "reader":
        result = download_cert_images(
            item,
            out_dir,
            size=size,
            session=session,
            html_fetcher=reader_html_fetcher,
            timeout=timeout,
        )
        result.fetch_url = reader_url(cert)
    elif fetcher == "direct":
        result = download_cert_images(
            item,
            out_dir,
            size=size,
            session=session,
            timeout=timeout,
        )
        result.fetch_url = cert_url(cert)
    elif fetcher == "browser":
        if browser_html_fetcher is None:
            raise RuntimeError("browser fetcher was not initialized")
        result = download_cert_images(
            item,
            out_dir,
            size=size,
            session=session,
            html_fetcher=browser_html_fetcher,
            timeout=timeout,
        )
        result.fetch_url = cert_url(cert)
    else:
        raise ValueError(f"unknown fetcher: {fetcher}")
    result.fetcher = fetcher
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    items = _read_items(args)
    if not items:
        parser.error("provide at least one cert number, cert URL, --input, or --html CERT=path")

    out_dir = Path(args.out)
    manifest_path = Path(args.manifest)
    html_overrides = _read_html_overrides(args.html)
    session = make_session(args.user_agent)
    fetch_plan = _fetcher_plan(args)
    reader_html_fetcher = _reader_fetcher(session, args.timeout, args.reader_retries, args.reader_retry_delay)
    browser_html_fetcher = None
    close_browser = None

    if "browser" in fetch_plan:
        try:
            verification_timeout = (
                args.browser_verification_timeout
                if args.browser_verification_timeout is not None
                else 300
                if args.browser_headful
                else 0
            )
            browser_html_fetcher, close_browser = _make_browser_fetcher(
                args.timeout,
                headless=not args.browser_headful,
                user_data_dir=args.browser_user_data_dir,
                wait_for_images=args.browser_wait_for_images,
                verification_timeout=verification_timeout,
                channel=args.browser_channel,
            )
        except Exception as exc:
            print(f"browser setup failed: {exc}", file=sys.stderr)
            return 2

    results = []
    try:
        for index, item in enumerate(items):
            cert = extract_cert_number(item)
            item_plan = ["saved-html"] if cert in html_overrides else fetch_plan
            attempts = []
            result = None
            for fetcher in item_plan:
                current_result = _download_with_fetcher(
                    fetcher,
                    item,
                    out_dir,
                    size=args.size,
                    session=session,
                    page_html=html_overrides.get(cert),
                    reader_html_fetcher=reader_html_fetcher,
                    browser_html_fetcher=browser_html_fetcher,
                    timeout=args.timeout,
                )
                attempts.append(_attempt_summary(current_result))
                if result is None or len(current_result.images) >= len(result.images):
                    result = current_result
                if current_result.status == "ok" or args.fetcher != "auto":
                    break
            if result is None:
                raise RuntimeError(f"no fetcher attempts were run for {cert}")
            result.attempts = attempts
            results.append(result)
            print(f"{cert}: {result.status} via {result.fetcher} ({len(result.images)} image(s))", file=sys.stderr)
            if args.delay and index < len(items) - 1:
                time.sleep(args.delay)
    finally:
        if close_browser:
            close_browser()

    manifest = {
        "summary": {
            "total": len(results),
            "ok": sum(1 for result in results if result.status == "ok"),
            "partial": sum(1 for result in results if result.status == "partial"),
            "failed": sum(1 for result in results if result.status == "failed"),
            "out_dir": str(out_dir),
        },
        "items": [result.to_dict() for result in results],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.zip_path:
        _write_zip(Path(args.zip_path), out_dir, manifest_path)
        manifest["summary"]["zip"] = args.zip_path
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(manifest["summary"], indent=2, ensure_ascii=False))
    if args.strict and manifest["summary"]["ok"] != manifest["summary"]["total"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
