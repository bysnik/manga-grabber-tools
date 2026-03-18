#!/usr/bin/env python3
"""
Автоматический загрузчик манги с автоматическим извлечением токенов из Cookie.
Каждый сайт использует свои cookie-файлы в формате Netscape.
Токены авторизации извлекаются автоматически из cookie.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse
from dataclasses import dataclass
from manga_grabber import mangalib, usagi, ranobehub
from manga_grabber.export import img_to_cbz, download_title
from manga_grabber.exceptions import TitleNotFoundError

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================
DOWNLOADS_DIR = Path("./")
COOKIES_DIR = Path("./cookies")
STATE_FILE = Path("./download_state.json")
MANGA_LIST_FILE = Path("./manga.txt")

# Имена cookie для авторизации на каждом сайте
AUTH_COOKIE_NAMES = {
    "mangalib": ["remember_token", "session", "access_token"],
    "hentailib": ["remember_token", "session", "access_token"],
    "ranobelib": ["remember_token", "session", "access_token"],
    "ranobehub": ["session", "token", "remember_token"],
    "usagi": [],  # Не требует авторизации
}

# ============================================================================
# МЕНЕДЖЕР COOKIE
# ============================================================================
@dataclass
class CookieEntry:
    """Одна запись cookie"""
    domain: str
    flag: str
    path: str
    secure: str
    expiration: str
    name: str
    value: str

class CookieManager:
    """Управление Cookie-файлами в формате Netscape"""
    def __init__(self, cookies_dir: Path = COOKIES_DIR):
        self.cookies_dir = cookies_dir
        self.cookies_dir.mkdir(parents=True, exist_ok=True)
        self._cookies: Dict[str, Dict[str, str]] = {}

    def _get_cookie_file(self, site_type: str) -> Path:
        """Получить путь к файлу cookie для сайта"""
        cookie_map = {
            "mangalib": "mangalib.cookies",
            "hentailib": "hentailib.cookies",
            "ranobelib": "ranobelib.cookies",
            "usagi": "usagi.cookies",
            "ranobehub": "ranobehub.cookies",
        }
        filename = cookie_map.get(site_type, f"{site_type}.cookies")
        return self.cookies_dir / filename

    def load_cookies(self, site_type: str) -> Dict[str, str]:
        """
        Загрузить все cookie из файла в словарь {name: value}
        Формат файла Netscape:
        domain\tflag\tpath\tsecure\texpiration\tname\tvalue
        """
        if site_type in self._cookies:
            return self._cookies[site_type]

        cookie_file = self._get_cookie_file(site_type)
        if not cookie_file.exists():
            print(f"⚠️  Cookie-файл не найден: {cookie_file}")
            return {}

        cookies = {}
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Пропустить комментарии и пустые строки
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        entry = CookieEntry(
                            domain=parts[0],
                            flag=parts[1],
                            path=parts[2],
                            secure=parts[3],
                            expiration=parts[4],
                            name=parts[5],
                            value=parts[6]
                        )
                        cookies[entry.name] = entry.value

            self._cookies[site_type] = cookies
            if cookies:
                print(f"✅ Загружено {len(cookies)} cookie для {site_type}")
            else:
                print(f"⚠️  Cookie-файл пуст: {cookie_file}")
        except Exception as e:
            print(f"❌ Ошибка чтения cookie: {e}")

        return cookies

    def extract_auth_token(self, site_type: str) -> Optional[str]:
        """
        Извлечь токен авторизации из cookie для сайта
        :param site_type: тип сайта (mangalib, hentailib, etc.)
        :return: токен авторизации или None
        """
        cookies = self.load_cookies(site_type)
        if not cookies:
            return None

        # Ищем подходящее имя cookie для авторизации
        auth_names = AUTH_COOKIE_NAMES.get(site_type, [])
        for auth_name in auth_names:
            if auth_name in cookies:
                token = cookies[auth_name]
                print(f"🔑 Найден токен авторизации ({auth_name}): {token[:20]}...")
                return token

        # Если не нашли конкретное имя, возвращаем первый подозрительный токен
        for name, value in cookies.items():
            if len(value) > 20 and not value.startswith('{'):
                print(f"🔑 Предполагаемый токен ({name}): {value[:20]}...")
                return value

        return None

    def get_all_cookies_for_url(self, url: str) -> Dict[str, str]:
        """Получить все cookie для конкретного URL"""
        site_type = get_site_type(url)
        return self.load_cookies(site_type)

    def check_auth_status(self, site_type: str) -> Tuple[bool, str]:
        """
        Проверить статус авторизации для сайта
        :return: (есть ли авторизация, сообщение)
        """
        cookies = self.load_cookies(site_type)
        if not cookies:
            return False, "Cookie-файл не найден"

        auth_names = AUTH_COOKIE_NAMES.get(site_type, [])
        for auth_name in auth_names:
            if auth_name in cookies:
                return True, f"Найден {auth_name}"

        # Проверка на наличие любых cookie
        if len(cookies) > 0:
            return True, f"Загружено {len(cookies)} cookie"

        return False, "Нет cookie для авторизации"

# ============================================================================
# СОСТОЯНИЕ ЗАГРУЗОК
# ============================================================================
class DownloadState:
    """Управление состоянием загрузок (что уже скачано)"""
    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self.state: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        """Загрузить состояние из файла"""
        if self.state_file.exists():
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save(self):
        """Сохранить состояние в файл"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def get(self, url: str) -> Optional[dict]:
        """Получить информацию о загруженной манге"""
        return self.state.get(url)

    def set(self, url: str, info: dict):
        """Обновить информацию о манге"""
        self.state[url] = info
        self.save()

    def get_downloaded_chapters(self, url: str) -> set:
        """Получить множество уже скачанных глав"""
        info = self.get(url)
        if not info:
            return set()
        return set(info.get("downloaded_chapters", []))

    def add_chapters(self, url: str, chapters: List[str]):
        """Добавить скачанные главы в состояние"""
        info = self.get(url) or {"downloaded_chapters": [], "last_update": None}
        existing = set(info["downloaded_chapters"])
        existing.update(chapters)
        info["downloaded_chapters"] = sorted(list(existing))
        info["last_update"] = datetime.now().isoformat()
        self.set(url, info)

