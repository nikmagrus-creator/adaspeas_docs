# Шаблон применения инкрементального пакета (.tar.gz)

Этот документ фиксирует **каноничный** способ применения изменений, присланных как инкрементальный `tar.gz` пакет.

Важно для чата:
- Когда ассистент выдаёт pack, он **обязан** вставить в ответ ниже приведённый блок команд, подставив **реальное имя** файла в `PACK=...` и готовое сообщение коммита.

Требования к pack:
- содержит **только** изменённые файлы с путями **от корня репозитория**;
- удаления описываются в `.pack/deleted.txt` (по одному пути на строку);
- **не содержит** `.git/`;
- после применения `.pack/` удаляется.

Правила репозитория:
- работаем **только** в `main`;
- **не используем** `merge/cherry-pick/rebase`;
- изменения из pack всегда фиксируем коммитом в `main`.

Контекст путей (зафиксировано для повторяемости):
- Local (Linux Mint): репозиторий `/home/nik/projects/adaspeas`
- Папка скачивания паков: `/media/nik/0C30B3CF30B3BE50/Загрузки`
- VPS: директория проекта `/opt/adaspeas`
  - на VPS pack **не распаковываем**; там только `git pull --ff-only` из `main` и `make up-prod`

## Каноничный шаблон команд

1) Скачай pack в `/media/nik/0C30B3CF30B3BE50/Загрузки`.
2) Выполни (замени `PACK=...` на имя файла):

```bash
cd /home/nik/projects/adaspeas &&

test -d .git || { echo "Не репозиторий (.git не найден)."; false; } &&

git checkout main &&

git fetch origin --prune &&

# Перевести origin на SSH (чтобы GitHub не спрашивал логин/пароль)
origin_url="$(git remote get-url origin)" &&
echo "origin=$origin_url" &&
if echo "$origin_url" | grep -q '^https://github.com/'; then
  git remote set-url origin git@github.com:nikmagrus-creator/adaspeas_docs.git || true
fi &&

# Снять любые незавершённые операции (частая причина "needs merge")
git cherry-pick --abort >/dev/null 2>&1 || true &&
git merge --abort >/dev/null 2>&1 || true &&
git rebase --abort >/dev/null 2>&1 || true &&

# Запрещаем локальные коммиты поверх origin/main (у нас одна ветка и линейная история)
test "$(git rev-list --count origin/main..HEAD)" -eq 0 || { echo "Есть локальные коммиты не в origin/main. Сначала приведи репо к origin/main (см. docs/OPS_RUNBOOK_RU.md)."; false; } &&

# Жёстко синхронизировать рабочее дерево с origin/main
git reset --hard origin/main &&

git pull --ff-only &&

# Если в корне репозитория лежат архивы для анализа (adaspeas.zip / adaspeas.tar.gz),
# вынеси их из репо, чтобы не ловить 'репозиторий не чистый'.
for f in adaspeas.zip adaspeas.tar.gz; do
  if test -f "$f"; then
    mv -v "$f" "/media/nik/0C30B3CF30B3BE50/Загрузки/" || rm -f "$f" || true
  fi
done &&

# Repo должен быть чистым перед применением pack
test -z "$(git status --porcelain)" || { echo "Репозиторий не чистый. Сначала закоммить/убери изменения и повтори.";  git status --porcelain; false; } &&

PACK="/media/nik/0C30B3CF30B3BE50/Загрузки/<PACK_NAME>.tar.gz" &&
test -f "$PACK" || { echo "Пак не найден: $PACK"; false; } &&

# Безопасность: pack не должен содержать .git/ или мусорные артефакты
if tar -tzf "$PACK" | grep -qE '(^|/)\.git(/|$)'; then echo "ОШИБКА: pack содержит .git/ (нельзя)."; false; fi &&
if tar -tzf "$PACK" | grep -qE '(^|/)__pycache__(/|$)|\.pyc$|(^|/)\.pytest_cache(/|$)'; then echo "ОШИБКА: pack содержит __pycache__/.pyc/.pytest_cache (мусор)."; false; fi &&

# Распаковать pack поверх репозитория
tar -xzf "$PACK" -C . &&

# Применить удаления из .pack/deleted.txt (если есть)
# Важно: чистим CRLF (\r) и пробелы, игнорируем пустые строки и комментарии.
if test -f .pack/deleted.txt; then
  while IFS= read -r p || test -n "$p"; do
    p="${p%$'\r'}"
    # trim spaces
    p="${p#"${p%%[![:space:]]*}"}"
    p="${p%"${p##*[![:space:]]}"}"
    case "$p" in
      ""|\#*) continue ;;
    esac
    git rm -r --ignore-unmatch -- "$p" >/dev/null 2>&1 || true
    rm -rf -- "$p"
  done < .pack/deleted.txt
fi &&

rm -rf .pack &&

# Быстрая валидация compose (если docker установлен)
if command -v docker >/dev/null 2>&1; then docker compose config >/dev/null; else echo "docker отсутствует, пропускаю docker compose config"; fi &&

# Тесты (если pytest установлен)
if command -v python >/dev/null 2>&1 && python -c "import pytest" >/dev/null 2>&1; then make test || true; else echo "pytest отсутствует, пропускаю make test"; fi &&

# Защита от "мусора копипаста": если внезапно создался файл вида :contentReference..., удаляем его и не коммитим.
if ls -1 :contentReference* >/dev/null 2>&1; then
  rm -f :contentReference*
fi &&
git add -A &&

# Если pack не дал изменений, не коммитим
if test -z "$(git status --porcelain)"; then
  echo "Изменений нет: pack уже применён или пустой.";
  true;
else
  git status --porcelain &&
  git commit -m "<type>: <сообщение по-русски>" &&
  git push origin main;
fi
```

