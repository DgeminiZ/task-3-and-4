# research-stand — WebGL-рендеринг в PWA при ограниченной сети

Воспроизводимый экспериментальный стенд для ВКР по темам:

1. «Исследование методов ускорения рендеринга WebGL графики для формирования рекомендаций для разработчиков».
2. «Исследование производительности и пользовательского опыта прогрессивных веб-приложений (PWA) в условиях ограниченного доступа к сети».

Обе темы исследуются на одном объекте: PWA с WebGL-сценой. Первая тема задаёт фактор
`render` (метод рендеринга), вторая — факторы `transport` и `mode` (профиль сети и режим
кеширования service worker). Метрики тоже общие: частота кадров и длительность кадра
для темы 1, LCP/TTFB/объём передачи/офлайн-доступность для темы 2.

## Исследовательские вопросы

- **RQ1.** Даёт ли переход от отдельных мешей к `InstancedMesh` и к LOD статистически
  значимый прирост FPS при одинаковой сцене, разрешении и железе?
- **RQ2.** Сокращает ли service worker время загрузки и объём передачи при повторном
  визите в сети 3G, и какова цена первого визита?
- **RQ3 (контроль).** Доступно ли приложение офлайн только при активном service worker?

Гипотезы, уровни факторов и критерии успеха зафиксированы в `docs/pr3-report.md`.

## Требования

| Что | Версия | Зачем |
|---|---|---|
| Docker Engine / Docker Desktop | 4.30+ (Compose v2) | основной режим: SUT, runner и analysis в контейнерах |
| Python | 3.12 | оркестратор и анализ (локальный режим и запуск `make`) |
| Playwright | 1.63.0 | браузерный раннер |
| Chromium | 153.0.8010.12 (образ `mcr.microsoft.com/playwright/python:v1.63.0-noble`) | исполнение сценария |
| nginx | 1.27.3-alpine | раздача SUT |
| three.js | r170 (`0.170.0`, файл `three.module.min.js`) | WebGL-рендеринг SUT |

Версия Chromium фиксируется образом раннера, версия three.js — файлом в `sut/public/vendor`,
версия Python-зависимостей анализа — `analysis/requirements.txt`, зависимости раннера —
`runner/requirements.txt`. Полный перечень пишется в манифест каждого прогона.

## Быстрый старт (Docker)

```bash
make up          # поднять SUT
make smoke       # проверить, что стенд измеряет
make experiment  # 110 прогонов по плану из configs/experiment.yaml
make analyze     # статистика и графики в results/
make down
```

Windows (PowerShell, без make):

```powershell
.\run.ps1 up
.\run.ps1 smoke
.\run.ps1 experiment
.\run.ps1 analyze
.\run.ps1 down
```

## Быстрый старт без Docker

Локальный режим поднимает статический сервер и запускает тот же браузерный раннер:

```bash
python -m pip install -r runner/requirements.txt
python -m playwright install chromium
python scripts/local_server.py --root sut/public --port 8080   # отдельный терминал
python runner/run_experiment.py --mode local --port 8080
python analysis/analyze.py
```

Оркестратор сам запускает локальный сервер, если порт свободен.

## Структура

```
research-stand/
├── README.md
├── Makefile / run.ps1
├── docker-compose.yml
├── configs/
│   ├── experiment.yaml     # основной план
│   ├── calibration.yaml    # проверка верхней границы стенда (пустая сцена)
│   └── ci.yaml             # сокращённый план для CI
├── sut/                    # System Under Test: PWA + WebGL
│   ├── Dockerfile
│   ├── nginx.conf
│   └── public/
│       ├── index.html, manifest.webmanifest, sw.js
│       ├── js/ (main.js, scene.js, metrics.js, rng.js)
│       └── vendor/three.module.min.js
├── runner/
│   ├── Dockerfile
│   ├── playwright_runner.py  # один прогон: сеть, кеш, измерения, сырые файлы
│   └── run_experiment.py     # план, рандомизация, манифест кампании
├── analysis/
│   ├── Dockerfile
│   └── analyze.py            # статистика, тесты, размеры эффекта, графики
├── scripts/
│   ├── smoke.py
│   └── local_server.py
├── results/
│   ├── raw/         # <run_id>.metrics.json, .manifest.json, .frames.csv
│   ├── processed/   # runs.csv, descriptives.csv, tests.csv, aa.json, drift.csv
│   └── figures/     # png-графики для отчёта
└── docs/
    ├── pr3-report.md
    └── pr4-report.md
```

## Факторы и режимы

| Фактор | Уровни | Смысл |
|---|---|---|
| `render` | `baseline`, `instanced`, `lod`, `none` | отдельные меши; один `InstancedMesh`; ручной LOD по расстоянию; пустая сцена для калибровки |
| `transport` | `fast`, `slow3g` | без троттлинга; 300 мс RTT, 1.6/0.75 Мбит/с, CPU ×4 |
| `mode` | `no_sw_cold`, `sw_cold`, `sw_warm`, `offline_sw`, `offline_control` | без service worker; первый визит с SW; повторный визит с SW; офлайн после прогрева; офлайн без SW (негативный контроль) |

Параметры сцены — `objects` и `seed`. Сид сцены равен `seed + rep`, поэтому все
конфигурации одного повторения видят одинаковую геометрию, а разные повторения —
разные раскладки. Это защита от «удачной» сцены.

## Метрики

Собираются в браузере (`sut/public/js/metrics.js`) и в раннере:

