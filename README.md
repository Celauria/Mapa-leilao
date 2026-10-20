# Mapa de Leilões (protótipo pessoal)

Coleta imóveis à venda/leilão da Caixa, geocodifica, lê editais com Claude e mostra tudo num mapa com filtros e score de oportunidade.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...                  # só para a análise de editais
```

## Uso

```bash
python -m leiloes.cli coletar SP                 # baixa a lista da Caixa de SP (pode passar várias UFs)
python -m leiloes.cli geocodificar --limite 300  # ~1 imóvel/s (limite do OpenStreetMap); rode em lotes
python -m leiloes.cli web                        # abre em http://127.0.0.1:5000
```

Analisar o edital de um imóvel (baixe o PDF pelo link do anúncio):

```bash
python -m leiloes.cli edital caixa:1444400012345 ~/Downloads/edital.pdf
```

Ver o que entrou nas últimas 24h dentro do seu filtro:

```bash
python -m leiloes.cli novos --cidade "SAO PAULO" --desconto-min 40 --preco-max 500000
```

## Rodar na nuvem (GitHub) e usar no iPhone

O workflow `.github/workflows/leiloes.yml` roda todo dia às 7h40 (horário de Brasília). Ele coleta, envia o alerta, geocodifica e atualiza o mapa em `docs/`. Nenhum computador precisa ficar ligado.

1. **Secrets** (Settings → Secrets and variables → Actions → New repository secret): `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`.
2. **Mapa** (Settings → Pages): Source = *Deploy from a branch*, Branch = `main`, pasta `/docs`.
3. **Primeira execução:** aba Actions → *Leilões — coleta diária* → *Run workflow*.
4. **No iPhone:** abra o endereço do Pages no Safari → Compartilhar → *Adicionar à Tela de Início*.

O GitHub Pages é público em contas gratuitas. A página tem `noindex` e só mostra dados que a Caixa já publica, mas qualquer pessoa com o link consegue ver. Os tokens ficam nos Secrets e nunca vão para o repositório.

Se a Caixa bloquear os servidores do GitHub, o passo de coleta falha e você recebe um aviso no Telegram.

## Alerta diário

Os filtros ficam em `filtros.json` (hoje: estados de SP e SC inteiros, até R$ 350 mil). O alerta avisa imóveis **novos** e **quedas de preço** que batem com algum filtro.

```bash
python -m leiloes.cli alerta --teste   # roda sem enviar nada
python -m leiloes.cli alerta           # envia por Telegram e/ou e-mail
```

1. Copie `.env.exemplo` para `.env` e preencha o Telegram (recomendado, chega no celular) ou o e-mail.
2. Agende uma vez:
   - Windows: `.\agendar_windows.ps1`
   - Mac/Linux: `bash agendar_cron.sh`

A primeira execução só registra a linha de base e informa quantos imóveis já batem com os filtros. Use o mapa para olhar esse estoque. Dali em diante, chega só o que mudou. Cada execução gera também um relatório em `relatorios/alerta_AAAA-MM-DD.html`.

## Testar sem internet

```bash
python -m leiloes.cli coletar SP --arquivo exemplos/lista_exemplo.csv
```
O arquivo de exemplo tem imóveis **fictícios**, só para validar o fluxo.

## Estrutura

| Arquivo | O que faz |
|---|---|
| `leiloes/coleta_caixa.py` | Baixa e interpreta o CSV da Caixa; detecta novos, preço alterado e removidos |
| `leiloes/geocode.py` | Endereço → lat/lon (Nominatim) com cache e fallback para bairro/cidade |
| `leiloes/edital.py` | PDF → texto → Claude extrai ocupação, débitos, praças, ações, alertas |
| `leiloes/score.py` | Score 0–100: desconto (sobre avaliação e R$/m² do bairro) menos riscos |
| `leiloes/app.py` + `static/` | Interface web com mapa (Leaflet) e lista ordenada por score |
| `data/leiloes.db` | SQLite criado na primeira execução |

## Observações

- A Caixa às vezes muda colunas do CSV; o parser localiza colunas pelo nome, mas confira se algo vier vazio.
- O score é uma heurística inicial — ajuste `PESOS` em `score.py`.
- Antes de dar lance, confira sempre a matrícula atualizada no cartório e o edital completo.
