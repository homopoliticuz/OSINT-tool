#!/bin/bash
# ОКО — запуск на macOS (двойной щелчок). Если система блокирует файл:
# щёлкните правой кнопкой → «Открыть».
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 oko.py "$@"
fi
echo "Python 3 не найден. Установите Python 3.8+ с https://www.python.org/downloads/"
open "https://www.python.org/downloads/" 2>/dev/null
read -r -p "Нажмите Enter, чтобы закрыть окно…"
