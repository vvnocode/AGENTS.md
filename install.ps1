<#
vvnocode/claude.md install.ps1 -- Windows counterpart of install.sh.
Links this repo's CLAUDE.md into every AI coding tool's user-level rules entry on this machine. Idempotent, add-only,
never overwrites an existing file.

Usage (no manual clone needed; the built-in Windows PowerShell 5.1 is enough):
  irm https://raw.githubusercontent.com/vvnocode/claude.md/main/install.ps1 | iex
  powershell -ExecutionPolicy Bypass -File .\install.ps1     # inside a clone of this repo: link that clone (development)

Where the repo comes from is decided by where the script runs, same as install.sh:
  outside a clone / piped : clone the repo into $env:RULES_REPO_DIR (default %USERPROFILE%\.vvnocode\rules, the same
                            convention as the skills repo at %USERPROFILE%\.vvnocode\skills), or git pull --ff-only if it
                            already exists. Re-running the same command updates it. $env:RULES_REPO_URL may point at a fork.
                            The early README kept the clone at ~\.config\vibe-coding-rules: when the new location is absent
                            and the old one holds a clone it is moved, and entries that point into the old location are repointed.
  inside a clone          : use that clone directly, no network, no managed copy.

Entries (each tool's own convention, see the README support matrix):
  ~\.claude\CLAUDE.md, ~\.codex\AGENTS.md, ~\.gemini\GEMINI.md, ~\.config\opencode\AGENTS.md ($env:XDG_CONFIG_HOME
  overrides ~\.config), $env:DSH_HOME\AGENTS.md (default ~\.dsh). Cursor's global User Rules live in its settings UI.

File symbolic links on Windows need Developer Mode or admin rights. When creating one fails the file is copied instead and
tagged with a trailing marker comment; rerunning this installer refreshes such copies after every update. A plain file
without the marker is treated as the user's own rules and is left alone with a warning.

Encoding: this file is intentionally pure ASCII, no BOM, English messages -- with a BOM, 5.1's "irm | iex" executes the
first line as a command; without a BOM, "-File" decodes with the ANSI code page and any non-ASCII byte breaks parsing.
#>
param()

# The whole body lives in one script block: "irm | iex" runs inside the caller's session, so preferences and temporaries
# must not leak into it. Fatal errors use throw, never exit (exit would close the user's console under iex).
& {
    $ErrorActionPreference = 'Stop'

    $IsWin = $env:OS -eq 'Windows_NT'
    $UserHome = if ($IsWin) { $env:USERPROFILE } else { $HOME }
    $RepoUrl = if ($env:RULES_REPO_URL) { $env:RULES_REPO_URL } else { 'https://github.com/vvnocode/claude.md.git' }
    $ConfigHome = if ($env:XDG_CONFIG_HOME) { $env:XDG_CONFIG_HOME } else { Join-Path $UserHome '.config' }
    $DshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $UserHome '.dsh' }
    $RepoDir = if ($env:RULES_REPO_DIR) { $env:RULES_REPO_DIR } else { Join-Path (Join-Path $UserHome '.vvnocode') 'rules' }
    $LegacyDir = Join-Path $ConfigHome 'vibe-coding-rules'   # early README location, migrated below
    $Entries = @(
        (Join-Path (Join-Path $UserHome '.claude') 'CLAUDE.md'),
        (Join-Path (Join-Path $UserHome '.codex') 'AGENTS.md'),
        (Join-Path (Join-Path $UserHome '.gemini') 'GEMINI.md'),
        (Join-Path (Join-Path $ConfigHome 'opencode') 'AGENTS.md'),
        (Join-Path $DshHome 'AGENTS.md')
    )
    $Marker = '<!-- copied by vvnocode/claude.md install.ps1: do not edit, rerun the installer to refresh -->'
    $Utf8 = New-Object Text.UTF8Encoding $false
    $Added = 0; $Kept = 0; $Moved = 0; $Copied = 0; $Warn = 0

    # git under 'Stop' would turn stderr output into terminating errors in Windows PowerShell 5.1: relax it per call.
    function Invoke-Git {
        $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { & git @args | Out-Host; return $LASTEXITCODE } finally { $ErrorActionPreference = $prev }
    }
    function Get-NormalizedPath([string]$Path) {
        if ($Path.StartsWith('\\?\')) { $Path = $Path.Substring(4) }
        $Path = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
        if ($IsWin) { $Path.ToLowerInvariant() } else { $Path }
    }
    function Write-Copy([string]$Rules, [string]$Link) {
        $text = [IO.File]::ReadAllText($Rules, [Text.Encoding]::UTF8)
        if (-not $text.EndsWith("`n")) { $text += "`n" }
        [IO.File]::WriteAllText($Link, $text + $Marker + "`n", $Utf8)
    }

    # -- Repo source: the script directory ($PSScriptRoot is empty under "irm | iex", fall back to the current directory)
    #    counts as a clone of this repo when it holds both install.ps1 and CLAUDE.md --
    $here = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }
    if ((Test-Path (Join-Path $here 'install.ps1') -PathType Leaf) -and (Test-Path (Join-Path $here 'CLAUDE.md') -PathType Leaf)) {
        $Repo = $here
        Write-Host "* source: local clone $Repo"
    } else {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'x git is required' }
        if (-not $env:RULES_REPO_DIR -and -not (Test-Path $RepoDir) -and (Test-Path (Join-Path $LegacyDir '.git') -PathType Container)) {
            New-Item -ItemType Directory -Force (Split-Path $RepoDir -Parent) | Out-Null
            Move-Item -LiteralPath $LegacyDir -Destination $RepoDir
            Write-Host "* managed clone moved from $LegacyDir to $RepoDir; entries pointing into the old location will be repointed"
        }
        if (Test-Path (Join-Path $RepoDir '.git') -PathType Container) {
            if ((Invoke-Git -C $RepoDir pull -q --ff-only) -eq 0) {
                Write-Host "* source: managed clone $RepoDir (updated)"
            } else {
                Write-Host "! $RepoDir could not be updated, keeping the current version (local changes or no network)"; $Warn++
            }
        } elseif (Test-Path $RepoDir) {
            throw "x $RepoDir exists but is not a git repository; move it away and retry"
        } else {
            New-Item -ItemType Directory -Force (Split-Path $RepoDir -Parent) | Out-Null
            if ((Invoke-Git clone -q $RepoUrl $RepoDir) -ne 0) { throw "x clone failed: $RepoUrl" }
            Write-Host "* source: cloned $RepoUrl into $RepoDir"
        }
        $Repo = (Resolve-Path $RepoDir).Path
    }
    $Rules = Join-Path $Repo 'CLAUDE.md'

    # -- Link each entry --
    foreach ($link in $Entries) {
        New-Item -ItemType Directory -Force (Split-Path $link -Parent) | Out-Null
        $item = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
        if ($item -and $item.LinkType) {
            # Already a link: at this repo means done; into the legacy location was made per the early README and is
            # repointed; elsewhere is only reported (may be the user's own rules repo)
            $target = [string](@($item.Target)[0])
            $legacyPrefix = (Get-NormalizedPath $LegacyDir) + [IO.Path]::DirectorySeparatorChar
            if ((Get-NormalizedPath $target) -eq (Get-NormalizedPath $Rules)) { $Kept++ }
            elseif ((Get-NormalizedPath $target).StartsWith($legacyPrefix)) {
                $item.Delete()   # removes the link only, never its target
                New-Item -ItemType SymbolicLink -Path $link -Value $Rules | Out-Null
                $Moved++
            }
            else { Write-Host "! $link already points to ${target}, left unchanged"; $Warn++ }
        } elseif ($item) {
            $text = [IO.File]::ReadAllText($link, [Text.Encoding]::UTF8)
            if ($text.TrimEnd().EndsWith($Marker)) {
                # A copy made by an earlier run: refresh it
                Write-Copy $Rules $link; $Copied++
            } else {
                Write-Host "! $link is a plain file, left unchanged: merge your own rules into the repo copy first, then replace it by hand"; $Warn++
            }
        } else {
            try {
                New-Item -ItemType SymbolicLink -Path $link -Value $Rules | Out-Null
                $Added++
            } catch {
                # No symlink privilege (Windows without Developer Mode): fall back to a tagged copy
                Write-Copy $Rules $link; $Copied++
                Write-Host "! ${link}: symbolic links need Developer Mode or admin rights, copied the file instead; rerun this installer after each update to refresh it"
            }
        }
    }
    Write-Host "* done: added $Added, kept $Kept, repointed $Moved, copied $Copied, warnings $Warn (rules: $Rules)"
    Write-Host "* Cursor: paste the rules into its global User Rules in the settings UI"
}
