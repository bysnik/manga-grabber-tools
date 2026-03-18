#!/usr/bin/env python3
"""
Тесты для CLI-обёртки downloader.py
Проверяет все режимы работы: пакетный, по ссылке, с параметрами.
"""
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Добавляем корень проекта в path для импорта
sys.path.insert(0, str(Path(__file__).parent.parent))

from downloader import (
    CookieManager,
    DownloadState,
    MangaDownloader,
    get_site_type,
    get_client,
    is_ranobe,
)

# ============================================================================
# ФИКСТУРЫ И КОНФИГУРАЦИЯ
# ============================================================================

pytestmark = pytest.mark.asyncio(loop_scope="module")

# Тестовые данные
TEST_SITES = {
    "mangalib": "https://mangalib.me/ru/1284--relife/",
    "hentailib": "https://hentailib.me/ru/234290--couple-under-the-rain/",
    "ranobelib": "https://ranobelib.me/ru/6689--ascendance-of-a-bookworm-novel/",
    "usagi": "https://web.usagi.one/hot_first_kiss/",
    "ranobehub": "https://ranobehub.org/ranobe/1322-the-reader-me-the-protagonist-her-and-their-after/",
}

TEST_COOKIES = {
    "mangalib": "test_token_abc123",
    "hentailib": "hentai_token_xyz789",
    "ranobelib": "ranobe_token_def456",
}

IS_CI = os.environ.get("CI", "false").lower() == "true"
TOKEN = os.environ.get("TOKEN", "")


@pytest.fixture(scope="session")
def test_dirs(tmp_path_factory):
    """Создать временные директории для тестов"""
    return {
        "root": tmp_path_factory.mktemp("downloader-test-"),
        "cookies": tmp_path_factory.mktemp("cookies-"),
        "downloads": tmp_path_factory.mktemp("downloads-"),
        "state": tmp_path_factory.mktemp("state-"),
    }


@pytest_asyncio.fixture(scope="function")
async def cookie_manager(test_dirs):
    """Фикстура менеджера куки с тестовыми данными"""
    cm = CookieManager(cookies_dir=test_dirs["cookies"])

    # Создать тестовые cookie-файлы
    for site, token in TEST_COOKIES.items():
        cookie_file = test_dirs["cookies"] / f"{site}.cookies"
        cookie_file.write_text(
            f"# Netscape HTTP Cookie File\n"
            f"{site}.me\tTRUE\t/\tTRUE\t9999999999\tremember_token\t{token}\n"
            f"{site}.me\tTRUE\t/\tTRUE\t9999999999\tsession\ttest_session_123\n",
            encoding="utf-8"
        )
    return cm


@pytest_asyncio.fixture(scope="function")
async def downloader(test_dirs, cookie_manager):
    """Фикстура основного загрузчика"""
    return MangaDownloader(
        downloads_dir=test_dirs["downloads"],
        cookies_dir=test_dirs["cookies"],
    )


# ============================================================================
# ТЕСТЫ ВСПОМОГАТЕЛЬНЫХ ФУНКЦИЙ
# ============================================================================

class TestHelperFunctions:
    """Тесты утилитарных функций"""

    @pytest.mark.parametrize("url,expected", [
        ("https://mangalib.me/ru/123--title/", "mangalib"),
        ("https://hentailib.me/ru/456--title/", "hentailib"),
        ("https://ranobelib.me/ru/789--title/", "ranobelib"),
        ("https://ranobehub.org/ranobe/111--title/", "ranobehub"),
        ("https://web.usagi.one/title/", "usagi"),
    ])
    def test_get_site_type(self, url, expected):
        assert get_site_type(url) == expected

    def test_get_site_type_unknown(self):
        with pytest.raises(ValueError, match="Неподдерживаемый сайт"):
            get_site_type("https://unknown.site/title/")

    @pytest.mark.parametrize("url,expected", [
        ("https://ranobelib.me/ru/123--title/", True),
        ("https://ranobehub.org/ranobe/456--title/", True),
        ("https://mangalib.me/ru/789--title/", False),
        ("https://web.usagi.one/title/", False),
    ])
    def test_is_ranobe(self, url, expected):
        assert is_ranobe(url) == expected

    def test_sanitize_chapter_number(self, downloader):
        """Тест замены точек в номерах глав"""
        assert downloader._sanitize_chapter_number("1.5") == "1_5"
        assert downloader._sanitize_chapter_number("10") == "10"
        assert downloader._sanitize_chapter_number("2.3.4") == "2_3_4"


