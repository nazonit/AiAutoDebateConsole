@echo off
chcp 65001 >nul
title AI Дебаты - Первый запуск
color 0A

echo ==============================================
echo   🚀 Установка и запуск проекта AI Дебаты
echo ==============================================
echo.

:: Проверка Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python не найден. Установите Python 3.10+ и добавьте в PATH.
    pause
    exit /b
)

:: Создание виртуального окружения
if not exist venv (
    echo 🔧 Создаю виртуальное окружение...
    python -m venv venv
)

:: Активация окружения
echo 🔧 Активирую окружение...
call venv\Scripts\activate.bat

:: Установка зависимостей
echo 📦 Устанавливаю зависимости...
pip install --upgrade pip
pip install requests colorama

:: Запуск проекта
echo 🚀 Запускаю AI Дебаты...
python debates.py

pause
