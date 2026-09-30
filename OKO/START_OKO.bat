@echo off
chcp 65001 >nul
title OKO
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo.
  echo  Python 3 не найден.
  echo  Установите Python 3.8 или новее: https://www.python.org/downloads/
  echo  При установке отметьте пункт "Add python.exe to PATH".
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% oko.py %*
if errorlevel 1 (
  echo.
  echo  ОКО завершилось с ошибкой. Если выше написано "Python was not found" —
  echo  установите Python с python.org ^(версия из Microsoft Store тоже подходит^).
  pause
)
