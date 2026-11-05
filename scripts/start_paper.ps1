param(
    [int]$Duration = 86400,
    [double]$Threshold = 0.0002,
    [double]$MaxAsk = 0.55
)

$ErrorActionPreference = 'Stop'
$repoDir = Split-Path -Parent $PSScriptRoot
Set-Location $repoDir

$paperDir = Join-Path $repoDir 'data\paper'
New-Item -ItemType Directory -Force -Path $paperDir | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH-mm-ssZ')
$output = Join-Path $paperDir ("live_{0}.jsonl" -f $stamp)

Write-Host "Paper-trading avviato."
Write-Host "Log: $output"
Write-Host "Durata: ${Duration}s | soglia: $Threshold | max ask: $MaxAsk"
Write-Host "Premi Ctrl+C per interrompere."

python -m polymarket_study.paper_live `
    --duration $Duration `
    --output $output `
    --threshold $Threshold `
    --max-ask $MaxAsk
