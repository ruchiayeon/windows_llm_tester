#Requires -Version 5.1
<#
.SYNOPSIS
    골든 이미지(base.vhdx)를 한 번 만든다. 관리자 PowerShell에서 실행해야 한다.

.DESCRIPTION
    Windows 설치 화면 없이 ISO의 install.wim을 VHDX에 바로 풀어(DISM) 부팅 가능한 원본을 만든다.
      1. ISO 마운트 → 에디션 선택
      2. VHDX 생성 · GPT 분할(EFI / MSR / Windows) · 이미지 적용 · 부팅 파일 생성      [관리자 필요]
      3. 무인 설정(unattend.xml) 주입: 한국어 · 로컬 관리자 wtest · OOBE 화면 생략
      4. 빌드용 VM으로 첫 부팅 → PowerShell Direct 응답 대기
      5. VM 안 정리: unattend 사본 삭제(비밀번호 평문), 자동 업데이트 끔, 절전 끔
      6. 서버 접속 확인 · MachineGuid · 평가판 만료일 기록
      7. 종료 → 빌드 VM 제거 → base.vhdx 읽기 전용

    VM 비밀번호는 무작위로 만들고, 실행한 사용자만 풀 수 있게 DPAPI로 암호화해 저장한다.
    → 반드시 테스트를 돌릴 계정(같은 Windows 사용자)으로 "관리자 권한으로 실행"해야 한다.

    기본값은 wtest.toml의 [image] · [target]과 같게 맞춰 두었다. 한쪽을 바꾸면 다른 쪽도 바꾼다.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build_base.ps1
#>
[CmdletBinding()]
param(
    [string]$IsoPath,
    [string]$Edition = 'Enterprise',
    [string]$OutVhdx,          # 기본: <프로젝트>\data\vms\base\base.vhdx
    [string]$CredentialPath,   # 기본: <프로젝트>\data\guest-cred.xml
    [string]$Switch = 'Default Switch',
    [string]$Server = '192.168.0.112:10443',
    [int]$SizeGB = 64,
    [int]$MemoryMB = 4096,
    [int]$Cpu = 2,
    [int]$BootTimeoutMin = 30,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$GPT_EFI = '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}'
$GPT_MSR = '{e3c9e316-0b5c-4db8-817d-f92df00215ae}'
$GPT_BASIC = '{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}'
$BuildVm = 'wtest-base-build'

function Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# ---- 0. 사전 확인 ---------------------------------------------------------------
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '관리자 PowerShell에서 실행해야 합니다 (디스크 분할 · 이미지 적용에 필요).'
}

# PowerShell 5.1은 param 기본값 계산 시점에 $PSScriptRoot가 비어 있으므로 경로 기본값은 여기서 정한다
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir '..')).Path
if (-not $OutVhdx) { $OutVhdx = Join-Path $root 'data\vms\base\base.vhdx' }
if (-not $CredentialPath) { $CredentialPath = Join-Path $root 'data\guest-cred.xml' }
if (-not $IsoPath) {
    $isos = @(Get-ChildItem (Join-Path $root 'images') -Filter *.iso -ErrorAction SilentlyContinue)
    if ($isos.Count -ne 1) { throw "images 폴더에 ISO가 정확히 1개 있어야 합니다 (현재 $($isos.Count)개). -IsoPath로 지정할 수도 있습니다." }
    $IsoPath = $isos[0].FullName
}
$OutVhdx = [IO.Path]::GetFullPath($OutVhdx)
$CredentialPath = [IO.Path]::GetFullPath($CredentialPath)
$serverHost, $serverPort = $Server.Split(':')

if (Test-Path $OutVhdx) {
    if (-not $Force) { throw "$OutVhdx 가 이미 있습니다. 다시 만들려면 -Force" }
    Set-ItemProperty $OutVhdx -Name IsReadOnly -Value $false
    Remove-Item $OutVhdx
}
if (Get-VM -Name $BuildVm -ErrorAction SilentlyContinue) { throw "이전 빌드 VM '$BuildVm' 이 남아 있습니다. Remove-VM 후 다시 실행하세요." }
New-Item -ItemType Directory -Force (Split-Path $OutVhdx) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $CredentialPath) | Out-Null

