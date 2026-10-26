@echo off
chcp 65001 > nul
title DuDu-Trading - Tự Động Cập Nhật Dữ Liệu
echo ==========================================================
echo    DUDU-TRADING: HE THONG CAP NHAT DU LIEU TU DONG
echo ==========================================================
echo [INFO] Dang kiem tra moi truong Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Khong tim thay Python tren he thong! Vui long kiem tra PATH.
    pause
    exit /b 1
)

echo [INFO] Bat dau tien trinh cap nhat dinh ky 5 phut...
echo [INFO] Nhan Ctrl+C de dung bat ky luc nao.
echo ==========================================================
python scripts/auto_updater.py --interval 300 --push
pause
