from __future__ import annotations

import html as html_lib
import re
import struct
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

import requests


PSA_CERT_URL = "https://www.psacard.com/cert/{cert}/psa"
READER_CERT_URL = "https://r.jina.ai/http://https://www.psacard.com/cert/{cert}/psa"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

_CERT_RE = re.compile(r"(?:/cert/)?(?P<cert>\d{5,})(?:/psa)?")
_CDN_IMAGE_RE = re.compile(
    r"https://d1htnxwo4o0jhw\.cloudfront\.net/cert/"
    r"(?P<asset>\d+)/"
    r"(?P<size>small|medium|large|xlarge|full|original)/"
    r"(?P<name>[^\"'<>\s)\\]+?\.(?:jpg|jpeg|png|webp))"
    r"(?:\?[^\"'<>\s)\\]+)?",
    re.IGNORECASE,
)


@dataclass
class DownloadedImage:
    side: str
    source_url: str
    file: str
    bytes: int
    width: int | None = None
    height: int | None = None
    content_type: str | None = None

    def to_dict(self) -> dict:
        data = {
            "side": self.side,
            "source_url": self.source_url,
            "file": self.file,
            "bytes": self.bytes,
        }
        if self.width and self.height:
            data["width"] = self.width
            data["height"] = self.height
        if self.content_type:
            data["content_type"] = self.content_type
        return data


@dataclass
class ScrapeResult:
    cert: str
    source_url: str
    status: str
    images: list[DownloadedImage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    candidate_urls: list[str] = field(default_factory=list)
    fetcher: str | None = None
    fetch_url: str | None = None
    attempts: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = {
            "cert": self.cert,
            "source_url": self.source_url,
            "status": self.status,
            "images": [image.to_dict() for image in self.images],
            "candidate_urls": self.candidate_urls,
        }
        if self.errors:
            data["errors"] = self.errors
        if self.fetcher:
            data["fetcher"] = self.fetcher
        if self.fetch_url:
            data["fetch_url"] = self.fetch_url
        if self.attempts:
            data["attempts"] = self.attempts
        return data


def extract_cert_number(value: str) -> str:
    match = _CERT_RE.search(value.strip())
    if not match:
        raise ValueError(f"cannot find PSA cert number in: {value!r}")
    return match.group("cert")


def cert_url(cert: str) -> str:
    return PSA_CERT_URL.format(cert=cert)


def reader_url(cert: str) -> str:
    return READER_CERT_URL.format(cert=cert)


def make_session(user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def fetch_html(url: str, session: requests.Session | None = None, timeout: float = 45) -> str:
    session = session or make_session()
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_reader_markdown(cert_or_url: str, session: requests.Session | None = None, timeout: float = 45) -> str:
    session = session or make_session()
    response = session.get(
        reader_url(extract_cert_number(cert_or_url)),
        timeout=timeout,
        headers={"Accept": "text/plain,*/*;q=0.8"},
    )
    response.raise_for_status()
    return response.text


def decode_page_text(text: str) -> str:
    decoded = text
    for _ in range(3):
        decoded = html_lib.unescape(decoded)
        decoded = decoded.replace("\\u002F", "/").replace("\\/", "/")
    return decoded


def normalize_image_url(url: str, size: str = "large") -> str:
    parts = urlsplit(url)
    path = re.sub(r"/(small|medium|large|xlarge|full|original)/", f"/{size}/", parts.path)
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def extract_cloudfront_image_urls(page_html: str, size: str = "large") -> list[str]:
    decoded = decode_page_text(page_html)
    urls: OrderedDict[str, None] = OrderedDict()
    for match in _CDN_IMAGE_RE.finditer(decoded):
        urls[normalize_image_url(match.group(0), size=size)] = None
    return list(urls.keys())


def _asset_id(url: str) -> str:
    match = re.search(r"/cert/(\d+)/", url)
    return match.group(1) if match else ""


def select_front_back_urls(urls: Iterable[str]) -> list[str]:
    groups: OrderedDict[str, list[str]] = OrderedDict()
    for url in urls:
        groups.setdefault(_asset_id(url), [])
        if url not in groups[_asset_id(url)]:
            groups[_asset_id(url)].append(url)
    if not groups:
        return []
    selected = max(groups.values(), key=len)
    return selected[:2]


def image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i < len(data):
            while i < len(data) and data[i] == 0xFF:
                i += 1
            if i >= len(data):
                break
            marker = data[i]
            i += 1
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            if i + 2 > len(data):
                break
            segment_len = struct.unpack(">H", data[i : i + 2])[0]
            if segment_len < 2 or i + segment_len > len(data):
                break
            if 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}:
                if segment_len >= 7:
                    height, width = struct.unpack(">HH", data[i + 3 : i + 7])
                    return width, height
            i += segment_len
    return None, None


def download_image(
    url: str,
    target: Path,
    session: requests.Session,
    timeout: float = 45,
) -> DownloadedImage:
    response = session.get(
        url,
        timeout=timeout,
        headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    data = response.content
    if not data:
        raise RuntimeError("empty response")
    if content_type and not content_type.lower().startswith("image/"):
        raise RuntimeError(f"not an image response: {content_type}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    width, height = image_dimensions(data)
    side = target.name.split("-", 1)[0]
    return DownloadedImage(
        side=side,
        source_url=url,
        file=str(target),
        bytes=len(data),
        width=width,
        height=height,
        content_type=content_type or None,
    )


def download_cert_images(
    cert_or_url: str,
    out_dir: Path,
    *,
    size: str = "large",
    session: requests.Session | None = None,
    page_html: str | None = None,
    html_fetcher: Callable[[str], str] | None = None,
    timeout: float = 45,
    delay: float = 0,
) -> ScrapeResult:
    cert = extract_cert_number(cert_or_url)
    source = cert_url(cert)
    session = session or make_session()
    errors: list[str] = []

    try:
        html_text = page_html if page_html is not None else (html_fetcher or (lambda url: fetch_html(url, session, timeout)))(source)
    except Exception as exc:
        return ScrapeResult(cert=cert, source_url=source, status="failed", errors=[f"page fetch failed: {exc}"])

    candidate_urls = extract_cloudfront_image_urls(html_text, size=size)
    selected_urls = select_front_back_urls(candidate_urls)
    if not selected_urls:
        return ScrapeResult(
            cert=cert,
            source_url=source,
            status="failed",
            errors=["no PSA CloudFront cert images found on page"],
            candidate_urls=candidate_urls,
        )

    images: list[DownloadedImage] = []
    cert_dir = out_dir / cert
    for index, image_url in enumerate(selected_urls):
        side = "front" if index == 0 else "back"
        suffix = Path(urlsplit(image_url).path).suffix or ".jpg"
        target = cert_dir / f"{side}-{size}{suffix}"
        try:
            downloaded = download_image(image_url, target, session=session, timeout=timeout)
            downloaded.side = side
            downloaded.file = str(target)
            images.append(downloaded)
        except Exception as exc:
            errors.append(f"{side} download failed: {exc}")
        if delay:
            time.sleep(delay)

    status = "ok" if len(images) == 2 else "partial" if images else "failed"
    return ScrapeResult(
        cert=cert,
        source_url=source,
        status=status,
        images=images,
        errors=errors,
        candidate_urls=candidate_urls,
    )