# ---- 비밀번호 · 자격 증명 ----------------------------------------------------------
$bytes = New-Object byte[] 18
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
# Base64(24자) + 복잡도 규칙용 문자. XML에 그대로 넣어도 안전한 문자만 쓴다
$password = [Convert]::ToBase64String($bytes).Replace('+', 'x').Replace('/', 'y') + 'Aa1-'
$securePw = ConvertTo-SecureString $password -AsPlainText -Force
# 비밀번호는 VHD에만 들어가므로 이후 단계가 실패해도 잃지 않도록 가장 먼저 저장한다
New-Object Management.Automation.PSCredential('.\wtest', $securePw) | Export-Clixml -Path $CredentialPath
Write-Host "자격 증명 저장: $CredentialPath (이 Windows 사용자만 해독 가능)"

$iso = $null; $vhd = $null
try {
    # ---- 1. ISO · 에디션 ----------------------------------------------------------
    Step "ISO 마운트: $IsoPath"
    $iso = Mount-DiskImage -ImagePath $IsoPath -PassThru
    $isoDrive = ($iso | Get-Volume).DriveLetter
    $wim = @("${isoDrive}:\sources\install.wim", "${isoDrive}:\sources\install.esd") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $wim) { throw 'ISO에 sources\install.wim / install.esd 가 없습니다.' }
    $images = @(Get-WindowsImage -ImagePath $wim)
    $images | ForEach-Object { Write-Host ("   [{0}] {1}" -f $_.ImageIndex, $_.ImageName) }
    $picked = @($images | Where-Object { $_.ImageName -like "*$Edition*" -and $_.ImageName -notmatch '\bN\b' })
    if ($picked.Count -ne 1) { throw "'$Edition' 에디션이 정확히 1개가 아닙니다 ($($picked.Count)개). -Edition을 더 구체적으로 지정하세요." }
    $index = $picked[0].ImageIndex
    Write-Host "   선택: [$index] $($picked[0].ImageName)"

    # ---- 2. VHDX · 분할 · 적용 · 부팅 파일 -------------------------------------------
    Step "VHDX 생성 ($SizeGB GB, 동적): $OutVhdx"
    New-VHD -Path $OutVhdx -SizeBytes ($SizeGB * 1GB) -Dynamic | Out-Null
    $vhd = Mount-VHD -Path $OutVhdx -Passthru
    $disk = $vhd | Get-Disk
    # 잘못된 디스크 번호로 초기화하면 실제 드라이브가 지워진다. 방금 만든 빈 가상 디스크인지 확인한다
    if ($disk.BusType -ne 'File Backed Virtual' -or $disk.PartitionStyle -ne 'RAW' -or $disk.Location -ne $OutVhdx) {
        throw "안전 확인 실패: 디스크 $($disk.Number) (BusType=$($disk.BusType), Style=$($disk.PartitionStyle), Location=$($disk.Location))"
    }
    Initialize-Disk -Number $disk.Number -PartitionStyle GPT
    # GPT 초기화 시 MSR이 자동으로 생길 수 있으므로 없을 때만 만든다
    $efi = New-Partition -DiskNumber $disk.Number -Size 260MB -GptType $GPT_EFI -AssignDriveLetter
    Format-Volume -Partition $efi -FileSystem FAT32 -NewFileSystemLabel 'System' -Confirm:$false | Out-Null
    if (-not (Get-Partition -DiskNumber $disk.Number | Where-Object { $_.GptType -eq $GPT_MSR })) {
        New-Partition -DiskNumber $disk.Number -Size 16MB -GptType $GPT_MSR | Out-Null
    }
    $win = New-Partition -DiskNumber $disk.Number -UseMaximumSize -GptType $GPT_BASIC -AssignDriveLetter
    Format-Volume -Partition $win -FileSystem NTFS -NewFileSystemLabel 'Windows' -Confirm:$false | Out-Null
    $efiDrive = (Get-Partition -DiskNumber $disk.Number -PartitionNumber $efi.PartitionNumber).DriveLetter
    $winDrive = (Get-Partition -DiskNumber $disk.Number -PartitionNumber $win.PartitionNumber).DriveLetter

    Step "이미지 적용 (수 분 걸립니다) → ${winDrive}:\"
    Expand-WindowsImage -ImagePath $wim -Index $index -ApplyPath "${winDrive}:\" | Out-Null

    Step '부팅 파일 생성 (UEFI)'
    & bcdboot.exe "${winDrive}:\Windows" /s "${efiDrive}:" /f UEFI | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "bcdboot 실패 (exit $LASTEXITCODE)" }

    # ---- 3. 무인 설정 주입 ----------------------------------------------------------
    Step 'unattend.xml 주입 (한국어 · 로컬 관리자 wtest)'
    $template = Get-Content (Join-Path $scriptDir 'unattend.template.xml') -Raw -Encoding UTF8
    $panther = "${winDrive}:\Windows\Panther"
    New-Item -ItemType Directory -Force $panther | Out-Null
    [IO.File]::WriteAllText("$panther\unattend.xml", $template.Replace('{{PASSWORD}}', $password), (New-Object Text.UTF8Encoding($false)))

    Remove-PartitionAccessPath -DiskNumber $disk.Number -PartitionNumber $efi.PartitionNumber -AccessPath "${efiDrive}:\"
}
finally {
    if ($vhd) { Dismount-VHD -Path $OutVhdx -ErrorAction SilentlyContinue }
    if ($iso) { Dismount-DiskImage -ImagePath $IsoPath -ErrorAction SilentlyContinue | Out-Null }
}