- **Рендеринг:** `fps_mean`, `frame_p50/p95/p99_ms`, `jank_pct` (доля кадров > 33.4 мс),
  `draw_calls`, `triangles`, строка GPU.
- **Загрузка и UX:** `lcp_ms`, `fcp_ms`, `ttfb_ms`, `dom_content_loaded_ms`, `load_ms`,
  `first_frame_ms`, `cls`, `interaction_proxy_ms` (задержка от `pointerdown` до
  следующего кадра — прокси, а не официальный INP).
- **Сеть и кеш:** `transfer_bytes`, `sw.cacheEntries`, `sw_controlled`, `offline_ok`.
- **Измерительный контур:** `main_thread_busy_pct` (доля времени занятости main thread
  по CDP `Performance.getMetrics`), число long tasks.

**Единица анализа — прогон.** Значение `fps_mean` или `lcp_ms` одного прогона является
одним наблюдением; `n` равно числу повторений (10), а не числу кадров. Кадры внутри
прогона автокоррелированы, поэтому по ним нельзя считать доверительные интервалы.

## План эксперимента

| Блок | Что проверяет | Конфигурации | Повторения | Прогонов |
|---|---|---|---|---|
| A | RQ1, методы рендеринга | 3 (`baseline`, `instanced`, `lod`) | 10 | 30 |
| B | RQ2, кеширование и сеть | 2 профиля × 3 режима | 10 | 60 |
| C | RQ3, офлайн-доступность | 2 режима | 10 | 20 |
| K | калибровка (отдельная команда) | 1 (`render=none`) | 5 | 5 |

Итого основной кампании — 110 прогонов плюс 5 калибровочных (`configs/calibration.yaml`). Порядок рандомизирован сидом `20261119`.
Перед каждым прогоном создаётся новый browser context: кеш, service worker и
состояние страницы не переносятся между прогонами. Внутри прогона есть прогрев
(`warmup_ms: 2000`), который не попадает в измеряемое окно (`measure_ms: 6000`).

## Проверка самого стенда

```bash
python scripts/smoke.py --base-url http://127.0.0.1:8080        # HTTP + WebGL + метрики
python runner/run_experiment.py --mode local --config configs/calibration.yaml --force
python analysis/analyze.py --raw results/raw --tag main          # A/A, дрейф, загрузка CPU
```

1. **Smoke:** все ресурсы отдаются, WebGL-контекст создаётся, кадры считаются.
2. **A/A:** 10 прогонов одной конфигурации (`A / baseline / fast / no_sw_cold`) случайно
   делятся на две группы; ожидается отсутствие значимого различия, а разброс между
   прогонами даёт «шум стенда».
3. **Узкое место генератора:** `main_thread_busy_pct` должен быть заметно ниже 80 %,
   а калибровочная пустая сцена — держать 60 FPS. Иначе измеряется не SUT, а контур.
4. **Стабильность:** проверяется ранговая корреляция метрики с временем запуска
   (`results/processed/main/drift.csv`).

Дополнительно можно повторить кампанию на другом сиде и сравнить выводы:

```bash
python runner/run_experiment.py --mode local --config configs/repeat.yaml
python analysis/analyze.py --raw results/raw-repeat --tag repeat
```

## Что получит проверяющий

После `make experiment && make analyze`:

- `results/raw/*.manifest.json` — коммит, сид, параметры, браузер, железо, хеш конфига;
- `results/raw/*.metrics.json` и `*.frames.csv` — сырые измерения;
- `results/processed/main/runs.csv` — таблица «прогон × метрики»;
- `results/processed/main/tests.csv` — p-value, поправка Холма, δ Клиффа, CI отношения медиан;
- `results/processed/main/aa.json` — A/A-тест и минимальный обнаруживаемый эффект;
- `results/figures/main/*.png` — графики для отчёта.

**Допустимое расхождение при повторной проверке.** На другой машине абсолютные значения
FPS и времени загрузки будут отличаться: стенд фиксирует программное окружение, но не
GPU и не планировщик ОС. Согласованными считаются направление эффекта и его порядок:
`instanced` быстрее `baseline` по FPS; `sw_warm` быстрее `no_sw_cold` по LCP и объёму
передачи в `slow3g`; офлайн открывается только при `sw`. Числовые допуски и фактические
результаты приведены в `docs/pr4-report.md`.

## Ограничения

- Кампания из `docs/pr4-report.md` выполнена в локальном режиме на машине без Docker
  (Windows 11, Intel Core i5-1335U, Intel UHD Graphics, Chromium 153 headless).
  Контейнерная конфигурация входит в репозиторий, но на этой машине не запускалась.

- Headless Chromium на машине без GPU использует программный растеризатор
  (SwiftShader), поэтому абсолютные FPS не переносятся на реальные GPU. Сравнение
  методов рендеринга при этом остаётся корректным, так как все конфигурации
  измеряются в одном окружении.
- Playwright и браузер добавляют накладные расходы; их вклад контролируется блоком K
  и метрикой `main_thread_busy_pct`.
- Троттлинг сети эмулируется через CDP и не воспроизводит потери пакетов и
  нестабильность реального мобильного канала.
- Внешние PWA-сайты не используются: SUT полностью локальный, чтобы эксперимент был
  воспроизводим и не зависел от третьих сторон.

## Лицензия и данные

Код стенда — учебный артефакт ВКР. Сырые данные прогонов лежат в `results/raw` и
содержат только синтетические измерения; персональных данных нет.
