# 📚 Manga Grabber CLI

> Простой CLI-загрузчик манги и ранобэ для пакетного скачивания.
> **Форк + обёртка** над [manga-grabber](https://github.com/qwertyadrian/manga-grabber) от Adrian Polyakov.

---

## 🚀 Быстрый старт

У Вас уже должен быть установлен Python 3 и git.

```bash
# 1. Клонировать репо
git clone git@github.com:bysnik/manga-grabber-tools.git && cd manga-grabber-tools

# 2. Установить Poetry (если нет)
pip3 install pipx
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
pipx install poetry

# 3. Установить зависимости
poetry install
```

---

## 🍪 Настройка (один раз)

```bash
# Создать папку для куки
mkdir -p cookies
```

Положите в `cookies/` файлы в формате **Netscape**:
| Файл | Сайт | Авторизация |
|------|------|-------------|
| `mangalib.cookies` | mangalib.me | рекомендуется |
| `ranobelib.cookies` | ranobelib.me | рекомендуется |
| `ranobehub.cookies` | ranobehub.org | опционально |
| `usagi.cookies` | web.usagi.one | не требуется |

Создать файл `manga.txt` со ссылками:
```txt
# manga.txt — одна ссылка на строку, # для комментариев
https://mangalib.me/ru/manga/12345--title-name
https://ranobelib.me/ru/1234--title-name/
```

---

## ▶️ Запуск

```bash
# Скачать всё из manga.txt
poetry run python downloader.py

# Скачать конкретную ссылку
poetry run python downloader.py -u "https://..."

# Запустить мастер настройки куки
poetry run python downloader.py --setup-cookies

# Полная справка
poetry run python downloader.py --help
```

---

## 📦 Опции CLI

| Опция | Описание |
|-------|----------|
| `-f, --file` | Файл со списком ссылок (по умолчанию: `manga.txt`) |
| `-u, --url` | Скачать одну ссылку (можно указать несколько раз) |
| `-o, --output` | Папка для загрузок |
| `-c, --cookies` | Папка с cookie-файлами |
| `--check-only` | Только проверить новые главы, без скачивания |
| `--no-cbz` | Не конвертировать в CBZ (скачать только изображения) |
| `--setup-cookies` | Запустить интерактивный мастер настройки куки |

---

## 🔄 Как это работает

1. Скрипт читает `manga.txt` или URL из `-u`
2. Автоматически определяет сайт и извлекает токен авторизации из соответствующего `.cookies`-файла
3. Сверяется с `download_state.json` — скачивает только новые главы
4. Сохраняет мангу в `volX_chY/`, затем конвертирует в `.cbz` (кроме ранобэ)
5. Обновляет состояние — при повторном запуске продолжит с места остановки

---

## ⚠️ Важно

- 📁 Папка загрузок по умолчанию: `./` (измените в `downloader.py`, строка 22)
- 🔄 Куки живут ~30 дней — при ошибках 404 обновите `*.cookies`
- 📦 Состояние хранится в `download_state.json` — не удаляйте, если хотите докачивать

---

## 🛠 Проблемы?

```bash
# Переустановить зависимости
poetry install --no-cache

# Сбросить состояние (начать заново)
rm download_state.json

# Очистить кэш Poetry
poetry cache clear . --all
```

---

> 📜 Лицензия: **MIT**
> Оригинал: [manga-grabber](https://github.com/qwertyadrian/manga-grabber) by Adrian Polyakov
