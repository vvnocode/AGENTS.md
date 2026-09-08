<#
vvnocode/AGENTS.md agent-memory-setup setup.ps1 -- Windows counterpart of setup.sh.
Lets Claude Code / Codex / dsh / opencode share one instruction file (AGENTS.md) and one in-repo memory (.memory/) in a repo.

Usage:  setup.ps1 [RepoPath] [-WithRule]        (the setup.sh spelling --with-rule is accepted as well)
  RepoPath   defaults to the git repository that contains the current directory
  -WithRule  append the "project memory" section to AGENTS.md. Machines carrying a cross-tool global rule set (for example
             the "project memory" section of vvnocode/AGENTS.md) do not need it; only repos meant for collaborators
             without such global rules do.

Without a clone (run inside the target repo):
  irm https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup/setup.ps1 | iex
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup/setup.ps1))) C:\path\to\repo -WithRule
Installed through install.ps1:
  powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.agents\skills\agent-memory-setup\setup.ps1" [RepoPath] [-WithRule]

Idempotent: what is already in place is left alone, only what is missing gets added; nothing is deleted or overwritten.
Conflicts it cannot settle (AGENTS.md and CLAUDE.md both plain files with different content) are reported for a human,
the remaining steps still run.

Pure ASCII on purpose (see install.ps1: irm keeps a BOM, -File decodes with the ANSI code page). The Chinese text this
script writes into the target repo is embedded below as base64 UTF-8, byte-identical to what setup.sh writes.
#>
param(
    [string]$RepoPath = '',
    [switch]$WithRule,
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest = @()
)

