from psa_image_scraper.cli import _should_use_browser, build_parser


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
        ]
    )

    assert _should_use_browser(args)


def test_direct_mode_stays_direct_by_default():
    parser = build_parser()
    args = parser.parse_args(["136046059"])

    assert not _should_use_browser(args)
