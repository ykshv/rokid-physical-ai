"""Check generated public URLs and essential crawler-visible content without a browser."""

from pathlib import Path
from xml.etree import ElementTree

BASE = "https://ykshv.github.io/rokid-physical-ai/"
site = Path("site")
for page in ("", "quickstart", "architecture", "robots", "calibration", "verification", "ru"):
    html = (site / page / "index.html").read_text(encoding="utf-8")
    expected = BASE + (page + "/" if page else "")
    assert f'href="{expected}"' in html, f"Missing canonical URL for {page}"
    assert 'name="description"' in html, f"Missing description for {page}"
    assert 'name="robots" content="noindex"' not in html
    assert "Rokid Physical AI" in html
tree = ElementTree.parse(site / "sitemap.xml")
urls = [node.text for node in tree.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
assert urls and all(url and url.startswith(BASE) for url in urls)
print(f"Public HTML and sitemap verified: {len(urls)} URLs")