# The body lives in one script block so that "irm | iex" does not leak preferences or temporaries into the caller's
# session. Fatal errors use throw, never exit (exit would close the console under iex).
& {
    param([string]$RepoPath, [bool]$WithRule, [bool]$Help, [string[]]$Rest, [string]$ScriptDir)
    $ErrorActionPreference = 'Stop'
    $RawBase = 'https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup'
    $Utf8 = New-Object Text.UTF8Encoding $false
    $Warn = 0
    function Ok([string]$Msg)   { Write-Host "* $Msg" }
    # the counter lives in the enclosing script block: bump it there (scope 1 = caller), not a script-scope copy
    function Warn([string]$Msg) { Write-Host "! $Msg"; Set-Variable -Scope 1 -Name Warn -Value ((Get-Variable -Scope 1 -Name Warn -ValueOnly) + 1) }
    function Get-Text([string]$B64) { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($B64)) }
    # .NET file APIs resolve relative paths against the process working directory, which Push-Location does not change:
    # anchor them at the repo root explicitly.
    # ($Root is read from the enclosing scope through dynamic scoping)
    function Get-RepoFile([string]$Path) { if ([IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $Root $Path } }
    function Read-File([string]$Path) { [IO.File]::ReadAllText((Get-RepoFile $Path), [Text.Encoding]::UTF8) }   # BOM detected automatically
    function Write-File([string]$Path, [string]$Text) { [IO.File]::WriteAllText((Get-RepoFile $Path), $Text, $Utf8) }
    # git with the error preference relaxed: Windows PowerShell 5.1 would otherwise turn stderr output into a terminating error.
    # Returns stdout, or $null when git failed.
    function Invoke-Git {
        $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { $out = & git @args 2>$null; if ($LASTEXITCODE -ne 0) { return $null }; return $out } finally { $ErrorActionPreference = $prev }
    }

    # -- Text written into the target repo (base64 of UTF-8, identical to setup.sh) --
    $B64 = @{
        AgentsSkeleton = 'IyBBR0VOVFMubWQKCumhueebruaMh+S7pOato+acrO+8m2BDTEFVREUubWRgIOWPquWQq+S4gOihjCBgQEFHRU5UUy5tZGAg5byV55So5pys5paH5Lu277yM5Lik6ICF5rC46L+c5ZCM5LiA5Lu944CCCg=='
        MemoryIndex    = 'IyDorrDlv4bntKLlvJUKCg=='
        GitignoreBlock = 'IyBDbGF1ZGUg5pys5py66YWN572u77yM5ZCr57ud5a+56Lev5b6E77yM5LiN5YWl5bqT77yIYWdlbnQtbWVtb3J5LXNldHVw77yJCi5jbGF1ZGUvc2V0dGluZ3MubG9jYWwuanNvbgo='
        CodexBlock     = 'IyDmnKzpobnnm67nmoTorrDlv4bnu5/kuIDlrZjmlL7lnKjku5PlupPlhoUgLm1lbW9yeS/vvIzlhpnlhaXop4TliJnop4EgQUdFTlRTLm1k44CCCiMKIyBDb2RleCDnmoTorrDlv4bnm67lvZXkuI3lj6/phY3nva7vvIjlm7rlrprkuLogJENPREVYX0hPTUUvbWVtb3JpZXPvvInvvIzlj6rog73miorlroPoh6rluKbnmoTorrDlv4bns7vnu5/lhbPmjonvvJoKIyAgIGdlbmVyYXRlX21lbW9yaWVzID0gZmFsc2UgIOacrOebruW9leeahOS6pOS6kuS8muivneS4jeWGjeayiea3gOWIsOS7k+W6k+WklgojICAgdXNlX21lbW9yaWVzICAgICAgPSBmYWxzZSAg5LiN5YaN5rOo5YWlIH4vLmNvZGV4L21lbW9yaWVzIOmHjOeahOaXp+WJr+acrAojICAgZGVkaWNhdGVkX3Rvb2xzICAgPSBmYWxzZSAg5pS25o6JIGxpc3QvcmVhZC9zZWFyY2gvYWRkX2FkX2hvY19ub3Rl77yI5pyA5ZCO5LiA5Liq5piv5YaZ5bel5YW377yM5LiN5YWz5Lya57uV6L+H5YmN5Lik6aG577yJCiMKIyDnlJ/mlYjliY3mj5DvvJrmnKzpobnnm67pobvlnKggfi8uY29kZXgvY29uZmlnLnRvbWwg6YeM6KKr5qCH6K6w5Li6IHRydXN0ZWTvvIzlkKbliJnmlbTkuKogLmNvZGV4LyDpnZnpu5jkuI3liqDovb3jgIIKW21lbW9yaWVzXQpnZW5lcmF0ZV9tZW1vcmllcyA9IGZhbHNlCnVzZV9tZW1vcmllcyA9IGZhbHNlCmRlZGljYXRlZF90b29scyA9IGZhbHNlCg=='
        RuleSection    = 'CiMjIOmhueebruiusOW/hu+8iOaJgOaciSBBZ2VudCDlhbHnlKjvvIkKCuacrOmhueebrueahOi3qOS8muivneiusOW/huS4gOW+i+WtmOWcqOS7k+WGhSBgLm1lbW9yeS9g77yM6ZqP5Luj56CB5o+Q5Lqk77yb5LiN5L2/55So5ZCE5bel5YW36Ieq5bim55qE5LuT5aSW6K6w5b+G44CCCgotIOS8muivneW8gOWni+WFiOivuyBgLm1lbW9yeS9NRU1PUlkubWRgIOe0ouW8le+8jOWRveS4reWGjeivu+WvueW6lOadoeebru+8m+e0ouW8leavj+adoeS4gOihjO+8mmAtIFvmoIfpophdKOaWh+S7ti5tZCkg4oCUIOaRmOimgWDjgIIKLSDlj6rorrDmjaLkuKrkvJror53ku43mnInnlKjjgIHkuJTku6PnoIHkuI4gR2l0IOWOhuWPsuivu+S4jeWHuuadpeeahOS6i++8mueUqOaIt+WBj+WlveOAgee6oOato+i/h+eahOWBmuazleOAgeWklumDqOi1hOa6kOaMh+mSiOOAgemdnuaYvueEtue6puadn+OAguS4jeiusOS7o+eggee7k+aehOOAgeW3suS/rueahCBidWfjgIHmnKzmrKHkvJror53nmoTkuLTml7bnu5PorrrjgIIKLSDkuIDmnaHorrDlv4bkuIDkuKogYC5tZGDvvJpmcm9udG1hdHRlciDlkKsgYG5hbWVg77yI55+t5qiq57q/IHNsdWfvvInjgIFgZGVzY3JpcHRpb25g77yI5LiA5Y+l6K+d77yM5L6b5Yik5pat55u45YWz5oCn77yJ44CBYG1ldGFkYXRhLnR5cGVg77yIYHVzZXJgIHwgYGZlZWRiYWNrYCB8IGBwcm9qZWN0YCB8IGByZWZlcmVuY2Vg77yJ77yb5q2j5paH5LiA5Liq5LqL5a6e77yMYGZlZWRiYWNrYCAvIGBwcm9qZWN0YCDnsbvpmYQgKipXaHkqKiDkuI4gKipIb3cgdG8gYXBwbHkqKuOAggotIOWGmeWFpeWJjeWFiOafpeW3suacieadoeebru+8muW3suimhuebluWwseabtOaWsO+8jOS4jeaWsOW7uumHjeWkje+8m+WPkeeOsOmUmeivr+eahOiusOW/huebtOaOpeWIoOmZpOOAggo='
    }

    # -- Arguments: accept --with-rule / -h / --help wherever they appear, the remaining token is the repo path --
    $tokens = @(); if ($RepoPath) { $tokens += $RepoPath }; $tokens += $Rest
    $Root = ''
    foreach ($t in $tokens) {
        switch ($t) {
            '--with-rule' { $WithRule = $true }
            '-h'          { $Help = $true }
            '--help'      { $Help = $true }
            default       { $Root = $t }
        }
    }
    if ($Help) {
        Write-Host @"
Usage: setup.ps1 [RepoPath] [-WithRule]        (--with-rule is accepted as well)

  RepoPath   defaults to the git repository that contains the current directory
  -WithRule  append the "project memory" section to AGENTS.md. Machines carrying a cross-tool global rule set
             (for example the "project memory" section of vvnocode/AGENTS.md) do not need it; only repos meant for
             collaborators without such global rules do.

Without a clone, run inside the target repo:
  irm $RawBase/setup.ps1 | iex
  & ([scriptblock]::Create((irm $RawBase/setup.ps1))) C:\path\to\repo -WithRule

Idempotent: existing items are left alone, only missing ones are added; nothing is deleted or overwritten. Conflicts it
cannot settle (AGENTS.md and CLAUDE.md both plain files with different content) are reported for a human.
"@
        return
    }
    if (-not $Root) {
        $top = Invoke-Git rev-parse --show-toplevel
        if (-not $top) { throw 'x the current directory is not inside a git repository; pass the repo path explicitly' }
        $Root = [string]$top
    }
    # git prints forward slashes on Windows and Resolve-Path keeps them; GetFullPath turns them into the native form
    $Root = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Root).Path)
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Host '! python not found: only the Codex probe hint at the end needs it' }
    Write-Host "=== agent-memory-setup: $Root ==="
    Push-Location -LiteralPath $Root
    try {
        # -- 1) One instruction file: AGENTS.md is the source, CLAUDE.md holds a single import line @AGENTS.md --
        #    Claude Code reads only CLAUDE.md; Codex / dsh / opencode read AGENTS.md. An import line instead of a symlink
        #    needs no privilege and survives a checkout on any platform. Links left by the old approach are migrated here.
        $ImportLine = '@AGENTS.md'
        function Write-Import { Write-File 'CLAUDE.md' ($ImportLine + "`n") }
        $agents = Get-Item -LiteralPath 'AGENTS.md' -Force -ErrorAction SilentlyContinue
        $claude = Get-Item -LiteralPath 'CLAUDE.md' -Force -ErrorAction SilentlyContinue
        # A symlink committed from macOS/Linux is checked out on Windows (core.symlinks=false) as a plain file holding the
        # link text, and the index still records mode 120000: recognise that case.
        $claudeIsCheckedOutLink = $false
        if ($claude -and -not $claude.LinkType -and ((Read-File 'CLAUDE.md').Trim() -eq 'AGENTS.md')) {
            $entry = [string](Invoke-Git ls-files -s CLAUDE.md)
            $claudeIsCheckedOutLink = $entry.StartsWith('120000 ')
        }
        if ($agents -and $agents.LinkType) {
            Warn "AGENTS.md itself is a link (-> $(@($agents.Target)[0])), left unchanged: make AGENTS.md the real file, then rerun"
        } elseif ($claude -and $claude.LinkType) {
            $target = [string](@($claude.Target)[0])
            if ((Split-Path $target -Leaf) -eq 'AGENTS.md') {
                Remove-Item -LiteralPath 'CLAUDE.md' -Force; Write-Import
                Ok 'CLAUDE.md: link replaced by the import line @AGENTS.md (migrated from the old approach)'
            } else {
                Warn "CLAUDE.md is a link to $target, left unchanged: make sure it ends up at AGENTS.md"
            }
        } elseif ($claudeIsCheckedOutLink) {
            # drop the symlink entry from the index so the new plain file is tracked as a regular file, then re-stage it
            Invoke-Git rm --cached --quiet CLAUDE.md | Out-Null
            Write-Import
            Invoke-Git add CLAUDE.md | Out-Null
            Ok 'CLAUDE.md: symlink checked out as plain text replaced by the import line @AGENTS.md and re-staged as a regular file'
        } elseif ($claude -and $agents) {
            if (((Read-File 'CLAUDE.md') -split "`r?`n") -contains $ImportLine) {
                Ok 'CLAUDE.md already imports AGENTS.md'
            } elseif ((Read-File 'CLAUDE.md') -eq (Read-File 'AGENTS.md')) {
                Write-Import; Ok 'CLAUDE.md had the same content as AGENTS.md: replaced by the import line'
            } else {
                Warn 'AGENTS.md and CLAUDE.md are both plain files with different content, left unchanged: merge CLAUDE.md into AGENTS.md by hand, then make CLAUDE.md a single line @AGENTS.md'
            }
        } elseif ($claude) {
            Move-Item -LiteralPath 'CLAUDE.md' -Destination 'AGENTS.md'; Write-Import
            Ok 'only CLAUDE.md existed: renamed to AGENTS.md and wrote the CLAUDE.md import line'
        } elseif ($agents) {
            Write-Import; Ok 'wrote the CLAUDE.md import line @AGENTS.md'
        } else {
            Write-File 'AGENTS.md' (Get-Text $B64.AgentsSkeleton); Write-Import
            Ok 'created AGENTS.md and the CLAUDE.md import line'
        }

        # -- 2) In-repo memory directory --
        New-Item -ItemType Directory -Force '.memory' | Out-Null
        if (Test-Path '.memory/MEMORY.md' -PathType Leaf) { Ok '.memory/MEMORY.md exists' }
        else { Write-File '.memory/MEMORY.md' (Get-Text $B64.MemoryIndex); Ok 'created .memory/MEMORY.md' }

        # -- 3) Claude Code: autoMemoryDirectory -> <repo>\.memory, absolute path, in the untracked settings.local.json --
        #    (the tracked settings.json ignores this key for safety, per the official docs)
        New-Item -ItemType Directory -Force '.claude' | Out-Null
        $settingsPath = '.claude/settings.local.json'
        $want = Join-Path $Root '.memory'
        $cur = $null
        if (Test-Path $settingsPath -PathType Leaf) {
            $raw = (Read-File $settingsPath).Trim()
            if ($raw) { try { $cur = $raw | ConvertFrom-Json } catch { throw "x $settingsPath is not valid JSON, fix it first" } }
        }
        if ($null -eq $cur) { $cur = New-Object PSObject }
        $prop = $cur.PSObject.Properties['autoMemoryDirectory']
        if ($prop -and $prop.Value -eq $want) {
            Ok "$settingsPath already points to $want"
        } else {
            if ($prop) { $prop.Value = $want } else { $cur | Add-Member -NotePropertyName 'autoMemoryDirectory' -NotePropertyValue $want }
            Write-File $settingsPath (($cur | ConvertTo-Json -Depth 20) + "`n")   # only this key changes, the rest is kept
            Ok "wrote $settingsPath (autoMemoryDirectory -> $want)"
        }

        # -- 4) .gitignore: settings.local.json carries a machine-local absolute path, keep it out of the repo --
        $giPath = '.gitignore'; $entry = '.claude/settings.local.json'
        $gi = if (Test-Path $giPath -PathType Leaf) { Read-File $giPath } else { '' }
        if (($gi -split "`r?`n") -contains $entry) {
            Ok ".gitignore already lists $entry"
        } else {
            if ($gi -and -not $gi.EndsWith("`n")) { $gi += "`n" }
            Write-File $giPath ($gi + (Get-Text $B64.GitignoreBlock))
            Ok "appended $entry to .gitignore"
        }

        # -- 5) Codex: its memory directory is fixed ($CODEX_HOME/memories), so its built-in memory is switched off entirely --
        New-Item -ItemType Directory -Force '.codex' | Out-Null
        $tomlPath = '.codex/config.toml'
        if (-not (Test-Path $tomlPath -PathType Leaf)) {
            Write-File $tomlPath (Get-Text $B64.CodexBlock); Ok "wrote $tomlPath"
        } else {
            $toml = Read-File $tomlPath
            if ($toml -match '(?m)^\[memories\]') {
                if (($toml -match '(?m)^generate_memories *= *false') -and ($toml -match '(?m)^use_memories *= *false') -and ($toml -match '(?m)^dedicated_tools *= *false')) {
                    Ok "$tomlPath [memories] already has all three switches off"
                } else {
                    Warn "$tomlPath has a [memories] section but not all three switches are false, left unchanged: check it by hand"
                }
            } else {
                Write-File $tomlPath ($toml + "`n" + (Get-Text $B64.CodexBlock)); Ok "appended [memories] to $tomlPath"
            }
        }

        # -- 6) Memory rules inside AGENTS.md (only with -WithRule): without a global rule set this is the only lever for
        #    Codex / dsh / opencode, whose read/write behaviour comes solely from rule files --
        $agentsNow = Get-Item -LiteralPath 'AGENTS.md' -Force -ErrorAction SilentlyContinue
        if (-not $WithRule) {
            Ok 'no -WithRule: AGENTS.md left alone (the memory read/write rules come from the global rule set)'
        } elseif ($agentsNow -and -not $agentsNow.LinkType -and ((Read-File 'AGENTS.md') -match '\.memory/')) {
            Ok 'AGENTS.md already mentions .memory/, not appended again'
        } elseif ($agentsNow -and -not $agentsNow.LinkType) {
            $a = Read-File 'AGENTS.md'; if (-not $a.EndsWith("`n")) { $a += "`n" }
            Write-File 'AGENTS.md' ($a + (Get-Text $B64.RuleSection))
            Ok 'appended the project-memory section to AGENTS.md'
        }
    } finally {
        Pop-Location
    }

    # -- 7) Two things left for a human --
    Write-Host ''
    Write-Host '-- Codex trust (only if you use Codex; an untrusted project silently ignores .codex/) --'
    Write-Host 'append this to ~/.codex/config.toml:'
    Write-Host ''
    Write-Host ('[projects."' + $Root.Replace('\', '\\') + '"]')
    Write-Host 'trust_level = "trusted"'
    Write-Host ''
    Write-Host '-- Verify --'
    Write-Host 'Claude Code: open a session in this directory and ask it to repeat, without tools, the project instruction about where memory is written'
    $probe = if ($ScriptDir) { Join-Path $ScriptDir 'codex-effective-config.py' } else { '' }   # empty under irm | iex
    if ($probe -and (Test-Path -LiteralPath $probe -PathType Leaf)) {
        Write-Host "Codex: once trusted, run: python `"$probe`" `"$Root`""
    } else {
        Write-Host "Codex: once trusted, run: irm $RawBase/codex-effective-config.py -OutFile `"`$env:TEMP\codex-effective-config.py`"; python `"`$env:TEMP\codex-effective-config.py`" `"$Root`""
    }
    Write-Host 'dsh / opencode: open a session here and ask the same question; they read AGENTS.md'
    if ($Warn -gt 0) { Write-Host ''; Write-Host "! $Warn warning(s) above need a human" }
} -RepoPath $RepoPath -WithRule ([bool]$WithRule) -Help ([bool]$Help) -Rest $Rest -ScriptDir $PSScriptRoot
