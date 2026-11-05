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
    Sort-Object Name -Descending | Select-Object -First 1
if ($latest) {
    Write-Host "Ultimo log: $($latest.FullName)"
    Write-Host "Dimensione: $($latest.Length) byte"
    Get-Content $latest.FullName -Tail 2
}

$supervisor = Get-ChildItem data\paper\supervisor_*.log -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
if ($supervisor) {
    Write-Host "Ultimo supervisore: $($supervisor.FullName)"
    Get-Content $supervisor.FullName -Tail 3
}
