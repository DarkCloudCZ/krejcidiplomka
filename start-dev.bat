@echo off
echo Starting MBDB Reviewer Development Environment...

:: Start backend in new window
start "MBDB Backend" cmd /k "cd /d %~dp0mbdb_reviewer\backend && .venv\Scripts\activate && uvicorn main:app --reload --port 8000"

:: Start frontend in new window
start "MBDB Frontend" cmd /k "cd /d %~dp0mbdb_reviewer\frontend\mbdb_reviewer_frontend && npm run dev"

echo.
echo Backend starting at http://localhost:8000
echo Frontend starting at http://localhost:5173
echo.
echo Close this window or press any key to exit (servers will keep running)
pause >nul
