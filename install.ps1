<#
vvnocode/AGENTS.md install.ps1 -- Windows counterpart of install.sh.
Links this repo's AGENTS.md into every AI coding tool's user-level rules entry on this machine. Idempotent, add-only,
never overwrites an existing file.

Usage (no manual clone needed; the built-in Windows PowerShell 5.1 is enough):
  irm https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/install.ps1 | iex
  powershell -ExecutionPolicy Bypass -File .\install.ps1     # inside a clone of this repo: link that clone (development)

Where the repo comes from is decided by where the script runs, same as install.sh:
  outside a clone / piped : clone the repo into $env:RULES_REPO_DIR (default %USERPROFILE%\.vvnocode\rules), or
                            git pull --ff-only if it already exists. Re-running the same command updates it. $env:RULES_REPO_URL may point at a fork.
                            The early README kept the clone at ~\.config\vibe-coding-rules: when the new location is absent
                            and the old one holds a clone it is moved, and entries that point into the old location are repointed.
  inside a clone          : use that clone directly, no network, no managed copy.

Entries (each tool's own convention, see the README support matrix):
  ~\.claude\CLAUDE.md, ~\.codex\AGENTS.md, ~\.gemini\GEMINI.md, ~\.config\opencode\AGENTS.md ($env:XDG_CONFIG_HOME
  overrides ~\.config), $env:DSH_HOME\AGENTS.md (default ~\.dsh). Cursor's global User Rules live in its settings UI.
The skill skills\agent-memory-setup (per-repo wiring: one instruction file, one in-repo memory, the worktree sharing hook)
is linked into the three global skill discovery roots ~\.agents\skills, ~\.claude\skills and ~\.codex\skills.
A SessionStart hook running memory-sync is appended to ~\.claude\settings.json and ~\.codex\hooks.json (RULES_NO_HOOKS=1 skips it).

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
    $RepoUrl = if ($env:RULES_REPO_URL) { $env:RULES_REPO_URL } else { 'https://github.com/vvnocode/AGENTS.md.git' }
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
    $Marker = '<!-- copied by vvnocode/AGENTS.md install.ps1: do not edit, rerun the installer to refresh -->'
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
    #    counts as a clone of this repo when it holds both install.ps1 and AGENTS.md --
    $here = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }
    if ((Test-Path (Join-Path $here 'install.ps1') -PathType Leaf) -and (Test-Path (Join-Path $here 'AGENTS.md') -PathType Leaf)) {
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
    $Rules = Join-Path $Repo 'AGENTS.md'

    # -- Link each entry --
    foreach ($link in $Entries) {
        New-Item -ItemType Directory -Force (Split-Path $link -Parent) | Out-Null
        $item = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
        if ($item -and $item.LinkType) {
            # Already a link: at this repo means done; into the legacy location (early README) or at this repo's old file
            # name CLAUDE.md (before the 2026-09-08 rename) is repointed; elsewhere is only reported (may be the user's own rules repo)
            $target = [string](@($item.Target)[0])
            $legacyPrefix = (Get-NormalizedPath $LegacyDir) + [IO.Path]::DirectorySeparatorChar
            $oldName = Get-NormalizedPath (Join-Path $Repo 'CLAUDE.md')
            if ((Get-NormalizedPath $target) -eq (Get-NormalizedPath $Rules)) { $Kept++ }
            elseif ((Get-NormalizedPath $target).StartsWith($legacyPrefix) -or ((Get-NormalizedPath $target) -eq $oldName)) {
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
    # -- Link the skill into the three global skill discovery roots --
    #    ~/.agents/skills is the cross-tool convention (dsh, opencode, Cline ...); Claude and Codex only scan their own
    #    directory and never ~/.agents/skills, so all three are needed. agent-memory-setup used to live in the
    #    vvnocode/skills repo (merged into this repo on 2026-09-08): links into that repo's managed clone
    #    (~/.vvnocode/skills) or the even older XDG location (vvnocode-skills) are repointed here; others are only reported.
    #    A directory symlink needs Developer Mode or admin rights; without it a junction (no privilege needed) is created.
    $SkillSrc = Join-Path (Join-Path $Repo 'skills') 'agent-memory-setup'
    $DataHome = if ($env:XDG_DATA_HOME) { $env:XDG_DATA_HOME } else { Join-Path (Join-Path $UserHome '.local') 'share' }
    $OldSkill = @(
        (Get-NormalizedPath (Join-Path $UserHome '.vvnocode\skills\skills\agent-memory-setup')),
        (Get-NormalizedPath (Join-Path $DataHome 'vvnocode-skills\skills\agent-memory-setup'))
    )
    $SkillRoots = @(
        (Join-Path (Join-Path $UserHome '.agents') 'skills'),
        (Join-Path (Join-Path $UserHome '.claude') 'skills'),
        (Join-Path (Join-Path $UserHome '.codex') 'skills')
    )
    function New-DirLink([string]$Path, [string]$Target) {
        try { New-Item -ItemType SymbolicLink -Path $Path -Value $Target -ErrorAction Stop | Out-Null }
        catch { New-Item -ItemType Junction -Path $Path -Value $Target -ErrorAction Stop | Out-Null }
    }
    $SAdded = 0; $SKept = 0; $SMoved = 0
    foreach ($root in $SkillRoots) {
        New-Item -ItemType Directory -Force $root | Out-Null
        $link = Join-Path $root 'agent-memory-setup'
        $item = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
        if ($item -and $item.LinkType) {
            $target = Get-NormalizedPath ([string](@($item.Target)[0]))
            if ($target -eq (Get-NormalizedPath $SkillSrc)) { $SKept++ }
            elseif ($OldSkill -contains $target) {
                $item.Delete()   # removes the link only, never its target
                New-DirLink $link $SkillSrc
                $SMoved++
            }
            else { Write-Host "! $link already points to ${target}, left unchanged"; $Warn++ }
        } elseif ($item) {
            Write-Host "! $link is a plain directory, left unchanged: replace it by a link to $SkillSrc by hand if it is not yours"; $Warn++
        } else {
            New-DirLink $link $SkillSrc
            $SAdded++
        }
    }
    # -- Global hooks: sync Codex memories into the current repo's .memory at session start --
    #    Claude Code and Codex both have a SessionStart event and run command hooks with the session directory as cwd,
    #    so the command takes no argument; the script finds the repo from cwd and exits silently where there is no .memory.
    #    The command uses the stable ~/.agents/skills path (expanded now, so the Codex trust prompt shows the final command).
    #    Only our own entry is appended (recognised by the substrings agent-memory-setup and memory-sync); everything else in
    #    the file is kept; invalid JSON is reported and left alone. RULES_NO_HOOKS=1 skips this section.
    function Add-Hook([string]$File, [string]$Event, [string]$Cmd) {
        # returns 'ok' | 'kept' | 'warn'
        $data = $null
        if (Test-Path -LiteralPath $File -PathType Leaf) {
            $raw = [IO.File]::ReadAllText($File, [Text.Encoding]::UTF8)
            if ($raw.Trim()) {
                try { $data = $raw | ConvertFrom-Json } catch { Write-Host "! $File is not valid JSON, left unchanged"; return 'warn' }
            }
        }
        if ($null -eq $data) { $data = [pscustomobject]@{} }
        if (-not ($data.PSObject.Properties.Name -contains 'hooks')) { $data | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{}) }
        if (-not ($data.hooks.PSObject.Properties.Name -contains $Event)) { $data.hooks | Add-Member -NotePropertyName $Event -NotePropertyValue @() }
        foreach ($g in @($data.hooks.$Event)) {
            foreach ($h in @($g.hooks)) {
                $c = [string]$h.command
                if ($c.Contains('agent-memory-setup') -and $c.Contains('memory-sync')) { Write-Host "* $File already has the memory-sync hook"; return 'kept' }
            }
        }
        $entry = [pscustomobject]@{ hooks = @([pscustomobject]@{ type = 'command'; command = $Cmd }) }
        $data.hooks.$Event = @($data.hooks.$Event) + @($entry)
        New-Item -ItemType Directory -Force (Split-Path $File -Parent) | Out-Null
        [IO.File]::WriteAllText($File, (($data | ConvertTo-Json -Depth 20) + "`n"), $Utf8)
        Write-Host "* wrote $File (hooks.$Event)"
        return 'ok'
    }
    if ($env:RULES_NO_HOOKS -eq '1') {
        Write-Host '* RULES_NO_HOOKS=1: global hooks skipped'
    } else {
        $syncDir = Join-Path (Join-Path (Join-Path $UserHome '.agents') 'skills') 'agent-memory-setup'
        $HookCmd = if ($IsWin) { "powershell -NoProfile -ExecutionPolicy Bypass -File `"$syncDir\memory-sync.ps1`"" }
                   else { "bash `"$syncDir/memory-sync.sh`" || true" }
        foreach ($spec in @(
            @{ File = (Join-Path (Join-Path $UserHome '.claude') 'settings.json'); Event = 'SessionStart' },
            @{ File = (Join-Path (Join-Path $UserHome '.codex') 'hooks.json');     Event = 'SessionStart' })) {
            Write-Host "* appending to $($spec.File) hooks.$($spec.Event): $HookCmd"
            if ((Add-Hook $spec.File $spec.Event $HookCmd) -eq 'warn') { $Warn++ }
        }
        Write-Host '* Codex asks you to review and trust this hook definition on its next start; it runs only after that'
    }
    Write-Host "* done: rules added $Added, kept $Kept, repointed $Moved, copied $Copied; skill added $SAdded, kept $SKept, repointed $SMoved; warnings $Warn (rules: $Rules)"
    if (Test-Path (Join-Path (Join-Path $UserHome '.vvnocode') 'skills')) { Write-Host "* the old skills repo clone under ~\.vvnocode\skills is no longer used and can be deleted" }
    Write-Host "* wire up a repository: powershell -ExecutionPolicy Bypass -File `"$SkillSrc\setup.ps1`" [RepoPath]"
    Write-Host "* Cursor: paste the rules into its global User Rules in the settings UI"
}
