from psa_image_scraper.cli import _looks_like_security_verification, _should_use_browser, build_parser


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
    assert args.browser_verification_timeout == 300


def test_direct_mode_stays_direct_by_default():
    parser = build_parser()
    args = parser.parse_args(["136046059"])

    assert not _should_use_browser(args)


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
