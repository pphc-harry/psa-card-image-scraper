# PSA Card Image Scraper

Download the public front/back certificate images from PSA cert pages at the
highest public size currently exposed by the page, usually `large`.

The scraper takes PSA cert numbers or PSA cert URLs, reads the public page,
extracts the CloudFront card image URLs, normalizes them to the requested size,
downloads the images into one folder per cert, and writes a JSON manifest.

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

Use Playwright if the page needs a rendered DOM:

```bash
psa-image-scraper 136046059 --browser --out downloads
```

If PSA returns `403 Forbidden`, use a visible browser with a persistent profile.
This lets you complete any normal PSA/Cloudflare browser check once, then reuse
the same browser cookies/session for the scrape:

```bash
pip install -e ".[browser]"
python -m playwright install chromium

psa-image-scraper --input certs.txt \
  --browser-headful \
  --browser-user-data-dir .psa-browser-profile \
  --browser-wait-for-images 120 \
  --out downloads \
  --zip psa-images.zip
```

If Playwright's bundled Chromium is unavailable but Chrome is installed:

```bash
psa-image-scraper --input certs.txt \
  --browser-headful \
  --browser-channel chrome \
  --browser-user-data-dir .psa-browser-profile \
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
- byte size and image dimensions
- status: `ok`, `partial`, or `failed`

## Notes

- This tool only uses public PSA cert pages and public image URLs found on those pages.
- It does not bypass authentication, paywalls, WAF, Cloudflare, or rate limits.
- A `403` means PSA blocked the current network/session before the public image
  URLs were visible. Try `--browser-headful --browser-user-data-dir .psa-browser-profile`
  from the same machine/network that can open PSA normally.
- Be respectful with request volume. Use `--delay` for bulk jobs.
- `large` is the highest public size seen on current PSA cert image URLs. Other labels such as `original`, `full`, or `xlarge` often return `404`.
