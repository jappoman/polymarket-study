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
$skipped = 0
$duplicates = 0
$seen = @{}
Set-Content -LiteralPath $outputPath -Value $null
foreach ($file in $files) {
    foreach ($line in Get-Content -LiteralPath $file.FullName) {
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            try { $row = $line | ConvertFrom-Json } catch { $skipped++; continue }
            if (($row.schema_version -ne 3 -and $row.schema_version -ne 4) -or -not $row.slug -or $row.btc_source -ne 'polymarket_rtds_chainlink_twap_60' -or
                $null -eq $row.chainlink_lag_seconds -or [double]$row.chainlink_lag_seconds -gt 5) {
                $skipped++
                continue
            }
            $key = "$($row.slug)|$($row.observation_type)|$($row.seconds)|$($row.strategy)"
            if ($seen.ContainsKey($key)) {
                $duplicates++
                continue
            }
            $seen[$key] = $true
            Add-Content -LiteralPath $outputPath -Value ($row | ConvertTo-Json -Compress)
            $count++
        }
    }
}

Write-Host "Sessioni unite: $($files.Count)"
Write-Host "Righe salvate: $count"
Write-Host "Righe scartate (vecchie/stale/non valide): $skipped"
Write-Host "Duplicati rimossi: $duplicates"
Write-Host "Output: $outputPath"
