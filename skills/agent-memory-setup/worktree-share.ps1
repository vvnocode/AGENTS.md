<#
vvnocode/AGENTS.md agent-memory-setup worktree-share.ps1 -- Windows counterpart of worktree-share.sh.
Shares the main worktree's gitignored machine-local assets into a linked worktree.

Usage:  pwsh -File worktree-share.ps1 link [WorktreePath]     (WorktreePath defaults to the current directory's worktree;
                                                              the main worktree itself is only reported, nothing is done)

Same contract as worktree-share.sh (read its header for the rationale):
  - files are copied, directories are linked with a SYMBOLIC LINK only (needs Developer Mode or an elevated shell on
    Windows). Without that privilege a directory is skipped with a warning. A junction is deliberately NOT used as a
    fallback: git (2.37.3 verified on Windows 10) treats a junction as a plain directory, so `git worktree remove`
    walks through it and deletes the main worktree's files; an existing junction is reported, never accepted.
    Setting WORKTREE_SHARE_NO_SYMLINK=1 simulates the missing privilege (used by the tests).
  - only items that exist in the main worktree, are untracked and are gitignored get shared; untracked-but-not-ignored
    items count as pending commits and are only reported.
  - tool config directories (.claude / .codex / .agents / .gemini / .opencode / .cursor) are listed as whole directories:
    a fully ignored one becomes one directory link (commands, hooks, skills, settings all visible through it); one that
    holds tracked files, or is not ignored itself, is expanded into its ignored children (repos/.gitkeep works the same).
  - a list entry may carry a wildcard (.env.*); it is expanded in the main worktree, each match handled as above.
  - .claude/settings.local.json and .claude/worktrees are skipped silently during expansion (Claude Code reads the main
    worktree's settings.local.json and it holds absolute paths, a copy would diverge; worktrees is Claude's own worktree
    container). Listing them explicitly warns. Through a whole-directory link they are the same file, nothing diverges.
  - after each action the item is re-checked with git check-ignore; when a trailing-slash rule does not match the link,
    a line without the slash is appended to the shared .git/info/exclude (never to the team's .gitignore).
  - after linking, memory-sync.ps1 runs once so Codex memories belonging to this repo land in the main worktree's .memory.
  - list = built-in list + .worktree-share at the repo root (one path per line, # comments, ! removes a built-in item;
    the main worktree's and the target worktree's copies are merged).

Pure ASCII on purpose (same reason as install.ps1). The one non-ASCII string written to disk (the info/exclude comment)
is embedded as base64 UTF-8, byte-identical to what worktree-share.sh writes.
#>
param(
    [string]$Command = '',
    [string]$WorktreePath = ''
)
$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path   # captured at script scope: empty inside functions
$Utf8 = New-Object Text.UTF8Encoding $false
$IsWin = $env:OS -eq 'Windows_NT'

$Builtin = @('CLAUDE.md', 'AGENTS.md', 'GEMINI.md', '.mcp.json', 'opencode.json', '.env', '.env.*',
             '.memory', '.claude', '.codex', '.agents', '.gemini', '.opencode', '.cursor')
$Never = @('.claude/settings.local.json', '.claude/worktrees')
# Directories whose own files may be copied one by one when a directory link cannot be created (static tool config).
# .memory (single writer) and skills trees are NOT in this list: file-by-file copies of those would diverge.
$CopyFallback = @('.claude', '.codex', '.agents', '.gemini', '.opencode', '.cursor')
$Conf = '.worktree-share'
$ExcludeMark = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('IyBhZ2VudC1tZW1vcnktc2V0dXDvvJp3b3JrdHJlZSDlhbHkuqvpobk='))
$script:New = 0; $script:Kept = 0; $script:Warn = 0

function Usage {
    Write-Host 'Usage: worktree-share.ps1 link [WorktreePath]'
    exit 1
}
function Warn([string]$Msg) { Write-Host "! $Msg"; $script:Warn++ }

