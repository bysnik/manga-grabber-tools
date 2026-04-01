import asyncio
import logging
import re
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup

from .base import BaseGrabber, register_grabber
from .exceptions import ChapterInfoError, GrabberException, TitleNotFoundError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


@register_grabber("mangalib.me")
class MangaLib(BaseGrabber):
    """A class to interact with the MangaLib API and download manga chapters"""

    api_base_url: str = "https://api.cdnlibs.org/api"
    resource_base_url: str = "https://img2.imglib.info"

    def __init__(self, title_url: str, token: str | None = None):
        super().__init__(title_url, token)
        self._headers["Referer"] = "https://mangalib.me/"
        if token is not None:
            self._headers["Authorization"] = f"Bearer {token}"
        self.manga_id = int(re.findall(r"/(\d+)--?([\w-]*)", title_url)[0][0])
        self.manga_name = re.findall(r"/(\d+)--?([\w-]*)", title_url)[0][1]

    async def get_chapters(self) -> list:
        """Fetch the list of chapters and additional info for the manga"""
        session = await self.session
        async with session.get(
            f"{self.api_base_url}/manga/{self.manga_id}--{self.manga_name}/chapters"
        ) as response:
            match response.status:
                case 404:
                    raise TitleNotFoundError(f"Title {self.manga_name} not found")
                case 200:
                    return (await response.json())["data"]
                case _:
                    raise GrabberException(
                        f"Failed to fetch chapters: {response.status}"
                    )

    async def get_chapter_info(
        self, chapter: int, volume: int, branch_id: int = 0
    ) -> dict:
        """
        Fetch detailed information about a specific chapter of the manga

        :param chapter: Chapter number
        :param volume: Volume number
        :param branch_id: ID of translation branch (optional, for multi-branch titles).
        If the specified translation branch for the chapter is not found, the function returns another available branch.
        """
        session = await self.session
        params = {"number": chapter, "volume": volume}
        if branch_id > 0:
            params["branch_id"] = branch_id
        async with session.get(
            f"{self.api_base_url}/manga/{self.manga_id}--{self.manga_name}/chapter",
            params=params,
        ) as response:
            match response.status:
                case 404:
                    raise ChapterInfoError(
                        f"Info for chapter {chapter} volume {volume} not found"
                    )
                case 200:
                    return (await response.json())["data"]
                case _:
                    raise GrabberException(
                        f"Failed to fetch chapter info: {response.status}"
                    )

    async def download_chapter(
        self,
        chapter: int,
        volume: int,
        output_dir: Path,
        branch_id: int = 0,
        prefix: str = "",
    ):
        """
        Download all pages of a specific chapter and save them to the specified directory

        :param chapter: Chapter number to download
        :param volume: Volume number to download
        :param output_dir: Directory where the chapter pages will be saved
        :param branch_id: ID of translation branch (optional, for multi-branch titles)
        :param prefix: Prefix for the downloaded files
        """
        ch = await self.get_chapter_info(chapter, volume, branch_id)

        if not output_dir.exists():
            output_dir.mkdir(parents=True)

        tasks = []
        for page in ch["pages"]:
            url = f"{self.resource_base_url}/{page['url']}"
            tasks.append(
                self._download_file(
                    await self.session,
                    url,
                    output_dir / f"{prefix}p{page['slug']:02d}_{page['image']}",
                )
            )
        return await asyncio.gather(*tasks)


