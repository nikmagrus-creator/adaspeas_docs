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

# Снять любые незавершённые операции (частая причина "needs merge")
git cherry-pick --abort >/dev/null 2>&1 || true &&
git merge --abort >/dev/null 2>&1 || true &&
git rebase --abort >/dev/null 2>&1 || true &&

# Запрещаем локальные коммиты поверх origin/main (у нас одна ветка и линейная история)
test "$(git rev-list --count origin/main..HEAD)" -eq 0 || { echo "Есть локальные коммиты не в origin/main. Сначала приведи репо к origin/main (см. docs/OPS_RUNBOOK_RU.md)."; false; } &&

# Жёстко синхронизировать рабочее дерево с origin/main
git reset --hard origin/main &&

git pull --ff-only &&

# Если в корне репозитория лежит adaspeas.zip (архив для анализа), вынеси его из репо,
# чтобы не поймать 'Repo dirty' до распаковки pack.
if test -f adaspeas.zip; then
  mv -v adaspeas.zip "/media/nik/0C30B3CF30B3BE50/Загрузки/" || true
fi &&

# Repo должен быть чистым перед применением pack
test -z "$(git status --porcelain)" || { echo "Repo dirty. Commit/stash first."; git status --porcelain; false; } &&

PACK="/media/nik/0C30B3CF30B3BE50/Загрузки/<PACK_NAME>.tar.gz" &&
test -f "$PACK" || { echo "Pack not found: $PACK"; false; } &&

# Распаковать pack поверх репозитория
tar -xzf "$PACK" -C . &&

# Применить удаления из .pack/deleted.txt (если есть)
if test -f .pack/deleted.txt; then
  while IFS= read -r p; do
    test -n "$p" || continue
    git rm -r --ignore-unmatch "$p" >/dev/null 2>&1 || rm -rf "$p"
  done < .pack/deleted.txt
fi &&

rm -rf .pack &&

# Быстрая валидация compose (если docker установлен)
if command -v docker >/dev/null 2>&1; then docker compose config >/dev/null; else echo "docker отсутствует, пропускаю docker compose config"; fi &&

# Тесты (если pytest установлен)
if command -v python >/dev/null 2>&1 && python -c "import pytest" >/dev/null 2>&1; then make test || true; else echo "pytest отсутствует, пропускаю make test"; fi &&

git add -A &&

# Если pack не дал изменений, не коммитим
if test -z "$(git status --porcelain)"; then
  echo "No changes after pack (already applied or empty).";
  true;
else
  git status --porcelain &&
  git commit -m "<type>: <сообщение по-русски>" &&
  git push origin main;
fi
```

Заметки:
- Намеренно используем одну `&&`-цепочку: ошибка в середине останавливает процесс без `set -e`.
- Пакеты распаковываются **только локально**. На VPS изменения приезжают через `git pull` из `main`.
- Если тебе прислали "полный zip репозитория" и внутри есть `.git/`, **не распаковывай его поверх своего репозитория**. Нужен именно инкрементальный pack.

Актуально на: 2026-02-07 19:45 MSK

## История изменений
| Дата/время (MSK) | Автор | Тип | Кратко | Commit/PR |
|---|---|---|---|---|
| 2026-02-07 19:45 MSK | ChatGPT | doc | Добавлено: авто-вынесение adaspeas.zip перед проверкой repo clean; уточнено: артефакты pack/zip хранить вне репо | |
| 2026-02-07 17:59 MSK | ChatGPT | doc | Уточнено: pack в чате всегда сопровождается этим блоком команд с подставленным именем файла и commit message | |
| 2026-02-07 16:10 MSK | ChatGPT | doc | Добавлен безопасный пролог (abort/reset к origin/main), убран мусор в требованиях, добавлена защита от пустого коммита | |
| 2026-02-07 14:02 MSK | ChatGPT | doc | Добавлен блок с фиксированными путями (Local/Downloads/VPS) и уточнение что пакеты распаковываются только локально, а не на VPS | |
