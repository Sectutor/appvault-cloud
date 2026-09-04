# ==============================================================================
# AppVault Installer for Windows
# Detects, validates, and installs everything needed to run AppVault locally.
# Usage: irm https://appvault.airepoindex.com/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 defaults to TLS 1.0/1.1, which modern HTTPS servers reject.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
$STEP = 0

function Step($msg) {
    $global:STEP++
    Write-Host "`n[$STEP] $msg" -ForegroundColor Cyan
}

function Success($msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
}

function Warn($msg) {
    Write-Host "  !  $msg" -ForegroundColor Yellow
}

function Fail($msg) {
    Write-Host "  [X] $msg" -ForegroundColor Red
    # throw (not exit) - exit would close the user's PowerShell window
    throw $msg
}

function CheckAdmin() {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) {
        Fail "Administrator rights required. Right-click PowerShell and 'Run as Administrator'."
    }
    Success "Administrator rights confirmed"
}

# ===========================================
# STEP 1: Admin check
# ===========================================
Clear-Host
Write-Host "* AppVault Installer for Windows" -ForegroundColor Cyan
Write-Host "=================================="
CheckAdmin

# ===========================================
# STEP 2: CPU virtualization check
# ===========================================
Step "Checking CPU virtualization support"
$cpu = Get-CimInstance Win32_Processor
$cpuName = $cpu.Name
$hasVT = $cpu.VirtualizationFirmwareEnabled

Write-Host "  CPU: $cpuName"
if ($hasVT) {
    Success "Virtualization (VT-x/AMD-V) is enabled in BIOS"
} else {
    Warn "Virtualization appears disabled in BIOS."
    Warn "  -> For Intel: Enable 'Intel Virtualization Technology (VT-x)' in BIOS"
    Warn "  -> For AMD: Enable 'SVM Mode' in BIOS"
    Warn "  -> Reboot, press F2/Del/ESC during startup to enter BIOS"
    Warn "  -> After enabling, run this installer again"
    $continue = Read-Host "Do you want to continue anyway? (y/N)"
    if ($continue -ne "y") { return }
}

# ===========================================
# STEP 3: Check OS version + WSL support
# ===========================================
Step "Checking Windows version"
$os = Get-CimInstance Win32_OperatingSystem
$ver = [System.Environment]::OSVersion.Version
$build = $ver.Build

if ($build -ge 19041) {
    Success "Windows 10 2004+ (build $build) - WSL2 supported"
} elseif ($build -ge 18362) {
    Warn "Windows 10 1903/1909 (build $build) - WSL2 requires manual update"
} else {
    Fail "Windows version too old (build $build). Need Windows 10 2004+"
}

# ===========================================
# STEP 4: Check/Install WSL2 + Virtual Machine Platform
# ===========================================
Step "Checking Windows Features (WSL2 + Virtual Machine Platform)"
$needsReboot = $false

# Hyper-V does NOT exist on Windows Home and is NOT required by Docker
# Desktop's WSL2 backend - attempting it on Home made dism fail silently and
# set the reboot flag on every run (permanent reboot-loop dead end).
$isHome = ($os.Caption -match "Home")
if ($isHome) {
    Warn "Windows Home edition - skipping Hyper-V (Docker Desktop's WSL2 backend does not need it)"
}

$features = @(
    @{Name="Microsoft-Windows-Subsystem-Linux"; Label="Windows Subsystem for Linux"},
    @{Name="VirtualMachinePlatform"; Label="Virtual Machine Platform"}
)
if (-not $isHome) {
    $features += @{Name="Microsoft-Hyper-V"; Label="Hyper-V"}
}

foreach ($f in $features) {
    # Use dism.exe - Get-WindowsOptionalFeature is Windows PowerShell 5.1 only
    # and fails with "Class not registered" under PowerShell 7.
    try { $out = & dism.exe /online /Get-FeatureInfo /FeatureName:$($f.Name) 2>$null | Out-String } catch { $out = "" }
    if ($out -match "State\s*:\s*Enabled") {
        Success "$($f.Label) - already enabled"
        continue
    }
    if ($out -match "State\s*:\s*EnablePending") {
        Success "$($f.Label) - enable pending (reboot required)"
        $needsReboot = $true
        continue
    }
    Warn "$($f.Label) - not enabled, installing..."
    try { $null = & dism.exe /online /Enable-Feature /FeatureName:$($f.Name) /All /NoRestart 2>$null } catch {}
    $dismRc = $LASTEXITCODE
    if ($dismRc -eq 0 -or $dismRc -eq 3010) {
        $needsReboot = $true
        Success "$($f.Label) - installed (reboot pending)"
    } else {
        # Missing on this edition or enable refused: warn and keep going -
        # never loop the user through reboots for a feature we can't enable.
        Warn "$($f.Label) - could not be enabled (dism exit $dismRc). Continuing; Docker Desktop will request it if truly required."
    }
}

# ===========================================
# STEP 5: Install WSL kernel update if needed
# ===========================================
Step "Setting WSL2 as default and RAM safety limits"
try {
    wsl --set-default-version 2 2>$null
    $wslDefault2 = ($LASTEXITCODE -eq 0)
} catch {
    # PS 5.1 turns redirected native stderr into a terminating error
    $wslDefault2 = $false
}
if ($wslDefault2) {
    Success "WSL2 set as default"
} else {
    Warn "WSL kernel update may be needed."
    Warn "  Download: https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi"
    Warn "  Install the .msi, then run: wsl --set-default-version 2"
}

# Create .wslconfig RAM cap if not present (prevents WSL2 VMMEM from consuming 100% host RAM)
$wslConfigFile = "$env:USERPROFILE\.wslconfig"
$wslTotalGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$wslCapGB = [math]::Max(6, [math]::Min(16, [math]::Floor($wslTotalGB * 0.25)))
$wslCpuCap = [math]::Max(4, [math]::Min(12, [Environment]::ProcessorCount))
$wslConfig = "[wsl2]`nmemory=${wslCapGB}GB`nprocessors=$wslCpuCap"
if (-not (Test-Path $wslConfigFile)) {
    $wslConfig | Out-File -Encoding ascii $wslConfigFile
    Success "Created .wslconfig (WSL2 capped at ${wslCapGB}GB RAM, $wslCpuCap cores)"
} else {
    $cur = Get-Content $wslConfigFile -Raw -ErrorAction SilentlyContinue
    if ($cur -match "memory\s*=\s*(\d+)\s*GB") {
        $curGB = [int]$matches[1]
        if ($curGB -lt $wslCapGB) {
            $wslConfig | Out-File -Encoding ascii $wslConfigFile
            Success "Updated .wslconfig WSL2 cap ${curGB}GB -> ${wslCapGB}GB (takes effect after Docker/WSL restart)"
        } else {
            Success ".wslconfig already capped at ${curGB}GB"
        }
    }
}

# ===========================================
# STEP 6: Check if reboot needed
# ===========================================
if ($needsReboot) {
    Warn "Windows features were installed - a reboot is required."
    $rebootNow = Read-Host "Reboot now? (Y/n)"
    if ($rebootNow -ne "n") {
        Restart-Computer -Confirm:$false
        return
    }
    Write-Host "`nAfter reboot, run this installer again to continue."
    return
}

