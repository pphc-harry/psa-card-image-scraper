# PSA Card Image Scraper

Download the public front/back certificate images from PSA cert pages at the
highest public size currently exposed by the page, usually `large`.

The scraper takes PSA cert numbers or PSA cert URLs, reads the public page data,
extracts the CloudFront card image URLs, normalizes them to the requested size,
downloads the images into one folder per cert, and writes a JSON manifest.

By default it uses `--fetcher auto`: public reader route first, direct PSA page
second, and browser fallback only when browser options are supplied. This is the
recommended mode for batch jobs because it avoids asking you to complete PSA
browser verification for every cert.

## Install

```bash
git clone https://github.com/pphc-harry/psa-card-image-scraper.git
cd psa-card-image-scraper
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional browser-rendered mode:

```bash
pip install -e ".[browser]"
python -m playwright install chromium
```

## Usage

Single cert:

```bash
psa-image-scraper 136046059 --out downloads --zip psa-images.zip
```

Multiple certs:

```bash
psa-image-scraper 136046059 114563249 https://www.psacard.com/cert/114563248/psa
```

Batch file:

```bash
cat certs.txt
# 136046059
# https://www.psacard.com/cert/114563249/psa

psa-image-scraper --input certs.txt --out downloads --zip psa-images.zip
```

The default `auto` mode is the batch-friendly route. For most lists, this is all
you need:

```bash
psa-image-scraper --input certs.txt \
  --out downloads \
  --zip psa-images.zip
```

If you need to force a route:

```bash
psa-image-scraper --input certs.txt --fetcher reader --out downloads
psa-image-scraper --input certs.txt --fetcher direct --out downloads
psa-image-scraper --input certs.txt --fetcher browser --browser-headful --out downloads
```

Use Playwright if the page needs a rendered DOM:

```bash
psa-image-scraper 136046059 --fetcher browser --browser --out downloads
```

If the public reader route is temporarily missing a cert and PSA direct page
fetching returns `403 Forbidden`, use a visible browser with a persistent
profile as an auto fallback. You should normally complete the normal
PSA/Cloudflare browser check once for the session, not once per cert:

```bash
pip install -e ".[browser]"
python -m playwright install chromium

psa-image-scraper --input certs.txt \
  --browser-headful \
  --browser-user-data-dir .psa-browser-profile \
  --browser-verification-timeout 300 \
  --browser-wait-for-images 120 \
  --out downloads \
  --zip psa-images.zip
```

If a page opens with "Verify you are human", complete that check in the opened
browser window and keep the browser open. The scraper waits for the page to
finish loading the public PSA cert image URLs, then continues automatically.
Use a larger value such as `--browser-verification-timeout 600` if you need more
time to finish the check.

If Playwright's bundled Chromium is unavailable but Chrome is installed:

```bash
psa-image-scraper --input certs.txt \
  --browser-headful \
  --browser-channel chrome \
  --browser-user-data-dir .psa-browser-profile \
  --browser-verification-timeout 300 \
  --browser-wait-for-images 120 \
  --out downloads
```

Use saved HTML if direct page fetching is blocked:

```bash
psa-image-scraper --html 136046059=./pages/136046059.html --out downloads
```

## Output

```text
downloads/
  136046059/
    front-large.jpg
    back-large.jpg
manifest.json
psa-images.zip
```

Each manifest item includes:

- PSA cert number
- source PSA URL
- extracted CDN URLs
- downloaded file path
- fetcher route used: `reader`, `direct`, `browser`, or `saved-html`
- fetch attempts made in auto mode
- byte size and image dimensions
- status: `ok`, `partial`, or `failed`

## Notes

- This tool only uses public PSA cert pages and public image URLs found on those pages.
- It does not bypass authentication, paywalls, WAF, Cloudflare, or rate limits.
- Default `auto` mode tries the public reader route before direct PSA page
  fetching. A `403` in direct mode means PSA blocked the current network/session
  before the public image URLs were visible.
- A Cloudflare "Verify you are human" page is expected on some networks. This
  tool does not bypass it; browser mode is only a fallback when reader/direct
  routes cannot expose the public image URLs.
- Be respectful with request volume. Use `--delay` for bulk jobs.
- `large` is the highest public size seen on current PSA cert image URLs. Other labels such as `original`, `full`, or `xlarge` often return `404`.
