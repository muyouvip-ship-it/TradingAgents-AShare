$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

if (-not $env:QMT_MINUTE_OUTPUT_ROOT) {
    $env:QMT_MINUTE_OUTPUT_ROOT = "D:\QMT\data\minute_history"
}

Write-Host "=========================================="
Write-Host "QMT Minute History Sync starting..."
Write-Host "Project Dir: $PWD"
Write-Host "QMT_MINUTE_OUTPUT_ROOT=$env:QMT_MINUTE_OUTPUT_ROOT"
Write-Host "=========================================="

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    Write-Host "[ERROR] Python not found. Please install Python or add it to PATH." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

try {
    if ($pythonCommand.Name -eq "py.exe" -or $pythonCommand.Name -eq "py") {
        py -3 scripts\qmt_minute_history_sync.py --sector all_a --period 1m --start-date 2000-01-01 --end-date (Get-Date -Format 'yyyy-MM-dd') --output-root $env:QMT_MINUTE_OUTPUT_ROOT --format parquet
    } else {
        python scripts\qmt_minute_history_sync.py --sector all_a --period 1m --start-date 2000-01-01 --end-date (Get-Date -Format 'yyyy-MM-dd') --output-root $env:QMT_MINUTE_OUTPUT_ROOT --format parquet
    }
} catch {
    Write-Host "[ERROR] QMT minute history sync failed." -ForegroundColor Red
    Write-Host $_
    Read-Host "Press Enter to exit"
    exit 1
}
