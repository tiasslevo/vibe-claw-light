[CmdletBinding()]
param(
    [ValidateSet('codex', 'claude')]
    [string]$Provider,
    [switch]$SkipSetup
)

# An inherited VIBE_CLAW_ROOT belongs to another instance and is left untouched.
# Official dependency installers may register their own user-level PATH entry.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DownloadDirectory = $null

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    $global:LASTEXITCODE = 0
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Echec de $Executable (code $LASTEXITCODE)."
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
    Invoke-Checked $script:PowerShellExecutable @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Destination)
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
    $script:PowerShellExecutable = (Get-Command powershell.exe -CommandType Application -ErrorAction Stop).Source
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
            Write-Host 'Verification Telegram et petit appel de test au moteur choisi...'
            Invoke-Checked $PythonExecutable @('run.py', 'doctor', '--live')
            Invoke-Checked $PythonExecutable @('run.py', 'start')
            Write-Host 'Installation terminee. Ecris a ton bot dans Telegram.'
            Write-Host 'Pour les prochains demarrages : start.cmd. Pour arreter : stop.cmd.'
        }
    } finally {
        Pop-Location
    }
} catch {
    Write-Host "Installation interrompue : $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Corrige cette etape puis relance install.cmd. Ta configuration et ta memoire sont conservees.'
    exit 1
} finally {
    if ($script:DownloadDirectory -and (Test-Path -LiteralPath $script:DownloadDirectory)) {
        Remove-Item -LiteralPath $script:DownloadDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}
exit 0
