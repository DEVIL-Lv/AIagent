@echo off
start powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'c:\traexiangmu\AIagent\backend'; python -m uvicorn app.main:app --host 0.0.0.0 --port 8001"
timeout /t 2 >NUL
start powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'c:\traexiangmu\AIagent\frontend'; node ./node_modules/vite/bin/vite.js dev --port 3000"
start "" "http://localhost:3000/"
