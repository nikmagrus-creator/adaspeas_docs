# Перенос на новый VPS (минимум боли)

Актуально на: 2026-02-03 18:20 UTC


Цель: при необходимости быстро “перетащить” прод на новый сервер без ручного шаманства.

## Что нужно перенести
1) Данные приложения:
- `app_data` (SQLite: `/data/app.db`)

2) TLS и конфиг прокси:
- `caddy_data`, `caddy_config` (сертификаты/состояние Caddy)

3) Опционально:
- `redis_data` (обычно можно не переносить, очередь восстановится)

## Бэкап на старом VPS
Перейти в каталог проекта:
```bash
cd /opt/adaspeas
```

Сделать архивы volume’ов (tar.gz в текущей папке). Рекомендуется именовать с UTC-временем:
```bash
TS=$(date -u +%Y%m%d_%H%M%S)
```

Сделать архивы volume’ов:
```bash
# app_data (SQLite)
docker run --rm -v app_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && tar -czf /backup/app_data_${TS}.tar.gz ."

# caddy certificates/state
docker run --rm -v caddy_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && tar -czf /backup/caddy_data_${TS}.tar.gz ."

docker run --rm -v caddy_config:/data -v "$PWD":/backup alpine   sh -c "cd /data && tar -czf /backup/caddy_config_${TS}.tar.gz ."

# опционально redis
docker run --rm -v redis_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && tar -czf /backup/redis_data_${TS}.tar.gz ."
```

Скачать архивы на локальную машину или сразу на новый VPS (scp/rsync).

## Быстрый бэкап SQLite (только файл app.db)
Если нужно быстро снять только базу (без остальных volume’ов):

```bash
cd /opt/adaspeas
TS=$(date -u +%Y%m%d_%H%M%S)
docker run --rm -v app_data:/data -v "$PWD":/backup alpine sh -c "cp /data/app.db /backup/app_${TS}.db"
```

Восстановление (после остановки сервиса):
```bash
cd /opt/adaspeas
sudo systemctl stop adaspeas-bot
docker run --rm -v app_data:/data -v "$PWD":/backup alpine sh -c "cp /backup/app_${TS}.db /data/app.db"
sudo systemctl start adaspeas-bot
```

## Развёртывание на новом VPS
1) Docker установлен.
2) Bootstrap репо:
```bash
REPO_URL=git@github.com:nikmagrus-creator/adaspeas_docs.git APP_DIR=/opt/adaspeas ./deploy/bootstrap_vps.sh
```
3) Заполнить `.env` (секреты).
4) Остановить сервис (чтобы спокойно восстановить данные):
```bash
sudo systemctl stop adaspeas-bot
```

## Восстановление volume’ов на новом VPS
```bash
cd /opt/adaspeas

# app_data
docker run --rm -v app_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && rm -rf ./* && tar -xzf /backup/app_data_${TS}.tar.gz"

# caddy
docker run --rm -v caddy_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && rm -rf ./* && tar -xzf /backup/caddy_data_${TS}.tar.gz"

docker run --rm -v caddy_config:/data -v "$PWD":/backup alpine   sh -c "cd /data && rm -rf ./* && tar -xzf /backup/caddy_config_${TS}.tar.gz"
```

5) Запуск:
```bash
sudo systemctl start adaspeas-bot
```

6) DNS переключить на новый IP (если менялся), проверить:
- `https://bot.adaspeas.ru/health`

## Если сертификаты не переносим
Можно не переносить `caddy_*` вообще. Тогда Caddy сам заново получит сертификаты, но:
- DNS должен уже указывать на новый сервер
- порты 80/443 открыты
- email в `.env` (`ACME_EMAIL`) валидный

## История изменений
| Дата/время (UTC) | Автор | Тип | Кратко что изменили | Причина/ссылка | Commit/PR |
|---|---|---|---|---|---|
| 2026-02-03 18:20 UTC | Nikolay | ops/doc | Добавлены таймстемпы, реальные ссылки на репо и быстрый бэкап SQLite | перенос/восстановление | |

