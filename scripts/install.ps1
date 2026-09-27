[CmdletBinding()]
param(
    [ValidateSet('codex', 'claude')]
    [string]$Provider,
    [switch]$SkipSetup
)

# An inherited VIBE_CLAW_ROOT belongs to another instance and is left untouched.
# Official dependency installers may register their own user-level PATH entry.
# Use modules shipped with the actual host, not a PS7 path inherited through
# cmd.exe/Python. Process-local only; never modify profiles or registry values.
$PreviousModulePath = $env:PSModulePath
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
$Utf8Encoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8Encoding
$OutputEncoding = $Utf8Encoding
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DownloadDirectory = $null

function Protect-InstallMessage {
    param([string]$Message)
    $Safe = [regex]::Replace($Message, '(?i)https?://[^\s<>"'']+', '[lien masque]')
    $Safe = [regex]::Replace($Safe, '\b[0-9]{5,16}:[A-Za-z0-9_-]{20,}\b', '[token masque]')
    $Safe = [regex]::Replace($Safe, '\bsk-[A-Za-z0-9_-]{10,}\b', '[cle masquee]')
    $Safe = [regex]::Replace($Safe, '(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [masque]')
    $Safe = [regex]::Replace($Safe, '(?i)\b(token|password|secret|api[_-]?key|authorization)\s*[=:]\s*\S+', '$1=[masque]')
    if ($Safe.Length -gt 1500) { $Safe = $Safe.Substring(0, 1500) + '...' }
    return $Safe
}

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments, [switch]$RedactOutput)
    $global:LASTEXITCODE = 0
    if ($RedactOutput) {
        $PreviousErrorPreference = $ErrorActionPreference
        try {
            # Native stderr must remain visible, without allowing an error
            # record to bypass redaction before the child's exit is checked.
            $ErrorActionPreference = 'Continue'
            & $Executable @Arguments 2>&1 | ForEach-Object {
                Write-Host (Protect-InstallMessage ([string]$_))
            }
            $CommandExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $PreviousErrorPreference
        }
    } else {
        & $Executable @Arguments
        $CommandExitCode = $LASTEXITCODE
    }
    if ($CommandExitCode -ne 0) {
        throw "Echec de $Executable (code $CommandExitCode)."
    }
}

function Find-Application {
    param([string]$Name)
    # The runtime uses native executables, never npm .cmd/.ps1 wrappers.
    $Found = Get-Command "$Name.exe" -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($Found) { return $Found.Source }
    foreach ($Directory in $script:ApplicationDirectories) {
        $Candidate = Join-Path $Directory "$Name.exe"
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) { return $Candidate }
    }
    return $null
}

function Install-OfficialScript {
    param([string]$Url, [string]$FileName)
    $Destination = Join-Path $script:DownloadDirectory $FileName
    Write-Host "Telechargement : $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
    # The command checks the real child process immediately before running the
    # downloaded script. Paths are passed as environment data, never shell code.
    $Bootstrap = @'
$ErrorActionPreference = 'Stop'
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
$Utf8 = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try {
    foreach ($Name in @('Get-FileHash', 'Invoke-WebRequest', 'Expand-Archive', 'ConvertFrom-Json', 'Join-Path', 'Test-Path')) {
        $null = Get-Command $Name -ErrorAction Stop
    }
    & $env:VIBE_LIGHT_INSTALLER_SCRIPT
} catch {
    Write-Output ('Installation du composant : ' + $_.Exception.Message)
    exit 1
}
'@
    $BootstrapPath = Join-Path $script:DownloadDirectory 'bootstrap.ps1'
    [IO.File]::WriteAllText($BootstrapPath, $Bootstrap, [Text.UTF8Encoding]::new($true))
    $PreviousInstallerScript = $env:VIBE_LIGHT_INSTALLER_SCRIPT
    $PreviousChildModulePath = $env:PSModulePath
    try {
        $env:VIBE_LIGHT_INSTALLER_SCRIPT = $Destination
        $env:PSModulePath = $null
        Invoke-Checked $script:PowerShellExecutable @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $BootstrapPath) -RedactOutput
    } finally {
        $env:PSModulePath = $PreviousChildModulePath
        $env:VIBE_LIGHT_INSTALLER_SCRIPT = $PreviousInstallerScript
    }
}

