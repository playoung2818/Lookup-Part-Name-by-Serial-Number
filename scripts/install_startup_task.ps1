# Run locally in an elevated PowerShell window. Never supply a password as an argument.
[CmdletBinding()]
param(
    [string]$UserName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    [string]$PythonPath = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
)
$ErrorActionPreference = 'Stop'
$taskName = 'Receiving Log Web App'
$project = Split-Path $PSScriptRoot -Parent
$entryPoint = Join-Path $PSScriptRoot 'run_web.py'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open PowerShell with Run as administrator, then run this script again.'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python not found: $PythonPath. Supply -PythonPath with the installed interpreter path."
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw "Task '$taskName' already exists. Review it in Task Scheduler before replacing it."
}

Write-Host 'Choose a Windows account with read access to the QuickBooks PDF share.'
Write-Host 'Use its actual Windows password, not a Windows Hello PIN.'
Write-Host 'Credentials will be stored by Windows Task Scheduler, not in this project.'
$credential = Get-Credential -UserName $UserName -Message 'Account for the Receiving Log startup task (must have network-share access)'
if ($null -eq $credential) { throw 'Cancelled. No task was created.' }

$action = New-ScheduledTaskAction -Execute $PythonPath -Argument ('-u "' + $entryPoint + '"') -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

try {
    # Task Scheduler's registration API requires the password transiently.
    # Never print, serialize, or save it. Windows persists the task credentials.
    $password = $credential.GetNetworkCredential().Password
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -User $credential.UserName -Password $password `
        -RunLevel Limited -Description 'Receiving Log website; password logon permits network-share access without a desktop login.' | Out-Null
} finally {
    $password = $null
    $credential = $null
}

$task = Get-ScheduledTask -TaskName $taskName
if ($task.Principal.LogonType -ne 'Password') {
    throw 'Unexpected task logon type. Check the task before using it.'
}
Write-Host "Created '$taskName' with Windows-managed password logon."
Write-Host 'It will start at the next boot. The currently running website was not stopped.'
Write-Host 'For an immediate test, stop the existing website first, then run:'
Write-Host "Start-ScheduledTask -TaskName '$taskName'"
Write-Host 'Logs: %LOCALAPPDATA%\ReceivingLog\logs\web.log (under the selected account).'
Write-Host 'If the account password changes, update the task credentials in Task Scheduler.'
