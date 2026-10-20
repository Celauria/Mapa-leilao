# Agenda o alerta de leilões todo dia às 7h40 (Windows).
# Rode uma vez no PowerShell, dentro da pasta do projeto:  .\agendar_windows.ps1
$pasta  = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $pasta ".venv\Scripts\python.exe"
$acao   = New-ScheduledTaskAction -Execute $python -Argument "-m leiloes.cli alerta" -WorkingDirectory $pasta
$quando = New-ScheduledTaskTrigger -Daily -At 7:40am
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "Alerta Leiloes" -Action $acao -Trigger $quando -Settings $config -Force
Write-Host "Agendado: todo dia 7h40. Variáveis de Telegram/e-mail precisam estar definidas como variáveis de usuário (setx)."
