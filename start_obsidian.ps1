Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "Starting TEAM OBSIDIAN Platform..." -ForegroundColor Green
Write-Host "===================================================" -ForegroundColor Cyan

# Start Backend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; python run.py"

# Start Frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev"

Write-Host ""
Write-Host "TEAM OBSIDIAN processes launched in separate windows!" -ForegroundColor Green
Write-Host "Backend API: http://localhost:8000 (Swagger docs at /docs)" -ForegroundColor Yellow
Write-Host "Frontend UI: http://localhost:3000" -ForegroundColor Yellow
Write-Host "===================================================" -ForegroundColor Cyan

