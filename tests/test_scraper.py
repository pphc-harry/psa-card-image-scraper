from psa_image_scraper.scraper import (
    decode_page_text,
    extract_cert_number,
    extract_cloudfront_image_urls,
    fetch_reader_markdown,
    image_dimensions,
    reader_url,
    select_front_back_urls,
)


def test_extract_cert_number_from_url_and_plain_code():
    assert extract_cert_number("136046059") == "136046059"
    assert extract_cert_number("https://www.psacard.com/cert/114563249/psa") == "114563249"


def test_extract_cloudfront_urls_normalizes_to_large():
    html = """
    <script>
    {"front":"https:\\/\\/d1htnxwo4o0jhw.cloudfront.net\\/cert\\/192407235\\/medium\\/front-name.jpg",
     "back":"https://d1htnxwo4o0jhw.cloudfront.net/cert/192407235/small/back-name.jpg"}
    </script>
    """
    assert extract_cloudfront_image_urls(html) == [
        "https://d1htnxwo4o0jhw.cloudfront.net/cert/192407235/large/front-name.jpg",
        "https://d1htnxwo4o0jhw.cloudfront.net/cert/192407235/large/back-name.jpg",
    ]


def test_select_front_back_prefers_largest_asset_group():
    urls = [
        "https://d1htnxwo4o0jhw.cloudfront.net/cert/1/large/one.jpg",
        "https://d1htnxwo4o0jhw.cloudfront.net/cert/2/large/front.jpg",
        "https://d1htnxwo4o0jhw.cloudfront.net/cert/2/large/back.jpg",
        "https://d1htnxwo4o0jhw.cloudfront.net/cert/2/large/extra.jpg",
    ]
    assert select_front_back_urls(urls) == [
        "https://d1htnxwo4o0jhw.cloudfront.net/cert/2/large/front.jpg",
        "https://d1htnxwo4o0jhw.cloudfront.net/cert/2/large/back.jpg",
    ]


def test_decode_page_text_unescapes_common_page_encodings():
    assert decode_page_text("https:\\/\\/example.com\\/a\\u002Fb") == "https://example.com/a/b"


def test_reader_url_builds_public_reader_endpoint():
    assert reader_url("120224951") == "https://r.jina.ai/http://https://www.psacard.com/cert/120224951/psa"


def test_fetch_reader_markdown_uses_reader_endpoint():
    calls = []

    class Response:
        text = "reader markdown"

        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, timeout, headers):
            calls.append((url, timeout, headers))
            return Response()

    assert fetch_reader_markdown("https://www.psacard.com/cert/120224951/psa", session=Session(), timeout=12) == "reader markdown"
    assert calls == [
        (
            "https://r.jina.ai/http://https://www.psacard.com/cert/120224951/psa",
            12,
            {"Accept": "text/plain,*/*;q=0.8"},
        )
    ]


def test_png_dimensions():
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"\x00\x00\x00\x10\x00\x00\x00 "
    assert image_dimensions(data) == (16, 32)