@register_grabber("hentailib.me")
class HentaiLib(MangaLib):
    api_base_url = "https://hapi.hentaicdn.org/api"
    resource_base_url = "https://img3h.hentaicdn.org"

    def __init__(self, title_url: str, token: str | None = None):
        super().__init__(title_url, token)
        self._headers["Referer"] = "https://hentailib.me/"
        self._headers["Accept"] = "application/json"

    async def get_chapter_info(
        self, chapter: int, volume: int, branch_id: int = 0
    ) -> dict:
        """
        Получить информацию о главе (страницы) для hentailib.
        Сначала пытается через API, затем через парсинг HTML.
        """
        # Получаем chapter_id из списка глав
        chapters = await self.get_chapters()
        target = None
        for ch in chapters:
            if ch["number"] == str(chapter) and ch["volume"] == str(volume):
                target = ch
                break
        if not target:
            raise ChapterInfoError(
                f"Chapter {chapter} volume {volume} not found in list"
            )
        chapter_id = target["id"]

        # Вариант 1: пробуем API-эндпоинт /chapter/{id}/pages
        session = await self.session
        pages_url = f"{self.api_base_url}/chapter/{chapter_id}/pages"
        async with session.get(pages_url, headers=self._headers) as resp:
            if resp.status == 200:
                try:
                    data = await resp.json()
                    # Предполагаем, что data — это список страниц с полями 'uuid', 'extension' и т.д.
                    pages = []
                    for idx, page in enumerate(data, start=1):
                        # Формируем URL по шаблону из HAR
                        uuid = page.get("uuid")
                        if uuid:
                            ext = page.get("extension", "png")
                            url = f"{self.resource_base_url}//manga/{self.manga_name}/chapters/{chapter_id}/{uuid}.{ext}"
                            pages.append({"url": url, "slug": idx})
                    if pages:
                        return {"pages": pages}
                except Exception:
                    pass

        # Вариант 2: парсим HTML страницы чтения
        read_url = f"https://hentailib.me/ru/{self.manga_id}--{self.manga_name}/read/v{volume}/c{chapter}"
        async with session.get(read_url, headers=self._headers) as resp:
            if resp.status != 200:
                raise ChapterInfoError(
                    f"Failed to load chapter page: {resp.status}"
                )
            html = await resp.text()

        # Ищем __NEXT_DATA__
        import re, json
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
        )
        if not match:
            raise ChapterInfoError("Could not find chapter data in HTML")
        data = json.loads(match.group(1))

        # Извлекаем страницы из структуры (зависит от версии сайта)
        try:
            pages_data = data["props"]["pageProps"]["chapter"]["pages"]
        except (KeyError, TypeError):
            raise ChapterInfoError("Could not extract pages from JSON")

        pages = []
        for idx, page in enumerate(pages_data, start=1):
            uuid = page.get("uuid")
            if uuid:
                ext = page.get("extension", "png")
                url = f"{self.resource_base_url}//manga/{self.manga_name}/chapters/{chapter_id}/{uuid}.{ext}"
                pages.append({"url": url, "slug": idx})
        return {"pages": pages}


