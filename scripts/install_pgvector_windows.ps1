param(
    [string]$PgRoot = "C:\Program Files\PostgreSQL\18",
    [string]$Database = "bugsift",
    [string]$User = "postgres",
    [string]$HostName = "localhost",
    [int]$Port = 5432,
    [string]$PgvectorVersion = "v0.8.3"
)

$ErrorActionPreference = "Stop"

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. Run this script from 'x64 Native Tools Command Prompt for VS' as Administrator."
    }
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script as Administrator so pgvector can be installed into $PgRoot."
}

if (-not (Test-Path $PgRoot)) {
    throw "PostgreSQL directory not found: $PgRoot"
}

Require-Command git
Require-Command nmake
Require-Command cl

$env:PGROOT = $PgRoot
$workDir = Join-Path $env:TEMP "pgvector-build"
$sourceDir = Join-Path $workDir "pgvector"

New-Item -ItemType Directory -Force -Path $workDir | Out-Null
if (Test-Path $sourceDir) {
    Remove-Item -Recurse -Force $sourceDir
}

git clone --branch $PgvectorVersion https://github.com/pgvector/pgvector.git $sourceDir
Push-Location $sourceDir
try {
    nmake /F Makefile.win
    nmake /F Makefile.win install
}
finally {
    Pop-Location
}

$psql = Join-Path $PgRoot "bin\psql.exe"
if (-not (Test-Path $psql)) {
    throw "psql.exe not found under $PgRoot\bin"
}

& $psql -h $HostName -p $Port -U $User -d $Database -c "CREATE EXTENSION IF NOT EXISTS vector;"

Write-Host "pgvector installed and enabled for database '$Database'."
Write-Host "Now run: cd backend; alembic upgrade head"
