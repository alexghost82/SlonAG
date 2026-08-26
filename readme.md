# Slon — AI Assistant Runtime Engine

**Slon** — кроссплатформенный AI-ассистент с голосовым интерфейсом, компьютерным контролем и набором инструментов для автоматизации. Агрегирует LLM-провайдеров (Google Gemini, OpenAI, локальные модели), управляет задачами через планировщик и предоставляет UI на PyQt6.

## Возможности

- **Многопровайдерность** — Gemini, OpenAI, Ollama, LlamaCPP через единый интерфейс `providers/`
- **Голосовой ввод/вывод** — STT (Whisper) и TTS (Piper) для hands-free взаимодействия
- **Компьютерный контроль** — управление окнами, скриншоты, клавиатура, мышь, буфер обмена (pyautogui, mss, cv2)
- **Инструменты (actions/)** — веб-поиск, погода, браузер, YouTube, файловый менеджер, напоминания, отправка сообщений, разработка ПО
- **Планировщик задач** — `agent/planner.py` + `task_queue` для приоритизации и async-выполнения
- **Память** — долговременное хранилище через `memory/memory_manager.py`
- **Сессии** — менеджер сессий с транскриптами и миграциями (`sessions/`)
- **Gateway** — шлюз авторизации, approval-проверок, веб-сокетов и аутентификации
- **Live Video** — стриминг камеры через сервер (`server/live_video.py`)
- **Политики** — управление стоимостью, fallback-стратегии (`policies/`)
- **i18n** — локализация (ru/en) через `localization/`
- **Server** — REST + WebSocket API, TLS, QR-спаривание, Bonjour-обнаружение

## Архитектура

```
main.py                  ← Точка входа, инициализация UI и агента
ui.py                    ← PyQt6 GUI (чат, лог, ввод, настройки)
├── actions/             ← Инструменты (web_search, weather, browser, ... )
├── agent/               ← Планировщик, executor, error_handler, steering
├── config/              ← Схема настроек, секреты, schema
├── gateway/             ← Шлюз: auth, bootstrap, router, websocket, approvals
├── i18n/                ← JSON-словари локализации (ru, en)
├── localization/        ← Python i18n translator, scan, locale catalogs
├── mark/                ← Runtime bridge, desktop control plane
├── memory/              ← Долговременная память, config manager
├── orchestration/       ← Оркестрация подзадач
├── policies/            ← Cost control, fallback
├── providers/           ← Абстракция провайдеров (OpenAI compatible, router, capabilities)
├── runtime/             ← Audio pipeline, lifecycle events, benchmark
├── server/              ← HTTP/WS API, TLS, QR, bonjour, live_video, pairing
├── sessions/            ← Сессии, транскрипты, store, migrations
├── speech/              ← STT (Whisper), TTS (Piper), playback
├── tests/               ← Pytest-тесты
└── core/prompt.txt      ← Системный промпт ассистента
```

## Установка

### Системные требования

- **Python 3.11** или 3.12
- **macOS** 12+, **Ubuntu** 20.04+, или **Windows** 10+
- Оперативная память: ≥ 4 ГБ (рекомендуется 8 ГБ)
- Для локальных моделей (Ollama/LlamaCPP): GPU с VRAM ≥ 4 ГБ

### macOS

```bash
# 1. Установите Python 3.11+ (если нет)
brew install python@3.12

# 2. Клонируйте репозиторий
git clone https://github.com/alexghost82/SlonAG.git
cd SlonAG

# 3. Создайте виртуальное окружение
python3.12 -m venv .venv
source .venv/bin/activate

# 4. Установите зависимости
python setup.py
# или вручную:
# pip install -r requirements-macos.txt
# python -m playwright install

# 5. Настройте API-ключ (или через GUI → Settings)
# См. ниже «Настройка»
```

### Ubuntu (Linux)

```bash
# 1. Установите Python 3.11+ и зависимости системы
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip \
    build-essential alsa-utils libasound2-dev \
    portaudio19-dev libx11-dev libxrandr-dev \
    libgtk-3-dev

# 2. Клонируйте репозиторий
git clone https://github.com/alexghost82/SlonAG.git
cd SlonAG

# 3. Создайте виртуальное окружение
python3.11 -m venv .venv
source .venv/bin/activate

# 4. Установите зависимости
python setup.py
# или вручную:
# pip install -r requirements-linux.txt
# python -m playwright install

# 5. Настройте API-ключ (или через GUI → Settings)
```

### Windows

```powershell
# 1. Установите Python 3.11+ с сайта python.org (галочка «Add to PATH»)

# 2. Клонируйте репозиторий
git clone https://github.com/alexghost82/SlonAG.git
cd SlonAG

# 3. Создайте виртуальное окрушение
python -m venv .venv
.venv\Scripts\activate

# 4. Установите зависимости
python setup.py
# или вручную:
# pip install -r requirements-windows.txt
# python -m playwright install

# 5. Настройте API-ключ (или через GUI → Settings)
```

## Настройка

### API-ключи

1. **Google Gemini:** получите ключ на [ai.google.dev](https://ai.google.dev) → вставьте в GUI Settings → `gemini_api_key`.
2. **OpenAI:** получите ключ на [platform.openai.com](https://platform.openai.com) → вставьте в GUI Settings → `openai_api_key`.
3. **Другие провайдеры:** ключи через Settings (например, `ollama_api_key` для локальных моделей).

Также можно создать файл `config/api_keys.json` вручную:

```json
{
  "gemini_api_key": "YOUR_GEMINI_KEY",
  "openai_api_key": "YOUR_OPENAI_KEY",
  "ollama_api_key": ""
}
```

### Выбор провайдера и модели

В GUI откройте **Settings** → выберите провайдер (Gemini, OpenAI, Ollama, LlamaCPP) и модель. Для локальных моделей через Ollama убедитесь, что `ollama serve` запущен.

### Локальные модели

- **Ollama:** `ollama pull <model_name>` (например, `ollama pull llama3.2`), затем выберите провайдер Ollama в настройках.
- **LlamaCPP:** требует скомпилированной библиотеки llama-cpp-python.

## Запуск

### Через GUI (рекомендуется)

```bash
python main.py
```

Запускает PyQt6-приложение с чат-интерфейсом, логами, настройками и голосовым управлением.

### Через сервер (API)

```bash
python -m server
```

Запускает HTTP + WebSocket сервер на локальном порту. Поддерживает TLS и QR-спаривание.

### Тесты

```bash
pytest tests/
```

### Линтинг и проверки

```bash
# Ruff (тесты)
ruff check tests/

# Mypy (типизация)
mypy .
```

## Конфигурация

Настройки хранятся в `config/settings.py` и загружаются через `load_settings()`. Основные параметры:

| Параметр         | Описание                          | По умолчанию        |
|------------------|-----------------------------------|---------------------|
| `provider_id`    | ID провайдера (gemini/openai/...) | `gemini`            |
| `model_id`       | Имя модели                        | Gemini 2.5 Flash    |
| `language`       | Язык ответа (ru/en)               | `ru`                |
| `tts_enabled`    | Включить синтез речи              | `true`              |
| `stt_enabled`    | Включить распознавание речи       | `true`              |

## Лицензия

CC BY-NC 4.0 — некоммерческое использование с указанием авторства. См. `THIRD_PARTY_LICENSES.md` для зависимостей.
