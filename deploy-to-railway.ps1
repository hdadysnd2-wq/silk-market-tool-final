#Requires -Version 5.1
<#
.SYNOPSIS
    Deploy the whole Silk United platform to Railway from GitHub — end to end,
    with no manual dashboard steps.

.DESCRIPTION
    Silk United is a monorepo: one GitHub repo → four services (api · worker ·
    beat · web) that share one Postgres and one Redis. This script provisions all
    of it headlessly:

      1. Ensure the Railway CLI (installs via `npm i -g @railway/cli` if missing).
      2. Authenticate (`railway login`, or RAILWAY_TOKEN / RAILWAY_API_TOKEN).
      3. Resolve the target repo (owner/repo) from -Repo, the origin remote, or a prompt.
      4. Create (or link) a Railway project.
      5. Provision Postgres + Redis.
      6. Create the four GitHub-linked services with all their variables.
      7. Generate public domains for api and web.

    How the usual manual steps are avoided
    --------------------------------------
    The Railway CLI cannot set a service's Root Directory or config-as-code path,
    so this script sidesteps both:
      • Every service builds from the REPOSITORY ROOT (Root Directory stays empty,
        which is the default), so nothing to set.
      • Each service selects its Dockerfile with the RAILWAY_DOCKERFILE_PATH
        service variable (api/worker/beat → apps/api/Dockerfile, web →
        apps/web/Dockerfile) — set from the CLI, not the dashboard.
      • api, worker, and beat share ONE image; the SILK_ROLE variable selects the
        entrypoint (api | worker | beat), so no per-service start command is needed.
      • Shared secrets are wired as Railway reference variables
        (${{Postgres.DATABASE_URL}}, ${{api.RAILWAY_PUBLIC_DOMAIN}}, …).

    NOTE: this depends on the Dockerfiles building from the repo root and on the
    SILK_ROLE / RAILWAY_DOCKERFILE_PATH conventions — those changes must be on the
    branch Railway deploys.

.PARAMETER Repo
    GitHub repository in owner/repo form. Falls back to the origin remote, then a prompt.

.PARAMETER Branch
    Branch Railway auto-deploys from (default: the repo's default branch).

.PARAMETER ProjectName
    Name for the Railway project created by `railway init`. Default: silk-united.

.PARAMETER Link
    Link to the Railway project already associated with this directory instead of
    creating a new one.

.EXAMPLE
    .\deploy-to-railway.ps1 owner/repo

.NOTES
    Non-interactive auth (CI): set RAILWAY_TOKEN (project token) or
    RAILWAY_API_TOKEN (account token) and the login step is skipped.
    Vendor keys (ANTHROPIC_API_KEY, SMARTLEAD_API_KEY, OAuth, …) are all optional —
    blank keeps the deterministic mock adapter. Add real keys later in the dashboard.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Repo,

    [string]$Branch,

    [string]$ProjectName = 'silk-united',

    [switch]$Link
)

$ErrorActionPreference = 'Stop'
# We check $LASTEXITCODE after every native call, so opt out of PowerShell 7.4+
# auto-throwing on non-zero exits (and it is harmless on Windows PowerShell 5.1).
$PSNativeCommandUseErrorActionPreference = $false

# ----------------------------------------------------------------------------
# Output helpers
# ----------------------------------------------------------------------------
function Write-Step { param([string]$Message) Write-Host "`n$Message" -ForegroundColor Cyan }
function Write-Info { param([string]$Message) Write-Host "  -> $Message" -ForegroundColor DarkGray }
function Write-Ok   { param([string]$Message) Write-Host "  [ok] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Warning $Message }
function Fail       { param([string]$Message) throw $Message }

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# Run a native CLI attached to the console without letting its stderr be promoted
# to a terminating error under $ErrorActionPreference='Stop' (a Windows PowerShell
# 5.1 gotcha). Call as a STATEMENT and read $LASTEXITCODE afterwards.
function Invoke-Native {
    param([Parameter(Mandatory)][scriptblock]$ScriptBlock)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $ScriptBlock } finally { $ErrorActionPreference = $prevEap }
}

# A url-safe 64-char hex secret, shared by api/worker/beat (it signs tokens and
# derives the mailbox token-encryption key, so it MUST be identical across them).
function New-SecretKey {
    $bytes = New-Object 'System.Byte[]' 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

# Create one GitHub-linked service and attach its variables in a single call.
function Add-RailwayService {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$RepoSlug,
        [string]$BranchName,
        [string[]]$Variables = @()
    )
    Write-Info "Creating service '$Name' (linked to $RepoSlug)..."
    $rwArgs = @('add', '--service', $Name, '--repo', $RepoSlug)
    if ($BranchName) { $rwArgs += @('--branch', $BranchName) }
    foreach ($v in $Variables) { $rwArgs += @('--variables', $v) }
    Invoke-Native { railway @rwArgs }
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "railway add --service $Name exited with code $LASTEXITCODE (it may already exist) — continuing."
        return $false
    }
    Write-Ok "service '$Name' created"
    return $true
}

