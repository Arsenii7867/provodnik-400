# API

Все маршруты живут под префиксом `/api`, принимают и отдают JSON. Интерактивное описание
доступно на работающем сервере: Swagger UI на `/docs`, ReDoc на `/redoc`, схема на
`/openapi.json` (страницы отдаются с файлов сервера, внешних адресов нет). Та же схема лежит в
репозитории в `docs/openapi.json`; после изменения маршрутов её перегенерируют командой
`python scripts/export_openapi.py` из папки `backend`, а тест `test_openapi_export_is_current`
падает при расхождении. Операции сгруппированы тегами по доменам, у каждой есть summary.
Примеры ниже для сервера на `http://localhost:8000`; демо-коды и PIN в README.

## Авторизация

Вход по коду сотрудника и PIN возвращает токен на `TOKEN_TTL_HOURS` часов (по умолчанию 12):

```
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"employee_code": "VSM-1001", "pin": "1234"}'
```

```json
{
  "token": "…",
  "expires_at": "2026-09-27T03:14:00.000+00:00",
  "employee": {"employee_code": "VSM-1001", "display_name": "…", "role": "conductor",
               "brigade": "М-01", "depot": "ТЧ Москва-ВСМ"}
}
```

Дальше токен передаётся в заголовке `Authorization: Bearer <token>`. Роли две: `conductor`
(проводник) и `mentor` (наставник: аналитика бригады, перечитывание и проверка контента).
Интеграция HR и LMS ходит без токена, с заголовком `X-API-Key` (значение из переменной
`INTEGRATION_API_KEY`, вне prod по умолчанию `demo-integration-key`). Неудачные попытки входа
ограничены `LOGIN_RATE_PER_MINUTE` в минуту (по умолчанию 10) отдельно на адрес соединения и на
код сотрудника; при превышении сервер отвечает `429` с заголовком `Retry-After`. Неизвестный код и
неверный PIN дают один и тот же ответ `401 pin_invalid`, чтобы по ответу нельзя было узнать,
существует ли код. `GET /api/auth/demo` отдаёт карточки демо-профилей для экрана входа без
токена; в prod список пуст.

## Формат ошибок

Любая ошибка, включая ошибки валидации и внутренние, приходит в одном виде, стек исключения
наружу не уходит никогда:

```json
{"error": {"code": "stale_step", "message": "Состояние устарело: обновите прохождение и повторите ход",
           "details": {"expected_step_no": 3}}}
```

| Статус | Коды | Когда |
|---|---|---|
| 400 | `bad_request` | запрос не удалось разобрать; preflight CORS с чужого origin отвечает 400 текстом фреймворка |
| 401 | `token_missing`, `token_invalid`, `token_expired`, `pin_invalid`, `api_key_required`, `api_key_invalid` | нет входа, токен отозван или истёк, неверный PIN, нет или не подходит ключ интеграции |
| 403 | `role_required`, `foreign_run`, `foreign_notification`, `graph_locked` | действие другой роли, чужое прохождение или уведомление, карта сценария до первого прохождения |
| 404 | `not_found`, `scenario_not_found`, `run_not_found`, `notification_not_found`, `employee_not_found`, `brigade_not_found` | нет адреса или объекта; чужие объекты дают 403, а не 404 |
| 405 | `method_not_allowed` | метод не поддерживается адресом |
| 409 | `stale_step`, `option_unavailable`, `too_early`, `already_finished`, `run_not_active`, `no_timer`, `idempotency_mismatch`, `run_not_finished`, `employee_exists` | конфликт состояния прохождения (подробности в разделе «Прохождение»), повтор ключа для другого сценария, разбор до завершения, сотрудник уже есть |
| 413 | `payload_too_large` | тело больше 1 МБ по фактическим байтам или Content-Length |
| 422 | `validation_error` | тело или параметры не прошли Pydantic; в `details.errors` список `{loc, msg}` |
| 429 | `rate_limited` | лимит входа; `details.retry_after` и заголовок `Retry-After` в секундах |
| 500 | `internal_error` | необработанная ошибка, в лог уходит трассировка, клиенту только код |