# ===========================================
# STEP 7: Check/Install Docker Desktop
# ===========================================
Step "Checking Docker Desktop"
# Refresh PATH so a fresh Docker Desktop install is visible in THIS session
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
# Find Docker wherever it lives: machine install, per-user install, or PATH
$dockerCandidates = @(
    "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
    "$env:LOCALAPPDATA\Docker\Docker\resources\bin\docker.exe",
    (Get-Command docker -ErrorAction SilentlyContinue).Source
) | Where-Object { $_ -and (Test-Path $_) }
$docker = if ($dockerCandidates) { @($dockerCandidates)[0] } else { "docker" }
$dockerDesktopExe = @(
    "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
    "$env:LOCALAPPDATA\Docker\Docker\Docker Desktop.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$dockerExists = [bool]$dockerCandidates -or [bool](Get-Command docker -ErrorAction SilentlyContinue)

if ($dockerExists) {
    try { $version = & $docker --version 2>$null } catch { $version = "docker CLI found" }
    Success "Docker already installed: $version"
} else {
    Warn "Docker Desktop not found - downloading..."
    
    # Detect architecture
    if ([Environment]::Is64BitOperatingSystem) {
        $url = "https://desktop.docker.com/win/stable/amd64/Docker%20Desktop%20Installer.exe"
    } else {
        Fail "Docker Desktop requires a 64-bit operating system"
    }
    
    $installer = "$env:TEMP\DockerDesktopInstaller.exe"
    Write-Host "  Downloading (250MB)..."
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    
    Write-Host "  Installing Docker Desktop (may take 5 minutes)..."
    Start-Process $installer -Wait -ArgumentList "install", "--quiet", "--accept-license"
    
    # Verify installation (PATH refresh again - the installer updates PATH)
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
    $dockerCandidates = @(
        "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
        "$env:LOCALAPPDATA\Docker\Docker\resources\bin\docker.exe",
        (Get-Command docker -ErrorAction SilentlyContinue).Source
    ) | Where-Object { $_ -and (Test-Path $_) }
    $docker = if ($dockerCandidates) { @($dockerCandidates)[0] } else { "docker" }
    if ($dockerCandidates) {
        Success "Docker Desktop installed: $(& $docker --version)"
    } else {
        Warn "Docker Desktop installer may still be running in background."
        Warn "  After it finishes, Docker will appear in your Start menu."
    }
}

# ===========================================
# STEP 8: Start Docker if not running
# ===========================================
Step "Starting Docker"
$dockerOK = $false
try {
    $info = & $docker info 2>&1
    $dockerOK = $LASTEXITCODE -eq 0
} catch {}

if (-not $dockerOK) {
    Warn "Docker is not running - starting Docker Desktop..."
    if (-not $dockerDesktopExe) {
        $dockerDesktopExe = (Get-ItemProperty "HKLM:\SOFTWARE\Docker Inc.\Docker Desktop" -ErrorAction SilentlyContinue).AppPath
    }
    if ($dockerDesktopExe -and (Test-Path $dockerDesktopExe)) {
        Start-Process $dockerDesktopExe
    } else {
        Warn "  Docker Desktop.exe not found - please start it from the Start menu."
        Start-Process "shell:AppsFolder\Docker Desktop" -ErrorAction SilentlyContinue
    }
    # An outdated WSL kernel is the #1 reason the engine stays down while the
    # Docker Desktop GUI is up - update it proactively.
    try { wsl --update 2>$null | Out-Null } catch {}
    Write-Host "  Waiting for the Docker engine (up to 5 minutes)..."
    Write-Host "  !  If a dialog appears (license, WSL update, sign-in), accept it - the installer keeps waiting."
    
    $maxWait = 300
    $waited = 0
    while ($waited -lt $maxWait) {
        try {
            & $docker info 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { break }
        } catch {}
        Start-Sleep -Seconds 3
        $waited += 3
        if ($waited % 30 -eq 0) { Write-Host "  ... still waiting ($waited seconds)" }
    }
}

try {
    & $docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Success "Docker is running"
    } else {
        Fail "Docker failed to start. Launch Docker Desktop manually, accept the license, and rerun this installer."
    }
} catch {
    Fail "Docker failed to start. Launch Docker Desktop manually, accept the license, and rerun this installer."
}

# ===========================================
# STEP 9: Pull AppVault Agent and start
# ===========================================
Step "Starting AppVault Agent"
Write-Host "  Pulling AppVault images..."

# Windows PowerShell 5.1 turns redirected native stderr into a terminating
# error when $ErrorActionPreference="Stop", and docker writes to stderr
# whenever the daemon isn't up yet. Relax EAP around the docker calls and
# check $LASTEXITCODE explicitly instead.
if (-not (Test-Path $docker) -and -not (Get-Command $docker -ErrorAction SilentlyContinue)) {
    Fail "Docker CLI not found ($docker) - install Docker Desktop and rerun this installer."
}
$dockerEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"

# Re-check the engine right before pulling (it may have dropped since step 8).
try { & $docker info 2>&1 | Out-Null; $engineOK = ($LASTEXITCODE -eq 0) } catch { $engineOK = $false }
if (-not $engineOK) {
    $ErrorActionPreference = $dockerEAP
    Fail "Docker engine is not running. Launch Docker Desktop, wait for 'Engine running', then run this installer again."
}

# Pull with retry + visible error text (transient network failures are common
# on the first large pulls; a bare exit code hides the real reason).
$script:lastPullError = ""
function Pull-Image([string]$image) {
    for ($try = 1; $try -le 3; $try++) {
        $out = & $docker pull $image 2>&1
        $code = $LASTEXITCODE
        if ($code -eq 0) { return 0 }
        $script:lastPullError = (($out | ForEach-Object { "$($_.ToString())" }) -join " ")
        $script:lastPullError = $script:lastPullError -replace "\x1b\[[0-9;]*m", ""
        if ($try -lt 3) {
            Write-Host "  !  docker pull failed (exit $code) - retrying in 5s..." -ForegroundColor Yellow
            Start-Sleep -Seconds 5
        }
    }
    return 1
}

$pullExit = Pull-Image "ghcr.io/sectutor/appvault-agent:latest"
if ($pullExit -eq 0) { $pullExit = Pull-Image "ghcr.io/sectutor/appvault-releases:v70" }
if ($pullExit -ne 0) {
    $ErrorActionPreference = $dockerEAP
    Fail "Could not pull the AppVault images (exit $pullExit). Docker said: $script:lastPullError Make sure Docker Desktop is running and you have internet access, then run this installer again."
}

# Create data directory
mkdir "$env:USERPROFILE\.appvault\data" -Force | Out-Null
mkdir "$env:USERPROFILE\.appvault\apps" -Force | Out-Null

# Stop/remove only if the container already exists (avoids scary errors on first install)
if (& $docker ps -a --filter "name=^/appvault-agent$" --format '{{.Names}}' 2>$null | Select-String -Quiet "appvault-agent") {
    & $docker stop appvault-agent 2>$null | Out-Null
    & $docker rm appvault-agent 2>$null | Out-Null
}

# Docker socket mount - the Linux VM path works on Linux, macOS, AND Windows
# Docker Desktop (the engine runs in a Linux utility VM, and the Windows named
# pipe cannot be bind-mounted into a Linux container - mounting it left every
# app install failing with "Docker unavailable" despite Docker being detected
# on the host during install).
$sockMount = "/var/run/docker.sock:/var/run/docker.sock"

# Start agent (Unauthenticated for local desktop - zero API key friction)
Write-Host "  Starting AppVault Agent on port 8086..."
& $docker run -d `
  --name appvault-agent `
  --restart unless-stopped `
  -p 8086:8086 `
  -v "$sockMount" `
  -v "$env:USERPROFILE\.appvault\data:/data" `
  -v "$env:USERPROFILE\.appvault\apps:/data/apps" `
  -e AGENT_PORT=8086 `
  -e CENTRAL_URL=https://appvault.airepoindex.com `
  -e AGENT_NAME="$env:COMPUTERNAME-agent" `
  -e STORAGE_PATH=/data `
  -e AGENT_CORS_ORIGINS=http://localhost:8090 `
  ghcr.io/sectutor/appvault-agent:latest
$agentRunExit = $LASTEXITCODE

Write-Host "  Starting App Store on port 8085..."
if (& $docker ps -a --filter "name=^/appvault-heimdall$" --format '{{.Names}}' 2>$null | Select-String -Quiet "appvault-heimdall") {
    & $docker stop appvault-heimdall 2>$null | Out-Null
    & $docker rm appvault-heimdall 2>$null | Out-Null
}

# Clear stale UI files - the store image re-seeds /config/www on first boot
Remove-Item "$env:USERPROFILE\.appvault\heimdall-config\www" -Recurse -Force -ErrorAction SilentlyContinue

