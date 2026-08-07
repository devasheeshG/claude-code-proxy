$ErrorActionPreference = 'Stop'

$BaseUrl = $env:CC_PROXY_URL
if (-not $BaseUrl) {
    Write-Host "Usage: `$env:CC_PROXY_URL = '<URL>'; irm <URL>/install.ps1 | iex"
    exit 1
}
if ($BaseUrl -notmatch '^https?://') {
    throw 'Base URL must start with http:// or https://'
}

# Never accept the API key in command text or a process argument. Read-Host
# keeps input hidden; the plaintext value exists only while this process writes
# the Claude Code settings file.
$secureApiKey = Read-Host 'API key (input hidden)' -AsSecureString
$apiKeyPointer = [IntPtr]::Zero
try {
    $apiKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureApiKey)
    $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($apiKeyPointer)
} finally {
    if ($apiKeyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($apiKeyPointer)
    }
}
if (-not $ApiKey) {
    throw 'API key cannot be empty.'
}

$claudeDir = Join-Path $env:USERPROFILE '.claude'
$settingsFile = Join-Path $claudeDir 'settings.json'
New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null

if (Test-Path $settingsFile) {
    try {
        $settings = Get-Content $settingsFile -Raw | ConvertFrom-Json
    } catch {
        throw "Could not parse $settingsFile; it was left unchanged. $($_.Exception.Message)"
    }
    Copy-Item -Force $settingsFile "$settingsFile.bak"
} else {
    $settings = [PSCustomObject]@{}
}

if ($null -eq $settings.env) {
    $settings | Add-Member -Force -NotePropertyName 'env' -NotePropertyValue ([PSCustomObject]@{})
}
$settings.env | Add-Member -Force -NotePropertyName 'ANTHROPIC_BASE_URL' -NotePropertyValue $BaseUrl
$settings.env | Add-Member -Force -NotePropertyName 'ANTHROPIC_AUTH_TOKEN' -NotePropertyValue $ApiKey
$settings | ConvertTo-Json -Depth 100 | Set-Content $settingsFile -Encoding UTF8
$ApiKey = $null

Write-Host ''
Write-Host 'Claude Code configured to use Claude Code Proxy.'
Write-Host "  Settings: $settingsFile"
Write-Host "  Base URL: $BaseUrl"
Write-Host ''
Write-Host 'Run: claude'