# Best-effort public domain for a service. Non-fatal: if the CLI can't, the user
# clicks Generate Domain in the dashboard.
function New-RailwayDomain {
    param([Parameter(Mandatory)][string]$Name)
    Write-Info "Generating a public domain for '$Name'..."
    Invoke-Native { railway domain --service $Name }
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Could not generate a domain for '$Name' from the CLI. In the dashboard: service '$Name' -> Settings -> Networking -> Generate Domain."
        return $false
    }
    Write-Ok "domain generated for '$Name'"
    return $true
}

# ----------------------------------------------------------------------------
Write-Host "railway :: Silk United -> Railway (full stack)" -ForegroundColor Magenta

try {
    # --- 1) Railway CLI ------------------------------------------------------
    Write-Step '1 - Railway CLI'
    if (Test-Command 'railway') {
        $version = (& railway --version 2>$null) -join ' '
        Write-Ok "Railway CLI present ($version)"
    }
    else {
        Write-Info 'Railway CLI not found - installing via npm (npm i -g @railway/cli)...'
        if (-not (Test-Command 'npm')) {
            Fail 'npm is required to install the Railway CLI but was not found. Install Node.js/npm from https://nodejs.org and re-run.'
        }
        Invoke-Native { npm install -g '@railway/cli' }
        if ($LASTEXITCODE -ne 0) { Fail "npm install -g @railway/cli exited with code $LASTEXITCODE." }
        if (-not (Test-Command 'railway')) {
            Fail 'Railway CLI installed but `railway` is still not on PATH. Open a new terminal and re-run.'
        }
        Write-Ok 'Railway CLI installed'
    }

    # --- 2) Authenticate -----------------------------------------------------
    Write-Step '2 - Authenticate'
    if ($env:RAILWAY_TOKEN -or $env:RAILWAY_API_TOKEN) {
        Write-Ok 'Using token from environment - skipping login'
    }
    else {
        & railway whoami 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Already logged in ($((& railway whoami 2>$null) -join ' '))"
        }
        else {
            Write-Info 'Opening a browser to log in... (headless? set RAILWAY_TOKEN instead)'
            Invoke-Native { railway login }
            if ($LASTEXITCODE -ne 0) { Fail "railway login exited with code $LASTEXITCODE." }
            Write-Ok 'Logged in'
        }
    }

    # --- 3) Resolve repo -----------------------------------------------------
    Write-Step '3 - GitHub repo'
    if ([string]::IsNullOrWhiteSpace($Repo) -and (Test-Command 'git')) {
        $originUrl = (& git remote get-url origin 2>$null)
        if ($LASTEXITCODE -eq 0 -and $originUrl) {
            $normalized = $originUrl.Trim() `
                -replace '\.git$', '' `
                -replace '^git@[^:]+:', '' `
                -replace '^[a-zA-Z]+://[^/]+/', ''
            $segments = $normalized -split '/' | Where-Object { $_ -ne '' }
            if ($segments.Count -ge 2) {
                $Repo = '{0}/{1}' -f $segments[-2], $segments[-1]
                Write-Info "Derived repo from origin remote: $Repo"
            }
        }
    }
    if ([string]::IsNullOrWhiteSpace($Repo)) { $Repo = Read-Host 'Enter the GitHub repo (owner/repo)' }
    if ([string]::IsNullOrWhiteSpace($Repo)) { Fail 'No repo specified. Pass one as: .\deploy-to-railway.ps1 owner/repo' }
    if ($Repo -notmatch '^[^/\s]+/[^/\s]+$') { Fail "Repo must be in owner/repo form (got: '$Repo')." }
    Write-Ok "repo   : $Repo"
    if ($Branch) { Write-Ok "branch : $Branch" }

    # --- 4) Project ----------------------------------------------------------
    Write-Step '4 - Railway project'
    if ($Link) {
        Write-Info 'Linking to an existing Railway project...'
        Invoke-Native { railway link }
        if ($LASTEXITCODE -ne 0) { Fail "railway link exited with code $LASTEXITCODE." }
        Write-Ok 'Linked'
    }
    else {
        & railway status 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Warn 'This directory is already linked to a Railway project - reusing it (pass -Link to pick another).'
            Write-Ok 'Reusing the linked project'
        }
        else {
            Write-Info "Creating project '$ProjectName'..."
            Invoke-Native { railway init --name $ProjectName }
            if ($LASTEXITCODE -ne 0) { Fail "railway init exited with code $LASTEXITCODE." }
            Write-Ok "Project '$ProjectName' created and linked"
        }
    }

    # --- 5) Databases --------------------------------------------------------
    Write-Step '5 - Databases (Postgres + Redis)'
    Write-Info 'Adding Postgres...'
    Invoke-Native { railway add --database postgres }
    if ($LASTEXITCODE -ne 0) { Write-Warn 'Postgres may already exist - continuing.' } else { Write-Ok 'Postgres added' }
    Write-Info 'Adding Redis...'
    Invoke-Native { railway add --database redis }
    if ($LASTEXITCODE -ne 0) { Write-Warn 'Redis may already exist - continuing.' } else { Write-Ok 'Redis added' }

    # --- 6) Services ---------------------------------------------------------
    Write-Step '6 - Services (api - worker - beat - web)'
    $secret = New-SecretKey

    # Shared backend variables. Reference variables (${{...}}) are stored verbatim
    # and resolved by Railway at deploy time — single-quoted so PowerShell does not
    # try to expand them.
    $backend = @(
        'ENVIRONMENT=production',
        "SECRET_KEY=$secret",
        'DATABASE_URL=${{Postgres.DATABASE_URL}}',
        'REDIS_URL=${{Redis.REDIS_URL}}',
        'API_BASE_URL=https://${{api.RAILWAY_PUBLIC_DOMAIN}}',
        'APP_BASE_URL=https://${{web.RAILWAY_PUBLIC_DOMAIN}}',
        'CORS_ORIGINS=https://${{web.RAILWAY_PUBLIC_DOMAIN}}',
        'STORAGE_BACKEND=local',
        'COMTRADE_OFFLINE=1'
    )

    # api — public HTTP; runs migrations + seed on boot (RUN_SEED handled by start-api.sh).
    Add-RailwayService -Name 'api' -RepoSlug $Repo -BranchName $Branch -Variables (
        $backend + @('SILK_ROLE=api', 'RAILWAY_DOCKERFILE_PATH=apps/api/Dockerfile', 'RUN_SEED=1')
    ) | Out-Null
    # Generate the api domain BEFORE creating web, so web's build-time API_PROXY_TARGET resolves.
    New-RailwayDomain -Name 'api' | Out-Null

    # worker — Celery worker (same image, SILK_ROLE=worker), no public domain.
    Add-RailwayService -Name 'worker' -RepoSlug $Repo -BranchName $Branch -Variables (
        $backend + @('SILK_ROLE=worker', 'RAILWAY_DOCKERFILE_PATH=apps/api/Dockerfile')
    ) | Out-Null

    # beat — Celery scheduler (same image, SILK_ROLE=beat), no public domain.
    Add-RailwayService -Name 'beat' -RepoSlug $Repo -BranchName $Branch -Variables (
        $backend + @('SILK_ROLE=beat', 'RAILWAY_DOCKERFILE_PATH=apps/api/Dockerfile')
    ) | Out-Null

    # web — Next.js. API_PROXY_TARGET is read at BUILD time; it points at the api
    # public domain (resolves because the api domain was generated above).
    Add-RailwayService -Name 'web' -RepoSlug $Repo -BranchName $Branch -Variables @(
        'RAILWAY_DOCKERFILE_PATH=apps/web/Dockerfile',
        'NODE_ENV=production',
        'API_PROXY_TARGET=https://${{api.RAILWAY_PUBLIC_DOMAIN}}'
    ) | Out-Null
    New-RailwayDomain -Name 'web' | Out-Null

    # --- Done ----------------------------------------------------------------
    Write-Step '[done] All four services + Postgres + Redis provisioned'
    Write-Host @"

Railway is now building api - worker - beat - web from $Repo. First builds take a
few minutes. Nothing left to set in the dashboard.

  See it:   railway open        (or: railway status | railway logs)
  Domains:  the api and web URLs were printed above; the app is the WEB one.
  Health:   open https://<web-domain>/  and  https://<api-domain>/health

If a domain step warned, generate it in the dashboard (service -> Settings ->
Networking -> Generate Domain) for api and web, then redeploy web so its
API_PROXY_TARGET picks up the api domain.

Optional real vendor keys (ANTHROPIC_API_KEY, SMARTLEAD_API_KEY, OAuth, S3, …)
are all optional — add them per service later; blank keeps the built-in mocks.
"@ -ForegroundColor DarkGray
}
catch {
    Write-Host ""
    Write-Host "[x] Deployment failed" -ForegroundColor Red
    Write-Host "    $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