# ============================================================================
# ОПРЕДЕЛЕНИЕ ТИПА САЙТА
# ============================================================================
def get_site_type(url: str) -> str:
    """Определить тип сайта по URL"""
    parsed = urlparse(url)
    domain = parsed.netloc
    if "mangalib.me" in domain:
        return "mangalib"
    elif "hentailib.me" in domain:
        return "hentailib"
    elif "ranobelib.me" in domain:
        return "ranobelib"
    elif "ranobehub.org" in domain:
        return "ranobehub"
    elif "web.usagi.one" in domain:
        return "usagi"
    else:
        raise ValueError(f"Неподдерживаемый сайт: {domain}")

def get_client(url: str, token: str = ""):
    """Создать клиент для соответствующего сайта"""
    site_type = get_site_type(url)
    if site_type == "mangalib":
        return mangalib.MangaLib(url, token=token)
    elif site_type == "hentailib":
        return mangalib.HentaiLib(url, token=token)
    elif site_type == "ranobelib":
        return mangalib.RanobeLib(url, token=token)
    elif site_type == "ranobehub":
        return ranobehub.RanobeHub(url, token=token)
    elif site_type == "usagi":
        return usagi.UsagiOne(url)
    else:
        raise ValueError(f"Неизвестный тип сайта: {site_type}")

def is_ranobe(url: str) -> bool:
    """Проверить, является ли ссылка на ранобэ"""
    domain = urlparse(url).netloc
    return "ranobelib" in domain or "ranobehub" in domain