Фронтенд отдельно проверяет разбор успешного JSON-ответа: HTML, оборванный JSON или пустое
тело при `200` дают локальную ошибку `invalid_response` с понятным сообщением. HTTP-статус
сохраняется; токен входа не сбрасывается. Автоматическое сообщение об истечении таймера
повторяется после такой ошибки. Ответы без тела `204`/`205` остаются допустимыми.

## Эндпоинты по тегам

Все маршруты, кроме здоровья, входа, демо-профилей и интеграции, требуют Bearer-токен.

### Здоровье

| Метод и путь | Что делает |
|---|---|
| `GET /api/health` | `{status, version, scenarios, db, content_errors}`: число сценариев в каталоге, диалект базы и число ошибок контента (больше нуля значит, что сервер работает на прежней версии сценариев). `HEAD` на тот же адрес отвечает 200 для проверок живости |

```
curl -s http://localhost:8000/api/health
```

### Авторизация

| Метод и путь | Что делает |
|---|---|
| `POST /api/auth/login` | вход: `{employee_code, pin}` -> `{token, expires_at, employee}` |
| `POST /api/auth/logout` | отзыв текущего токена -> `{ok: true}` |
| `GET /api/auth/me` | сотрудник по токену: код, имя, роль, бригада, депо |
| `GET /api/auth/demo` | демо-профили для экрана входа (без токена, вне prod) |

### Профиль

| Метод и путь | Что делает |
|---|---|
| `GET /api/profile` | XP, уровень с порогами (`level.next_threshold`, `xp_to_next`), владение по компетенциям со статусами `ok`, `weak`, `few_data`, `gap`, число достижений, прохождений, место в бригаде, последний результат, действующие и сгорающие бонусы |
| `GET /api/profile/runs` | история прохождений, новые первыми: сценарий, статус, исход, финальные шкалы, очки, XP, класс, число истёкших таймеров |

```
curl -s http://localhost:8000/api/profile -H "Authorization: Bearer $TOKEN"
```

### Сценарии

| Метод и путь | Что делает |
|---|---|
| `GET /api/scenarios` | каталог карточек; фильтры `competency`, `difficulty`, `service_class`, `critical`; у карточки класс, компетенции, длительность, число узлов и концовок, признак таймеров, лучший исход и число прохождений сотрудника |
| `GET /api/scenarios/filters` | значения фильтров: компетенции, классы, сложности из справочников |
| `GET /api/scenarios/{scenario_id}` | карточка плюс версия, источники (номера карточек ситуаций), контекст (класс, компоновка, норматив ожидания, чувствительность лояльности, перегон, минуты до станции, пассажир без имени, доступные каналы эскалации), число путей и исходов по перебору |
| `GET /api/scenarios/{scenario_id}/graph` | граф для карты: узлы (тип, слой, таймер, исходы путей через концовку), рёбра (вариант, истечение, условие), число путей, разброс шкал, текст Mermaid и фрагмент YAML стартового узла; проводнику доступен после первого прохождения сценария (`403 graph_locked`), наставнику всегда |

```
curl -s "http://localhost:8000/api/scenarios?critical=true" -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/api/scenarios/{scenario_id}/graph -H "Authorization: Bearer $TOKEN"
```

### Прохождение

| Метод и путь | Что делает |
|---|---|
| `POST /api/sessions` | старт: `{scenario_id, service_class?}` -> `201` состояние прохождения; необязательный заголовок `Idempotency-Key` длиной от 1 до 128 символов (повтор возвращает то же прохождение с `200`); пустой или слишком длинный ключ даёт `422` без изменения прохождения; новый старт переводит прежнее активное прохождение сотрудника в `abandoned` |
| `GET /api/sessions/active` | `{active: состояние}` для кнопки «Продолжить», без активного прохождения `active` равен `null` |
| `GET /api/sessions/{run_id}` | состояние прохождения (варианты берутся из текущего файла сценария) |
| `POST /api/sessions/{run_id}/choose` | ход: `{option_id, step_no}`; у узла-события единственный ход `continue` |
| `POST /api/sessions/{run_id}/expire` | сообщить об истечении таймера: `{step_no}` |
| `POST /api/sessions/{run_id}/abandon` | прервать активное прохождение |