# git with the error preference relaxed (Windows PowerShell 5.1 turns stderr into terminating errors). Returns stdout
# lines; sets $script:GitExit. Output is decoded as UTF-8 so paths and -z NUL separators survive.
function Invoke-Git([string]$Dir) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $prevEnc = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = $Utf8
        $out = & git -C $Dir @args 2>$null
        $script:GitExit = $LASTEXITCODE
        return @($out)
    } finally { [Console]::OutputEncoding = $prevEnc; $ErrorActionPreference = $prev }
}
# Full path, trailing separators trimmed, lower-cased on Windows, so that link targets and directories compare equal
function Get-NormalizedPath([string]$Path) {
    if ($Path.StartsWith('\\?\')) { $Path = $Path.Substring(4) }
    $Path = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    if ($IsWin) { $Path.ToLowerInvariant() } else { $Path }
}
# The path a link points at, or $null when the item is not a link (symbolic link or junction)
function Get-LinkTarget([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item -or -not $item.LinkType) { return $null }
    return [string](@($item.Target)[0])
}
function Test-IsLink([string]$Path) { return $null -ne (Get-LinkTarget $Path) }
# A junction (Windows only). Never accepted as a shared directory: git worktree remove deletes through it
function Test-IsJunction([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    return ($null -ne $item) -and ($item.LinkType -eq 'Junction')
}
# Main worktree of the repository that contains $Dir: the first line of git worktree list is always the main one
function Get-MainWorktree([string]$Dir) {
    $first = [string](@(Invoke-Git $Dir worktree list --porcelain)[0])
    return Get-NormalizedPath ($first -replace '^worktree ', '')
}
# One .worktree-share file: drop comments and blanks, trim, strip a leading ./ and trailing slashes
function Read-Conf([string]$File) {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { return @() }
    $lines = [IO.File]::ReadAllText($File, [Text.Encoding]::UTF8) -split "`r?`n"
    $out = @()
    foreach ($l in $lines) {
        $t = $l.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        if ($t.StartsWith('./')) { $t = $t.Substring(2) }
        $t = $t.TrimEnd('/')
        if ($t) { $out += $t }
    }
    return $out
}
# Final list: built-in + both config files, minus the ! entries, unique
function Build-List([string]$Root, [string]$Wt) {
    $items = @($Builtin); $removed = @()
    foreach ($line in @(Read-Conf (Join-Path $Root $Conf)) + @(Read-Conf (Join-Path $Wt $Conf))) {
        if ($line.StartsWith('!')) { $removed += $line.Substring(1) } else { $items += $line }
    }
    return @($items | Sort-Object -Unique | Where-Object { $removed -notcontains $_ })
}
# Make sure $Rel is ignored inside the worktree; append a slash-less line to the shared info/exclude when it is not
function Ensure-Ignored([string]$Wt, [string]$Rel) {
    Invoke-Git $Wt check-ignore -q -- $Rel | Out-Null
    if ($script:GitExit -eq 0) { return $true }
    $common = [string](@(Invoke-Git $Wt rev-parse --git-common-dir)[0])
    if (-not [IO.Path]::IsPathRooted($common)) { $common = Join-Path $Wt $common }
    $exclude = Join-Path (Join-Path ([IO.Path]::GetFullPath($common)) 'info') 'exclude'
    New-Item -ItemType Directory -Force (Split-Path $exclude -Parent) | Out-Null
    $text = if (Test-Path -LiteralPath $exclude -PathType Leaf) { [IO.File]::ReadAllText($exclude, [Text.Encoding]::UTF8) } else { '' }
    if ($text -and -not $text.EndsWith("`n")) { $text += "`n" }
    if (-not (($text -split "`r?`n") -contains $ExcludeMark)) { $text += $ExcludeMark + "`n" }
    $text += $Rel + "`n"
    [IO.File]::WriteAllText($exclude, $text, $Utf8)
    Invoke-Git $Wt check-ignore -q -- $Rel | Out-Null
    return ($script:GitExit -eq 0)
}
function Test-SameFile([string]$A, [string]$B) {
    return (Get-FileHash -LiteralPath $A -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $B -Algorithm SHA256).Hash
}
# Directory symbolic link; $false when it cannot be created (no privilege). No junction fallback, see the header
function New-DirLink([string]$Dst, [string]$Src) {
    if ($env:WORKTREE_SHARE_NO_SYMLINK -eq '1') { return $false }
    try { New-Item -ItemType SymbolicLink -Path $Dst -Value $Src -ErrorAction Stop | Out-Null; return $true } catch { return $false }
}
# Share one item: copy a file, link a directory; count what is already in place; report conflicts; re-check ignoring
function Share-One([string]$Root, [string]$Wt, [string]$Rel) {
    $src = Join-Path $Root $Rel; $dst = Join-Path $Wt $Rel
    if (Test-IsJunction $dst) {
        Warn "$Rel is a junction, left unchanged: git worktree remove would delete the main worktree's files through it; remove it (rmdir) and re-run to get a symbolic link"
        return
    }
    $target = Get-LinkTarget $dst
    if ($null -ne $target) {
        if ((Get-NormalizedPath $target) -eq (Get-NormalizedPath $src)) { $script:Kept++ } else { Warn "$Rel is already a link to ${target}, left unchanged" }
        return
    }
    if (Test-Path -LiteralPath $dst) {
        if ((Test-Path -LiteralPath $dst -PathType Leaf) -and (Test-Path -LiteralPath $src -PathType Leaf) -and (Test-SameFile $src $dst)) { $script:Kept++ }
        else { Warn "$Rel already exists in the worktree as a real file/directory, left unchanged" }
        return
    }
    New-Item -ItemType Directory -Force (Split-Path $dst -Parent) | Out-Null
    $isDir = Test-Path -LiteralPath $src -PathType Container
    if ($isDir) {
        if (-not (New-DirLink $dst $src)) {
            # No privilege for a directory link. A tool config directory falls back to its own files (copied one by one,
            # $Never skipped; subdirectories stay unshared). Anything else (.memory, skills trees) is skipped entirely:
            # file-by-file copies of those would diverge from the main worktree
            if ($CopyFallback -contains $Rel) {
                Warn "$Rel is not linked: creating a symbolic link needs Developer Mode (Settings > For developers) or an elevated shell; its files are copied instead and its subdirectories are skipped until you enable one and re-run. A junction is not used because git worktree remove would delete the main worktree's files through it"
                foreach ($child in (Get-ChildItem -LiteralPath $src -Force -File | Sort-Object Name)) {
                    $childRel = "$Rel/$($child.Name)"
                    if ($Never -contains $childRel) { continue }
                    Share-One $Root $Wt $childRel
                }
            } else {
                Warn "$Rel is not shared: creating a symbolic link needs Developer Mode (Settings > For developers) or an elevated shell; enable one and re-run. A junction is not used because git worktree remove would delete the main worktree's files through it"
            }
            return
        }
    } else { Copy-Item -LiteralPath $src -Destination $dst }
    if (-not (Ensure-Ignored $Wt $Rel)) {
        if ($isDir) { (Get-Item -LiteralPath $dst -Force).Delete() } else { Remove-Item -LiteralPath $dst -Force }
        Warn "$Rel is still not ignored after sharing, undone: check the ignore rules"
        return
    }
    if ($isDir) { Write-Host "* linked $Rel" } else { Write-Host "* copied $Rel" }
    $script:New++
}
# Expand one directory: share its ignored children (the !! lines), skip $Never silently, warn about untracked ones (?? lines)
function Share-Children([string]$Root, [string]$Wt, [string]$Rel) {
    $raw = (Invoke-Git $Root status --ignored=matching --porcelain -z --untracked-files=normal -- $Rel) -join ''
    foreach ($entry in ($raw -split "`0")) {
        if ($entry.StartsWith('!! ')) {
            $child = $entry.Substring(3).TrimEnd('/')
            if ($Never -contains $child) { continue }
            Share-One $Root $Wt $child
        } elseif ($entry.StartsWith('?? ')) {
            Warn "$($entry.Substring(3).TrimEnd('/')) is untracked and not ignored, treated as a pending commit, not shared"
        }
    }
}
# One list entry: expand a wildcard in the main worktree first; a fully ignored directory becomes one link, any other
# directory is expanded; a file is tracked (skip) / ignored (share) / pending (warn)
function Share-Item([string]$Root, [string]$Wt, [string]$Rel) {
    if ($Rel -match '[\*\?]') {
        $dir = (Split-Path $Rel -Parent).Replace('\', '/'); $leaf = Split-Path $Rel -Leaf
        $base = if ($dir) { Join-Path $Root $dir } else { $Root }
        if (Test-Path -LiteralPath $base -PathType Container) {
            foreach ($item in (Get-ChildItem -LiteralPath $base -Force | Where-Object { $_.Name -like $leaf } | Sort-Object Name)) {
                $childRel = if ($dir) { "$dir/$($item.Name)" } else { $item.Name }
                Share-Item $Root $Wt $childRel
            }
        }
        return
    }
    if ($Never -contains $Rel) {
        Warn "$Rel is not shared: Claude Code's own machine-local state (settings.local.json is read from the main worktree and holds absolute paths; worktrees is Claude's own worktree container)"
        return
    }
    $srcPath = Join-Path $Root $Rel
    if (-not (Test-Path -LiteralPath $srcPath) -and -not (Test-IsLink $srcPath)) { return }
    $tracked = @(Invoke-Git $Root ls-files -- $Rel)
    $isTracked = ($tracked.Count -gt 0 -and $tracked[0])
    if ((Test-Path -LiteralPath $srcPath -PathType Container) -and -not (Test-IsLink $srcPath)) {
        Invoke-Git $Root check-ignore -q -- $Rel | Out-Null
        if (-not $isTracked -and $script:GitExit -eq 0) { Share-One $Root $Wt $Rel }   # whole directory untracked and ignored: one link
        else { Share-Children $Root $Wt $Rel }                                          # holds tracked files, or not ignored itself: expand
        return
    }
    if ($isTracked) { return }   # a tracked file: the checkout brings it
    Invoke-Git $Root check-ignore -q -- $Rel | Out-Null
    if ($script:GitExit -ne 0) {
        Warn "$Rel is untracked and not ignored, treated as a pending commit, not shared"
        return
    }
    Share-One $Root $Wt $Rel
}
function Invoke-Link([string]$Path) {
    $wt = Get-NormalizedPath $Path
    $root = Get-MainWorktree $wt
    if ($wt -eq $root) {
        Write-Host "* $wt is the main worktree, nothing to share"
        return
    }
    Write-Host "=== worktree sharing: $root -> $wt ==="
    foreach ($rel in Build-List $root $wt) { Share-Item $root $wt $rel }
    Write-Host "+ new $($script:New), kept $($script:Kept), warnings $($script:Warn)"
    # Sync Codex memories into the main worktree's .memory before a session starts there (memory-sync.ps1);
    # best effort: run with the current PowerShell host, never change this script's exit code
    $sync = Join-Path $ScriptDir 'memory-sync.ps1'
    if (Test-Path -LiteralPath $sync -PathType Leaf) {
        $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { & (Get-Process -Id $PID).Path -NoProfile -NonInteractive -File $sync $root } catch { }
        finally { $ErrorActionPreference = $prev }
    }
}

switch ($Command) {
    'link' { if (-not $WorktreePath) { $WorktreePath = (Get-Location).Path }; Invoke-Link $WorktreePath }
    default { Usage }
}
