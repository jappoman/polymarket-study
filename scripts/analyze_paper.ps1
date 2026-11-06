param(
    [string]$InputPath = 'data\paper\all_sessions_settled.jsonl',
    [string]$OutputPath = 'data\paper\paper_analysis.json'
)

$ErrorActionPreference = 'Stop'
$repoDir = Split-Path -Parent $PSScriptRoot
Set-Location $repoDir
python -m polymarket_study.analyze_paper --input $InputPath --output $OutputPath
