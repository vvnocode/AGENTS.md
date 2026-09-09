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
  - a directory that itself holds tracked files (repos/.gitkeep tracked, clones below it ignored) is expanded into its
    ignored children.
  - .claude/settings.local.json is never shared (Claude Code reads the main worktree's copy; it holds absolute paths).
  - after each action the item is re-checked with git check-ignore; when a trailing-slash rule does not match the link,
    a line without the slash is appended to the shared .git/info/exclude (never to the team's .gitignore).
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
$Utf8 = New-Object Text.UTF8Encoding $false
$IsWin = $env:OS -eq 'Windows_NT'

$Builtin = @('CLAUDE.md', 'AGENTS.md', 'GEMINI.md', '.claude/settings.json', '.codex/config.toml', '.mcp.json', '.env',
             '.memory', '.claude/skills', '.codex/skills', '.agents/skills', '.claude/agents')
$Never = '.claude/settings.local.json'
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
            Warn "$Rel is not shared: creating a symbolic link needs Developer Mode (Settings > For developers) or an elevated shell; enable one and re-run. A junction is not used because git worktree remove would delete the main worktree's files through it"
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
function Invoke-Link([string]$Path) {
    $wt = Get-NormalizedPath $Path
    $root = Get-MainWorktree $wt
    if ($wt -eq $root) {
        Write-Host "* $wt is the main worktree, nothing to share"
        return
    }
    Write-Host "=== worktree sharing: $root -> $wt ==="
    foreach ($rel in Build-List $root $wt) {
        if ($rel -eq $Never) {
            Warn "$rel is not shared: Claude Code reads the main worktree's copy, and it holds machine-local absolute paths"
            continue
        }
        $srcPath = Join-Path $root $rel
        if (-not (Test-Path -LiteralPath $srcPath) -and -not (Test-IsLink $srcPath)) { continue }
        $tracked = @(Invoke-Git $root ls-files -- $rel)
        if ($tracked.Count -gt 0 -and $tracked[0]) {
            if (-not (Test-Path -LiteralPath $srcPath -PathType Container)) { continue }   # a tracked file: the checkout brings it
            # a directory holding tracked files: expand into its ignored children (the !! lines)
            $raw = (Invoke-Git $root status --ignored=matching --porcelain -z --untracked-files=normal -- $rel) -join ''
            foreach ($entry in ($raw -split "`0")) {
                if ($entry.StartsWith('!! ')) { Share-One $root $wt ($entry.Substring(3).TrimEnd('/')) }
            }
            continue
        }
        Invoke-Git $root check-ignore -q -- $rel | Out-Null
        if ($script:GitExit -ne 0) {
            Warn "$rel is untracked and not ignored, treated as a pending commit, not shared"
            continue
        }
        Share-One $root $wt $rel
    }
    Write-Host "+ new $($script:New), kept $($script:Kept), warnings $($script:Warn)"
}

switch ($Command) {
    'link' { if (-not $WorktreePath) { $WorktreePath = (Get-Location).Path }; Invoke-Link $WorktreePath }
    default { Usage }
}
