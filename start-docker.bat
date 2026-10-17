@echo off
echo Starting ContractLens on Docker...
cd /d E:\2026-27\m0347
docker-compose up -d contractlens
echo.
echo ContractLens is running at http://localhost:5000
echo.
echo To view logs: docker-compose logs -f
echo To stop: docker-compose down
pause
