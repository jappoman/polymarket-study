param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputPath
)

$ErrorActionPreference = 'Stop'
$repoDir = Split-Path -Parent $PSScriptRoot
Set-Location $repoDir

$outputPath = $InputPath -replace '\.jsonl$', '_settled.jsonl'
python -m polymarket_study.settle_paper --input $InputPath --output $outputPath
Write-Host "Output: $outputPath"
