from pathlib import Path

from crawler import Downloader
from parsers import GpxParser, HikrParser


def main() -> None:
    """Download one Hikr page, parse its metadata and measure the GPX track."""
    url = "https://www.hikr.org/tour/post202345.html"  # Replace with a real Hikr tour URL.
    html_dir = Path("data/html")
    html_dir.mkdir(parents=True, exist_ok=True)
    html_path = html_dir / "hikr_tour.html"

    downloader = Downloader()
    print(f"Downloading page: {url}")
    saved_file = downloader.download_url(url, html_path)
    print(f"Saved HTML to: {saved_file}")

    metadata = HikrParser().parse_local_html(saved_file, base_url=url)

    gpx_url = metadata["gpx_url"]
    if gpx_url is None:
        print("No GPX link found in this tour.")
    else:
        gpx_path = downloader.download_gpx(
            gpx_url,
            title=metadata["title"],
            date_iso=metadata["date_iso"],
        )
        print(f"Saved GPX to: {gpx_path}")

        # Die Distanz steht nicht im HTML, sie kommt erst aus der GPX Datei.
        gpx_data = GpxParser().parse_local_gpx(gpx_path)
        metadata["distance"] = gpx_data["distance_km"]

    print("\nExtracted metadata:")
    for key, value in metadata.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
