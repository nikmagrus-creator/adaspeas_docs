# Перенос на новый VPS (минимум боли)

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

Сделать архивы volume’ов (tar.gz в текущей папке):
```bash
# app_data (SQLite)
docker run --rm -v app_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && tar -czf /backup/app_data.tar.gz ."

# caddy certificates/state
docker run --rm -v caddy_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && tar -czf /backup/caddy_data.tar.gz ."

docker run --rm -v caddy_config:/data -v "$PWD":/backup alpine   sh -c "cd /data && tar -czf /backup/caddy_config.tar.gz ."

# опционально redis
docker run --rm -v redis_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && tar -czf /backup/redis_data.tar.gz ."
```

Скачать архивы на локальную машину или сразу на новый VPS (scp/rsync).

## Развёртывание на новом VPS
1) Docker установлен.
2) Bootstrap репо:
```bash
REPO_URL=git@github.com:OWNER/REPO.git APP_DIR=/opt/adaspeas ./deploy/bootstrap_vps.sh
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
docker run --rm -v app_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && rm -rf ./* && tar -xzf /backup/app_data.tar.gz"

# caddy
docker run --rm -v caddy_data:/data -v "$PWD":/backup alpine   sh -c "cd /data && rm -rf ./* && tar -xzf /backup/caddy_data.tar.gz"

docker run --rm -v caddy_config:/data -v "$PWD":/backup alpine   sh -c "cd /data && rm -rf ./* && tar -xzf /backup/caddy_config.tar.gz"
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

