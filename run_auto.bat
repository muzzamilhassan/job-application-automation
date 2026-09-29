@echo off
cd /d "C:\Users\Revnix\Desktop\personal\automation"
if not exist out mkdir out
"C:\Python314\python.exe" run_daily.py --auto >> "out\auto_log.txt" 2>&1
