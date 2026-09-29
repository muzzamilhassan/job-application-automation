@echo off
title Job Apply-Assist Queue
cd /d "C:\Users\Revnix\Desktop\personal\automation"
echo Pulling latest jobs from cloud run...
git pull --rebase -q origin main
echo.
echo Opening apply-assist queue (browser will open - review and click Submit on each form)
"C:\Python314\python.exe" browser\apply_queue.py
echo.
pause
