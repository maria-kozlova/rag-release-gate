<#
    Windows parity for the Makefile. `make` does not exist in PowerShell.

    Usage:  .\tasks.ps1 unit
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'sync', 'unit', 'live', 'lint', 'fmt', 'ingest', 'evaluate', 'report', 'clean')]
    [string]$Task = 'help'
)

$ErrorActionPreference = 'Stop'

switch ($Task) {
    'help' {
        Write-Host "sync      install the exact locked environment"
        Write-Host "unit      unit checks (NOT the release gate) - no key, no network"
        Write-Host "live      THE RELEASE GATE - costs money, requires OPENROUTER_API_KEY"
        Write-Host "lint      ruff check"
        Write-Host "fmt       ruff format"
        Write-Host "ingest    build data/index/ from the corpus"
        Write-Host "evaluate  one live run (default scope: smoke)"
        Write-Host "report    render the latest run to reports/"
    }
    'sync' { uv sync --locked }
    'unit' { uv run pytest -m "not live" }
    'live' { uv run pytest -m live }
    'lint' { uv run ruff check . }
    'fmt' { uv run ruff format . }
    'ingest' { uv run python -m rag_release_gate.ingest }
    'evaluate' { uv run python -m rag_release_gate.cli evaluate --scope smoke }
    'report' { uv run python -m rag_release_gate.cli report }
    'clean' {
        foreach ($p in @('.pytest_cache', '.ruff_cache', 'data/index/index.npz')) {
            if (Test-Path $p) { Remove-Item -Recurse -Force $p }
        }
    }
}
