param(
    [string]$Output = 'data\paper\all_sessions.jsonl'
)

$ErrorActionPreference = 'Stop'
$repoDir = Split-Path -Parent $PSScriptRoot
Set-Location $repoDir

$outputPath = Join-Path $repoDir $Output
$outputDir = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$files = Get-ChildItem data\paper\live_*.jsonl -File -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -ne (Resolve-Path $outputPath -ErrorAction SilentlyContinue).Path } |
    Sort-Object Name

if (-not $files) {
    throw 'Nessun log live_*.jsonl trovato in data\paper.'
}

$count = 0
Set-Content -LiteralPath $outputPath -Value $null
foreach ($file in $files) {
    foreach ($line in Get-Content -LiteralPath $file.FullName) {
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            Add-Content -LiteralPath $outputPath -Value $line
            $count++
        }
    }
}

Write-Host "Sessioni unite: $($files.Count)"
Write-Host "Righe salvate: $count"
Write-Host "Output: $outputPath"