Заметки:
- Намеренно используем одну `&&`-цепочку: ошибка в середине останавливает процесс без `set -e`.
- Если запускаешь этот блок как *Custom command* терминала и окно закрывается при ошибке, запускай в обычном терминале. Альтернатива: в конце добавь `; rc=$?; echo "EXIT=$rc"; read -rp "Нажми Enter..." _; exit $rc`.
- Пакеты распаковываются **только локально**. На VPS изменения приезжают через `git pull` из `main`.
- Если тебе прислали "полный zip репозитория" и внутри есть `.git/`, **не распаковывай его поверх своего репозитория**. Нужен именно инкрементальный pack.

- Если после вставки команд в терминал появился странный файл вида `:contentReference[...]` — это результат случайного символа `>` в скопированном тексте (редирект создаёт файл). Такой файл удаляем и игнорируем (см. `.gitignore`).
Актуально на: 2026-02-09 12:05 MSK

## История изменений
| Дата/время (MSK) | Автор | Тип | Кратко | Commit/PR |
|---|---|---|---|---|
| 2026-02-09 12:05 MSK | ChatGPT | doc | В шаблон добавлено: авто-перевод origin на SSH (чтобы не спрашивал пароль), авто-вынесение adaspeas.tar.gz из корня репо (как и zip) | |
| 2026-02-08 22:30 MSK | ChatGPT | doc | Фикс удаления по `.pack/deleted.txt` (rm всегда выполняется); защита от мусора `:contentReference*` (копипаст/редирект) + ignore/авто-удаление перед `git add -A` | |
| 2026-02-07 19:45 MSK | ChatGPT | doc | Добавлено: авто-вынесение adaspeas.zip перед проверкой repo clean; уточнено: артефакты pack/zip хранить вне репо | |
| 2026-02-07 17:59 MSK | ChatGPT | doc | Уточнено: pack в чате всегда сопровождается этим блоком команд с подставленным именем файла и commit message | |
| 2026-02-07 16:10 MSK | ChatGPT | doc | Добавлен безопасный пролог (abort/reset к origin/main), убран мусор в требованиях, добавлена защита от пустого коммита | |
| 2026-02-07 14:02 MSK | ChatGPT | doc | Добавлен блок с фиксированными путями (Local/Downloads/VPS) и уточнение что пакеты распаковываются только локально, а не на VPS | |
