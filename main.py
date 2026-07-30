from pathlib import Path

from crawler import Downloader
from parsers import HikrParser


def main() -> None:
    """Download one Hikr page and parse its metadata."""
    url = "https://www.hikr.org/tour/post12345.html"  # Replace with a real Hikr tour URL.
    html_dir = Path("data/html")
    html_dir.mkdir(parents=True, exist_ok=True)
    html_path = html_dir / "hikr_tour.html"

    downloader = Downloader()
    print(f"Downloading page: {url}")
    saved_file = downloader.download_url(url, html_path)
    print(f"Saved HTML to: {saved_file}")

    parser = HikrParser()
    metadata = parser.parse_local_html(saved_file, base_url=url)

    print("\nExtracted metadata:")
    for key, value in metadata.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