# ---- 4. 첫 부팅 ----------------------------------------------------------------
$completed = $false
try {
Step "빌드 VM 첫 부팅: $BuildVm (Gen2 · Secure Boot · $MemoryMB MB · CPU $Cpu)"
New-VM -Name $BuildVm -Generation 2 -MemoryStartupBytes ($MemoryMB * 1MB) -VHDPath $OutVhdx -SwitchName $Switch | Out-Null
Set-VM -Name $BuildVm -ProcessorCount $Cpu -StaticMemory -AutomaticCheckpointsEnabled $false
Set-VMFirmware -VMName $BuildVm -EnableSecureBoot On -SecureBootTemplate MicrosoftWindows
Start-VM -Name $BuildVm

$cred = $null
$lastError = $null
$deadline = (Get-Date).AddMinutes($BootTimeoutMin)
Write-Host "   PowerShell Direct 응답 대기 (최대 $BootTimeoutMin 분, 첫 부팅은 5~15분)..."
while (-not $cred) {
    foreach ($user in @('.\wtest', 'wtest')) {
        $try = New-Object Management.Automation.PSCredential($user, $securePw)
        try {
            Invoke-Command -VMName $BuildVm -Credential $try -ScriptBlock { $true } -ErrorAction Stop | Out-Null
            $cred = $try; break
        } catch {
            # 부팅 중에는 연결 실패가 정상이므로 시간 초과까지 재시도하고, 마지막 원인은 남겨 둔다
            $lastError = $_.Exception.Message
        }
    }
    if ($cred) { break }
    if ((Get-Date) -gt $deadline) {
        throw "첫 부팅이 $BootTimeoutMin 분 안에 끝나지 않았습니다 (마지막 오류: $lastError). vmconnect localhost $BuildVm 로 화면을 확인하세요."
    }
    Start-Sleep -Seconds 15
}
Write-Host "   연결됨 ($($cred.UserName))"
$cred | Export-Clixml -Path $CredentialPath   # 실제로 통한 사용자 이름 형식으로 다시 저장

# ---- 5 · 6. VM 안 정리 · 정보 수집 -------------------------------------------------
Step 'VM 안 정리 · 서버 접속 확인'
$info = Invoke-Command -VMName $BuildVm -Credential $cred -ArgumentList $serverHost, $serverPort -ScriptBlock {
    param($h, $p)
    $warnings = New-Object System.Collections.Generic.List[string]
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)

    # [필수] 비밀번호 평문이 든 unattend 사본 삭제. 실패하면 빌드를 중단한다
    'C:\Windows\Panther\unattend.xml', 'C:\Windows\Panther\Unattend\unattend.xml', 'C:\Windows\System32\Sysprep\unattend.xml' |
        Where-Object { Test-Path $_ } | Remove-Item -Force -ErrorAction Stop

    # [선택] 테스트 도중 재부팅되지 않도록 자동 업데이트 끔. 실패는 기록만 한다
    try {
        $au = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
        New-Item -Path $au -Force -ErrorAction Stop | Out-Null
        Set-ItemProperty -Path $au -Name NoAutoUpdate -Value 1 -Type DWord -ErrorAction Stop
    } catch { $warnings.Add("업데이트 정책: $($_.Exception.Message)") }
    try {
        Stop-Service wuauserv -Force -ErrorAction Stop
        Set-Service wuauserv -StartupType Disabled -ErrorAction Stop
    } catch { $warnings.Add("wuauserv: $($_.Exception.Message)") }
    # [선택] 절전 · 최대 절전 끔
    & powercfg.exe /change standby-timeout-ac 0 | Out-Null
    if ($LASTEXITCODE -ne 0) { $warnings.Add("powercfg standby exit $LASTEXITCODE") }
    & powercfg.exe /hibernate off | Out-Null
    if ($LASTEXITCODE -ne 0) { $warnings.Add("powercfg hibernate exit $LASTEXITCODE") }

    # 정보 수집
    $lic = Get-CimInstance SoftwareLicensingProduct -Filter "PartialProductKey IS NOT NULL AND Name LIKE 'Windows%'" |
        Select-Object -First 1
    $os = Get-CimInstance Win32_OperatingSystem
    $tcp = New-Object Net.Sockets.TcpClient
    $reach = $false; $reachError = $null
    try { $reach = $tcp.ConnectAsync($h, [int]$p).Wait(5000) }
    catch { $reachError = $_.Exception.GetBaseException().Message }
    finally { $tcp.Dispose() }
    [pscustomobject]@{
        is_admin         = $isAdmin
        os               = $os.Caption
        version          = $os.Version
        ui_language      = (Get-WinSystemLocale).Name
        machine_guid     = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography').MachineGuid
        license_status   = if ($lic) { $lic.LicenseStatus } else { $null }   # 1 = 정품 인증됨
        eval_days_left   = if ($lic) { [math]::Floor($lic.GracePeriodRemaining / 1440) } else { $null }
        server_reachable = $reach
        server_error     = $reachError
        warnings         = @($warnings)
    }
}
$info | Format-List is_admin, os, version, ui_language, machine_guid, license_status, eval_days_left, server_reachable, server_error | Out-Host
foreach ($w in $info.warnings) { Write-Warning "VM 설정 일부 실패: $w" }
if (-not $info.is_admin) { Write-Warning 'PowerShell Direct 세션이 관리자 권한이 아닙니다. M2 설치 단계에서 문제가 됩니다.' }
# 정품 인증 전이면 GracePeriodRemaining은 평가판 90일 시계가 아니다
$evalKnown = ($info.license_status -eq 1 -and $null -ne $info.eval_days_left)
if (-not $evalKnown) { Write-Warning "평가판 만료일을 확정하지 못했습니다 (LicenseStatus=$($info.license_status)). 나중에 VM 안에서 slmgr /dli 로 확인하세요." }

