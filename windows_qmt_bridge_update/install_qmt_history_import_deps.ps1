$ErrorActionPreference = "Stop"

Write-Host "[qmt] installing Python dependencies for minute history import..." -ForegroundColor Cyan

$python = "python"

& $python -m pip install --upgrade pip
& $python -m pip install sqlalchemy psycopg2-binary pandas pyarrow fastparquet

Write-Host "[qmt] dependency install completed." -ForegroundColor Green
Write-Host "[qmt] you can now run run_qmt_minute_history_import.ps1 or start a bridge job with import_db=true." -ForegroundColor Green
