$envLines = Get-Content 'C:\Users\emman\Projects\coolify-mcp\.env' | Where-Object { $_ -match '=' -and $_ -notmatch '^\s*#' }
$tok = $null
foreach ($l in $envLines) {
    $p = $l -split '=', 2
    if ($p[0].Trim() -match 'TOKEN|KEY') { $tok = $p[1].Trim().Trim('"'); break }
}
$headers = @{ Authorization = 'Bearer ' + $tok }
$resp = Invoke-RestMethod -Uri 'http://169.58.9.191:8000/api/v1/deploy?uuid=uuc85ypiss34ajm4qcjfeekx' -Method Post -Headers $headers -TimeoutSec 60
Write-Output ("deployment queued: " + $resp.deployments[0].deployment_uuid)
$uuid = $resp.deployments[0].deployment_uuid
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 15
    try {
        $d = Invoke-RestMethod -Uri "http://169.58.9.191:8000/api/v1/deployments/$uuid" -Headers $headers -TimeoutSec 30
        Write-Output ("poll {0}: status={1}" -f ($i + 1), $d.status)
        if ($d.status -in @('finished', 'success', 'failed', 'error')) { break }
    } catch {
        Write-Output ("poll {0}: error {1}" -f ($i + 1), $_.Exception.Message)
    }
}
