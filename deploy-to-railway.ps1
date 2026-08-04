#Requires -Version 5.1
<#
.SYNOPSIS
    Deploy this project to Railway from its GitHub repository.

.DESCRIPTION
    deploy-to-railway.ps1 automates a headless Railway deploy driven from the
    GitHub repo. It performs, in order:

      1. Ensure the Railway CLI is installed (installs via `npm i -g @railway/cli`
         when it is missing).
      2. Authenticate with `railway login`.
      3. Resolve the target repo (owner/repo) from the -Repo parameter, the
         origin remote of this clone, or an interactive prompt.
      4. Create a new Railway project with `railway init` — or `railway link`
         when the directory is already linked to one.
      5. Link and deploy the repo with `railway add --repo <owner/repo>`.

    Every step is wrapped in try/catch and prints a clear message so a failure
    tells you exactly which step broke and why.

.PARAMETER Repo
    GitHub repository in owner/repo form. When omitted, the script derives it
    from the `origin` git remote, and finally prompts for it.

.PARAMETER Branch
    Branch Railway auto-deploys from. Passed through to `railway add` when set.

.PARAMETER ProjectName
    Name for the Railway project created by `railway init`. Default: silk-united.

.PARAMETER Link
    Link to the Railway project already associated with this directory
    (`railway link`) instead of creating a new one.

.EXAMPLE
    .\deploy-to-railway.ps1 owner/repo

.EXAMPLE
    .\deploy-to-railway.ps1 -Repo owner/repo -Branch main -ProjectName silk-united

.NOTES
    Non-interactive auth (CI): set the RAILWAY_TOKEN (project token) or
    RAILWAY_API_TOKEN (account token) environment variable and the login step
    is skipped automatically.

    Silk United is a monorepo: one repo, four services (api · worker · beat ·
    web) plus Postgres and Redis. `railway add --repo` links the repo and
    creates the first service; use the Railway dashboard (or deploy-to-railway.sh)
    to finish wiring the remaining services, root directories, and config paths.
    See docs/DEPLOY_RAILWAY.md for the full runbook.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Repo,

    [string]$Branch,

    [string]$ProjectName = 'silk-united',

    [switch]$Link
)

# Fail fast: any unhandled error becomes a terminating exception we can catch.
$ErrorActionPreference = 'Stop'

# We check $LASTEXITCODE after every native (railway/npm/git) call ourselves,
# so opt out of PowerShell 7.4+ auto-throwing on non-zero exit codes. This keeps
# expected non-zero probes (e.g. `railway whoami` when logged out) from being
# misreported as errors, and behaves identically on Windows PowerShell 5.1.
$PSNativeCommandUseErrorActionPreference = $false

# ----------------------------------------------------------------------------
# Pretty output helpers
# ----------------------------------------------------------------------------
function Write-Step { param([string]$Message) Write-Host "`n$Message" -ForegroundColor Cyan }
function Write-Info { param([string]$Message) Write-Host "  -> $Message" -ForegroundColor DarkGray }
function Write-Ok   { param([string]$Message) Write-Host "  [ok] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Warning $Message }
function Fail       { param([string]$Message) throw $Message }

# Test whether a command is available on PATH.
function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# Run a native CLI command (railway/npm/git) attached to the console, so its
# interactive prompts and browser logins still work, WITHOUT letting its stderr
# chatter be promoted to a terminating error. Under $ErrorActionPreference =
# 'Stop', Windows PowerShell 5.1 turns any native stderr line - including a TUI's
# ANSI escape codes (e.g. `railway init`'s workspace picker) - into a terminating
# error whose message is empty. This wrapper drops the preference to 'Continue'
# just for the wrapped call.
#
# Call it as a STATEMENT (not `$x = Invoke-Native {...}`) and read $LASTEXITCODE
# afterwards: the native command's own stdout must flow to the console, and
# $LASTEXITCODE carries its real exit code out of the wrapper unchanged.
function Invoke-Native {
    param([Parameter(Mandatory)][scriptblock]$ScriptBlock)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $ScriptBlock
    }
    finally {
        $ErrorActionPreference = $prevEap
    }
}

# ----------------------------------------------------------------------------
# 0) Banner
# ----------------------------------------------------------------------------
Write-Host "railway :: Silk United -> Railway" -ForegroundColor Magenta

