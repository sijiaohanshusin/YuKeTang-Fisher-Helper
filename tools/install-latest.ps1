param([switch]$Launch)
$ErrorActionPreference = 'Stop'
$releaseRepository = 'sijiaohanshusin/YuKeTang-Fisher-Helper'
$releaseInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/$releaseRepository/releases/latest" -Headers @{'User-Agent'='YuketangHelper-Installer'}
$setupAsset = $releaseInfo.assets | Where-Object { $_.name -like 'YuketangHelper-Setup-*-Windows-x64.exe' } | Select-Object -First 1
$hashAsset = $releaseInfo.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' } | Select-Object -First 1
if (-not $setupAsset -or -not $hashAsset) { throw 'The latest release has no verified Windows installer.' }
$downloadFolder = Join-Path $env:TEMP ('YuketangHelper-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $downloadFolder | Out-Null
$setupPath = Join-Path $downloadFolder $setupAsset.name
$hashPath = Join-Path $downloadFolder 'SHA256SUMS.txt'
Invoke-WebRequest -Uri $setupAsset.browser_download_url -OutFile $setupPath
Invoke-WebRequest -Uri $hashAsset.browser_download_url -OutFile $hashPath
$expectedHash = $null
foreach ($hashLine in Get-Content -LiteralPath $hashPath) {
    if ($hashLine -match '^([a-fA-F0-9]{64})\s+\*?(.+)$' -and $Matches[2] -eq $setupAsset.name) { $expectedHash = $Matches[1] }
}
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $setupPath).Hash
if (-not $expectedHash -or $actualHash -ne $expectedHash) { throw 'Installer SHA256 verification failed. Nothing was installed.' }
$installProcess = Start-Process -FilePath $setupPath -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER' -WindowStyle Hidden -Wait -PassThru
if ($installProcess.ExitCode -ne 0) { throw "Installer returned exit code $($installProcess.ExitCode)." }
Write-Host 'Installed. Open Yuketang Helper from the desktop or Start menu.'
if ($Launch) {
    $appExecutable = Join-Path $env:LOCALAPPDATA 'Programs\YuketangHelper\YuketangHelper.exe'
    $appDataDirectory = Join-Path $env:LOCALAPPDATA 'YuketangHelper\store'
    Start-Process -FilePath $appExecutable -ArgumentList ('--data-dir "{0}"' -f $appDataDirectory) -WindowStyle Hidden
}
