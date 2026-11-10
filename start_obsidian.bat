@echo off
echo ===================================================
echo Starting TEAM OBSIDIAN Platform...
echo ===================================================

echo Starting Backend API on http://localhost:8000 ...
start "Obsidian Backend" cmd /k "cd backend && python run.py"

echo Starting Frontend on http://localhost:3000 ...
start "Obsidian Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo ===================================================
echo TEAM OBSIDIAN is launching!
echo Backend:  http://localhost:8000 (Docs at /docs)
echo Frontend: http://localhost:3000
echo ===================================================

