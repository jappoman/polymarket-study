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
    $tail = Get-Content $latest.FullName -Tail 2000 |
        ForEach-Object { try { $_ | ConvertFrom-Json } catch { $null } } |
        Where-Object { $_ }
    $signals = @($tail | Where-Object { $_.observation_type -eq 'signal' })
    if ($signals.Count -gt 0) {
        $schemas = ($signals | Group-Object schema_version | ForEach-Object { "$($_.Name):$($_.Count)" }) -join ', '
        $bothBooks = @($signals | Where-Object { $null -ne $_.up_ask -and $null -ne $_.down_ask }).Count
        $asOfViolations = @($signals | Where-Object {
            $row = $_
            $bookTimes = @($row.up_book_ts, $row.down_book_ts) | Where-Object { $_ }
            $bookTimes | ForEach-Object {
                $ts = [double]$_ / 1000
                $ts -gt ([double]$row.start_ts + [double]$row.seconds)
            } | Where-Object { $_ }
        }).Count
        Write-Host "Ultime righe: schema=$schemas | signal=$($signals.Count) | Up+Down best ask=$bothBooks | look-ahead rilevati=$asOfViolations"
    }
    Get-Content $latest.FullName -Tail 2
}

$supervisor = Get-ChildItem data\paper\supervisor_*.log -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
if ($supervisor) {
    Write-Host "Ultimo supervisore: $($supervisor.FullName)"
    Get-Content $supervisor.FullName -Tail 3
}
