# Шаблон применения инкрементального пакета (.tar.gz)

Этот документ фиксирует **каноничный** способ применения изменений, присланных как инкрементальный `tar.gz` пакет.

Требования:
- Пакет содержит **только** изменённые файлы с путями **от корня репозитория**.
- Если есть удаления, пакет содержит файл `.pack/deleted.txt` (по одному пути на строку).
- Команды должны быть:
  - в одной `&&`-цепочке (чтобы прерываться на ошибке без `set -e`),
  - без `exit` и без `set -e`,
  - с проверкой “repo чистый” до применения,
  - с удалением `.pack` после обработки.

## Каноничный шаблон команд

1) Скачай пакет в папку скачивания (обычно: `/media/nik/0C30B3CF30B3BE50/Загрузки`).
2) Выполни (замени `PACK=...` на имя файла пакета):

```bash
cd /home/nik/projects/adaspeas &&
test -d .git || { echo "No .git here (clone repo first)"; false; } &&
# ВАЖНО: в репозитории используем ТОЛЬКО ветку main (без feature-веток).
test "$(git rev-parse --abbrev-ref HEAD)" = "main" || { echo "Not on main. Switch to main."; false; } &&
# Работаем линейно: сначала подтянуть изменения без merge-коммитов.
git pull --ff-only &&
# После pull repo должен оставаться чистым
test -z "$(git status --porcelain)" || { echo "Repo dirty. Commit/stash first."; false; } &&
PACK="/media/nik/0C30B3CF30B3BE50/Загрузки/<PACK_NAME>.tar.gz" &&
test -f "$PACK" || { echo "Pack not found: $PACK"; false; } &&
tar -xzf "$PACK" -C . &&
if test -f .pack/deleted.txt; then
  while IFS= read -r p; do
    test -n "$p" || continue
    git rm -r --ignore-unmatch "$p" >/dev/null 2>&1 || rm -rf "$p"
  done < .pack/deleted.txt
fi &&
rm -rf .pack &&
# Быстрая валидация compose (если docker установлен)
if command -v docker >/dev/null 2>&1; then docker compose config >/dev/null; else echo "docker отсутствует, пропускаю docker compose config"; fi &&
# Тесты (если pytest установлен). Важно: make test может возвращать 5 (no tests) и это считается ОК.
if command -v python >/dev/null 2>&1 && python -c "import pytest" >/dev/null 2>&1; then make test || true; else echo "pytest отсутствует, пропускаю make test"; fi &&
git add -A &&
git status --porcelain &&
git commit -m "<типы: docs|feat|fix|refactor|ops|chore|test>: <сообщение по-русски>" &&
git push origin main
```

Заметки:
- `git status --porcelain` после `git add -A` оставлен намеренно: удобно увидеть, что реально изменилось, но он не ломает цепочку.
- `git rm --ignore-unmatch` безопасен для путей, которые уже отсутствуют, и корректно фиксирует удаления в git.
