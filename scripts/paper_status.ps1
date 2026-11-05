$ErrorActionPreference = 'Stop'
$repoDir = Split-Path -Parent $PSScriptRoot
Set-Location $repoDir

$processes = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match 'polymarket_study\.paper_live' }

if ($processes) {
    $processes | Select-Object ProcessId, CommandLine | Format-List
} else {
    Write-Host 'Paper-trading non attivo.'
}

$latest = Get-ChildItem data\paper\live_*.jsonl -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latest) {
    Write-Host "Ultimo log: $($latest.FullName)"
    Write-Host "Dimensione: $($latest.Length) byte"
    Get-Content $latest.FullName -Tail 2
}
