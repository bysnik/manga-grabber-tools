import logging
import urllib.parse
import zipfile
from importlib.resources import files
from pathlib import Path
from typing import Literal

import natsort
from bs4 import BeautifulSoup
from fpdf import FPDF
from fpdf.outline import TableOfContents
from PIL import Image

from . import mangalib, usagi, ranobehub
from .base import GRABBER_REGISTRY
from .utils import find_font

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def img_to_cbz(img_dir: Path):
    """
    Creates a CBZ archive from the contents of the specified directory

    :param img_dir: Directory containing manga chapter pages
    :return: Path to the created CBZ file
    """
    cbz_path = img_dir.with_suffix(".cbz")
    with zipfile.ZipFile(cbz_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        for page in natsort.natsorted(img_dir.iterdir(), alg=natsort.ns.REAL):
            zipf.write(page, arcname=page.name)
    logger.info(f"CBZ file created: {cbz_path}")
    return cbz_path


def img_to_pdf(img_path: Path):
    """
    Creates a PDF file from the contents of the specified directory

    :param img_path: Directory containing manga chapter pages
    :return: Path to the created PDF file
    """
    pdf_path = img_path.with_suffix(".pdf")
    pdf = FPDF(unit="pt")  # Use points as unit for better control over dimensions

    # Sort pages by name to maintain order
    pages = natsort.natsorted(img_path.iterdir(), alg=natsort.ns.REAL)

    for page in pages:
        # Open the image file to get its dimensions
        with Image.open(page) as image:
            width, height = image.size
            # Convert pixels to points (1 pixel = 0.75 points)
            pdf.add_page(format=(width * 0.75, height * 0.75))
            pdf.image(image, x=0, y=0, w=width * 0.75, h=height * 0.75)

    pdf.output(str(pdf_path))
    logger.info(f"PDF file created: {pdf_path}")
    return pdf_path


def html_to_pdf(html_dir: Path):
    """
    Creates a PDF file from the HTML content in the specified directory

    :param html_dir: Directory containing the HTML file and assets
    :return: Path to the created PDF file
    """
    html_files = natsort.natsorted(html_dir.glob("*.html"), alg=natsort.ns.REAL)

    pdf_path = html_dir.with_suffix(".pdf")
    pdf = FPDF(unit="pt")
    pdf.add_page()
    if len(html_files) > 1:
        toc = TableOfContents()
        pdf.insert_toc_placeholder(toc.render_toc, allow_extra_pages=True)

    # Add fonts
    fonts_path = files("manga_grabber.fonts")
    pdf.add_font("DejaVuSerif", "", fonts_path / "DejaVuSerif.ttf")
    pdf.add_font("DejaVuSerif", "B", fonts_path / "DejaVuSerif-Bold.ttf")
    pdf.add_font("DejaVuSerif", "I", fonts_path / "DejaVuSerif-Italic.ttf")
    pdf.add_font("DejaVuSerif", "BI", fonts_path / "DejaVuSerif-BoldItalic.ttf")
    pdf.add_font(fname=fonts_path / "DejaVuSans.ttf")
    fallback_fonts = ["DejaVuSans"]
    # Set fallback fonts for CJK characters
    for family in ("Noto Sans CJK JP", "Yu Gothic"):
        if cjk_font := find_font(family, "Regular"):
            pdf.add_font(fname=cjk_font)
            fallback_fonts.append(cjk_font.stem)

    pdf.set_fallback_fonts(fallback_fonts)

    for html_file in html_files:
        # Load the HTML file
        html_content = html_file.read_text(encoding="utf-8")

        soup = BeautifulSoup(html_content, "html.parser")
        # Set images width to fit the page
        for img in soup.find_all("img"):
            img_path = html_dir / img["src"]
            img["width"] = int(pdf.epw)
            img["src"] = str(img_path)
        # Convert the modified HTML back to a string
        html_content = str(soup)

        pdf.write_html(html_content, font_family="DejaVuSerif")
        pdf.add_page()

    pdf.named_destinations = {}

    pdf.output(str(pdf_path))
    logger.info(f"PDF file created: {pdf_path}")
    return pdf_path


def html_to_epub(html_dir: Path):
    """
    Creates an EPUB file from the HTML content in the specified directory

    :param html_dir: Directory containing the HTML file and assets
    :return: Path to the created EPUB file
    """
    from ebooklib import epub

    html_files = natsort.natsorted(html_dir.glob("*.html"), alg=natsort.ns.REAL)

    if not html_files:
        logger.warning(f"No HTML files found in {html_dir}")
        return None

    # Create EPUB book
    book = epub.EpubBook()

    # Extract metadata from directory name (e.g., "vol1_ch1")
    dir_name = html_dir.name
    book.set_title(dir_name)
    book.set_language("ru")

    # Add chapters and collect spine items
    chapters = []
    spine_items = ["nav"]

    for idx, html_file in enumerate(html_files, start=1):
        # Read HTML content
        html_content = html_file.read_text(encoding="utf-8")

        # Parse HTML to extract title
        soup = BeautifulSoup(html_content, "html.parser")
        title_tag = soup.find("title")
        chapter_title = title_tag.string if title_tag else f"Глава {idx}"

        # Create EPUB chapter
        chapter = epub.EpubHtml(
            title=chapter_title,
            file_name=f"chapter_{idx}.xhtml",
        )

        # Process images in HTML
        for img in soup.find_all("img"):
            img_src = img.get("src")
            if img_src:
                img_path = html_dir / img_src
                if img_path.exists():
                    # Read image file
                    img_content = img_path.read_bytes()

                    # Create EPUB image item
                    epub_img = epub.EpubItem(
                        uid=f"img_{idx}_{img_path.name}",
                        file_name=f"images/{img_path.name}",
                        content=img_content,
                    )
                    book.add_item(epub_img)

                    # Update image src in HTML
                    img["src"] = f"images/{img_path.name}"

        # Set chapter content with processed HTML
        chapter.set_content(str(soup))

        # Add chapter to book
        book.add_item(chapter)
        chapters.append(chapter)
        spine_items.append(chapter)

    # Add navigation files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Define Table of Contents
    book.toc = tuple(chapters)

    # Define spine (order of chapters)
    book.spine = spine_items

    # Write EPUB file
    epub_path = html_dir.with_suffix(".epub")
    epub.write_epub(str(epub_path), book)

    logger.info(f"EPUB file created: {epub_path}")
    return epub_path


def get_grabber(url: str) -> type[mangalib.BaseGrabber]:
    """
    Returns the appropriate grabber class based on the URL hostname

    :param url: URL of the manga or ranobe title
    :return: Grabber class corresponding to the URL
    """
    hostname = urllib.parse.urlparse(url).hostname
    grabber_cls = GRABBER_REGISTRY.get(hostname)
    if not grabber_cls:
        logger.warning(
            f"No specific parser found for {hostname}, falling back to MangaLib"
        )

    return grabber_cls or mangalib.MangaLib


async def download_title(
    manga_url: str,
    output_dir: Path,
    *,
    branch_id: int = -1,
    token: str | None = None,
    from_chapter: int | float = 0,
    from_volume: int = 0,
    cbz: bool = False,
    pdf: bool = False,
    epub: bool = False,
    save_mode: Literal["chapter", "volume", "all"] = "chapter",
):
    """
    Downloads all chapters of a manga from MangaLib and saves them to the specified directory

    :param manga_url: URL of the manga on MangaLib
    :param output_dir: Directory where the manga chapters will be saved
    :param branch_id: ID of translation branch (optional, for multi-branch titles).
    If set to -1, main and alt branch will be downloaded
    :param token: Optional API token for authenticated requests
    :param from_chapter: Chapter number to start downloading from
    :param from_volume: Volume number to start downloading from
    :param cbz: If True, chapters will be archived as CBZ files
    :param pdf: If True, chapters will be archived as PDF files
    :param epub: If True, chapters will be archived as EPUB files
    :param save_mode: How to save chapters, can be 'chapter' (one chapter per dir/file),
    'volume' (one volume per dir/file), or 'all' (one dir/file for all chapters)
    """
    grabber_class = get_grabber(manga_url)
    downloaded_dirs = list()

    async with grabber_class(manga_url, token) as manga_lib:
        chapters = await manga_lib.get_chapters()
        for chapter in chapters:
            # Check if the volume and chapter numbers are within the specified ranges
            if (
                int(chapter["volume"]) < from_volume
                or float(chapter["number"]) < from_chapter
            ):
                continue

            branch_found = any(
                (branch["branch_id"] == branch_id for branch in chapter["branches"])
            )
            if not branch_found and branch_id >= 0:
                continue

            logger.info(
                f"Downloading chapter {chapter['number']} from volume {chapter['volume']}..."
            )
            match save_mode:
                case "chapter":
                    chapter_dir = (
                        output_dir / f"vol{chapter['volume']}_ch{chapter['number']}"
                    )
                    prefix = ""
                case "volume":
                    chapter_dir = output_dir / f"vol{chapter['volume']}"
                    prefix = f"ch{chapter['number']}_"
                case "all":
                    chapter_dir = output_dir
                    prefix = f"vol{chapter['volume']}_ch{chapter['number']}_"
            await manga_lib.download_chapter(
                chapter["number"],
                chapter["volume"],
                chapter_dir,
                branch_id=branch_id,
                prefix=prefix,
            )
            # Track directories and volumes for later export
            if chapter_dir not in downloaded_dirs:
                downloaded_dirs.append(chapter_dir)

        for chapter_dir in downloaded_dirs:
            if cbz:
                img_to_cbz(chapter_dir)
            if pdf:
                if any(chapter_dir.glob("*.html")):
                    html_to_pdf(chapter_dir)
                else:
                    img_to_pdf(chapter_dir)
            if epub:
                if any(chapter_dir.glob("*.html")):
                    html_to_epub(chapter_dir)
                else:
                    logger.warning(
                        f"EPUB export is only supported for HTML content (ranobe). "
                        f"Skipping chapter {chapter['number']} from volume {chapter['volume']}."
                    )
