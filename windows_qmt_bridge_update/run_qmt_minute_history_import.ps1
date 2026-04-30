$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

if (-not $env:QMT_MINUTE_OUTPUT_ROOT) {
    $env:QMT_MINUTE_OUTPUT_ROOT = "D:\QMT\data\minute_history"
}

if (-not $env:QMT_MINUTE_DATABASE_URL) {
    Write-Host "[ERROR] Missing QMT_MINUTE_DATABASE_URL environment variable." -ForegroundColor Red
    Write-Host "Example:"
    Write-Host 'setx QMT_MINUTE_DATABASE_URL "postgresql://user:password@host:5432/dbname"'
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "=========================================="
Write-Host "QMT Minute History Import starting..."
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
    $commonArgs = @(
        "scripts\qmt_minute_history_sync.py",
        "--sector", "all_a",
        "--period", "1m",
        "--start-date", "2000-01-01",
        "--end-date", (Get-Date -Format 'yyyy-MM-dd'),
        "--output-root", $env:QMT_MINUTE_OUTPUT_ROOT,
        "--format", "parquet",
        "--import-db",
        "--import-existing-only",
        "--database-url", $env:QMT_MINUTE_DATABASE_URL
    )

    if ($pythonCommand.Name -eq "py.exe" -or $pythonCommand.Name -eq "py") {
        py -3 -u @commonArgs
    } else {
        python -u @commonArgs
    }
} catch {
    Write-Host "[ERROR] QMT minute history import failed." -ForegroundColor Red
    Write-Host $_
    Read-Host "Press Enter to exit"
    exit 1
}