try {
    if ($env:OS -ne 'Windows_NT') { throw 'Utilise scripts/install.sh sur macOS ou Linux.' }
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'run.py'))) {
        throw 'Le projet est incomplet. Extrais toute l archive avant de lancer install.cmd.'
    }
    if (-not $Provider) {
        Write-Host 'Choisis le moteur auquel tu as acces : codex ou claude.'
        $Provider = (Read-Host 'Moteur').Trim().ToLowerInvariant()
        if ($Provider -notin @('codex', 'claude')) { throw 'Choix inconnu. Relance avec -Provider codex ou -Provider claude.' }
    }

    $script:ApplicationDirectories = @(
        (Join-Path $env:USERPROFILE '.local\bin'),
        (Join-Path $env:LOCALAPPDATA 'Programs\OpenAI\Codex\bin'),
        (Join-Path $env:APPDATA 'npm')
    )
    if ($env:UV_INSTALL_DIR) { $script:ApplicationDirectories += $env:UV_INSTALL_DIR }
    if ($env:CODEX_INSTALL_DIR) { $script:ApplicationDirectories += $env:CODEX_INSTALL_DIR }
    $env:PATH = ($script:ApplicationDirectories -join ';') + ';' + $env:PATH
    $script:PowerShellExecutable = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $script:PowerShellExecutable)) {
        throw 'Windows PowerShell est introuvable. Le lancement est arrete sans modifier les politiques de ce PC.'
    }
    $script:DownloadDirectory = Join-Path ([IO.Path]::GetTempPath()) ('vibe-claw-light-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $script:DownloadDirectory | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $UvExecutable = Find-Application 'uv'
    if (-not $UvExecutable) {
        $PreviousUvNoModifyPath = $env:UV_NO_MODIFY_PATH
        try {
            $env:UV_NO_MODIFY_PATH = '1'
            Install-OfficialScript 'https://astral.sh/uv/install.ps1' 'uv-install.ps1'
        } finally {
            $env:UV_NO_MODIFY_PATH = $PreviousUvNoModifyPath
        }
        $UvExecutable = Find-Application 'uv'
        if (-not $UvExecutable) { throw 'uv reste introuvable apres installation. Consulte docs/INSTALLATION.md.' }
    }
    Invoke-Checked $UvExecutable @('--version')

    $EngineExecutable = Find-Application $Provider
    if (-not $EngineExecutable) {
        Write-Host "Installation du moteur choisi : $Provider"
        if ($Provider -eq 'codex') {
            $PreviousCodexNonInteractive = $env:CODEX_NON_INTERACTIVE
            try {
                $env:CODEX_NON_INTERACTIVE = '1'
                Install-OfficialScript 'https://chatgpt.com/codex/install.ps1' 'codex-install.ps1'
            } finally {
                $env:CODEX_NON_INTERACTIVE = $PreviousCodexNonInteractive
            }
        } else {
            Install-OfficialScript 'https://claude.ai/install.ps1' 'claude-install.ps1'
        }
        $EngineExecutable = Find-Application $Provider
        if (-not $EngineExecutable) { throw "$Provider reste introuvable apres installation. Consulte docs/INSTALLATION.md." }
    }
    Invoke-Checked $EngineExecutable @('--version')

    Push-Location -LiteralPath $ProjectRoot
    try {
        Write-Host 'Preparation de Python 3.11 et de l environnement local...'
        Invoke-Checked $UvExecutable @('sync', '--python', '3.11')
        $PythonExecutable = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $PythonExecutable)) { throw 'Python local introuvable apres uv sync.' }
        if ($SkipSetup) {
            Write-Host 'Dependances installees. Lance ensuite :'
            Write-Host ".\.venv\Scripts\python.exe run.py setup --provider $Provider"
        } else {
            Invoke-Checked $PythonExecutable @('run.py', 'setup', '--provider', $Provider)
            Write-Host 'Assistant pret. Ecris a ton bot dans Telegram.'
            Write-Host 'Pour les prochains demarrages : start.cmd. Pour arreter : stop.cmd.'
        }
    } finally {
        Pop-Location
    }
} catch {
    Write-Host ('Installation interrompue : ' + (Protect-InstallMessage $_.Exception.Message)) -ForegroundColor Red
    Write-Host 'Corrige cette etape puis relance install.cmd. Ta configuration et ta memoire sont conservees.'
    exit 1
} finally {
    if ($script:DownloadDirectory -and (Test-Path -LiteralPath $script:DownloadDirectory)) {
        Remove-Item -LiteralPath $script:DownloadDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
    $env:PSModulePath = $PreviousModulePath
}
exit 0