# ============================================================================
# ЗАГРУЗЧИК
# ============================================================================
class MangaDownloader:
    """Основной класс загрузчика с автоматическим извлечением токенов из Cookie"""
    def __init__(
        self,
        downloads_dir: Path = DOWNLOADS_DIR,
        cookies_dir: Path = COOKIES_DIR,
    ):
        self.downloads_dir = downloads_dir
        self.cookies_dir = cookies_dir
        self.state = DownloadState()
        self.cookie_manager = CookieManager(cookies_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_chapter_number(self, chapter_num) -> str:
        """Заменить точки в номере главы на подчёркивания для имени файла"""
        return str(chapter_num).replace('.', '_')

    def _get_title_name(self, url: str) -> str:
        """Извлечь имя тайтла из URL"""
        path = urlparse(url).path.strip('/')
        parts = path.split('/')
        for part in reversed(parts):
            if part and '--' in part:
                return part
        return path.replace('/', '_')

    def _get_output_dir(self, url: str) -> Path:
        """Получить директорию для загрузки тайтла"""
        title_name = self._get_title_name(url)
        return self.downloads_dir / title_name

    def _get_auth_token(self, url: str) -> Optional[str]:
        """
        Автоматически извлечь токен авторизации из cookie для сайта
        :param url: URL манги
        :return: токен или None
        """
        site_type = get_site_type(url)
        # Usagi не требует авторизации
        if site_type == "usagi":
            return None
        # Извлечь токен из cookie
        token = self.cookie_manager.extract_auth_token(site_type)
        if token:
            print(f"✅ Авторизация: {site_type} (токен найден)")
        else:
            print(f"⚠️  Нет авторизации: {site_type}")
        return token

    def _check_auth_requirements(self, url: str) -> bool:
        """
        Проверить требования к авторизации для сайта
        :return: True если можно продолжать
        """
        site_type = get_site_type(url)
        # Usagi не требует авторизации
        if site_type == "usagi":
            return True

        # HentaiLib требует обязательной авторизации
        if site_type == "hentailib":
            has_auth, message = self.cookie_manager.check_auth_status(site_type)
            if not has_auth:
                print(f"❌ HentaiLib требует авторизации!")
                print(f"💡 Добавьте cookie-файл: {self.cookies_dir / f'{site_type}.cookies'}")
                print(f"💡 Экспортируйте cookie из браузера после входа в аккаунт")
                return False
            else:
                print(f"✅ HentaiLib: {message}")
                return True

        # Остальные сайты работают без авторизации, но с ней лучше
        has_auth, message = self.cookie_manager.check_auth_status(site_type)
        if has_auth:
            print(f"✅ {site_type}: {message}")
        else:
            print(f"⚠️  {site_type}: работает без авторизации, но могут быть ограничения")
        return True

    async def _download_chapter(self, client, chapter: dict, output_dir: Path, is_ranobe: bool = False):
        """Скачать одну главу"""
        chapter_num = chapter["number"]
        volume = chapter["volume"]

        # Папка для главы
        if is_ranobe:
            chapter_dir = output_dir / f"volume_{volume}"
        else:
            # 🔥 ИСПРАВЛЕНО: используем sanitize для номера главы
            chapter_dir = output_dir / f"vol{volume}_ch{self._sanitize_chapter_number(chapter_num)}"

        # Проверка ветки перевода
        branch_id = None
        if chapter.get("branches"):
            branch_id = chapter["branches"][0].get("branch_id")

        # Скачивание
        try:
            if branch_id and "usagi" in str(type(client)).lower():
                await client.download_chapter(chapter_num, volume, chapter_dir, branch_id)
            else:
                await client.download_chapter(chapter_num, volume, chapter_dir)
            return chapter_dir
        except Exception as e:
            error_msg = str(e).lower()
            if "404" in error_msg or "not found" in error_msg:
                print(f"    ⚠️  Возможно требуется авторизация")
                site_type = get_site_type(str(client))
                print(f"    💡 Проверьте cookie-файл: {self.cookies_dir / f'{site_type}.cookies'}")
            raise

    async def _convert_to_cbz(self, chapter_dir: Path) -> Optional[Path]:
        """Конвертировать главу в CBZ"""
        if not chapter_dir.exists():
            return None

        # Проверка, есть ли изображения
        images = list(chapter_dir.glob("*.jpg")) + \
                 list(chapter_dir.glob("*.png")) + \
                 list(chapter_dir.glob("*.jpeg"))
        if not images:
            return None

        try:
            # 🔥 ВАЖНО: передаём Path, а не str!
            result = img_to_cbz(chapter_dir)
            # Нормализуем результат в Path
            return Path(result) if isinstance(result, str) else result
        except Exception as e:
            print(f"⚠️  Ошибка конвертации {chapter_dir}: {e}")
            return None

    async def process_title(self, url: str) -> bool:
        """Обработать один тайтл"""
        print(f"\n{'='*60}")
        print(f"📖 Обработка: {url}")
        print(f"{'='*60}")

        try:
            site_type = get_site_type(url)
            print(f"🌐 Сайт: {site_type}")

            is_ranobe_flag = is_ranobe(url)
            if is_ranobe_flag:
                print("📚 Тип: Ранобэ (HTML)")
            else:
                print("📚 Тип: Манга (Изображения)")

            # Проверка авторизации
            if not self._check_auth_requirements(url):
                return False

            # Автоматическое извлечение токена из cookie
            token = self._get_auth_token(url)

            output_dir = self._get_output_dir(url)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Получить уже скачанные главы
            downloaded = self.state.get_downloaded_chapters(url)
            print(f"📦 Уже скачано глав: {len(downloaded)}")

            # Подключение к сайту
            async with get_client(url, token) as client:
                # Получить список глав
                chapters = await client.get_chapters()
                if not chapters:
                    print("⚠️  Нет доступных глав")
                    return False

                print(f"📑 Всего глав доступно: {len(chapters)}")

                # Определить новые главы
                new_chapters = []
                for chapter in chapters:
                    # 🔥 ИСПРАВЛЕНО: используем sanitize для chapter_id
                    chapter_id = f"v{chapter['volume']}_c{self._sanitize_chapter_number(chapter['number'])}"
                    if chapter_id not in downloaded:
                        new_chapters.append(chapter)

                if not new_chapters:
                    print("✅ Нет новых глав")
                    return True

                print(f"🆕 Новых глав: {len(new_chapters)}")

                # Скачать новые главы
                downloaded_chapters = []
                for i, chapter in enumerate(new_chapters, 1):
                    chapter_num = chapter["number"]
                    volume = chapter["volume"]
                    # 🔥 ИСПРАВЛЕНО: используем sanitize для chapter_id
                    chapter_id = f"v{volume}_c{self._sanitize_chapter_number(chapter_num)}"

                    print(f"\n[{i}/{len(new_chapters)}] Глава {chapter_num} (Том {volume})")

                    try:
                        chapter_dir = await self._download_chapter(
                            client, chapter, output_dir, is_ranobe_flag
                        )

                        # Конвертация в CBZ (только для манги)
                        if not is_ranobe_flag:
                            cbz_path = await self._convert_to_cbz(chapter_dir)
                            if cbz_path:
                                print(f"    ✅ CBZ: {cbz_path.name}")

                        downloaded_chapters.append(chapter_id)
                        print(f"    ✅ Скачано")

                    except Exception as e:
                        print(f"    ❌ Ошибка: {e}")
                        continue

                # Обновить состояние
                if downloaded_chapters:
                    self.state.add_chapters(url, downloaded_chapters)
                    print(f"\n💾 Состояние сохранено")

                return len(downloaded_chapters) > 0

        except TitleNotFoundError:
            print(f"❌ Тайтл не найден")
            return False
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def process_all(self, manga_list_file: Path = MANGA_LIST_FILE):
        """Обработать все тайтлы из файла"""
        if not manga_list_file.exists():
            print(f"❌ Файл {manga_list_file} не найден")
            return

        # Читать список манги
        with open(manga_list_file, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        print(f"📋 Найдено тайтлов: {len(urls)}")
        print(f"📁 Папка загрузок: {self.downloads_dir.absolute()}")
        print(f"🍪 Папка cookie: {self.cookies_dir.absolute()}")

        # Проверка наличия cookie
        print(f"\n📋 Статус cookie-файлов:")
        for site in ["mangalib", "hentailib", "ranobelib", "usagi", "ranobehub"]:
            cookie_file = self.cookies_dir / f"{site}.cookies"
            has_auth, message = self.cookie_manager.check_auth_status(site)
            status = "✅" if has_auth else "❌"
            print(f"  {status} {site}.cookies - {message}")

        # Обработать каждый тайтл
        success = 0
        failed = 0
        for i, url in enumerate(urls, 1):
            print(f"\n{'#'*60}")
            print(f"#{i}/{len(urls)}")
            print(f"{'#'*60}")

            if await self.process_title(url):
                success += 1
            else:
                failed += 1

            # Небольшая пауза между запросами
            if i < len(urls):
                await asyncio.sleep(1)

        # Итоги
        print(f"\n{'='*60}")
        print(f"🎉 Завершено!")
        print(f"{'='*60}")
        print(f"✅ Успешно: {success}")
        print(f"❌ Ошибки: {failed}")
        print(f"📁 Загрузки: {self.downloads_dir.absolute()}")

# ============================================================================
# CLI ИНТЕРФЕЙС
# ============================================================================
async def main():
    """Точка входа"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Автоматический загрузчик манги с извлечением токенов из Cookie",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python downloader.py                          # Загрузить из manga.txt
  python downloader.py -f my_list.txt           # Загрузить из другого файла
  python downloader.py -u "https://..."         # Загрузить одну ссылку
  python downloader.py --setup-cookies          # Мастер настройки cookie

Авторизация:
  - Токены автоматически извлекаются из cookie-файлов
  - Каждый сайт использует свой cookie-файл в папке cookies/
  - HentaiLib требует обязательной авторизации!

Как экспортировать cookie:
  1. Установите расширение для браузера:
     - Chrome: "Get cookies.txt LOCALLY" или "EditThisCookie"
     - Firefox: "cookies.txt"
  2. Зайдите на сайт и авторизуйтесь
  3. Экспортируйте cookie в формате Netscape
  4. Сохраните в папку cookies/ с именем {сайт}.cookies
        """
    )
    parser.add_argument(
        "-f", "--file",
        type=Path,
        default=MANGA_LIST_FILE,
        help=f"Файл со списком манги (по умолчанию: {MANGA_LIST_FILE})"
    )
    parser.add_argument(
        "-u", "--url",
        type=str,
        action="append",
        help="URL манги (можно указать несколько)"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=DOWNLOADS_DIR,
        help=f"Папка для загрузок (по умолчанию: {DOWNLOADS_DIR})"
    )
    parser.add_argument(
        "-c", "--cookies",
        type=Path,
        default=COOKIES_DIR,
        help=f"Папка для cookie-файлов (по умолчанию: {COOKIES_DIR})"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Только проверить наличие новых глав (без скачивания)"
    )
    parser.add_argument(
        "--no-cbz",
        action="store_true",
        help="Не конвертировать в CBZ"
    )
    parser.add_argument(
        "--setup-cookies",
        action="store_true",
        help="Запустить мастер настройки cookie-файлов"
    )

    args = parser.parse_args()

    # Мастер настройки cookie
    if args.setup_cookies:
        await setup_cookies_wizard(args.cookies)
        return

    # Создать загрузчик
    downloader = MangaDownloader(
        downloads_dir=args.output,
        cookies_dir=args.cookies,
    )

    # Если указаны URL напрямую
    if args.url:
        for url in args.url:
            await downloader.process_title(url)
    else:
        # Загрузить из файла
        await downloader.process_all(args.file)

async def setup_cookies_wizard(cookies_dir: Path):
    """Мастер настройки cookie-файлов"""
    print("\n" + "="*60)
    print("🍪 Мастер настройки Cookie-файлов")
    print("="*60)

    cookies_dir.mkdir(parents=True, exist_ok=True)

    sites = {
        "mangalib": {
            "name": "MangaLib",
            "domain": "mangalib.me",
            "required": False,
            "url": "https://mangalib.me/login",
            "cookie_names": "remember_token, session"
        },
        "hentailib": {
            "name": "HentaiLib",
            "domain": "hentailib.me",
            "required": True,
            "url": "https://hentailib.me/login",
            "cookie_names": "remember_token"
        },
        "ranobelib": {
            "name": "RanobeLib",
            "domain": "ranobelib.me",
            "required": False,
            "url": "https://ranobelib.me/login",
            "cookie_names": "remember_token, session"
        },
        "usagi": {
            "name": "Usagi",
            "domain": "web.usagi.one",
            "required": False,
            "url": "https://web.usagi.one",
            "cookie_names": "не требуется"
        },
        "ranobehub": {
            "name": "RanobeHub",
            "domain": "ranobehub.org",
            "required": False,
            "url": "https://ranobehub.org/login",
            "cookie_names": "session, token"
        },
    }

    print("\n📋 Статус cookie-файлов:")
    for site_id, info in sites.items():
        cookie_file = cookies_dir / f"{site_id}.cookies"
        exists = cookie_file.exists()
        status = "✅" if exists else "❌"
        req = "⚠️  ОБЯЗАТЕЛЬНО" if info["required"] else ""
        print(f"\n{status} {info['name']} {req}")
        print(f"   Файл: {cookie_file}")
        print(f"   Домен: {info['domain']}")
        print(f"   Cookie: {info['cookie_names']}")
        print(f"   Войти: {info['url']}")

    print("\n" + "="*60)
    print("📝 Инструкция по экспорту cookie:")
    print("="*60)
    print("""
1. Установите расширение для браузера:
   • Chrome: "Get cookies.txt LOCALLY"
     https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc
   • Firefox: "cookies.txt"
     https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/

2. Зайдите на сайт (например, hentailib.me) и авторизуйтесь

3. Нажмите на расширение и экспортируйте cookie:
   • Выберите формат: Netscape
   • Сохраните файл

4. Переименуйте файл в {сайт}.cookies:
   • mangalib.cookies
   • hentailib.cookies
   • ranobelib.cookies
   • ranobehub.cookies

5. Поместите файл в папку: {cookies_dir}

6. Запустите загрузчик:
   python downloader.py
    """)

    print("\n💡 Важные заметки:")
    print("   • HentaiLib требует обязательной авторизации!")
    print("   • Cookie имеют срок действия (обычно 30 дней)")
    print("   • При ошибках 404 обновите cookie-файлы")
    print("   • Токены автоматически извлекаются из cookie")
    print("="*60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Прервано пользователем")
        sys.exit(0)
