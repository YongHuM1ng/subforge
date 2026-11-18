# One-click polishing for an already translated SRT.
# Reads <translated>.analysis.json to find the original SRT, then runs
# translate_srt.py --translated, so analysis and translation are skipped.
# Compatible with Windows PowerShell 5.1. Keep this file ASCII-only.

param(
    [Parameter(Position = 0)]
    [string]$TranslatedSrt,

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$Python = Join-Path $ProjectRoot 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
}
$Program = Join-Path $ScriptDir 'translate_srt.py'
$Config = Join-Path $ProjectRoot 'config.toml'

try {
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python runtime not found. Expected: runtime\python\python.exe or .venv\Scripts\python.exe"
    }
    if (-not (Test-Path -LiteralPath $Program)) {
        throw "Program not found: $Program"
    }
    if (-not (Test-Path -LiteralPath $Config)) {
        throw "Config not found: $Config"
    }
    if ($Rest -and $Rest.Count -gt 0) {
        throw 'Drop only one translated SRT file.'
    }

    if ([string]::IsNullOrWhiteSpace($TranslatedSrt)) {
        $translatedPath = Read-Host 'Translated SRT file path'
    } else {
        $translatedPath = $TranslatedSrt
        Write-Host "Translated file: $translatedPath" -ForegroundColor Cyan
    }
    if ([string]::IsNullOrWhiteSpace($translatedPath)) {
        throw 'Translated SRT path cannot be empty'
    }
    $translatedPath = $translatedPath.Trim().Trim('"')
    if (-not $translatedPath.EndsWith('.srt', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Only .srt files are supported: $translatedPath"
    }
    if (-not [System.IO.Path]::IsPathRooted($translatedPath)) {
        $translatedPath = Join-Path (Get-Location) $translatedPath
    }
    $translatedPath = [System.IO.Path]::GetFullPath($translatedPath)
    if (-not (Test-Path -LiteralPath $translatedPath)) {
        throw "Translated file not found: $translatedPath"
    }

    $dir = [System.IO.Path]::GetDirectoryName($translatedPath)
    $base = [System.IO.Path]::GetFileNameWithoutExtension($translatedPath)
    # movie.zh.polished.srt / movie.zh.polished.2.srt -> movie.zh (same rule as track.translation_stem)
    $base = $base -replace '\.polished(\.\d+)?$', ''
    $sidecar = Join-Path $dir ($base + '.analysis.json')
    $originalPath = ''
    $target = ''
    $hasAnalysis = Test-Path -LiteralPath $sidecar

    if ($hasAnalysis) {
        Write-Host "Analysis : $sidecar" -ForegroundColor Cyan
        try {
            $data = Get-Content -LiteralPath $sidecar -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            throw "Cannot read analysis file: $sidecar"
        }
        $originalPath = [string]$data.input
        $target = [string]$data.target
        if ([string]::IsNullOrWhiteSpace($originalPath)) {
            throw "Analysis file has no input path: $sidecar"
        }
        if (-not [System.IO.Path]::IsPathRooted($originalPath)) {
            $originalPath = Join-Path $dir $originalPath
        }
        $originalPath = [System.IO.Path]::GetFullPath($originalPath)
    }
    else {
        Write-Host "Analysis file not found: $sidecar" -ForegroundColor Yellow
        Write-Host 'The original SRT is needed. It will be analyzed once (one API request).'
        $originalPath = Read-Host 'Original SRT file path'
        if ([string]::IsNullOrWhiteSpace($originalPath)) {
            throw 'Original SRT path cannot be empty'
        }
        $originalPath = $originalPath.Trim().Trim('"')
        if (-not [System.IO.Path]::IsPathRooted($originalPath)) {
            $originalPath = Join-Path (Get-Location) $originalPath
        }
        $originalPath = [System.IO.Path]::GetFullPath($originalPath)
    }

    if (-not $originalPath.EndsWith('.srt', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Only .srt files are supported for the original: $originalPath"
    }
    if (-not (Test-Path -LiteralPath $originalPath)) {
        throw "Original file not found: $originalPath"
    }
    if ([string]::Equals($originalPath, $translatedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Original and translated SRT must be different files.'
    }

    $outputPath = Join-Path $dir ($base + '.polished.srt')
    Write-Host ''
    Write-Host 'Starting polish only...' -ForegroundColor Cyan
    Write-Host "Original  : $originalPath"
    Write-Host "Translated: $translatedPath"
    Write-Host "Output    : $outputPath (auto-renamed if it exists)"
    Write-Host "Config    : $Config"
    Write-Host ''
    Write-Host 'Polish instructions (optional, press Enter to skip):' -ForegroundColor Cyan
    $polishPrompt = Read-Host
    Write-Host ''

    $arguments = @($Program, $originalPath, $outputPath, '--translated', $translatedPath, '--config', $Config)
    if ($hasAnalysis) {
        $arguments += @('--analysis-file', $sidecar)
    }
    if (-not [string]::IsNullOrWhiteSpace($target)) {
        $arguments += @('--target', $target)
    }
    if (-not [string]::IsNullOrWhiteSpace($polishPrompt)) {
        $arguments += @('--polish-prompt', $polishPrompt)
    }
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Polisher failed with exit code $LASTEXITCODE"
    }
    Write-Host ''
    Write-Host 'Done. See the completion path above.' -ForegroundColor Green
}
catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}