Состояние прохождения (ответ старта, чтения, хода и истечения):

```json
{
  "run_id": 120, "scenario_id": "smoking_vestibule", "title": "Дым в тамбуре",
  "status": "active", "step_no": 1, "loyalty": 65, "safety": 65, "flags": {"device_checked": true},
  "node": {"id": "refuses", "type": "dialog", "text": "…", "passenger_says": "…", "title": null,
           "timer_seconds": 20,
           "options": [{"id": "rule_and_call_ptb", "text": "…", "role_step": "rule", "escalation_target": "ptb"}]},
  "deadline_at": "2026-09-26T12:10:20.000+00:00", "server_now": "2026-09-26T12:10:00.000+00:00",
  "expired": false,
  "last_step": {"step_no": 1, "node_id": "intro", "option_id": "acknowledge_ask_device", "expired": false,
                "loyalty_before": 55, "loyalty_after": 65, "safety_before": 55, "safety_after": 65,
                "effects": {"loyalty": 10, "safety": 10}, "competencies": {"empathy": 2, "rules": 2, "safety": 2},
                "delayed_applied": [], "role_step": "acknowledge"},
  "context": {"service_class": "standard", "service_class_title": "Стандарт", "layout": "3+2",
              "wait_minutes": 20, "loyalty_sensitivity": 1.0, "segment": "…", "next_station_minutes": 30,
              "time_of_day": "вечер", "passenger": {"label": "…", "state": "…"}, "loyalty_of": "…",
              "crew_available": ["chief", "ptb", "engineer"]},
  "role_chain": {"steps": ["acknowledge"], "next_expected": "rule", "complete": false},
  "expired_timers": 0, "timers_answered": 0, "outcome": null, "xp": null
}
```

Как сервер ведёт таймер и ходы:

- При входе в узел с таймером сервер записывает `deadline_at`; клиент считает смещение своих
  часов по `server_now` и рисует остаток. Решает только время сервера.
- Ход после `deadline_at` плюс допуск `TIMER_GRACE_SECONDS` (по умолчанию 1 с, не больше 5)
  не отклоняется: сервер применяет ветку истечения `on_expire` и отвечает `200` с
  `expired: true`. Истечение, присланное раньше `deadline_at` минус допуск, даёт
  `409 too_early`; истечение у узла без таймера `409 no_timer`.
- `step_no` обязателен и должен совпадать с текущим: иначе `409 stale_step` с
  `details.expected_step_no` (двойной клик, вторая вкладка, гонка истечения и выбора).
  Вариант, скрытый условием или не принадлежащий узлу, даёт `409 option_unavailable`;
  ход в завершённом прохождении `409 already_finished`; если сценарий изменили так, что текущего
  узла больше нет, прохождение закрывается с `409 run_not_active`.
- Неизвестный `service_class` при старте это `422 validation_error`, неизвестный сценарий `404`.
- Завершённое прохождение XP повторно не начисляет; повтор того же сценария даёт долю очков по
  `xp.repeat_factor` из `content/rules.yaml`.

```
curl -s -X POST http://localhost:8000/api/sessions \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-1" -d '{"scenario_id": "smoking_vestibule"}'
curl -s -X POST http://localhost:8000/api/sessions/{run_id}/choose \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"option_id": "acknowledge_ask_device", "step_no": 0}'
curl -s -X POST http://localhost:8000/api/sessions/{run_id}/expire \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"step_no": 1}'
```

### Разбор

| Метод и путь | Что делает |
|---|---|
| `GET /api/runs/{run_id}/debrief` | покадровый разбор завершённого прохождения; до завершения `409 run_not_finished` |

Ответ: исход, стартовые и финальные шкалы, `xp` и `xp_breakdown` (`base`, `scales`, `tempo`,
`role`), `score`, признак повтора, счётчики таймеров, цепочка ролевой модели, список `steps`
(по каждому ходу текст узла и реплика пассажира, выбранный вариант или истечение, секунды
ответа, вердикт `best`, `ok`, `bad` или `expired`, `why`, `better`, лучший вариант узла,
`refs` с названием, документом, пунктом и цитатой нормы, шкалы до и после, эффекты, очки
компетенций, применённые отложенные последствия, шаг ролевой модели и адресат эскалации),
концовка с `summary` и `refs`, новые достижения, выполненные челленджи с бонусом и сроком его
сгорания, дельты владения компетенциями и уровень до и после.