# ---- 7. 종료 · 정리 · 읽기 전용 ----------------------------------------------------
Step '종료 → 빌드 VM 제거 → base.vhdx 읽기 전용'
Stop-VM -Name $BuildVm -Force
Remove-VM -Name $BuildVm -Force
Set-ItemProperty $OutVhdx -Name IsReadOnly -Value $true
$completed = $true
}
finally {
    if (-not $completed -and (Get-VM -Name $BuildVm -ErrorAction SilentlyContinue)) {
        Write-Warning "빌드가 중간에 실패했습니다. 원인 확인용으로 빌드 VM '$BuildVm' 을 남겨 두었습니다."
        Write-Warning "  화면 확인: vmconnect localhost $BuildVm   (계정 wtest)"
        Write-Warning "  비밀번호:  (Import-Clixml '$CredentialPath').GetNetworkCredential().Password"
        Write-Warning "  정리:      Stop-VM $BuildVm -TurnOff; Remove-VM $BuildVm -Force   후 -Force 로 다시 실행"
    }
}
$meta = [ordered]@{
    built_at         = (Get-Date).ToString('s')
    iso              = Split-Path $IsoPath -Leaf
    edition          = $picked[0].ImageName
    os_version       = $info.version
    ui_language      = $info.ui_language
    base_machine_guid = $info.machine_guid
    license_status   = $info.license_status
    eval_days_left   = if ($evalKnown) { $info.eval_days_left } else { $null }
    eval_expires_on  = if ($evalKnown) { (Get-Date).AddDays($info.eval_days_left).ToString('yyyy-MM-dd') } else { $null }
    server           = $Server
    server_reachable = $info.server_reachable
    credential_user  = $cred.UserName
}
$meta | ConvertTo-Json | Set-Content -Path ([IO.Path]::ChangeExtension($OutVhdx, '.json')) -Encoding UTF8

Write-Host "`n완료: $OutVhdx" -ForegroundColor Green
if (-not $info.server_reachable) {
    Write-Warning "VM에서 $Server 에 접속하지 못했습니다 ($($info.server_error)). 네트워크 설정을 확인해야 SAVEX 테스트가 가능합니다."
}