try {
    # ------------------------------------------------------------------------
    # 1) Railway CLI — install via npm when missing
    # ------------------------------------------------------------------------
    Write-Step '1 - Railway CLI'
    try {
        if (Test-Command 'railway') {
            $version = (& railway --version 2>$null) -join ' '
            Write-Ok "Railway CLI present ($version)"
        }
        else {
            Write-Info 'Railway CLI not found - installing via npm (npm i -g @railway/cli)...'
            if (-not (Test-Command 'npm')) {
                Fail 'npm is required to install the Railway CLI but was not found on PATH. Install Node.js/npm from https://nodejs.org and re-run.'
            }
            Invoke-Native { npm install -g '@railway/cli' }
            if ($LASTEXITCODE -ne 0) { Fail "npm install -g @railway/cli exited with code $LASTEXITCODE." }

            if (-not (Test-Command 'railway')) {
                Fail 'Railway CLI installed but `railway` is still not on PATH. Open a new terminal (so PATH refreshes) and re-run this script.'
            }
            Write-Ok 'Railway CLI installed'
        }
    }
    catch {
        Fail "Step 1 (Railway CLI) failed: $($_.Exception.Message)"
    }

    # ------------------------------------------------------------------------
    # 2) Authenticate
    # ------------------------------------------------------------------------
    Write-Step '2 - Authenticate'
    try {
        if ($env:RAILWAY_TOKEN -or $env:RAILWAY_API_TOKEN) {
            Write-Ok 'Using token from environment (RAILWAY_TOKEN/RAILWAY_API_TOKEN) - skipping login'
        }
        else {
            # `railway whoami` succeeds only when already authenticated.
            & railway whoami 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $who = (& railway whoami 2>$null) -join ' '
                Write-Ok "Already logged in ($who)"
            }
            else {
                Write-Info 'Opening a browser to log in... (headless? set RAILWAY_TOKEN instead)'
                Invoke-Native { railway login }
                if ($LASTEXITCODE -ne 0) { Fail "railway login exited with code $LASTEXITCODE." }
                Write-Ok 'Logged in'
            }
        }
    }
    catch {
        Fail "Step 2 (Authenticate) failed: $($_.Exception.Message)"
    }

    # ------------------------------------------------------------------------
    # 3) Resolve repo (owner/repo)
    # ------------------------------------------------------------------------
    Write-Step '3 - GitHub repo'
    try {
        # Derive owner/repo from the origin remote when not supplied.
        if ([string]::IsNullOrWhiteSpace($Repo) -and (Test-Command 'git')) {
            $originUrl = (& git remote get-url origin 2>$null)
            if ($LASTEXITCODE -eq 0 -and $originUrl) {
                # Normalise git@host:owner/repo.git and scheme://host/.../owner/repo.git,
                # then keep only the final two path segments (owner/repo).
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

        # Still nothing? Prompt the user.
        if ([string]::IsNullOrWhiteSpace($Repo)) {
            $Repo = Read-Host 'Enter the GitHub repo (owner/repo)'
        }

        if ([string]::IsNullOrWhiteSpace($Repo)) {
            Fail 'No repo specified. Pass one as: .\deploy-to-railway.ps1 owner/repo'
        }
        if ($Repo -notmatch '^[^/\s]+/[^/\s]+$') {
            Fail "Repo must be in owner/repo form (got: '$Repo')."
        }
        Write-Ok "repo   : $Repo"
        if ($Branch) { Write-Ok "branch : $Branch" }
    }
    catch {
        Fail "Step 3 (GitHub repo) failed: $($_.Exception.Message)"
    }

    # ------------------------------------------------------------------------
    # 4) Railway project — init a new one, or link an existing one
    # ------------------------------------------------------------------------
    Write-Step '4 - Railway project'
    try {
        if ($Link) {
            Write-Info 'Linking to an existing Railway project (railway link)...'
            Invoke-Native { railway link }
            if ($LASTEXITCODE -ne 0) { Fail "railway link exited with code $LASTEXITCODE." }
            Write-Ok 'Linked to existing project'
        }
        else {
            # If the directory is already linked, `railway status` returns 0.
            & railway status 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Warn 'This directory is already linked to a Railway project - reusing it (pass -Link to link a different one).'
                Write-Ok 'Reusing the linked project'
            }
            else {
                Write-Info "Creating project '$ProjectName' (railway init)..."
                Invoke-Native { railway init --name $ProjectName }
                if ($LASTEXITCODE -ne 0) { Fail "railway init exited with code $LASTEXITCODE." }
                Write-Ok "Project '$ProjectName' created and linked"
            }
        }
    }
    catch {
        Fail "Step 4 (Railway project) failed: $($_.Exception.Message)"
    }

    # ------------------------------------------------------------------------
    # 5) Link the GitHub repo and deploy
    # ------------------------------------------------------------------------
    Write-Step '5 - Link repo and deploy'
    try {
        $addArgs = @('add', '--repo', $Repo)
        if ($Branch) { $addArgs += @('--branch', $Branch) }

        Write-Info ("Running: railway {0}" -f ($addArgs -join ' '))
        Invoke-Native { railway @addArgs }
        if ($LASTEXITCODE -ne 0) {
            Fail (@"
railway add exited with code $LASTEXITCODE.
If '$Repo' is a PRIVATE repository, Railway cannot pull it until you connect
your GitHub account to Railway and grant its GitHub App access to this repo:
  1. Open https://railway.com , then Account Settings -> connect GitHub, and
     grant access to the '$Repo' repository (all repos, or just this one).
  2. Re-run this script, or: railway add --repo $Repo
The easiest path for a private repo is the dashboard: New Project -> Deploy
from GitHub repo, which walks you through authorising access as you select it.
See docs/DEPLOY_RAILWAY.md for the full runbook.
"@)
        }
        Write-Ok "Repo $Repo linked and deploying"
    }
    catch {
        Fail "Step 5 (Link repo and deploy) failed: $($_.Exception.Message)"
    }

    # ------------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------------
    Write-Step '[done] Provisioned'
    Write-Host @"
Railway is now building $Repo.

Silk United is a monorepo (api - worker - beat - web + Postgres + Redis).
'railway add --repo' links the repo and creates the first service; finish
wiring the remaining services, per-service Root Directories, and
config-as-code paths in the Railway dashboard.

  Full runbook : docs/DEPLOY_RAILWAY.md
  Handy        : railway status | railway logs | railway open
"@ -ForegroundColor DarkGray
}
catch {
    Write-Host ""
    Write-Host "[x] Deployment failed" -ForegroundColor Red
    Write-Host "    $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