```
curl -s http://localhost:8000/api/runs/{run_id}/debrief -H "Authorization: Bearer $TOKEN"
```

### Достижения

| Метод и путь | Что делает |
|---|---|
| `GET /api/achievements` | каталог из `content/achievements.yaml`: `{id, title, description, rule_text, rule_type, earned, earned_at}` |

### Лидерборд

| Метод и путь | Что делает |
|---|---|
| `GET /api/leaderboard` | `scope` равен `brigade`, `depot` или `company` (по умолчанию бригада), `limit` до 100 (по умолчанию 20) -> `{scope, scope_title, rows, me}`; строка: место, код, имя, бригада, депо, `score` (сумма лучших очков по сценариям плюс неистёкшие бонусы), `best_scores_sum`, `bonus_points`, число достижений, `is_me`; `me` это своя строка с местом по всему охвату, у наставника `null` |

```
curl -s "http://localhost:8000/api/leaderboard?scope=depot&limit=20" -H "Authorization: Bearer $TOKEN"
```

### Уведомления

| Метод и путь | Что делает |
|---|---|
| `GET /api/notifications` | до 100 последних, новые первыми: `{id, kind, title, body, payload, created_at, read_at}`; виды `achievement`, `level_up`, `challenge`, `points_expiring`, `new_scenario`; уведомления о сгорании создаются при этом чтении, когда до срока бонуса меньше `bonus.expiring_notice_hours` |
| `POST /api/notifications/read-all` | отметить все прочитанными -> `{read: N}` |
| `POST /api/notifications/{notification_id}/read` | отметить одно; чужое даёт `403 foreign_notification` |

### Челленджи

| Метод и путь | Что делает |
|---|---|
| `GET /api/challenges` | челленджи из `content/challenges.yaml` с окном (`starts_at`, `ends_at`), прогрессом `{done, total, completed}`, статусом `active`, `completed`, `expired` и сроком сгорания начисленного бонуса |

### Аналитика

| Метод и путь | Что делает |
|---|---|
| `GET /api/analytics/me` | владение по компетенциям со статусами, списки `weak` и `gaps`, типичные ошибки (отрицательные очки в окне прохождений), рекомендации сценариев с причиной, темп решений под таймером, своевременность эскалации в критических сценариях, динамика по неделям, вывод фразой |
| `GET /api/analytics/team` | только наставник; `brigade_id` необязателен (по умолчанию своя бригада, чужой номер без бригады даёт 404): проводники с владением, прохождениями, инцидентами, проседающими и пробелами; средние по компетенциям; пробелы бригады; рекомендации бригаде; вывод фразой |

```
curl -s http://localhost:8000/api/analytics/me -H "Authorization: Bearer $TOKEN"
curl -s "http://localhost:8000/api/analytics/team?brigade_id=1" -H "Authorization: Bearer $MENTOR_TOKEN"
```

### Интеграция

Маршруты для HR и LMS, заголовок `X-API-Key`, сравнение ключа за постоянное время; наружу
уходят коды сотрудников и агрегаты, имена только в карточке сотрудника.