& $docker run -d `
  --name appvault-heimdall `
  --restart unless-stopped `
  -p 8085:80 `
  -v /var/run/docker.sock:/var/run/docker.sock `
  -v "$env:USERPROFILE\.appvault\heimdall-config:/config" `
  -e CENTRAL_URL=https://appvault.airepoindex.com `
  -e REMOTE_CATALOG_URL=http://host.docker.internal:8086/api/catalog `
  -e PUID=1000 `
  -e PGID=1000 `
  -e TZ=Etc/UTC `
  ghcr.io/sectutor/appvault-releases:v70
$storeRunExit = $LASTEXITCODE

$ErrorActionPreference = $dockerEAP

if ($agentRunExit -ne 0) { Fail "Could not start the AppVault Agent container (docker exit code $agentRunExit)." }
if ($storeRunExit -ne 0) { Fail "Could not start the App Store container (docker exit code $storeRunExit)." }

# Verify both services actually answer before declaring success.
Step "Verifying services"
$agentUp = $false; $storeUp = $false
$verifyDeadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $verifyDeadline) {
    if (-not $agentUp) {
        try { $h = Invoke-WebRequest "http://localhost:8086/api/health" -UseBasicParsing -TimeoutSec 4; if ($h.StatusCode -eq 200) { $agentUp = $true } } catch {}
    }
    if (-not $storeUp) {
        try { $s = Invoke-WebRequest "http://localhost:8085/" -UseBasicParsing -TimeoutSec 4; if ($s.StatusCode -eq 200) { $storeUp = $true } } catch {}
    }
    if ($agentUp -and $storeUp) { break }
    Start-Sleep -Seconds 5
}
if ($agentUp) { Success "AppVault Agent is online (http://localhost:8086/)" } else { Warn "Agent did not answer yet - check: docker logs appvault-agent" }
if ($storeUp) { Success "App Store is online (http://localhost:8085/)" } else { Warn "App Store did not answer yet - check: docker logs appvault-heimdall" }

# ===========================================
# STEP: Install the AppVault User Dashboard (:8090)
# The full user UI - Apps, Agentic OS, Missions, Memory, Crews, etc. Served
# from a tiny nginx container (no Python requirement on the host).
# ===========================================
Step "Installing AppVault User Dashboard (localhost:8090)"
try {
    $dashDir = "$env:USERPROFILE\.appvault\dashboard"
    New-Item -ItemType Directory -Path $dashDir -Force | Out-Null
    $dashBase = "https://raw.githubusercontent.com/Sectutor/appvault-agent/main/dashboard"
    $idxPath = Join-Path $dashDir "index.html"
    $fontPath = Join-Path $dashDir "msr.woff2"

    Invoke-WebRequest "$dashBase/index.html" -OutFile $idxPath -UseBasicParsing
    Invoke-WebRequest "$dashBase/msr.woff2" -OutFile $fontPath -UseBasicParsing

    # Point the dashboard at the local agent by default (overridable in the UI).
    # Two generations of the default are handled: the old empty-string default
    # and the current port-aware default (which already resolves to :8086 when
    # served from the nginx dashboard on :8090 - the Replace is then a no-op).
    $html = [System.IO.File]::ReadAllText($idxPath, [System.Text.Encoding]::UTF8)
    $html = $html.Replace("var API = localStorage.getItem('appvault_api') || '';",
                          "var API = localStorage.getItem('appvault_api') || 'http://localhost:8086';")
    $html = $html.Replace("var API = localStorage.getItem('appvault_api') || (window.location.port === '8086' ? '' : 'http://localhost:8086');",
                          "var API = localStorage.getItem('appvault_api') || 'http://localhost:8086';")
    [System.IO.File]::WriteAllText($idxPath, $html, (New-Object System.Text.UTF8Encoding($false)))

    if (& $docker ps -a --filter "name=^/appvault-dashboard$" --format '{{.Names}}' 2>$null | Select-String -Quiet "appvault-dashboard") {
        & $docker rm -f appvault-dashboard 2>$null | Out-Null
    }
    # nginx config: static dashboard + same-origin /hermes/ proxy to the
    # hermes-agent (:8095) so the "Hermes (Full)" console embeds cleanly.
    $nginxConf = "$env:USERPROFILE\.appvault\dashboard-nginx.conf"
    $nginxConfBody = @"
server {
    listen       80;
    listen  [::]:80;
    server_name  localhost;
    location / {
        root   /usr/share/nginx/html;
        index  index.html index.htm;
    }
    location /hermes/ {
        proxy_pass http://host.docker.internal:8095/;
        proxy_set_header Host `$host;
        proxy_set_header X-Real-IP `$remote_addr;
        proxy_set_header X-Forwarded-For `$proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Upgrade `$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    error_page 500 502 503 504 /50x.html;
    location = /50x.html { root /usr/share/nginx/html; }
}
"@
    $nginxConfBody | Out-File -Encoding ascii $nginxConf
    & $docker pull nginx:alpine 2>$null | Out-Null
    & $docker run -d --name appvault-dashboard --restart unless-stopped `
      -p 8090:80 `
      -v "${dashDir}:/usr/share/nginx/html:ro" `
      -v "$env:USERPROFILE\.appvault\dashboard-nginx.conf:/etc/nginx/conf.d/default.conf:ro" `
      nginx:alpine 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Success "User Dashboard online at http://localhost:8090/"
    } else {
        Warn "Dashboard container failed to start (non-critical - the store still works). Check: docker logs appvault-dashboard"
    }
} catch {
    Warn "Dashboard setup failed (non-critical): $($_.Exception.Message)"
}
# ===========================================
# STEP: Auto-update - watchtower (agent/store images)
# ===========================================
Step "Installing Auto-Update (watchtower)"
try {
    if (& $docker ps -a --filter "name=^/appvault-watchtower$" --format '{{.Names}}' 2>$null | Select-String -Quiet "appvault-watchtower") {
        & $docker rm -f appvault-watchtower 2>$null | Out-Null
    }
    & $docker pull containrrr/watchtower:latest 2>$null | Out-Null
    & $docker run -d --name appvault-watchtower --restart unless-stopped `
      -v /var/run/docker.sock:/var/run/docker.sock `
      -e WATCHTOWER_CLEANUP=true `
      -e WATCHTOWER_POLL_INTERVAL=3600 `
      -e WATCHTOWER_INCLUDE_STOPPED=false `
      -e DOCKER_API_VERSION=1.40 `
      containrrr/watchtower:latest appvault-agent appvault-heimdall appvault-hermes-agent appvault-crewai-runner appvault-litellm appvault-memory-mcp 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Success "Auto-update enabled - checks hourly for new agent/store images"
    } else {
        Warn "Auto-update setup failed (non-critical). Update manually: docker rm -f appvault-agent && re-run this installer"
    }
} catch {
    Warn "Auto-update setup failed (non-critical): $($_.Exception.Message)"
}

# Register auto-start scheduled task so containers launch on Windows boot
Step "Configuring Windows Startup Task"
try {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -Command ""docker start appvault-agent appvault-heimdall"""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    Register-ScheduledTask -TaskName "AppVaultAutoStart" -Action $action -Trigger $trigger -Description "Auto-start AppVault containers on login" -User $env:USERNAME -ErrorAction SilentlyContinue | Out-Null
    Success "Windows startup task 'AppVaultAutoStart' registered"
} catch {
    Warn "Could not register startup task automatically (non-critical)"
}






# ---- APPVAULT DESKTOP HELPER (embedded) ----
# Desktop Apps tab launcher: local HTTP helper that discovers Start-Menu apps,
# serves icons, and launches them. Installed to %USERPROFILE%\.appvault.
# (base64-embedded - the helper contains its own '@ here-strings)
Step "Installing Desktop App Helper (desktop launcher)"
try {
    $helperDir = "$env:USERPROFILE\.appvault"
    New-Item -ItemType Directory -Path $helperDir -Force | Out-Null
    $helperPath = Join-Path $helperDir "appvault-desktop.ps1"
    $helperContent = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PCMKLkFwcFZhdWx0IERlc2t0b3AgQXBwIEhlbHBlcgpMYXVuY2hlcyBkZXNrdG9wIGFwcGxpY2F0aW9ucyBmcm9tIHRoZSBBcHBWYXVsdCBsYXVuY2hlciAoRGVza3RvcCBBcHBzIHRhYikuCgpNb2RlczoKICBzZXJ2ZSAgICAgIChkZWZhdWx0KSBydW4gdGhlIGxvY2FsIEhUVFAgc2VydmVyIG9uIGh0dHA6Ly9sb2NhbGhvc3Q6ODc5MQogIHN0YXJ0ICAgICAgc3Bhd24gdGhlIHNlcnZlciBoaWRkZW4gYW5kIGV4aXQgKHVzZWQgYnkgdGhlIGFwcHZhdWx0Oi8vIHByb3RvY29sKQogIGxpc3QgICAgICAgcHJpbnQgdGhlIGRlc2t0b3AtYXBwIHJlZ2lzdHJ5IGFzIEpTT04KICBkaXNjb3ZlciAgIHByaW50IGluc3RhbGxlZCBhcHBzIGZvdW5kIGluIHRoZSBTdGFydCBNZW51IGFzIEpTT04KICBhZGQgICAgICAgIC1OYW1lIDxuPiAtUGF0aCA8cD4gIGFkZCBhbiBhcHAgdG8gdGhlIHJlZ2lzdHJ5CiAgcmVtb3ZlICAgICAtSWQgPGlkPiAgcmVtb3ZlIGFuIGFwcAogIGxhdW5jaCAgICAgLUlkIDxpZD4gIGxhdW5jaCBhbiBhcHAKClJlZ2lzdHJ5OiAlVVNFUlBST0ZJTEUlXC5hcHB2YXVsdFxkZXNrdG9wLWFwcHMuanNvbiAocGVyLW1hY2hpbmUgb24gcHVycG9zZSAtCmRlc2t0b3AgYXBwcyBleGlzdCBvbmx5IG9uIHRoZSBtYWNoaW5lIHRoZXkgd2VyZSBpbnN0YWxsZWQgb24pLgoKSFRUUCBBUEkgKENPUlMtZW5hYmxlZCBmb3IgdGhlIEFwcFZhdWx0IHN0b3JlIHBhZ2UpOgogIEdFVCAgL2hlYWx0aCAgICAgICAgICAgICAgICAge29rfQogIEdFVCAgL2FwcHMgICAgICAgICAgICAgICAgICAgcmVnaXN0cnkKICBHRVQgIC9kaXNjb3ZlciAgICAgICAgICAgICAgIFN0YXJ0LU1lbnUgYXBwcwogIEdFVCAgL2ljb24/cD08cGF0aD4gICAgICAgICAgUE5HIGljb24gZm9yIGFuIGV4ZS9sbmsKICBQT1NUIC9hZGQgICAge25hbWUscGF0aH0KICBQT1NUIC9yZW1vdmUge2lkfQogIFBPU1QgL2xhdW5jaCB7aWR9CiM+CnBhcmFtKAogICAgW3N0cmluZ10kTW9kZSA9ICJzZXJ2ZSIsCiAgICBbc3RyaW5nXSROYW1lID0gIiIsCiAgICBbc3RyaW5nXSRQYXRoID0gIiIsCiAgICBbc3RyaW5nXSRJZCA9ICIiCikKCiRFcnJvckFjdGlvblByZWZlcmVuY2UgPSAiU3RvcCIKJFBvcnQgPSA4NzkxCiRCYXNlID0gImh0dHA6Ly9sb2NhbGhvc3Q6JFBvcnQvIgokSGVscGVyRGlyID0gSm9pbi1QYXRoICRlbnY6VVNFUlBST0ZJTEUgIi5hcHB2YXVsdCIKJFJlZ2lzdHJ5UGF0aCA9IEpvaW4tUGF0aCAkSGVscGVyRGlyICJkZXNrdG9wLWFwcHMuanNvbiIKJFNjcmlwdFBhdGggPSAkTXlJbnZvY2F0aW9uLk15Q29tbWFuZC5QYXRoCkFkZC1UeXBlIC1Bc3NlbWJseU5hbWUgU3lzdGVtLkRyYXdpbmcKCmZ1bmN0aW9uIEdldC1SZWdpc3RyeSB7CiAgICBpZiAoVGVzdC1QYXRoICRSZWdpc3RyeVBhdGgpIHsKICAgICAgICB0cnkgewogICAgICAgICAgICAkcmF3ID0gR2V0LUNvbnRlbnQgJFJlZ2lzdHJ5UGF0aCAtUmF3IC1FcnJvckFjdGlvbiBTdG9wCiAgICAgICAgICAgIGlmICgkcmF3IC1hbmQgJHJhdy5UcmltKCkpIHsgcmV0dXJuICgkcmF3IHwgQ29udmVydEZyb20tSnNvbikgfQogICAgICAgIH0gY2F0Y2ggeyB9CiAgICB9CiAgICByZXR1cm4gQCgpCn0KCmZ1bmN0aW9uIFNhdmUtUmVnaXN0cnkoW2FycmF5XSRBcHBzKSB7CiAgICBpZiAoLW5vdCAoVGVzdC1QYXRoICRIZWxwZXJEaXIpKSB7IE5ldy1JdGVtIC1JdGVtVHlwZSBEaXJlY3RvcnkgLVBhdGggJEhlbHBlckRpciAtRm9yY2UgfCBPdXQtTnVsbCB9CiAgICAkanNvbiA9ICRBcHBzIHwgQ29udmVydFRvLUpzb24gLURlcHRoIDYKICAgIFtTeXN0ZW0uSU8uRmlsZV06OldyaXRlQWxsVGV4dCgkUmVnaXN0cnlQYXRoLCAkanNvbiwgW1N5c3RlbS5UZXh0LkVuY29kaW5nXTo6VVRGOCkKfQoKZnVuY3Rpb24gUmVzb2x2ZS1UYXJnZXQoW3N0cmluZ10kcCkgewogICAgIyBub3JtYWxpemUgc2VwYXJhdG9ycyAoZm9yd2FyZCBzbGFzaGVzIHdvcmsgZXZlcnl3aGVyZSBvbiBXaW5kb3dzKQogICAgJHAgPSAkcCAtcmVwbGFjZSAiXFwiLCAiLyIKICAgICMgLmxuayAtPiByZXNvbHZlZCBleGUgcGF0aDsgb3RoZXJ3aXNlIHJldHVybiBhcy1pcwogICAgdHJ5IHsKICAgICAgICBpZiAoJHAgLW1hdGNoICJcLmxuayQiKSB7CiAgICAgICAgICAgICRzaGVsbCA9IE5ldy1PYmplY3QgLUNvbU9iamVjdCBXU2NyaXB0LlNoZWxsCiAgICAgICAgICAgICRzYyA9ICRzaGVsbC5DcmVhdGVTaG9ydGN1dCgkcCkKICAgICAgICAgICAgaWYgKCRzYy5UYXJnZXRQYXRoIC1hbmQgKFRlc3QtUGF0aCAkc2MuVGFyZ2V0UGF0aCkpIHsgcmV0dXJuICRzYy5UYXJnZXRQYXRoIH0KICAgICAgICB9CiAgICB9IGNhdGNoIHsgfQogICAgcmV0dXJuICRwCn0KCmZ1bmN0aW9uIEdldC1EaXNjb3ZlcmVkIHsKICAgICRkaXJzID0gQCgpCiAgICAkcGQgPSAiJGVudjpQcm9ncmFtRGF0YVxNaWNyb3NvZnRcV2luZG93c1xTdGFydCBNZW51XFByb2dyYW1zIgogICAgJGFkID0gIiRlbnY6QVBQREFUQVxNaWNyb3NvZnRcV2luZG93c1xTdGFydCBNZW51XFByb2dyYW1zIgogICAgaWYgKFRlc3QtUGF0aCAkcGQpIHsgJGRpcnMgKz0gJHBkIH0KICAgIGlmIChUZXN0LVBhdGggJGFkKSB7ICRkaXJzICs9ICRhZCB9CiAgICAkc2hlbGwgPSBOZXctT2JqZWN0IC1Db21PYmplY3QgV1NjcmlwdC5TaGVsbAogICAgJHNlZW4gPSBAe30KICAgICRvdXQgPSBAKCkKICAgIGZvcmVhY2ggKCRkIGluICRkaXJzKSB7CiAgICAgICAgR2V0LUNoaWxkSXRlbSAtUGF0aCAkZCAtUmVjdXJzZSAtRmlsdGVyICIqLmxuayIgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29udGludWUgfCBGb3JFYWNoLU9iamVjdCB7CiAgICAgICAgICAgIHRyeSB7CiAgICAgICAgICAgICAgICAkc2MgPSAkc2hlbGwuQ3JlYXRlU2hvcnRjdXQoJF8uRnVsbE5hbWUpCiAgICAgICAgICAgICAgICAkdGFyZ2V0ID0gJHNjLlRhcmdldFBhdGgKICAgICAgICAgICAgICAgIGlmICgtbm90ICR0YXJnZXQpIHsgcmV0dXJuIH0KICAgICAgICAgICAgICAgIGlmICgtbm90IChUZXN0LVBhdGggJHRhcmdldCkpIHsgcmV0dXJuIH0KICAgICAgICAgICAgICAgICRrZXkgPSAkdGFyZ2V0LlRvTG93ZXIoKQogICAgICAgICAgICAgICAgaWYgKCRzZWVuLkNvbnRhaW5zS2V5KCRrZXkpKSB7IHJldHVybiB9CiAgICAgICAgICAgICAgICAkc2Vlblska2V5XSA9ICR0cnVlCiAgICAgICAgICAgICAgICAkb3V0ICs9IFtQU0N1c3RvbU9iamVjdF1AewogICAgICAgICAgICAgICAgICAgIGlkICAgICA9IFtndWlkXTo6TmV3R3VpZCgpLlRvU3RyaW5nKCJOIikKICAgICAgICAgICAgICAgICAgICBuYW1lICAgPSAkXy5CYXNlTmFtZQogICAgICAgICAgICAgICAgICAgIHBhdGggICA9ICgkXy5GdWxsTmFtZSAtcmVwbGFjZSAiXFwiLCAiLyIpCiAgICAgICAgICAgICAgICAgICAgdGFyZ2V0ID0gKCR0YXJnZXQgLXJlcGxhY2UgIlxcIiwgIi8iKQogICAgICAgICAgICAgICAgfQogICAgICAgICAgICB9IGNhdGNoIHsgfQogICAgICAgIH0KICAgIH0KICAgIHJldHVybiAoJG91dCB8IFNvcnQtT2JqZWN0IG5hbWUpCn0KCmZ1bmN0aW9uIEdldC1JY29uQnl0ZXMoW3N0cmluZ10kcCkgewogICAgaWYgKC1ub3QgJHAgLW9yIC1ub3QgKFRlc3QtUGF0aCAkcCkpIHsgcmV0dXJuICRudWxsIH0KICAgICMgU0hHZXRGaWxlSW5mbyByZXNvbHZlcyAubG5rIGljb25zIENPUlJFQ1RMWSAoRXh0cmFjdEFzc29jaWF0ZWRJY29uIHJldHVybnMKICAgICMgYSBnZW5lcmljIDI1MS1ieXRlIGljb24gZm9yIHNob3J0Y3V0cykgYW5kIGdpdmVzIHRoZSBzaGVsbC1zaXplIGljb24uCiAgICAjIE5PVEU6IHRoZSBXaW4zMiBBUEkgUkVKRUNUUyBmb3J3YXJkIHNsYXNoZXMgLSBwYXNzIGEgbmF0aXZlIGJhY2tzbGFzaCBwYXRoLgogICAgJGljb24gPSAkbnVsbDsgJGJtcCA9ICRudWxsOyAkbXMgPSAkbnVsbAogICAgdHJ5IHsKICAgICAgICBpZiAoLW5vdCAkc2NyaXB0OlNoZWxsVHlwZSkgewogICAgICAgICAgICAkc2NyaXB0OlNoZWxsVHlwZSA9IEFkZC1UeXBlIC1NZW1iZXJEZWZpbml0aW9uIEAnCltEbGxJbXBvcnQoInNoZWxsMzIuZGxsIiwgQ2hhclNldCA9IENoYXJTZXQuVW5pY29kZSldCnB1YmxpYyBzdGF0aWMgZXh0ZXJuIEludFB0ciBTSEdldEZpbGVJbmZvKHN0cmluZyBwc3pQYXRoLCB1aW50IGR3RmlsZUF0dHJpYnV0ZXMsIG91dCBTSEZJTEVJTkZPIHBzZmksIHVpbnQgY2JTaXplRmlsZUluZm8sIHVpbnQgdUZsYWdzKTsKW0RsbEltcG9ydCgidXNlcjMyLmRsbCIpXQpwdWJsaWMgc3RhdGljIGV4dGVybiBib29sIERlc3Ryb3lJY29uKEludFB0ciBoSWNvbik7CltTdHJ1Y3RMYXlvdXQoTGF5b3V0S2luZC5TZXF1ZW50aWFsLCBDaGFyU2V0ID0gQ2hhclNldC5Vbmljb2RlKV0KcHVibGljIHN0cnVjdCBTSEZJTEVJTkZPIHsKICAgIHB1YmxpYyBJbnRQdHIgaEljb247CiAgICBwdWJsaWMgaW50IGlJY29uOwogICAgcHVibGljIHVpbnQgZHdBdHRyaWJ1dGVzOwogICAgW01hcnNoYWxBcyhVbm1hbmFnZWRUeXBlLkJ5VmFsVFN0ciwgU2l6ZUNvbnN0ID0gMjYwKV0KICAgIHB1YmxpYyBzdHJpbmcgc3pEaXNwbGF5TmFtZTsKICAgIFtNYXJzaGFsQXMoVW5tYW5hZ2VkVHlwZS5CeVZhbFRTdHIsIFNpemVDb25zdCA9IDgwKV0KICAgIHB1YmxpYyBzdHJpbmcgc3pUeXBlTmFtZTsKfQonQCAtTmFtZSBTaGVsbCAtTmFtZXNwYWNlIFdpbjMyIC1QYXNzVGhydQogICAgICAgIH0KICAgICAgICAkbmF0aXZlID0gJHAgLXJlcGxhY2UgIi8iLCAiXCIKICAgICAgICAjIFNIR0ZJX0lDT04gKDB4MTAwKSB8IFNIR0ZJX1NIRUxMSUNPTlNJWkUgKDB4NCkgPSBzaGVsbC1zaXplIHJlYWwgaWNvbgogICAgICAgICRpbmZvID0gTmV3LU9iamVjdCBXaW4zMi5TaGVsbCtTSEZJTEVJTkZPCiAgICAgICAgJHJlcyA9IFtXaW4zMi5TaGVsbF06OlNIR2V0RmlsZUluZm8oJG5hdGl2ZSwgMCwgW3JlZl0kaW5mbywKICAgICAgICAgICAgICAgW1N5c3RlbS5SdW50aW1lLkludGVyb3BTZXJ2aWNlcy5NYXJzaGFsXTo6U2l6ZU9mKCRpbmZvKSwgMHgxMDQpCiAgICAgICAgaWYgKCRyZXMgLWVxIFtJbnRQdHJdOjpaZXJvIC1vciAkaW5mby5oSWNvbiAtZXEgW0ludFB0cl06Olplcm8pIHsKICAgICAgICAgICAgIyBmYWxsYmFjazogcGxhaW4gYXNzb2NpYXRlZC1pY29uIGV4dHJhY3Rpb24KICAgICAgICAgICAgJGljb24gPSBbU3lzdGVtLkRyYXdpbmcuSWNvbl06OkV4dHJhY3RBc3NvY2lhdGVkSWNvbigkcCkKICAgICAgICAgICAgaWYgKC1ub3QgJGljb24pIHsgcmV0dXJuICRudWxsIH0KICAgICAgICAgICAgJGJtcCA9ICRpY29uLlRvQml0bWFwKCkKICAgICAgICB9IGVsc2UgewogICAgICAgICAgICAkaWNvbiA9IFtTeXN0ZW0uRHJhd2luZy5JY29uXTo6RnJvbUhhbmRsZSgkaW5mby5oSWNvbikKICAgICAgICAgICAgJGJtcCA9ICRpY29uLlRvQml0bWFwKCkKICAgICAgICAgICAgW1dpbjMyLlNoZWxsXTo6RGVzdHJveUljb24oJGluZm8uaEljb24pIHwgT3V0LU51bGwKICAgICAgICB9CiAgICAgICAgJG1zID0gTmV3LU9iamVjdCBTeXN0ZW0uSU8uTWVtb3J5U3RyZWFtCiAgICAgICAgJGJtcC5TYXZlKCRtcywgW1N5c3RlbS5EcmF3aW5nLkltYWdpbmcuSW1hZ2VGb3JtYXRdOjpQbmcpCiAgICAgICAgIyBwbGFpbiByZXR1cm4gKGJ5dGVbXSB1bnJvbGxzIHRvIGJ5dGVzIG9uIHRoZSBwaXBlbGluZSkgLSBjYWxsZXIKICAgICAgICAjIGNvbGxlY3RzIHdpdGggQCgpIGFuZCBjYXN0cyBbYnl0ZVtdXSwgd2hpY2ggaXMgdGhlIHJlbGlhYmxlIHBhdHRlcm4KICAgICAgICByZXR1cm4gJG1zLlRvQXJyYXkoKQogICAgfSBjYXRjaCB7CiAgICAgICAgcmV0dXJuICRudWxsCiAgICB9IGZpbmFsbHkgewogICAgICAgIGlmICgkbXMpIHsgJG1zLkRpc3Bvc2UoKSB9CiAgICAgICAgaWYgKCRibXApIHsgJGJtcC5EaXNwb3NlKCkgfQogICAgfQp9CgpmdW5jdGlvbiBTZW5kLUpzb24oJGN0eCwgW2ludF0kY29kZSwgJG9iaikgewogICAgJGJvZHkgPSAoJG9iaiB8IENvbnZlcnRUby1Kc29uIC1EZXB0aCA4KQogICAgJGJ5dGVzID0gW1N5c3RlbS5UZXh0LkVuY29kaW5nXTo6VVRGOC5HZXRCeXRlcygkYm9keSkKICAgICRyZXNwID0gJGN0eC5SZXNwb25zZQogICAgJHJlc3AuU3RhdHVzQ29kZSA9ICRjb2RlCiAgICAkcmVzcC5Db250ZW50VHlwZSA9ICJhcHBsaWNhdGlvbi9qc29uOyBjaGFyc2V0PXV0Zi04IgogICAgJHJlc3AuSGVhZGVycy5BZGQoIkFjY2Vzcy1Db250cm9sLUFsbG93LU9yaWdpbiIsICIqIikKICAgICRyZXNwLkhlYWRlcnMuQWRkKCJBY2Nlc3MtQ29udHJvbC1BbGxvdy1NZXRob2RzIiwgIkdFVCwgUE9TVCwgT1BUSU9OUyIpCiAgICAkcmVzcC5IZWFkZXJzLkFkZCgiQWNjZXNzLUNvbnRyb2wtQWxsb3ctSGVhZGVycyIsICJDb250ZW50LVR5cGUiKQogICAgJHJlc3AuQ29udGVudExlbmd0aDY0ID0gJGJ5dGVzLkxlbmd0aAogICAgJHJlc3AuT3V0cHV0U3RyZWFtLldyaXRlKCRieXRlcywgMCwgJGJ5dGVzLkxlbmd0aCkKICAgICRyZXNwLk91dHB1dFN0cmVhbS5DbG9zZSgpCn0KCmZ1bmN0aW9uIFNlbmQtRW1wdHkoJGN0eCwgW2ludF0kY29kZSkgewogICAgJHJlc3AgPSAkY3R4LlJlc3BvbnNlCiAgICAkcmVzcC5TdGF0dXNDb2RlID0gJGNvZGUKICAgICRyZXNwLkhlYWRlcnMuQWRkKCJBY2Nlc3MtQ29udHJvbC1BbGxvdy1PcmlnaW4iLCAiKiIpCiAgICAkcmVzcC5IZWFkZXJzLkFkZCgiQWNjZXNzLUNvbnRyb2wtQWxsb3ctTWV0aG9kcyIsICJHRVQsIFBPU1QsIE9QVElPTlMiKQogICAgJHJlc3AuSGVhZGVycy5BZGQoIkFjY2Vzcy1Db250cm9sLUFsbG93LUhlYWRlcnMiLCAiQ29udGVudC1UeXBlIikKICAgICRyZXNwLkNvbnRlbnRMZW5ndGg2NCA9IDAKICAgICRyZXNwLk91dHB1dFN0cmVhbS5DbG9zZSgpCn0KCmZ1bmN0aW9uIEhhbmRsZS1SZXF1ZXN0KCRjdHgpIHsKICAgICRyZXEgPSAkY3R4LlJlcXVlc3QKICAgICRtZXRob2QgPSAkcmVxLkh0dHBNZXRob2QKICAgICRwYXRoID0gJHJlcS5VcmwuQWJzb2x1dGVQYXRoCgogICAgaWYgKCRtZXRob2QgLWVxICJPUFRJT05TIikgeyBTZW5kLUVtcHR5ICRjdHggMjA0OyByZXR1cm4gfQogICAgaWYgKCRwYXRoIC1lcSAiL2hlYWx0aCIpIHsgU2VuZC1Kc29uICRjdHggMjAwIEB7IG9rID0gJHRydWU7IHBpZCA9ICRQSUQgfTsgcmV0dXJuIH0KICAgIGlmICgkcGF0aCAtZXEgIi9hcHBzIikgewogICAgICAgIFNlbmQtSnNvbiAkY3R4IDIwMCBAeyBvayA9ICR0cnVlOyBhcHBzID0gQChHZXQtUmVnaXN0cnkpIH0KICAgICAgICByZXR1cm4KICAgIH0KICAgIGlmICgkcGF0aCAtZXEgIi9kaXNjb3ZlciIpIHsKICAgICAgICBTZW5kLUpzb24gJGN0eCAyMDAgQHsgb2sgPSAkdHJ1ZTsgYXBwcyA9IEAoR2V0LURpc2NvdmVyZWQpIH0KICAgICAgICByZXR1cm4KICAgIH0KICAgIGlmICgkcGF0aCAtZXEgIi9pY29uIiAtYW5kICRtZXRob2QgLWVxICJHRVQiKSB7CiAgICAgICAgJGlkID0gJHJlcS5RdWVyeVN0cmluZ1siaWQiXQogICAgICAgICRhcHAgPSBAKEdldC1SZWdpc3RyeSkgfCBXaGVyZS1PYmplY3QgeyAkXy5pZCAtZXEgJGlkIH0gfCBTZWxlY3QtT2JqZWN0IC1GaXJzdCAxCiAgICAgICAgaWYgKC1ub3QgJGFwcCkgeyBTZW5kLUVtcHR5ICRjdHggMjA0OyByZXR1cm4gfQogICAgICAgIFtieXRlW11dJGJ5dGVzID0gQChHZXQtSWNvbkJ5dGVzICIkKCRhcHAucGF0aCkiKQogICAgICAgIGlmICgtbm90ICRieXRlcyAtb3IgJGJ5dGVzLkxlbmd0aCAtZXEgMCkgeyBTZW5kLUVtcHR5ICRjdHggMjA0OyByZXR1cm4gfQogICAgICAgICRyZXNwID0gJGN0eC5SZXNwb25zZQogICAgICAgICRyZXNwLlN0YXR1c0NvZGUgPSAyMDAKICAgICAgICAkcmVzcC5Db250ZW50VHlwZSA9ICJpbWFnZS9wbmciCiAgICAgICAgJHJlc3AuSGVhZGVycy5BZGQoIkFjY2Vzcy1Db250cm9sLUFsbG93LU9yaWdpbiIsICIqIikKICAgICAgICAkcmVzcC5Db250ZW50TGVuZ3RoNjQgPSAkYnl0ZXMuTGVuZ3RoCiAgICAgICAgJHJlc3AuT3V0cHV0U3RyZWFtLldyaXRlKCRieXRlcywgMCwgJGJ5dGVzLkxlbmd0aCkKICAgICAgICAkcmVzcC5PdXRwdXRTdHJlYW0uQ2xvc2UoKQogICAgICAgIHJldHVybgogICAgfQogICAgaWYgKCRtZXRob2QgLWVxICJQT1NUIiAtYW5kICgkcGF0aCAtZXEgIi9hZGQiIC1vciAkcGF0aCAtZXEgIi9yZW1vdmUiIC1vciAkcGF0aCAtZXEgIi9sYXVuY2giKSkgewogICAgICAgICRyZWFkZXIgPSBOZXctT2JqZWN0IFN5c3RlbS5JTy5TdHJlYW1SZWFkZXIoJHJlcS5JbnB1dFN0cmVhbSwgW1N5c3RlbS5UZXh0LkVuY29kaW5nXTo6VVRGOCkKICAgICAgICAkYm9keSA9ICRyZWFkZXIuUmVhZFRvRW5kKCkKICAgICAgICAkcmVhZGVyLkNsb3NlKCkKICAgICAgICB0cnkgeyAkZGF0YSA9ICRib2R5IHwgQ29udmVydEZyb20tSnNvbiB9IGNhdGNoIHsgU2VuZC1Kc29uICRjdHggNDAwIEB7IG9rID0gJGZhbHNlOyBlcnJvciA9ICJiYWQganNvbiIgfTsgcmV0dXJuIH0KCiAgICAgICAgaWYgKCRwYXRoIC1lcSAiL2FkZCIpIHsKICAgICAgICAgICAgJG5hbWUgPSAiJCgkZGF0YS5uYW1lKSIuVHJpbSgpCiAgICAgICAgICAgICRwID0gKCIkKCRkYXRhLnBhdGgpIi5UcmltKCkgLXJlcGxhY2UgIlxcIiwgIi8iKQogICAgICAgICAgICBpZiAoLW5vdCAkbmFtZSAtb3IgLW5vdCAkcCkgeyBTZW5kLUpzb24gJGN0eCA0MDAgQHsgb2sgPSAkZmFsc2U7IGVycm9yID0gIm5hbWUrcGF0aCByZXF1aXJlZCIgfTsgcmV0dXJuIH0KICAgICAgICAgICAgJHJlZyA9IEAoR2V0LVJlZ2lzdHJ5KQogICAgICAgICAgICAkZXhpc3RpbmcgPSAkcmVnIHwgV2hlcmUtT2JqZWN0IHsgJF8ucGF0aCAtaWVxICRwIH0KICAgICAgICAgICAgaWYgKCRleGlzdGluZykgeyBTZW5kLUpzb24gJGN0eCAyMDAgQHsgb2sgPSAkdHJ1ZTsgYXBwID0gJGV4aXN0aW5nIH07IHJldHVybiB9CiAgICAgICAgICAgICRhcHAgPSBbUFNDdXN0b21PYmplY3RdQHsKICAgICAgICAgICAgICAgIGlkICAgICA9IFtndWlkXTo6TmV3R3VpZCgpLlRvU3RyaW5nKCJOIikKICAgICAgICAgICAgICAgIG5hbWUgICA9ICRuYW1lCiAgICAgICAgICAgICAgICBwYXRoICAgPSAkcAogICAgICAgICAgICAgICAgdGFyZ2V0ID0gKFJlc29sdmUtVGFyZ2V0ICRwKQogICAgICAgICAgICAgICAgYWRkZWQgID0gKEdldC1EYXRlKS5Ub1N0cmluZygieXl5eS1NTS1kZCBISDptbSIpCiAgICAgICAgICAgIH0KICAgICAgICAgICAgJHJlZyArPSAkYXBwCiAgICAgICAgICAgIFNhdmUtUmVnaXN0cnkgJHJlZwogICAgICAgICAgICBTZW5kLUpzb24gJGN0eCAyMDAgQHsgb2sgPSAkdHJ1ZTsgYXBwID0gJGFwcCB9CiAgICAgICAgICAgIHJldHVybgogICAgICAgIH0KICAgICAgICBpZiAoJHBhdGggLWVxICIvcmVtb3ZlIikgewogICAgICAgICAgICAkaWQgPSAiJCgkZGF0YS5pZCkiLlRyaW0oKQogICAgICAgICAgICAkcmVnID0gQChHZXQtUmVnaXN0cnkpIHwgV2hlcmUtT2JqZWN0IHsgJF8uaWQgLW5lICRpZCB9CiAgICAgICAgICAgIFNhdmUtUmVnaXN0cnkgJHJlZwogICAgICAgICAgICBTZW5kLUpzb24gJGN0eCAyMDAgQHsgb2sgPSAkdHJ1ZSB9CiAgICAgICAgICAgIHJldHVybgogICAgICAgIH0KICAgICAgICBpZiAoJHBhdGggLWVxICIvbGF1bmNoIikgewogICAgICAgICAgICAkaWQgPSAiJCgkZGF0YS5pZCkiLlRyaW0oKQogICAgICAgICAgICAkYXBwID0gQChHZXQtUmVnaXN0cnkpIHwgV2hlcmUtT2JqZWN0IHsgJF8uaWQgLWVxICRpZCB9IHwgU2VsZWN0LU9iamVjdCAtRmlyc3QgMQogICAgICAgICAgICBpZiAoLW5vdCAkYXBwKSB7IFNlbmQtSnNvbiAkY3R4IDQwNCBAeyBvayA9ICRmYWxzZTsgZXJyb3IgPSAiYXBwIG5vdCBmb3VuZCIgfTsgcmV0dXJuIH0KICAgICAgICAgICAgJHRhcmdldCA9ICRhcHAucGF0aAogICAgICAgICAgICBpZiAoLW5vdCAoVGVzdC1QYXRoICR0YXJnZXQpKSB7IFNlbmQtSnNvbiAkY3R4IDQwNCBAeyBvayA9ICRmYWxzZTsgZXJyb3IgPSAiYXBwIG5vdCBmb3VuZCBvbiBkaXNrOiAkdGFyZ2V0IiB9OyByZXR1cm4gfQogICAgICAgICAgICAkcCA9IFN0YXJ0LVByb2Nlc3MgLUZpbGVQYXRoICR0YXJnZXQgLVBhc3NUaHJ1CiAgICAgICAgICAgICMgbGF1bmNoZWQgZnJvbSBhIGJhY2tncm91bmQgaGVscGVyOiB0aGUgd2luZG93IG9wZW5zIGJ1dCBpcyBOT1QKICAgICAgICAgICAgIyBhY3RpdmF0ZWQgKHNpdHMgbWluaW1pemVkL2JlaGluZCkgLSBBcHBBY3RpdmF0ZSBicmluZ3MgaXQgdXAKICAgICAgICAgICAgdHJ5IHsKICAgICAgICAgICAgICAgIFN0YXJ0LVNsZWVwIC1NaWxsaXNlY29uZHMgNzAwCiAgICAgICAgICAgICAgICAkd3MgPSBOZXctT2JqZWN0IC1Db21PYmplY3QgV1NjcmlwdC5TaGVsbAogICAgICAgICAgICAgICAgJG51bGwgPSAkd3MuQXBwQWN0aXZhdGUoJHAuSWQpCiAgICAgICAgICAgIH0gY2F0Y2ggeyB9CiAgICAgICAgICAgIFNlbmQtSnNvbiAkY3R4IDIwMCBAeyBvayA9ICR0cnVlOyBsYXVuY2hlZCA9ICRhcHAubmFtZTsgcGlkID0gJHAuSWQgfQogICAgICAgICAgICByZXR1cm4KICAgICAgICB9CiAgICB9CiAgICBTZW5kLUpzb24gJGN0eCA0MDQgQHsgb2sgPSAkZmFsc2U7IGVycm9yID0gIm5vdCBmb3VuZDogJHBhdGgiIH0KfQoKZnVuY3Rpb24gU3RhcnQtU2VydmVyIHsKICAgICRsaXN0ZW5lciA9IE5ldy1PYmplY3QgU3lzdGVtLk5ldC5IdHRwTGlzdGVuZXIKICAgICMgQmluZCB0aGUgVVJMLUFDTCdkIHdpbGRjYXJkIHByZWZpeCAodGhlIGluc3RhbGxlciByZWdpc3RlcnMKICAgICMgImh0dHAgYWRkIHVybGFjbCB1cmw9aHR0cDovLys6ODc5MS8gdXNlcj1FdmVyeW9uZSIpLiBBIHBsYWluCiAgICAjICJodHRwOi8vbG9jYWxob3N0Ojg3OTEvIiBwcmVmaXggZ2V0cyBBQ0NFU1MgREVOSUVEIG9uY2UgdGhhdCBBQ0wKICAgICMgcmVzZXJ2YXRpb24gZXhpc3RzIC0gd2hpY2ggbWFkZSAiU3RhcnQgRGVza3RvcCBIZWxwZXIiIHNpbGVudGx5IGZhaWwuCiAgICAjICIrIiBhbHNvIGxldHMgY29udGFpbmVycyByZWFjaCB0aGUgaGVscGVyIHZpYSBob3N0LmRvY2tlci5pbnRlcm5hbC4KICAgICRsaXN0ZW5lci5QcmVmaXhlcy5BZGQoImh0dHA6Ly8rOjg3OTEvIikKICAgIHRyeSB7ICRsaXN0ZW5lci5TdGFydCgpIH0gY2F0Y2ggewogICAgICAgICMgcG9ydCBhbHJlYWR5IGluIHVzZSAtPiBhbm90aGVyIGhlbHBlciBpcyBydW5uaW5nCiAgICAgICAgV3JpdGUtSG9zdCAiaGVscGVyIGFscmVhZHkgcnVubmluZzogJCgkXy5FeGNlcHRpb24uTWVzc2FnZSkiCiAgICAgICAgcmV0dXJuCiAgICB9CiAgICBXcml0ZS1Ib3N0ICJBcHBWYXVsdCBEZXNrdG9wIEhlbHBlciBsaXN0ZW5pbmcgb24gJEJhc2UgKHBpZCAkUElEKSIKICAgIHdoaWxlICgkdHJ1ZSkgewogICAgICAgIHRyeSB7CiAgICAgICAgICAgICRjdHggPSAkbGlzdGVuZXIuR2V0Q29udGV4dCgpCiAgICAgICAgICAgIHRyeSB7IEhhbmRsZS1SZXF1ZXN0ICRjdHggfSBjYXRjaCB7IHRyeSB7IFNlbmQtSnNvbiAkY3R4IDUwMCBAeyBvayA9ICRmYWxzZTsgZXJyb3IgPSAiJCgkXy5FeGNlcHRpb24uTWVzc2FnZSkiIH0gfSBjYXRjaCB7IH0gfQogICAgICAgIH0gY2F0Y2ggewogICAgICAgICAgICBTdGFydC1TbGVlcCAtTWlsbGlzZWNvbmRzIDIwMAogICAgICAgIH0KICAgIH0KfQoKZnVuY3Rpb24gU3RhcnQtSGlkZGVuIHsKICAgICMgc3Bhd24gdGhlIHNlcnZlciBoaWRkZW4gYW5kIGV4aXQgKHByb3RvY29sLWhhbmRsZXIgZW50cnkpCiAgICAkcnVubmluZyA9IEdldC1OZXRUQ1BDb25uZWN0aW9uIC1Mb2NhbFBvcnQgJFBvcnQgLVN0YXRlIExpc3RlbiAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZQogICAgaWYgKC1ub3QgJHJ1bm5pbmcpIHsKICAgICAgICAjIGtpbGwgYW55IHN0YWxlIGhlbHBlciBwcm9jZXNzIGZpcnN0IChhIGRlYWQgaW5zdGFuY2UgY2FuIGxlYXZlCiAgICAgICAgIyBIVFRQLnN5cyBzdGF0ZSB0aGF0IGJsb2NrcyBhIGZyZXNoIGJpbmQpCiAgICAgICAgR2V0LUNpbUluc3RhbmNlIFdpbjMyX1Byb2Nlc3MgLUZpbHRlciAiTmFtZT0ncG93ZXJzaGVsbC5leGUnIiAtRXJyb3JBY3Rpb24gU2lsZW50bHlDb250aW51ZSB8CiAgICAgICAgICAgIFdoZXJlLU9iamVjdCB7ICRfLkNvbW1hbmRMaW5lIC1tYXRjaCAnYXBwdmF1bHQtZGVza3RvcFwucHMxJyB9IHwKICAgICAgICAgICAgRm9yRWFjaC1PYmplY3QgeyBTdG9wLVByb2Nlc3MgLUlkICRfLlByb2Nlc3NJZCAtRm9yY2UgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29udGludWUgfQogICAgICAgIFN0YXJ0LVNsZWVwIC1NaWxsaXNlY29uZHMgNTAwCiAgICAgICAgU3RhcnQtUHJvY2VzcyBwb3dlcnNoZWxsLmV4ZSAtQXJndW1lbnRMaXN0IEAoCiAgICAgICAgICAgICItTm9Qcm9maWxlIiwgIi1FeGVjdXRpb25Qb2xpY3kiLCAiQnlwYXNzIiwgIi1XaW5kb3dTdHlsZSIsICJIaWRkZW4iLAogICAgICAgICAgICAiLUZpbGUiLCAiYCIkU2NyaXB0UGF0aGAiIiwgInNlcnZlIgogICAgICAgICkgLVdpbmRvd1N0eWxlIEhpZGRlbgogICAgICAgICMgZ2l2ZSBpdCBhIG1vbWVudCB0byBiaW5kLCB0aGVuIHJlcG9ydCAodGhlIHByb3RvY29sIGhhbmRsZXIgcnVucwogICAgICAgICMgaGlkZGVuIC0gdGhlIHN0b3JlIFVJIHBvbGxzIC9oZWFsdGggYWZ0ZXJ3YXJkcyBhbnl3YXkpCiAgICAgICAgU3RhcnQtU2xlZXAgLU1pbGxpc2Vjb25kcyAxMjAwCiAgICB9Cn0KCiMgLS0gQ0xJIG1vZGVzIC0tCnN3aXRjaCAoJE1vZGUpIHsKICAgICJzZXJ2ZSIgICAgeyBTdGFydC1TZXJ2ZXI7IGJyZWFrIH0KICAgICJzdGFydCIgICAgeyBTdGFydC1IaWRkZW47IGJyZWFrIH0KICAgICJsaXN0IiAgICAgeyBAKEdldC1SZWdpc3RyeSkgfCBDb252ZXJ0VG8tSnNvbiAtRGVwdGggNjsgYnJlYWsgfQogICAgImRpc2NvdmVyIiB7IEAoR2V0LURpc2NvdmVyZWQpIHwgQ29udmVydFRvLUpzb24gLURlcHRoIDY7IGJyZWFrIH0KICAgICJhZGQiICAgICAgewogICAgICAgICRyZWcgPSBAKEdldC1SZWdpc3RyeSkKICAgICAgICAkYXBwID0gW1BTQ3VzdG9tT2JqZWN0XUB7IGlkID0gW2d1aWRdOjpOZXdHdWlkKCkuVG9TdHJpbmcoIk4iKTsgbmFtZSA9ICROYW1lOyBwYXRoID0gJFBhdGg7IHRhcmdldCA9IChSZXNvbHZlLVRhcmdldCAkUGF0aCk7IGFkZGVkID0gKEdldC1EYXRlKS5Ub1N0cmluZygieXl5eS1NTS1kZCBISDptbSIpIH0KICAgICAgICAkcmVnICs9ICRhcHA7IFNhdmUtUmVnaXN0cnkgJHJlZwogICAgICAgICRhcHAgfCBDb252ZXJ0VG8tSnNvbjsgYnJlYWsKICAgIH0KICAgICJyZW1vdmUiICAgeyBTYXZlLVJlZ2lzdHJ5IChAKEdldC1SZWdpc3RyeSkgfCBXaGVyZS1PYmplY3QgeyAkXy5pZCAtbmUgJElkIH0pOyAicmVtb3ZlZCAkSWQiOyBicmVhayB9CiAgICAibGF1bmNoIiAgIHsKICAgICAgICAkYXBwID0gQChHZXQtUmVnaXN0cnkpIHwgV2hlcmUtT2JqZWN0IHsgJF8uaWQgLWVxICRJZCB9IHwgU2VsZWN0LU9iamVjdCAtRmlyc3QgMQogICAgICAgIGlmICgkYXBwKSB7IFN0YXJ0LVByb2Nlc3MgLUZpbGVQYXRoICRhcHAucGF0aDsgImxhdW5jaGVkICQoJGFwcC5uYW1lKSIgfSBlbHNlIHsgIm5vdCBmb3VuZCIgfQogICAgICAgIGJyZWFrCiAgICB9CiAgICBkZWZhdWx0ICAgIHsgU3RhcnQtU2VydmVyIH0KfQo='))
    [System.IO.File]::WriteAllText($helperPath, $helperContent, [System.Text.Encoding]::UTF8)
    # auto-start at login (hidden window)
    $da = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$helperPath`" serve"
    Register-ScheduledTask -TaskName "AppVaultDesktopHelper" -Action $da -Trigger (New-ScheduledTaskTrigger -AtLogOn) -User $env:USERNAME -Description "AppVault desktop app launcher helper" -ErrorAction SilentlyContinue | Out-Null
    Start-ScheduledTask -TaskName "AppVaultDesktopHelper" -ErrorAction SilentlyContinue
    # appvault:// protocol handler (start helper on demand from the store page)
    New-Item "HKCU:\Software\Classes\appvault\shell\open\command" -Force | Out-Null
    Set-ItemProperty "HKCU:\Software\Classes\appvault\shell\open\command" "(default)" "`"$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"& '$helperPath' start`""
    # URL ACL so the helper (user-session process) can bind http://+:8791/ -
    # required for containers reaching it via host.docker.internal
    netsh http add urlacl url=http://+:8791/ user=Everyone | Out-Null
    Success "Desktop helper installed - auto-starts at login"
} catch {
    Warn "Desktop helper setup failed (non-critical): $($_.Exception.Message)"
}

# ===========================================
# DONE
# ===========================================
Write-Host "`n" -NoNewline
Write-Host "==================================" -ForegroundColor Green
Write-Host "[OK] AppVault is ready!" -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Green
Write-Host "`n"
Write-Host "  >> AppVault Dashboard:  http://localhost:8090/" -ForegroundColor Cyan
Write-Host "  [pkg] App Store:           http://localhost:8085/" -ForegroundColor Cyan
Write-Host "  *  Agent API:           http://localhost:8086/" -ForegroundColor Cyan
Write-Host "`n"
if ($Host.UI.RawUI -and $Host.Name -notlike "*NonInteractive*") {
    Write-Host "  Press any key to open AppVault..."
    try { $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") } catch {}
}
try { Start-Process "http://localhost:8090/" } catch {}
