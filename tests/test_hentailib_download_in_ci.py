# tests/test_hentailib_download_in_ci.py
import os
import pytest
import pytest_asyncio
from pathlib import Path

from manga_grabber import mangalib
from manga_grabber.exceptions import TitleNotFoundError


TOKEN = os.environ.get("TOKEN")
# Тайтл, который точно существует и имеет хотя бы одну главу
TEST_TITLE = "234290--couple-under-the-rain"
MANGA_URL = f"https://hentailib.me/ru/{TEST_TITLE}/"


@pytest.mark.asyncio
async def test_download_hentailib_chapter_in_ci(tmp_path):
    """
    В CI окружении скачиваем первую главу и проверяем, что есть изображения.
    Если токен отсутствует, тест пропускается.
    """
    if not TOKEN:
        pytest.skip("TOKEN environment variable not set")

    async with mangalib.HentaiLib(MANGA_URL, token=TOKEN) as client:
        chapters = await client.get_chapters()
        assert chapters, "No chapters found"

        chapter = chapters[0]
        chapter_num = chapter["number"]
        volume = chapter["volume"]
        chapter_dir = tmp_path / f"vol{volume}_ch{chapter_num}"

        await client.download_chapter(chapter_num, volume, chapter_dir)

        # Проверяем, что папка не пуста и содержит хотя бы одно изображение
        files = list(chapter_dir.glob("*"))
        assert files, "No files downloaded"

        # Проверяем, что есть хотя бы один файл с ожидаемым расширением (png/jpg/jpeg)
        images = [f for f in files if f.suffix.lower() in {'.png', '.jpg', '.jpeg'}]
        assert images, f"No images found, files: {[f.name for f in files]}"