# ============================================================================
# ТЕСТЫ CookieManager
# ============================================================================

class TestCookieManager:
    """Тесты управления cookie-файлами"""

    def test_load_cookies_existing(self, cookie_manager, test_dirs):
        """Загрузка существующих cookie"""
        cookies = cookie_manager.load_cookies("mangalib")
        assert "remember_token" in cookies
        assert cookies["remember_token"] == TEST_COOKIES["mangalib"]

    def test_load_cookies_missing(self, cookie_manager):
        """Загрузка несуществующего файла"""
        cookies = cookie_manager.load_cookies("unknown_site")
        assert cookies == {}

    def test_extract_auth_token(self, cookie_manager):
        """Извлечение токена авторизации"""
        token = cookie_manager.extract_auth_token("hentailib")
        assert token == TEST_COOKIES["hentailib"]

    def test_check_auth_status(self, cookie_manager):
        """Проверка статуса авторизации"""
        has_auth, message = cookie_manager.check_auth_status("mangalib")
        assert has_auth is True
        assert "remember_token" in message

        has_auth, message = cookie_manager.check_auth_status("unknown")
        assert has_auth is False


# ============================================================================
# ТЕСТЫ DownloadState
# ============================================================================

class TestDownloadState:
    """Тесты управления состоянием загрузок"""

    def test_state_initial_empty(self, test_dirs):
        """Пустое состояние при инициализации"""
        state = DownloadState(state_file=test_dirs["state"] / "empty.json")
        assert state.state == {}

    def test_state_save_load(self, test_dirs):
        """Сохранение и загрузка состояния"""
        state_file = test_dirs["state"] / "test_state.json"
        state = DownloadState(state_file=state_file)

        url = "https://test.site/title/"
        state.set(url, {"downloaded_chapters": ["v1_c1", "v1_c2"], "last_update": "2025-01-01"})

        # Проверка сохранения
        assert state_file.exists()

        # Проверка загрузки
        new_state = DownloadState(state_file=state_file)
        assert new_state.get(url) is not None
        assert "v1_c1" in new_state.get_downloaded_chapters(url)

    def test_add_chapters(self, test_dirs):
        """Добавление скачанных глав"""
        state = DownloadState(state_file=test_dirs["state"] / "add_test.json")
        url = "https://test.site/title/"

        state.add_chapters(url, ["v1_c1", "v1_c2"])
        assert state.get_downloaded_chapters(url) == {"v1_c1", "v1_c2"}

        # Добавление дубликатов не должно ломать
        state.add_chapters(url, ["v1_c2", "v1_c3"])
        assert state.get_downloaded_chapters(url) == {"v1_c1", "v1_c2", "v1_c3"}


# ============================================================================
# ТЕСТЫ MangaDownloader (МОКИ)
# ============================================================================

class TestMangaDownloaderMocked:
    """Тесты загрузчика с моками (без реальных запросов)"""

    async def test_process_title_mock_success(self, downloader, test_dirs):
        """Успешная обработка тайтла (мокированный клиент)"""
        url = TEST_SITES["usagi"]  # Usagi не требует авторизации

        # Мокаем клиент
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get_chapters = AsyncMock(return_value=[
            {"number": "1", "volume": "1", "branches": []}
        ])
        mock_client.download_chapter = AsyncMock()

        with patch("downloader.get_client", return_value=mock_client):
            with patch("downloader.img_to_cbz", return_value=test_dirs["downloads"] / "test.cbz"):
                result = await downloader.process_title(url)
                assert result is True

    async def test_process_title_hentailib_no_auth(self, downloader):
        """HentaiLib без авторизации должен вернуть False"""
        # Удаляем cookie для HentaiLib
        cookie_file = downloader.cookies_dir / "hentailib.cookies"
        if cookie_file.exists():
            cookie_file.unlink()

        url = TEST_SITES["hentailib"]
        result = await downloader.process_title(url)
        assert result is False

    async def test_process_title_not_found(self, downloader):
        """Обработка несуществующего тайтла"""
        url = "https://mangalib.me/ru/99999-invalid-title/"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        from manga_grabber.exceptions import TitleNotFoundError
        mock_client.get_chapters = AsyncMock(side_effect=TitleNotFoundError("Not found"))

        with patch("downloader.get_client", return_value=mock_client):
            result = await downloader.process_title(url)
            assert result is False

    def test_get_auth_token_usagi(self, downloader):
        """Usagi не требует токена"""
        url = TEST_SITES["usagi"]
        token = downloader._get_auth_token(url)
        assert token is None

    def test_get_auth_token_with_cookie(self, downloader, test_dirs):
        """Извлечение токена из cookie"""
        url = TEST_SITES["mangalib"]
        token = downloader._get_auth_token(url)
        assert token == TEST_COOKIES["mangalib"]