@register_grabber("ranobelib.me")
class RanobeLib(MangaLib):
    resource_base_url = "https://ranobelib.me"
    url_regex = re.compile(
        r"https?://(www\.)?[-a-zA-Zа-яA-Я0-9@:%._+~#=]{1,256}\.[a-zA-Zа-яA-Я0-9]{1,6}\b([-a-zA-Zа-яA-Я0-9()@:%_+.~#?&/=]*)"
    )

    async def download_chapter(
        self,
        chapter: int,
        volume: int,
        output_dir: Path,
        branch_id: int = 0,
        prefix: str = "",
    ):
        """
        Download all pages of a specific chapter and save them to the specified directory

        :param chapter: Chapter number to download
        :param volume: Volume number to download
        :param output_dir: Directory where the chapter pages will be saved
        :param branch_id: ID of translation branch (optional, for multi-branch titles)
        :param prefix: Prefix for the downloaded files
        """
        ch = await self.get_chapter_info(chapter, volume, branch_id)

        output_dir.mkdir(parents=True, exist_ok=True)

        file = output_dir / f"{prefix}index.html"
        assets_path = output_dir / "assets"
        assets_path.mkdir(parents=True, exist_ok=True)

        attachments = ch.get("attachments", [])
        text = (
            f"<!DOCTYPE html>\n"
            f'<html lang="ru">\n'
            f"<head>\n"
            f'<meta charset="UTF-8">\n'
            f'<title>Том {volume} Глава {chapter} — {ch["name"]}</title>\n'
            f"</head>\n"
            f"<body>\n"
            f"<h1>Том {volume} Глава {chapter} — {ch['name']}</h1>\n"
        )
        if isinstance(ch["content"], str):
            logger.info("Content is in old HTML format")
            # If content is a string, it is likely using old HTML format
            soup = BeautifulSoup(ch["content"], "html.parser")
            for tag in soup.find_all("img"):
                img_filename = tag["src"].split("/")[-1]
                if attachments:
                    attachment = next(
                        (a for a in attachments if a["filename"] == img_filename), None
                    )
                    if attachment:
                        tag["src"] = f"{assets_path.name}/{attachment['filename']}"
            text += str(soup)
        elif isinstance(ch["content"], dict):
            # If content is a dict, it is using the new custom format
            text += self.convert_ranobe_content_to_html(
                ch["content"]["content"], attachments
            )
        text += "\n</body>\n</html>"
        # Replace URLs in the text with links
        soup = BeautifulSoup(text, "html.parser")
        for element in soup.find_all(string=True):
            if element.parent.name != "a":
                new_text = re.sub(self.url_regex, self._create_hyperlink, str(element))
                if new_text != str(element):
                    element.replace_with(BeautifulSoup(new_text, "html.parser"))
        text = str(soup)

        file.write_text(text, encoding="utf-8")

        tasks = []
        for attachment in attachments:
            img_url = f"{self.resource_base_url}{attachment['url']}"
            img_path = assets_path / attachment["filename"]
            tasks.append(self._download_file(await self.session, img_url, img_path))

        await asyncio.gather(*tasks)

    @staticmethod
    def convert_ranobe_content_to_html(
        content: list[dict], attachments: list[dict], assets_base: str = "assets"
    ) -> str:
        """
        Convert RanobeLib content from custom to HTML format

        :param content: The content in custom format
        :param attachments: Attachments list
        :param assets_base: Base path for assets in the HTML
        :return: The content converted to HTML format
        """
        soup = BeautifulSoup()
        for item in content:
            if item["type"] == "paragraph":
                p = soup.new_tag("p")
                for c in item.get("content", []):
                    if c["type"] == "text":
                        if marks := c.get("marks"):
                            match marks[0]["type"]:
                                case "bold":
                                    b = soup.new_tag("b")
                                    b.string = c["text"]
                                    p.append(b)
                                case "italic":
                                    i = soup.new_tag("i")
                                    i.string = c["text"]
                                    p.append(i)
                                case "underline":
                                    u = soup.new_tag("u")
                                    u.string = c["text"]
                                    p.append(u)
                                case _:
                                    logger.warning(
                                        "Unknown mark type: %s", marks[0]["type"]
                                    )
                                    p.append(c["text"])
                        else:
                            p.append(c["text"])
                    if c["type"] == "hardBreak":
                        br = soup.new_tag("br")
                        p.append(br)
                soup.append(p)
            elif item["type"] == "horizontalRule":
                hr = soup.new_tag("hr")
                soup.append(hr)
            elif item["type"] == "image":
                images = item["attrs"].get("images", [])
                for attachment in attachments:
                    for image in images:
                        if attachment["name"] == image["image"]:
                            img = soup.new_tag("img")
                            img["src"] = f"{assets_base}/{attachment['filename']}"
                            soup.append(img)
        return str(soup)

    @staticmethod
    def _create_hyperlink(match: re.Match) -> str:
        """
        Create a hyperlink HTML tag from a regex match object

        :param match: Regex match object containing the URL
        :return: HTML hyperlink tag
        """
        url = match.group(0)
        parsed_url = urllib.parse.urlparse(url)
        parsed_url = parsed_url._replace(path=urllib.parse.quote(parsed_url.path))
        return f'<a href="{parsed_url.geturl()}" target="_blank">{url}</a>'