| Метод и путь | Что делает |
|---|---|
| `GET /api/integration/employees/{code}/results` | карточка сотрудника: код, имя, роль, бригада, депо, `xp_total`, уровень, владение по компетенциям (`code`, `mastery`, `status`, `runs_assessed`), завершённые прохождения от старых к новым, достижения с датой |
| `GET /api/integration/results` | экспорт завершённых прохождений по возрастанию `run_id`: `since` (ISO 8601, знак плюс в смещении кодировать как `%2B`), `limit` до 500, `cursor` (последний полученный `run_id`) -> `{items, next_cursor}`; `next_cursor` отдаётся только при полной странице |
| `GET /api/integration/events` | события для LMS: `after_id`, `limit` -> `{items: [{id, event_type, payload, created_at, delivered_at}], next_after_id}` |
| `POST /api/integration/events/ack` | подтверждение доставки `{ids: [...]}` -> `{acked: N}` (сколько впервые подтверждены) |
| `GET /api/integration/competencies` | справочник компетенций: код, название, описание |
| `GET /api/integration/employees/{code}/actions` | журнал действий сотрудника с курсором `after_id`: вход, выход, старт, ход, истечение, отказ, завершение с полезной нагрузкой |
| `POST /api/integration/employees` | создать сотрудника из HR: `{employee_code, display_name, brigade, role?}` -> `201` карточка плюс `pin`, который отдаётся один раз (`409 employee_exists`, `404 brigade_not_found`); такой сотрудник помечен `is_synthetic: false` и сразу получает анонсы идущих челленджей |

Элемент экспорта результатов:

```json
{"run_id": 57, "employee_code": "VSM-1007", "brigade": "М-02", "scenario_id": "unattended_bag",
 "scenario_version": 2, "finished_at": "2026-09-20T08:41:00.000+00:00", "outcome": "acceptable",
 "loyalty_final": 70, "safety_final": 85, "score": 129, "xp": 129,
 "competencies": {"safety": {"earned": 4, "assessed": 6}, "escalation": {"earned": 2, "assessed": 4}}}
```

События пишутся в одной транзакции с тем, что их вызвало, и сохраняются в таблице после
подтверждения LMS. `ack` устанавливает `delivered_at`, но не удаляет событие и не исключает
его из чтения: клиент сохраняет `next_after_id` и передаёт его как `after_id` следующего
запроса. Повторное подтверждение уже доставленного события не увеличивает `acked`.
Фоновой доставки и автоматической очистки нет, подтверждение выполняется пачками. Типы:
`run_completed` (код сотрудника, сценарий и версия, исход, шкалы, очки, XP, компетенции,
`finished_at`), `achievement_earned`, `level_up`, `challenge_completed`, `employee_created`.

```
curl -s "http://localhost:8000/api/integration/results?since=2026-09-01T00:00:00%2B00:00&limit=100" \
  -H "X-API-Key: demo-integration-key"
curl -s "http://localhost:8000/api/integration/events?after_id=0&limit=100" -H "X-API-Key: demo-integration-key"
curl -s -X POST http://localhost:8000/api/integration/events/ack \
  -H "X-API-Key: demo-integration-key" -H "Content-Type: application/json" -d '{"ids": [1, 2, 3]}'
curl -s -X POST http://localhost:8000/api/integration/employees \
  -H "X-API-Key: demo-integration-key" -H "Content-Type: application/json" \
  -d '{"employee_code": "VSM-3001", "display_name": "Новый проводник", "brigade": "М-01"}'
curl -s http://localhost:8000/api/integration/employees/{code}/results -H "X-API-Key: demo-integration-key"
curl -s http://localhost:8000/api/integration/employees/{code}/actions -H "X-API-Key: demo-integration-key"
curl -s http://localhost:8000/api/integration/competencies -H "X-API-Key: demo-integration-key"
```

### Администрирование

Только роль `mentor`.

| Метод и путь | Что делает |
|---|---|
| `POST /api/admin/scenarios/reload` | принудительно перечитать `content/`: `{loaded, new, removed, errors: [{file, line, message}], summary, notified}`; о новых сценариях всем сотрудникам уходит уведомление, новые челленджи получают окно |
| `GET /api/admin/scenarios/validate` | тот же отчёт валидатора по файлам на диске без применения |

```
curl -s -X POST http://localhost:8000/api/admin/scenarios/reload -H "Authorization: Bearer $MENTOR_TOKEN"
```

## Заголовки и кэш

На каждом ответе `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`; ответы API идут с `Cache-Control: no-store`, страница приложения
с политикой `Content-Security-Policy: default-src 'self'`. CORS разрешён только источникам из
`CORS_ORIGINS` (нужен для `npm run dev`); сервер не читает `X-Forwarded-For`, пока перед ним нет
доверенного прокси (uvicorn запускается с `--no-proxy-headers`). Подробности и список того, что
не сделано, в `docs/security.md`.
