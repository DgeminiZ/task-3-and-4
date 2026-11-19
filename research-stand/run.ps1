param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "down", "smoke", "experiment", "analyze", "all", "local", "calibrate")]
    [string]$Command = "all",
    [string]$Config = "configs/experiment.yaml",
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

function Invoke-Python {
    param([string[]]$Arguments)
    & python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "python $($Arguments -join ' ') failed" }
}

switch ($Command) {
    "up" {
        docker compose up -d --build sut
    }
    "down" {
        docker compose --profile run --profile analysis down -v
    }
    "smoke" {
        docker compose run --rm --entrypoint python runner scripts/smoke.py --base-url http://sut
    }
    "experiment" {
        $args = @("runner/run_experiment.py", "--mode", "docker", "--config", $Config)
        if ($Limit -gt 0) { $args += @("--limit", "$Limit") }
        Invoke-Python $args
    }
    "local" {
        $args = @("runner/run_experiment.py", "--mode", "local", "--config", $Config)
        if ($Limit -gt 0) { $args += @("--limit", "$Limit") }
        Invoke-Python $args
    }
    "analyze" {
        Invoke-Python @("analysis/analyze.py")
    }
    "all" {
        Invoke-Python @("scripts/smoke.py", "--base-url", "http://127.0.0.1:8080")
        Invoke-Python @("runner/run_experiment.py", "--mode", "local", "--config", $Config)
        Invoke-Python @("analysis/analyze.py")
    }
    "calibrate" {
        Invoke-Python @("runner/run_experiment.py", "--mode", "local", "--config", "configs/calibration.yaml", "--force")
        Invoke-Python @("analysis/analyze.py")
    }
}
