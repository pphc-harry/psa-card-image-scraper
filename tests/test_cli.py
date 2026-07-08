import psa_image_scraper.cli as cli
from psa_image_scraper.cli import _fetcher_plan, _looks_like_security_verification, _reader_fetcher, _should_use_browser, build_parser


def test_browser_recovery_options_enable_browser_mode():
    parser = build_parser()
    args = parser.parse_args(
        [
            "136046059",
            "--browser-headful",
            "--browser-user-data-dir",
            ".psa-browser-profile",
            "--browser-wait-for-images",
            "120",
            "--browser-verification-timeout",
            "300",
        ]
    )

    assert _should_use_browser(args)
    assert _fetcher_plan(args) == ["reader", "direct", "browser"]
    assert args.browser_verification_timeout == 300


def test_auto_mode_uses_reader_first_by_default():
    parser = build_parser()
    args = parser.parse_args(["136046059"])

    assert args.fetcher == "auto"
    assert not _should_use_browser(args)
    assert _fetcher_plan(args) == ["reader", "direct"]


def test_explicit_direct_mode_stays_direct():
    parser = build_parser()
    args = parser.parse_args(["136046059", "--fetcher", "direct"])

    assert not _should_use_browser(args)
    assert _fetcher_plan(args) == ["direct"]


def test_explicit_browser_fetcher_enables_browser_mode():
    parser = build_parser()
    args = parser.parse_args(["136046059", "--fetcher", "browser"])

    assert _should_use_browser(args)
    assert _fetcher_plan(args) == ["browser"]


def test_reader_fetcher_retries_until_image_urls_are_present(monkeypatch):
    calls = []

    def fake_fetch_reader_markdown(url, session, timeout):
        calls.append((url, session, timeout))
        if len(calls) == 1:
            return "Title: no images yet"
        return '![Image 2: Cert image 1](https://d1htnxwo4o0jhw.cloudfront.net/cert/1/small/front.jpg)'

    monkeypatch.setattr(cli, "fetch_reader_markdown", fake_fetch_reader_markdown)
    fetcher = _reader_fetcher(session="session", timeout=12, retries=2, retry_delay=0)

    assert "front.jpg" in fetcher("120224951")
    assert calls == [("120224951", "session", 12), ("120224951", "session", 12)]


def test_security_verification_detection_matches_cloudflare_copy():
    html = """
    <html>
      <title>Just a moment...</title>
      <body>
        <h1>www.psacard.com</h1>
        <h2>Performing security verification</h2>
        <label>Verify you are human</label>
      </body>
    </html>
    """

    assert _looks_like_security_verification(html)


def test_security_verification_detection_ignores_normal_cert_page():
    html = '<html><img src="https://d1htnxwo4o0jhw.cloudfront.net/cert/123/large/front.jpg"></html>'

    assert not _looks_like_security_verification(html)
