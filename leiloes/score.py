"""Score de oportunidade (0-100): desconto real menos penalidades de risco.

Heurística inicial e transparente; ajuste os pesos conforme sua experiência.
O "desconto real" usa a mediana de R$/m² dos outros imóveis do mesmo bairro
como referência quando há área, além do desconto sobre a avaliação da Caixa.
"""
import json
import statistics

PESOS = {
    "ocupado": 25,          # desocupação custa tempo e dinheiro
    "ocupado_desconhecido": 10,
    "sem_financiamento": 8,
    "debito_arrematante": 10,
    "acao_judicial": 12,
    "por_alerta": 3,
}


def referencia_m2(imoveis: list[dict]) -> dict:
    """Mediana de valor de avaliação por m² por (cidade, bairro)."""
    grupos: dict = {}
    for im in imoveis:
        if im.get("area_privativa") and im.get("valor_avaliacao"):
            chave = (im["cidade"], im["bairro"])
            grupos.setdefault(chave, []).append(im["valor_avaliacao"] / im["area_privativa"])
    return {k: statistics.median(v) for k, v in grupos.items() if len(v) >= 3}


def calcular(im: dict, edital: dict | None, ref_m2: dict) -> dict:
    desconto = im.get("desconto") or 0
    motivos = []
    base = min(desconto, 70) / 70 * 100  # 70% de desconto = teto

    m2 = ref_m2.get((im.get("cidade"), im.get("bairro")))
    if m2 and im.get("area_privativa") and im.get("preco"):
        preco_m2 = im["preco"] / im["area_privativa"]
        desc_bairro = (1 - preco_m2 / m2) * 100
        br = lambda v: f"{v:,.0f}".replace(",", ".")
        motivos.append(f"R$ {br(preco_m2)}/m² vs mediana do bairro R$ {br(m2)}/m²")
        base = (base + min(max(desc_bairro, 0), 70) / 70 * 100) / 2

    penal = 0
    if edital:
        if edital.get("ocupado") == "sim":
            penal += PESOS["ocupado"]; motivos.append("ocupado")
        elif edital.get("ocupado") == "desconhecido":
            penal += PESOS["ocupado_desconhecido"]
        if edital.get("aceita_financiamento") == 0:
            penal += PESOS["sem_financiamento"]; motivos.append("sem financiamento")
        for campo in ("debitos_iptu", "debitos_cond"):
            if "arrematante" in (edital.get(campo) or "").lower():
                penal += PESOS["debito_arrematante"]; motivos.append(f"{campo.split('_')[1].upper()} por conta do comprador")
        acoes = (edital.get("acoes_judiciais") or "").lower()
        if acoes and "não" not in acoes[:15] and "nao informado" not in acoes:
            penal += PESOS["acao_judicial"]; motivos.append("há ações judiciais")
        alertas = json.loads(edital.get("alertas") or "[]")
        penal += PESOS["por_alerta"] * len(alertas)
    else:
        motivos.append("edital não analisado")
        if (im.get("financiamento") or "").strip().lower().startswith("n"):
            penal += PESOS["sem_financiamento"]; motivos.append("sem financiamento")

    if "ocupado" in (im.get("descricao") or "").lower() and not edital:
        penal += PESOS["ocupado"]; motivos.append("descrição indica ocupado")

    return {"score": round(max(0, min(100, base - penal))), "motivos": motivos}
