<#
vvnocode/AGENTS.md agent-memory-setup memory-sync.ps1 -- thin wrapper around memory-sync.py (Windows counterpart of
memory-sync.sh). Finds python, forwards the arguments, passes the exit code through. Output prefixes are ASCII
(MEMORY_SYNC_ASCII=1) so Windows PowerShell 5.1 consoles show them intact; the payload itself is UTF-8.

Usage:  pwsh -File memory-sync.ps1 [RepoPath]        (RepoPath defaults to the current directory's repository)

Pure ASCII on purpose (same reason as install.ps1).
#>
param([string]$RepoPath = '')
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = @((Get-Command python3 -ErrorAction SilentlyContinue), (Get-Command python -ErrorAction SilentlyContinue)) |
    Where-Object { $_ } | Select-Object -First 1
if (-not $py) { Write-Host '! memory-sync: python3 or python is required'; exit 0 }   # hook context: never fail the session
$env:MEMORY_SYNC_ASCII = '1'
$env:PYTHONIOENCODING = 'utf-8'
$pyArgs = @((Join-Path $here 'memory-sync.py'))
if ($RepoPath) { $pyArgs += $RepoPath }
& $py.Source @pyArgs
exit $LASTEXITCODE
