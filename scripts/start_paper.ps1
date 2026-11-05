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
$supervisorStamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH-mm-ssZ')
$supervisorLog = Join-Path $paperDir ("supervisor_{0}.log" -f $supervisorStamp)

Write-Host "Paper-trading supervisionato avviato."
Write-Host "Durata: ${Duration}s | soglia: $Threshold | max ask: $MaxAsk"
Write-Host "Se il recorder termina per un errore, verrà riavviato automaticamente."
Write-Host "Premi Ctrl+C per interrompere tutto."

$deadline = [DateTime]::UtcNow.AddSeconds($Duration)
$attempt = 0
while ([DateTime]::UtcNow -lt $deadline) {
    $attempt++
    $remaining = [Math]::Max(1, [int]([Math]::Ceiling(($deadline - [DateTime]::UtcNow).TotalSeconds)))
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH-mm-ssZ')
    $output = Join-Path $paperDir ("live_{0}.jsonl" -f $stamp)
    $startLine = "$(Get-Date -Format o) attempt=$attempt duration=$remaining output=$output"
    Add-Content -LiteralPath $supervisorLog -Value $startLine
    Write-Host "[supervisor] avvio tentativo $attempt | log: $output"

    & python -u -m polymarket_study.paper_live `
        --duration $remaining `
        --output $output `
        --threshold $Threshold `
        --max-ask $MaxAsk
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Add-Content -LiteralPath $supervisorLog -Value "$(Get-Date -Format o) exit=0"
        break
    }

    Add-Content -LiteralPath $supervisorLog -Value "$(Get-Date -Format o) exit=$exitCode restart_in=15s"
    Write-Warning "[supervisor] recorder terminato con exit code $exitCode; nuovo tentativo tra 15 secondi."
    if ([DateTime]::UtcNow.AddSeconds(15) -lt $deadline) {
        Start-Sleep -Seconds 15
    }
}

Write-Host "[supervisor] raccolta terminata. Log supervisore: $supervisorLog"