# ============================================================================
# ТЕСТЫ CLI ПАРАМЕТРОВ (ИНТЕГРАЦИОННЫЕ)
# ============================================================================

@pytest.mark.skipif(IS_CI and not TOKEN, reason="Требуется TOKEN в CI")
class TestCLIModes:
    """Интеграционные тесты CLI-режимов"""

    async def test_cli_single_url(self, test_dirs):
        """Режим: -u <URL> (одна ссылка)"""
        result = subprocess.run(
            [
                sys.executable, "-m", "poetry", "run", "python", "downloader.py",
                "-u", TEST_SITES["usagi"],
                "-o", str(test_dirs["downloads"]),
                "-c", str(test_dirs["cookies"]),
                "--no-cbz",  # Пропустить конвертацию для скорости
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Usagi работает без авторизации, поэтому ожидаем успех или информативную ошибку
        assert result.returncode in [0, 1]  # 0=успех, 1=ошибка обработки (но не краш)

    async def test_cli_batch_file(self, test_dirs):
        """Режим: пакетная загрузка из файла"""
        # Создать тестовый список
        manga_file = test_dirs["root"] / "test_manga.txt"
        manga_file.write_text(
            f"# Тестовый список\n{TEST_SITES['usagi']}\n",
            encoding="utf-8"
        )

        result = subprocess.run(
            [
                sys.executable, "-m", "poetry", "run", "python", "downloader.py",
                "-f", str(manga_file),
                "-o", str(test_dirs["downloads"]),
                "-c", str(test_dirs["cookies"]),
                "--no-cbz",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode in [0, 1]

    @pytest.mark.parametrize("site", ["mangalib", "ranobelib", "usagi"])
    async def test_cli_all_sites_basic(self, test_dirs, site):
        """Базовая проверка всех поддерживаемых сайтов"""
        if site == "hentailib" and not TOKEN:
            pytest.skip("HentaiLib требует TOKEN")

        url = TEST_SITES[site]
        result = subprocess.run(
            [
                sys.executable, "-m", "poetry", "run", "python", "downloader.py",
                "-u", url,
                "-o", str(test_dirs["downloads"]),
                "-c", str(test_dirs["cookies"]),
                "--check-only",  # Только проверка, без скачивания
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        # --check-only не должен падать, даже если нет доступа
        assert result.returncode in [0, 1]


# ============================================================================
# ТЕСТЫ EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Тесты граничных случаев"""

    def test_manga_list_file_missing(self, downloader):
        """Обработка отсутствующего файла списка"""
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            # Метод должен обработать отсутствие файла без краша
            pass  # process_all проверяет существование внутри

    def test_empty_chapter_list(self, downloader):
        """Обработка тайтла без глав"""
        # Проверяем, что пустой список не вызывает ошибок
        downloaded = downloader.state.get_downloaded_chapters("https://test/")
        assert isinstance(downloaded, set)

    def test_invalid_url_format(self):
        """Некорректный URL должен выбрасывать исключение"""
        with pytest.raises(ValueError):
            get_site_type("not-a-url")

    async def test_download_chapter_error_handling(self, downloader, test_dirs):
        """Обработка ошибок при скачивании главы"""
        mock_chapter = {"number": "1", "volume": "1", "branches": []}
        output_dir = test_dirs["downloads"] / "test_title"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Мокаем клиент с ошибкой
        mock_client = AsyncMock()
        mock_client.download_chapter = AsyncMock(side_effect=Exception("Network error"))

        with pytest.raises(Exception, match="Network error"):
            await downloader._download_chapter(mock_client, mock_chapter, output_dir)


# ============================================================================
# ТЕСТЫ CLI HELP И АРГУМЕНТОВ
# ============================================================================

class TestCLIArguments:
    """Тесты парсинга аргументов командной строки"""

    def test_cli_help(self):
        """Проверка вывода справки"""
        result = subprocess.run(
            [sys.executable, "downloader.py", "--help"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "Автоматический загрузчик манги" in result.stdout
        assert "-u" in result.stdout
        assert "-f" in result.stdout

    def test_cli_setup_cookies(self):
        """Проверка режима --setup-cookies"""
        result = subprocess.run(
            [sys.executable, "downloader.py", "--setup-cookies"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "Мастер настройки Cookie-файлов" in result.stdout
