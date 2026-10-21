# Instala o coletor do Mapa de Leilões neste Windows.
# Uso (PowerShell, sem precisar de administrador):
#   irm https://raw.githubusercontent.com/Celauria/Mapa-leilao/main/instalar_windows.ps1 | iex
# ou, se já baixou o repositório:  .\instalar_windows.ps1
#
# O que faz:
#   1. Confere Python e Git (instala pelo winget se faltar, com sua confirmação).
#   2. Baixa o repositório em %USERPROFILE%\Mapa-leilao (ou atualiza, se já existir).
#   3. Instala o Playwright (usa o Edge do Windows; não baixa navegador).
#   4. Roda a primeira coleta (o Git pode pedir login no GitHub uma vez).
#   5. Agenda a coleta: ao entrar no Windows, ao desbloquear e às 8h; no máximo 1x por dia.

$ErrorActionPreference = "Stop"
$Repo   = "https://github.com/Celauria/Mapa-leilao.git"
$Pasta  = Join-Path $env:USERPROFILE "Mapa-leilao"
$Tarefa = "Mapa de Leiloes - coleta"

function Garantir($comando, $idWinget, $nome) {
  if (Get-Command $comando -ErrorAction SilentlyContinue) { return }
  Write-Host "$nome não encontrado."
  $r = Read-Host "Instalar $nome agora pelo winget? (S/N)"
  if ($r -notmatch '^[sS]') { throw "Instale $nome e rode este script de novo." }
  winget install --id $idWinget -e --accept-source-agreements --accept-package-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  if (-not (Get-Command $comando -ErrorAction SilentlyContinue)) { throw "$nome instalado; feche e abra o PowerShell e rode o script de novo." }
}

Write-Host "`n== 1/5 Conferindo Python e Git" -ForegroundColor Cyan
Garantir "py"  "Python.Python.3.12" "Python"
Garantir "git" "Git.Git"            "Git"

Write-Host "`n== 2/5 Repositório em $Pasta" -ForegroundColor Cyan
if (Test-Path (Join-Path $Pasta ".git")) { git -C $Pasta pull --rebase --autostash -q }
else { git clone -q $Repo $Pasta }

Write-Host "`n== 3/5 Dependências" -ForegroundColor Cyan
py -3 -m pip install --user -q --upgrade pip
$versao = py -3 -c "import sys; print(sys.version_info >= (3, 10))"
if ($versao -ne "True") { throw "É preciso Python 3.10 ou mais novo (winget install Python.Python.3.12)." }
py -3 -m pip install --user -q playwright   # usa o Edge do Windows; não baixa navegador

Write-Host "`n== 4/5 Primeira coleta (pode abrir o navegador para login no GitHub)" -ForegroundColor Cyan
Push-Location $Pasta
py -3 -m leiloes.coletor_local --forcar
$ok = $LASTEXITCODE
Pop-Location
if ($ok -ne 0) { Write-Warning "A primeira coleta não terminou bem. Veja o log em $env:LOCALAPPDATA\MapaLeiloes\coleta.log" }

Write-Host "`n== 5/5 Agendando a coleta" -ForegroundColor Cyan
$pyw = (Get-Command pyw -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = (Get-Command py).Source }   # sem pyw, roda com janela minimizada
$acao = New-ScheduledTaskAction -Execute $pyw -Argument "-3 -m leiloes.coletor_local" -WorkingDirectory $Pasta
$aoEntrar = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$as8 = New-ScheduledTaskTrigger -Daily -At 8:00am
$classe = Get-CimClass -Namespace Root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskSessionStateChangeTrigger
$aoDesbloquear = New-CimInstance -CimClass $classe -ClientOnly -Property @{ StateChange = 8; UserId = "$env:USERDOMAIN\$env:USERNAME"; Delay = "PT2M" }
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries `
          -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Tarefa -Action $acao -Trigger @($aoEntrar, $as8, $aoDesbloquear) -Settings $config `
  -Description "Baixa as listas da Caixa e envia ao GitHub (no máximo 1x por dia)." -Force | Out-Null

Write-Host "`nPronto. A coleta roda ao entrar no Windows, ao desbloquear e às 8h (1x por dia)." -ForegroundColor Green
Write-Host "Log: $env:LOCALAPPDATA\MapaLeiloes\coleta.log"
Write-Host "Para rodar na hora:  cd $Pasta; py -3 -m leiloes.coletor_local --forcar"
Write-Host "Para desinstalar:    Unregister-ScheduledTask -TaskName '$Tarefa' -Confirm:`$false"
