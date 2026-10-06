$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & $pythonCommand.Source -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)"
        if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.10 through 3.14. Check python --version.' }
        & $pythonCommand.Source -m venv .venv
    } else {
        py -3 -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the environment. Check python --version and try python -m venv .venv.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your internet connection.' }
if (-not (Test-Path '.streamlit\secrets.toml')) {
    Copy-Item '.streamlit\secrets.toml.example' '.streamlit\secrets.toml'
    Write-Host 'Add your API key to .streamlit\secrets.toml using VS Code, then refresh the app.'
}
& '.\.venv\Scripts\python.exe' -m streamlit run app.py --server.address 127.0.0.1
