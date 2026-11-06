param(
    [string]$MergedPath = 'data\paper\all_sessions.jsonl',
    [string]$SettledPath = 'data\paper\all_sessions_settled_v2.jsonl',
    [string]$AnalysisPath = 'data\paper\paper_analysis.json'
)

$ErrorActionPreference = 'Stop'
$repoDir = Split-Path -Parent $PSScriptRoot
Set-Location $repoDir

& "$PSScriptRoot\merge_paper.ps1" -Output $MergedPath
python -m polymarket_study.settle_paper --input $MergedPath --output $SettledPath
python -m polymarket_study.analyze_paper --input $SettledPath --output $AnalysisPath
