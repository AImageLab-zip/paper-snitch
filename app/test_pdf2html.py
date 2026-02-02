"""
PDF to HTML Converter using pdf2htmlEX

This module provides functions to convert PDF files to HTML format using pdf2htmlEX.
The output HTML is optimized for text annotation tools like Label Studio.

Requirements:
    - pdf2htmlEX must be installed on your system
    - Install via: brew install pdf2htmlex (macOS) or apt-get install pdf2htmlex (Linux)
    - Or use Docker: docker pull bwits/pdf2htmlex
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "media" / "pdfs"


def convert_pdf_to_html(
    pdf_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    zoom: float = 1.0,
    embed_fonts: bool = True,
    embed_images: bool = True,
    split_pages: bool = False,
    process_outline: bool = True,
    dest_dir: Optional[Union[str, Path]] = None,
    extra_options: Optional[list] = None,
) -> str:
    """
    Convert a PDF file to HTML using pdf2htmlEX.

    This function produces HTML output that preserves the PDF layout and is suitable
    for annotation with tools like Label Studio. The text remains selectable and
    the visual structure is maintained.

    Args:
        pdf_path: Path to the input PDF file.
        output_path: Path for the output HTML file. If None, uses the PDF name with .html extension.
        zoom: Zoom ratio for the output (default 1.0). Higher values = larger output.
        embed_fonts: Whether to embed fonts in the HTML (default True).
        embed_images: Whether to embed images as base64 in the HTML (default True).
        split_pages: Whether to split pages into separate HTML files (default False).
        process_outline: Whether to process PDF outline/bookmarks (default True).
        dest_dir: Destination directory for output files. If None, uses current directory.
        extra_options: Additional command-line options for pdf2htmlEX.

    Returns:
        str: Path to the generated HTML file.

    Raises:
        FileNotFoundError: If the PDF file doesn't exist or pdf2htmlEX is not installed.
        RuntimeError: If the conversion fails.
    """
    # Validate inputs
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    # Determine output path
    if output_path is None:
        output_filename = pdf_path.stem + ".html"
    else:
        output_filename = Path(output_path).name

    # Determine destination directory
    if dest_dir is None:
        dest_dir = Path.cwd()
    else:
        dest_dir = Path(dest_dir).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)

    # Build command
    cmd = ["pdf2htmlEX"]

    # Add options for better Label Studio compatibility
    cmd.extend(["--zoom", str(zoom)])

    if embed_fonts:
        cmd.extend(["--embed-font", "1"])
    else:
        cmd.extend(["--embed-font", "0"])

    if embed_images:
        cmd.extend(["--embed-image", "1"])
    else:
        cmd.extend(["--embed-image", "0"])

    if split_pages:
        cmd.extend(["--split-pages", "1"])
    else:
        cmd.extend(["--split-pages", "0"])

    if process_outline:
        cmd.extend(["--process-outline", "1"])
    else:
        cmd.extend(["--process-outline", "0"])

    # Options that improve text selection and annotation compatibility
    cmd.extend(
        [
            "--dest-dir",
            str(dest_dir),
            "--optimize-text",
            "1",  # Optimize text for better selection
        ]
    )

    # Add any extra options
    if extra_options:
        cmd.extend(extra_options)

    # Add input and output files
    cmd.append(str(pdf_path))
    cmd.append(output_filename)

    # Run conversion
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"pdf2htmlEX conversion failed:\n"
            f"Command: {' '.join(cmd)}\n"
            f"Error: {e.stderr}"
        )

    output_file = dest_dir / output_filename

    if not output_file.exists():
        raise RuntimeError(
            f"Conversion completed but output file not found: {output_file}"
        )

    return str(output_file)


def get_html(html_path: Union[str, Path]) -> str:
    """
    Get HTML content from a file.

    Args:
        html_path: Path to the input HTML file.

    Returns:
        str: The HTML content as a string.
    """

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    return html_content


def convert_pdf_to_html_for_labeling(
    pdf_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    include_page_markers: bool = True,
) -> str:
    """
    Convert a PDF to HTML optimized for Label Studio annotation.

    This function applies settings that make the HTML more suitable for
    text annotation tasks:
    - Embeds all resources (fonts, images) for portability
    - Optimizes text layer for selection
    - Optionally adds page markers for reference

    Args:
        pdf_path: Path to the input PDF file.
        output_path: Path for the output HTML file.
        include_page_markers: Whether to include visible page number markers.

    Returns:
        str: Path to the generated HTML file.
    """
    pdf_path = Path(pdf_path).resolve()

    # Determine output path
    if output_path is None:
        output_dir = pdf_path.parent
        output_filename = pdf_path.stem + "_labeled.html"
        output_path = output_dir / output_filename
    else:
        output_path = Path(output_path).resolve()
        output_dir = output_path.parent
        output_filename = output_path.name

    # Convert with optimized settings for labeling
    html_path = convert_pdf_to_html(
        pdf_path,
        output_path=output_filename,
        dest_dir=output_dir,
        zoom=1.5,  # Slightly larger for better readability during annotation
        embed_fonts=True,
        embed_images=True,
        split_pages=False,  # Keep all pages in one file for easier annotation
        process_outline=True,
    )

    return html_path


def convert_pdf_with_docker(
    pdf_path: Union[str, Path], project_root: Union[str, Path] = "."
) -> str:
    """
    Convert a PDF to HTML using the 'pdf2html' service defined in docker-compose.yml.

    Args:
        pdf_path: Name or path of the PDF file (e.g., "my_file.pdf").
        project_root: Path to the directory containing docker-compose.yml.

    Returns:
        str: Relative path to the generated HTML file on the host.

    Raises:
        FileNotFoundError: If Docker is not found.
        RuntimeError: If the conversion fails.
    """
    # 1. We only need the filename because the container mounts the specific folder
    # logic: /app/media/pdf/doc.pdf -> doc.pdf
    input_filename = Path(pdf_path).name
    stem_name = Path(pdf_path).stem

    # 2. Check if Docker is available
    try:
        subprocess.run(["docker", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise FileNotFoundError("Docker is not installed or not running")

    # 3. Build Docker Compose command
    # correspond to: docker compose run --rm pdf2html --zoom 1.3 --dest-dir /output filename.pdf
    cmd = [
        "docker",
        "compose",
        "-f",
        "/home/dsantoli/papersnitch/compose.dev.yml",
        "run",
        "--rm",
        "pdf2html",  # The service name in compose.dev.yml
        "--zoom",
        "1.3",
        "--embed-font",
        "1",
        "--embed-image",
        "1",
        "--optimize-text",
        "1",
        "--dest-dir",
        "/output",  # Internal container path (mapped to app/media/htmls)
        input_filename,  # File is expected to be in /input inside container
    ]

    try:
        # We run this command from the project root so it finds compose.dev.yml
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, cwd=project_root
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Docker conversion failed: {e.stderr}")

    # 4. Return the path where the file appeared on the HOST machine
    # Based on your volume mapping: ./app/media/htmls:/output
    return str(Path("app/media/htmls") / f"{stem_name}.html")


if __name__ == "__main__":
    pdf_file = "A_Frequency-Aware_Self-Supervised_Learning_for_Ultra-Wide-Field_Image_Enhancement.pdf"

    print(f"\nConverting: {pdf_file}")

    try:
        # Assuming you run this script from the same folder as compose.dev.yml
        html_path = convert_pdf_with_docker(pdf_file)
        print(f"✓ Conversion successful!")
        print(f"  Output location: {html_path}")
    except Exception as e:
        print(f"✗ Conversion failed: {e}")
