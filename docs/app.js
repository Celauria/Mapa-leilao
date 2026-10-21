// Mapa de Leilões — lê imoveis.json (gerado pela coleta diária) e filtra no navegador.
// O DOM é montado só com textContent: dados de terceiros nunca viram HTML.
"use strict";

// ---------- Utilidades ----------
const brl = v => v == null || !isFinite(v) ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const fmt = n => n.toLocaleString("pt-BR");
const pct = v => v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const hoje = () => new Date().toISOString().slice(0, 10);
const dataBR = d => d ? `${d.slice(8, 10)}/${d.slice(5, 7)}${d.length > 10 ? " " + d.slice(11, 16) : ""}` : "";
const m2 = v => v ? `${v.toLocaleString("pt-BR", { maximumFractionDigits: 0 })} m²` : null;
const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
const css = nome => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
const telaGrande = matchMedia("(min-width: 1024px)");

// Desconto sobre a avaliação (Caixa) ou o informado pelo leiloeiro. Negativo = acima da avaliação.
const descReal = im => im.valor_avaliacao > 0 && im.preco != null ? (1 - im.preco / im.valor_avaliacao) * 100 : im.desconto;
const fmtDesc = d => d == null ? "" : d >= 0.5 ? `-${d.toFixed(0)}%` : d <= -0.5 ? `+${(-d).toFixed(0)}% acima` : "sem desconto";
// Menor valor pelo qual ainda pode sair (a 2ª praça futura costuma ser mais barata)
const precoMin = im => Math.min(...[im.preco, im.praca2_valor && (im.praca2_data || "") >= hoje() ? im.praca2_valor : null].filter(v => v));
const areaRef = im => im.area_total || im.area_privativa;
// Quanto o preço/m² fica abaixo da mediana das vendas reais (ITBI). Positivo = abaixo do mercado.
const descMercado = im => im.mercado_m2 && areaRef(im) ? (1 - (precoMin(im) / areaRef(im)) / im.mercado_m2) * 100 : null;
const proximoLeilao = im => [im.praca1_data, im.praca2_data].filter(d => d && d.slice(0, 10) >= hoje()).sort()[0] || null;
const diasDesde = iso => iso ? (Date.now() - Date.parse(iso.replace(" ", "T") + "Z")) / 864e5 : 999;
const classeScore = s => s >= 70 ? "s-alto" : s >= 45 ? "s-medio" : "s-baixo";
const corScore = s => css(s >= 70 ? "--oportunidade" : s >= 45 ? "--atencao" : "--risco");

function caracteristicas(im, completo = false) {
  const p = [];
  if (im.quartos) p.push(plural(im.quartos, "quarto", "quartos"));
  if (im.vagas != null && im.quartos) p.push(im.vagas ? plural(im.vagas, "vaga", "vagas") : "sem vaga");
  if (im.area_privativa) p.push(completo ? `${m2(im.area_privativa)} privativos` : m2(im.area_privativa));
  if (completo && im.area_total && im.area_total !== im.area_privativa) p.push(`${m2(im.area_total)} totais`);
  if (im.area_terreno && (completo || !im.area_privativa)) p.push(`terreno ${m2(im.area_terreno)}`);
  return p.join(", ");
}

// ---------- Custo total e parcela (premissas salvas só neste navegador) ----------
const PADRAO = { itbi: 3, cartorio: 1.5, comissao: 5, entrada: 20, juros: 11.5, prazo: 420 };
let PREM = { ...PADRAO };
try { PREM = { ...PADRAO, ...JSON.parse(localStorage.getItem("premissas") || "{}") }; } catch (e) {}
const ehLeilao = im => /leil/i.test(im.modalidade || "");

function custos(im) {
  const preco = precoMin(im) || im.preco || 0;
  const itens = [["Lance ou preço", preco], [`ITBI (~${pct(PREM.itbi)}%)`, preco * PREM.itbi / 100],
                 [`Cartório e registro (~${pct(PREM.cartorio)}%)`, preco * PREM.cartorio / 100]];
  if (ehLeilao(im)) itens.push([`Comissão do leiloeiro (${pct(PREM.comissao)}%)`, preco * PREM.comissao / 100]);
  const total = itens.reduce((a, [, v]) => a + v, 0);
  let fin = null;
  if ((im.financiamento || "").trim() === "Sim") {
    const entrada = preco * PREM.entrada / 100, financiado = preco - entrada, n = PREM.prazo,
          i = Math.pow(1 + PREM.juros / 100, 1 / 12) - 1;
    fin = { primeira: financiado / n + financiado * i, ultima: financiado / n * (1 + i), naMao: entrada + total - preco };
  }
  return { itens, total, fin };
}

function linhas(pares, extra) {
  const dl = el("dl", "linhas");
  pares.forEach(([r, v, cls]) => { const d = el("div", cls); d.append(el("dt", null, r), el("dd", null, v)); dl.append(d); });
  if (extra) dl.append(extra);
  return dl;
}

// ---------- A régua: preço/m² entre avaliação e vendas reais ----------
function regua(im) {
  const area = areaRef(im);
  if (!area) return null;
  const pontos = [{ nome: "este imóvel", v: precoMin(im) / area, este: true }];
  if (im.valor_avaliacao) pontos.push({ nome: "avaliação", v: im.valor_avaliacao / area });
  if (im.mercado_m2) pontos.push({ nome: im.mercado_nivel === "rua" ? "vendas na rua" : "vendas no bairro", v: im.mercado_m2 });
  if (pontos.length < 2) return null;
  const vs = pontos.map(p => p.v), min = Math.min(...vs) * 0.85, max = Math.max(...vs) * 1.08;
  const r = el("div", "regua");
  r.setAttribute("role", "img");
  r.setAttribute("aria-label", pontos.map(p => `${p.nome}: ${brl(p.v)} por m²`).join("; "));
  pontos.sort((a, b) => a.v - b.v).forEach((p, i) => {
    const pos = ((p.v - min) / (max - min)) * 100;
    // rótulo alinhado pela ponta quando o marco fica perto das bordas, para não sair da área
    const lado = pos < 18 ? "ini " : pos > 82 ? "fim " : "";
    const m = el("div", `marco ${p.este ? "este " : ""}${lado}${i % 2 ? "abaixo" : "acima"}`);
    m.style.left = `${pos}%`;
    m.append(el("span", null, `${p.nome} ${brl(p.v)}/m²`));
    r.append(m);
  });
  return r;
}

// ---------- Ficha do imóvel (painel no computador, balão no celular) ----------
function ficha(im) {
  const box = el("div", "detalhe-conteudo");
  box.append(el("h2", null, `${im.tipo || "Imóvel"} em ${im.bairro || im.cidade || ""}`));
  box.append(el("div", "endereco", `${im.endereco || ""}, ${im.cidade || ""}/${im.uf || ""}`));
  if (im.geo_precisao && !im.geo_precisao.startsWith("endereco"))
    box.append(el("div", "endereco", `Posição no mapa aproximada (centro do ${im.geo_precisao === "cidade" ? "município" : "bairro"})`));

  const pm = precoMin(im), dr = descReal(im);
  const valor = el("div", "valor", brl(pm));
  valor.append(el("small", null, pm < im.preco ? "no 2º leilão" : fmtDesc(dr)));
  box.append(valor);

  const dm = descMercado(im), r = regua(im);
  if (r) {
    const s = el("section");
    s.append(el("h3", null, dm != null ? `${Math.abs(dm).toFixed(0)}% ${dm >= 0 ? "abaixo" : "acima"} das vendas reais por m²` : "Preço por m²"), r);
    if (im.mercado_m2) s.append(el("div", "regua-legenda", `Mediana de ${im.mercado_n} compras e vendas ${im.mercado_nivel === "rua" ? "nesta rua" : "neste bairro"} nos últimos 12 meses (ITBI da Prefeitura de SP).`));
    box.append(s);
  }

  const sobre = el("section");
  sobre.append(el("h3", null, "Imóvel e venda"));
  const pares = [];
  const car = caracteristicas(im, true);
  if (car) pares.push(["Características", car]);
  if (im.praca1_valor) {
    [[im.praca2_valor ? "1º leilão" : "Lance inicial", im.praca1_valor, im.praca1_data], ["2º leilão", im.praca2_valor, im.praca2_data]]
      .filter(([, v]) => v).forEach(([rot, v, d]) => pares.push([`${rot}, ${dataBR(d)}`, brl(v), (d || "") < hoje() ? "passou" : null]));
  } else {
    pares.push(["Preço", brl(im.preco)], ["Avaliação", brl(im.valor_avaliacao)]);
  }
  pares.push(["Vendedor", im.banco || "Caixa"], ["Modalidade", (im.modalidade || "").replace(" - Edital Único", "")]);
  if (im.financiamento) pares.push(["Financiamento", im.financiamento === "Sim" ? "Aceita" : "Não aceita"]);
  if (im.estacao_nome) {
    const dist = im.estacao_m < 1000 ? `${Math.round(im.estacao_m / 50) * 50} m` : `${(im.estacao_m / 1000).toFixed(1).replace(".", ",")} km`;
    pares.push([`Estação de ${im.estacao_tipo}`, `${im.estacao_nome}, ~${dist}`]);
  }
  sobre.append(linhas(pares));
  if (/SFI/i.test(im.modalidade || "") && (dr ?? 0) < 0.5)
    sobre.append(el("p", "aviso", "O 1º leilão parte da avaliação. Sem lances, o 2º costuma partir do valor da dívida, às vezes bem menor. Confira datas e valores no edital."));
  box.append(sobre);

  const { itens, total, fin } = custos(im);
  const c = el("section");
  c.append(el("h3", null, "Custo estimado"));
  const pc = itens.map(([r, v]) => [r, brl(v)]);
  pc.push(["Custo total", brl(total), "total"]);
  if (fin) pc.push([`Entrada (${pct(PREM.entrada)}%) e custos`, brl(fin.naMao)],
                   [`1ª parcela, SAC, TR + ${pct(PREM.juros)}% a.a., ${PREM.prazo} meses`, brl(fin.primeira)]);
  c.append(linhas(pc));
  if (fin) c.append(el("p", "nota", `As parcelas caem até cerca de ${brl(fin.ultima)}. Sujeito à aprovação de crédito.`));
  box.append(c);

  if (im.edital && ((im.edital.alertas || []).length || im.edital.resumo)) {
    const rk = el("section");
    rk.append(el("h3", null, "Riscos encontrados no anúncio"));
    (im.edital.alertas || []).forEach(a => rk.append(el("div", "risco", a)));
    if (im.edital.resumo) rk.append(el("p", "nota", im.edital.resumo));
    box.append(rk);
  }

  const lk = el("section", "links");
  if (im.link && /^https:\/\//.test(im.link)) {
    const a = el("a", null, "Abrir anúncio e edital"); a.href = im.link; a.target = "_blank"; a.rel = "noopener noreferrer"; lk.append(a);
  }
  const end = `${(im.endereco || "").split(/,?\s*(apto|ap|apartamento|bloco|bl|casa|lote|qd)\b/i)[0]}, ${im.cidade || ""} - ${im.uf || ""}`;
  const g = el("a", null, "Ver a rua no Google Maps");
  g.href = "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(end); g.target = "_blank"; g.rel = "noopener noreferrer";
  lk.append(g);
  box.append(lk);
  return box;
}

// ---------- Mapa ----------
const mapa = L.map("mapa", { zoomControl: true }).setView([-23.6, -47.5], 7);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap", maxZoom: 19 }).addTo(mapa);
const camada = L.layerGroup().addTo(mapa);
let TODOS = [], DADOS = [], marcadores = {}, selecionado = null;

function marcador(im) {
  const exato = im.geo_precisao === "endereco";
  const m = L.circleMarker([im.lat, im.lon], { radius: 7, weight: 2, color: corScore(im.score), fillOpacity: exato ? .85 : .3, dashArray: exato ? null : "3 3" });
  if (telaGrande.matches) {
    m.bindTooltip(`${brl(precoMin(im))} · ${im.tipo || "Imóvel"}, ${im.bairro || ""}`, { direction: "top", offset: [0, -6] });
    m.on("click", () => mostrarDetalhe(im, { centralizar: false }));
  } else {
    m.bindPopup(() => ficha(im), { maxHeight: Math.max(240, mapa.getSize().y - 60), autoPanPadding: [10, 10] });
  }
  return m;
}

function destacar(id, liga) {
  const m = marcadores[id];
  if (m) m.setStyle({ radius: liga ? 11 : 7, weight: liga ? 3 : 2 });
}

// ---------- Lista e detalhe ----------
const lista = document.getElementById("lista"), detalhe = document.getElementById("detalhe");

function item(im) {
  const d = el("div", "item");
  d.tabIndex = 0; d.setAttribute("role", "button");
  const pm = precoMin(im), dr = descReal(im);
  const p = el("span", "preco", brl(pm));
  if (pm < im.preco) p.title = "Valor do 2º leilão";
  if (diasDesde(im.primeira_vez) <= 1) p.append(el("span", "etiqueta novo", "novo"));
  const sc = el("span", `score ${classeScore(im.score)}`, im.score); sc.title = "Score de oportunidade (0 a 100)";
  d.append(p, sc);
  const onde = el("div", "onde", `${im.tipo || "Imóvel"} em ${im.bairro || ""}, ${im.cidade || ""}/${im.uf}`);
  d.append(onde);
  const linhaDesc = el("div", "carac");
  const dm = descMercado(im);
  const partes = [fmtDesc(dr), dm != null ? `${Math.abs(dm).toFixed(0)}% ${dm >= 0 ? "abaixo" : "acima"} do mercado` : "", caracteristicas(im)].filter(Boolean);
  linhaDesc.textContent = partes.join(", ");
  d.append(linhaDesc);
  const meta = el("div", "meta", (im.modalidade || "").replace(" - Edital Único", ""));
  if (im.banco && im.banco !== "Caixa") meta.append(el("span", "etiqueta banco", im.banco));
  const prox = proximoLeilao(im);
  if (prox) meta.append(`, leilão em ${dataBR(prox).slice(0, 5)}`);
  d.append(meta);
  const abrir = () => {
    if (telaGrande.matches) return mostrarDetalhe(im, { centralizar: true });
    // Celular: balão no mapa; sem posição, a ficha abre na própria lista
    document.querySelectorAll(".item.ativo").forEach(x => x.classList.remove("ativo"));
    d.classList.add("ativo");
    const m = marcadores[im.id];
    if (m) { mapa.setView(m.getLatLng(), 15); m.openPopup(); return; }
    const aberta = d.querySelector(".detalhe-conteudo");
    if (aberta) { aberta.remove(); return; }
    d.append(ficha(im));
  };
  d.addEventListener("click", ev => { if (!ev.target.closest("a")) abrir(); });
  d.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); abrir(); } });
  d.addEventListener("mouseenter", () => destacar(im.id, true));
  d.addEventListener("mouseleave", () => destacar(im.id, false));
  return d;
}

function mostrarDetalhe(im, { centralizar }) {
  if (selecionado) destacar(selecionado, false);
  selecionado = im.id;
  destacar(im.id, true);
  const voltar = el("button", "link voltar", "← Voltar à lista");
  voltar.type = "button";
  voltar.addEventListener("click", fecharDetalhe);
  detalhe.replaceChildren(voltar, ficha(im));
  lista.hidden = true; detalhe.hidden = false;
  document.getElementById("lateral").scrollTop = 0;
  detalhe.focus({ preventScroll: true });
  const m = marcadores[im.id];
  if (m && centralizar) mapa.setView(m.getLatLng(), Math.max(mapa.getZoom(), 15));
}

function fecharDetalhe() {
  if (selecionado) destacar(selecionado, false);
  selecionado = null;
  detalhe.hidden = true; lista.hidden = false;
}

// ---------- Filtros (busca facetada: cada seletor conta aplicando os OUTROS filtros) ----------
const TESTES = {
  banco:         (im, v) => (im.banco || "Caixa") === v,
  filtro:        (im, v) => im.filtro === v,
  cidade:        (im, v) => `${im.cidade}|${im.uf}` === v,
  bairro:        (im, v) => (im.bairro || "") === v,
  tipo:          (im, v) => im.tipo === v,
  quartos:       (im, v) => (im.quartos || 0) >= +v,
  vagas:         (im, v) => +v === 0 ? im.vagas === 0 : (im.vagas || 0) >= +v,
  modalidade:    (im, v) => im.modalidade === v,
  desconto_min:  (im, v) => (descReal(im) ?? -Infinity) >= +v,
  preco_max:     (im, v) => +v <= 0 || precoMin(im) <= +v,
  financiamento: (im, v) => (im.financiamento || "").trim() === v,
  periodo:       (im, v) => diasDesde(im.primeira_vez) <= +v,
  busca:         (im, v) => norm(`${im.bairro} ${im.endereco} ${im.tipo} ${im.cidade}`).includes(norm(v)),
};
const valores = () => Object.fromEntries(Object.keys(TESTES)
  .map(id => [id, document.getElementById(id).value.trim()]).filter(([, v]) => v !== ""));
const filtrar = (vals, exceto = []) => TODOS.filter(im =>
  Object.entries(vals).every(([id, v]) => exceto.includes(id) || TESTES[id](im, v)));
const contar = (l, chave) => l.reduce((c, im) => { const k = chave(im); if (k) c[k] = (c[k] || 0) + 1; return c; }, {});

function opcoes(id, rotuloTodos, itens) {
  const sel = document.getElementById(id), atual = sel.value;
  const ls = [{ valor: "", rotulo: rotuloTodos }, ...itens.filter(i => i.n > 0 || i.valor === atual)];
  sel.replaceChildren(...ls.map(i => { const o = el("option", null, i.rotulo); o.value = i.valor; return o; }));
  sel.value = atual;
}

function atualizarOpcoes(vals) {
  const porBanco = contar(filtrar(vals, ["banco"]), im => im.banco || "Caixa");
  opcoes("banco", "Todos", Object.entries(porBanco).sort((a, b) => b[1] - a[1]).map(([b, n]) => ({ valor: b, rotulo: `${b} (${fmt(n)})`, n })));

  const porEstado = contar(filtrar(vals, ["filtro", "cidade", "bairro"]), im => im.filtro);
  const nEst = Object.values(porEstado).reduce((a, b) => a + b, 0);
  opcoes("filtro", `SP e SC (${fmt(nEst)})`, Object.keys(porEstado).sort()
    .map(f => ({ valor: f, rotulo: `${f.replace("Estado de ", "")} (${fmt(porEstado[f])})`, n: porEstado[f] })));

  const baseCid = filtrar(vals, ["cidade", "bairro"]);
  const porCidade = contar(baseCid, im => im.cidade && `${im.cidade}|${im.uf}`);
  opcoes("cidade", `Todas (${fmt(baseCid.length)})`, Object.keys(porCidade).sort().map(k => {
    const [c, uf] = k.split("|");
    return { valor: k, rotulo: `${c}${vals.filtro ? "" : "/" + uf} (${porCidade[k]})`, n: porCidade[k] };
  }));
  if (vals.cidade && !porCidade[vals.cidade] && vals.filtro && !vals.cidade.endsWith("|" + vals.filtro.slice(-2)))
    document.getElementById("cidade").value = "";

  const selBairro = document.getElementById("bairro"), cidadeAtual = document.getElementById("cidade").value;
  if (!cidadeAtual) {
    selBairro.replaceChildren(Object.assign(el("option", null, "Escolha a cidade"), { value: "" }));
    selBairro.disabled = true;
  } else {
    const baseBai = filtrar({ ...vals, cidade: cidadeAtual }, ["bairro"]);
    const porBairro = contar(baseBai, im => im.bairro);
    if (vals.bairro && !porBairro[vals.bairro]) selBairro.value = "";
    opcoes("bairro", `Todos (${fmt(baseBai.length)})`, Object.keys(porBairro).sort().map(b => ({ valor: b, rotulo: `${b} (${porBairro[b]})`, n: porBairro[b] })));
    selBairro.disabled = false;
  }

  const porTipo = contar(filtrar(vals, ["tipo"]), im => im.tipo);
  opcoes("tipo", "Todos", Object.entries(porTipo).sort((a, b) => b[1] - a[1]).map(([t, n]) => ({ valor: t, rotulo: `${t} (${fmt(n)})`, n })));

  const porMod = contar(filtrar(vals, ["modalidade"]), im => im.modalidade);
  opcoes("modalidade", "Todas", Object.entries(porMod).sort((a, b) => b[1] - a[1])
    .map(([m, n]) => ({ valor: m, rotulo: `${m.replace(" - Edital Único", "")} (${fmt(n)})`, n })));

  const porFin = contar(filtrar(vals, ["financiamento"]), im => (im.financiamento || "").trim());
  opcoes("financiamento", "Tanto faz", [
    { valor: "Sim", rotulo: `Aceita financiamento (${fmt(porFin["Sim"] || 0)})`, n: porFin["Sim"] || 0 },
    { valor: "Não", rotulo: `Só à vista (${fmt(porFin["Não"] || 0)})`, n: porFin["Não"] || 0 },
  ]);
}

const ORDENS = {
  score: im => -im.score,
  desconto: im => -(descReal(im) ?? -1e9),
  mercado: im => -(descMercado(im) ?? -1e9),
  preco: im => precoMin(im) || 1e12,
  leilao: im => { const d = proximoLeilao(im); return d ? Date.parse(d.replace(" ", "T")) : 9e15; },
  recentes: im => -Date.parse((im.primeira_vez || "1970-01-01").replace(" ", "T") + "Z"),
};

function render({ reenquadrar = true } = {}) {
  let vals = valores();
  atualizarOpcoes(vals);
  vals = valores();
  DADOS = filtrar(vals);
  const chave = ORDENS[document.getElementById("ordem").value] || ORDENS.score;
  DADOS.sort((a, b) => chave(a) - chave(b));

  camada.clearLayers(); marcadores = {};
  const pts = [];
  DADOS.forEach(im => {
    if (im.lat == null) return;
    const m = marcador(im); m.addTo(camada); marcadores[im.id] = m; pts.push([im.lat, im.lon]);
  });
  fecharDetalhe();
  lista.replaceChildren(...DADOS.slice(0, 400).map(item));
  if (!DADOS.length) lista.append(el("p", "vazio", "Nenhum imóvel com esses filtros. Remova algum filtro acima para ver mais opções."));
  else if (DADOS.length > 400) lista.append(el("p", "vazio", `Mostrando os 400 primeiros de ${fmt(DADOS.length)}. Use os filtros ou a tabela para ver o resto.`));

  document.getElementById("contagem").textContent = `${fmt(DADOS.length)} imóveis, ${fmt(pts.length)} no mapa`;
  atualizarChips(DADOS.length);
  if (!document.getElementById("vistaTabela").hidden) renderTabela();
  if (reenquadrar && pts.length) mapa.fitBounds(pts, { padding: [30, 30], maxZoom: 14 });
}

// ---------- Tabela (computador) ----------
const COLUNAS = [
  { id: "preco", titulo: "Preço", num: true, valor: im => precoMin(im), texto: im => brl(precoMin(im)) },
  { id: "desc", titulo: "Desconto", num: true, valor: im => descReal(im) ?? -1e9, texto: im => fmtDesc(descReal(im)), cls: im => (descReal(im) ?? 0) >= 0.5 ? "pos" : "neg" },
  { id: "m2", titulo: "R$/m²", num: true, valor: im => areaRef(im) ? precoMin(im) / areaRef(im) : null, texto: im => areaRef(im) ? brl(precoMin(im) / areaRef(im)) : "—" },
  { id: "merc", titulo: "Vs. vendas reais", num: true, valor: im => descMercado(im) ?? -1e9,
    texto: im => { const d = descMercado(im); return d == null ? "—" : `${Math.abs(d).toFixed(0)}% ${d >= 0 ? "abaixo" : "acima"}`; },
    cls: im => (descMercado(im) ?? -1) >= 0 ? "pos" : "neg" },
  { id: "tipo", titulo: "Tipo", valor: im => im.tipo || "", texto: im => im.tipo || "—" },
  { id: "qtos", titulo: "Quartos", num: true, valor: im => im.quartos || 0, texto: im => im.quartos || "—" },
  { id: "area", titulo: "Área", num: true, valor: im => areaRef(im) || 0, texto: im => m2(im.area_privativa || im.area_total || im.area_terreno) || "—" },
  { id: "local", titulo: "Bairro e cidade", valor: im => `${im.cidade} ${im.bairro}`, texto: im => `${im.bairro || ""}, ${im.cidade || ""}/${im.uf}` },
  { id: "banco", titulo: "Vendedor", valor: im => im.banco || "Caixa", texto: im => im.banco || "Caixa" },
  { id: "mod", titulo: "Modalidade", valor: im => im.modalidade || "", texto: im => (im.modalidade || "").replace(" - Edital Único", "") },
  { id: "fin", titulo: "Financia", valor: im => im.financiamento || "", texto: im => im.financiamento || "—" },
  { id: "leilao", titulo: "Próximo leilão", num: true, valor: im => proximoLeilao(im) || "9999", texto: im => dataBR(proximoLeilao(im)).slice(0, 5) || "—" },
  { id: "score", titulo: "Score", num: true, valor: im => im.score, texto: im => im.score },
];
let ordemTabela = { col: null, dir: -1 };

function renderTabela() {
  const tab = document.getElementById("tabela"), cab = tab.tHead.rows[0], corpo = tab.tBodies[0];
  cab.replaceChildren(...COLUNAS.map(c => {
    const th = el("th", c.num ? "num" : null, c.titulo);
    th.scope = "col"; th.tabIndex = 0;
    if (ordemTabela.col === c.id) th.setAttribute("aria-sort", ordemTabela.dir > 0 ? "ascending" : "descending");
    const ordenar = () => { ordemTabela = { col: c.id, dir: ordemTabela.col === c.id ? -ordemTabela.dir : (c.num ? -1 : 1) }; renderTabela(); };
    th.addEventListener("click", ordenar);
    th.addEventListener("keydown", e => { if (e.key === "Enter") ordenar(); });
    return th;
  }));
  let linhasT = DADOS.slice();
  const col = COLUNAS.find(c => c.id === ordemTabela.col);
  if (col) linhasT.sort((a, b) => { const x = col.valor(a), y = col.valor(b); return (x > y ? 1 : x < y ? -1 : 0) * ordemTabela.dir; });
  const LIM = 1500;
  corpo.replaceChildren(...linhasT.slice(0, LIM).map(im => {
    const tr = el("tr");
    COLUNAS.forEach(c => {
      const td = el("td", c.num ? "num" : null);
      const v = el("span", c.cls ? c.cls(im) : null, String(c.texto(im)));
      td.append(v); tr.append(td);
    });
    tr.addEventListener("click", () => { trocarVista("mapa"); mostrarDetalhe(im, { centralizar: true }); });
    return tr;
  }));
  document.getElementById("tabelaNota").textContent = linhasT.length > LIM
    ? `Mostrando ${fmt(LIM)} de ${fmt(linhasT.length)} imóveis. Use os filtros ou exporte o CSV para ver todos.`
    : "Clique numa linha para ver o imóvel no mapa. Clique no título de uma coluna para ordenar.";
}

function trocarVista(v) {
  const tabela = v === "tabela";
  document.getElementById("vistaMapa").hidden = tabela;
  document.getElementById("vistaTabela").hidden = !tabela;
  document.querySelectorAll(".vista button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.vista === v)));
  if (tabela) renderTabela(); else setTimeout(() => mapa.invalidateSize(), 0);
}
document.querySelectorAll(".vista button").forEach(b => b.addEventListener("click", () => trocarVista(b.dataset.vista)));

// ---------- Exportar CSV (Excel em português: ponto e vírgula, BOM) ----------
document.getElementById("exportar").addEventListener("click", () => {
  const cols = [["Preço", im => precoMin(im)], ["Avaliação", im => im.valor_avaliacao ?? ""], ["Desconto %", im => descReal(im)?.toFixed(1) ?? ""],
    ["Vs. vendas reais %", im => descMercado(im)?.toFixed(1) ?? ""], ["Tipo", im => im.tipo], ["Quartos", im => im.quartos ?? ""],
    ["Vagas", im => im.vagas ?? ""], ["Área m²", im => areaRef(im) ?? ""], ["Endereço", im => im.endereco], ["Bairro", im => im.bairro],
    ["Cidade", im => im.cidade], ["UF", im => im.uf], ["Vendedor", im => im.banco || "Caixa"], ["Modalidade", im => im.modalidade],
    ["Financiamento", im => im.financiamento ?? ""], ["1º leilão", im => im.praca1_data ?? ""], ["2º leilão", im => im.praca2_data ?? ""],
    ["Score", im => im.score], ["Link", im => im.link]];
  const esc = v => { const s = String(v ?? "").replace(/\.(?=\d+$)/, ","); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const csv = [cols.map(c => c[0]).join(";"), ...DADOS.map(im => cols.map(([, f]) => esc(f(im))).join(";"))].join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = el("a"); a.href = url; a.download = `leiloes_${hoje()}.csv`; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

// ---------- Painel de filtros, etiquetas e eventos ----------
const painel = document.getElementById("painel"), botaoFiltros = document.getElementById("abrirFiltros");
const abrirPainel = () => { painel.hidden = false; document.getElementById("verResultados").focus(); };
const fecharPainel = () => { painel.hidden = true; botaoFiltros.focus(); setTimeout(() => mapa.invalidateSize(), 50); };
botaoFiltros.addEventListener("click", abrirPainel);
document.getElementById("verResultados").addEventListener("click", fecharPainel);
document.getElementById("fundoPainel").addEventListener("click", fecharPainel);
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (!telaGrande.matches && !painel.hidden) fecharPainel();
  else if (!detalhe.hidden) fecharDetalhe();
});
document.getElementById("limpar").addEventListener("click", () => { Object.keys(TESTES).forEach(id => { document.getElementById(id).value = ""; }); render(); });

const semContagem = t => t.replace(/\s*\([\d.]+\)\s*$/, "");
function rotuloFiltro(id, v) {
  const e = document.getElementById(id);
  if (id === "preco_max") return `Até ${brl(+v)}`;
  if (id === "busca") return `“${v}”`;
  const txt = semContagem(e.options[e.selectedIndex]?.textContent || v);
  const prefixo = { quartos: "Quartos: ", vagas: "Vagas: ", desconto_min: "Desconto: ", periodo: "" }[id] ?? "";
  return prefixo + txt;
}
function atualizarChips(total) {
  const vals = valores(), chips = document.getElementById("chips");
  chips.replaceChildren(...Object.entries(vals).map(([id, v]) => {
    const c = el("button", "chip", rotuloFiltro(id, v));
    c.type = "button"; c.setAttribute("aria-label", `Remover filtro ${rotuloFiltro(id, v)}`);
    c.append(el("span", null, "×"));
    c.addEventListener("click", () => {
      document.getElementById(id).value = "";
      if (id === "cidade" || id === "filtro") document.getElementById("bairro").value = "";
      render();
    });
    return c;
  }));
  const n = Object.keys(vals).length, badge = document.getElementById("nFiltros");
  badge.hidden = n === 0; badge.textContent = n;
  document.getElementById("verResultados").textContent = `Ver ${fmt(total)} imóve${total === 1 ? "l" : "is"}`;
  setTimeout(() => mapa.invalidateSize(), 0);
}

["filtro", "cidade"].forEach(id => document.getElementById(id).addEventListener("change", () => { document.getElementById("bairro").value = ""; }));
let t;
document.querySelectorAll("#painel select, #painel input:not([id^=p_]), #busca").forEach(e =>
  e.addEventListener(e.tagName === "SELECT" ? "change" : "input", () => { clearTimeout(t); t = setTimeout(render, e.tagName === "SELECT" ? 0 : 300); }));
document.getElementById("ordem").addEventListener("change", () => render({ reenquadrar: false }));

Object.keys(PADRAO).forEach(k => {
  const inp = document.getElementById("p_" + k);
  inp.value = PREM[k];
  inp.addEventListener("change", () => {
    const v = parseFloat(inp.value);
    PREM[k] = isFinite(v) && v >= 0 ? v : PADRAO[k]; inp.value = PREM[k];
    try { localStorage.setItem("premissas", JSON.stringify(PREM)); } catch (e) {}
    mapa.closePopup();
    const atual = TODOS.find(im => im.id === selecionado);
    if (atual) mostrarDetalhe(atual, { centralizar: false });
  });
});

// A busca fica no topo no computador e dentro do painel no celular.
function posicionarBusca() {
  const busca = document.getElementById("busca");
  if (telaGrande.matches) document.getElementById("lugarBusca").append(busca);
  else document.querySelector("#painel fieldset legend").after(busca);
}
telaGrande.addEventListener("change", () => { posicionarBusca(); if (!telaGrande.matches) trocarVista("mapa"); render({ reenquadrar: false }); });
posicionarBusca();

// ---------- Carregar dados ----------
fetch("imoveis.json", { cache: "no-cache" }).then(r => r.json()).then(j => {
  TODOS = j.imoveis || [];
  const quando = new Date(j.atualizado);
  document.getElementById("atualizado").textContent = `Atualizado em ${quando.toLocaleDateString("pt-BR")} às ${quando.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
  render();
}).catch(() => { document.getElementById("contagem").textContent = "Sem dados ainda. A primeira coleta ainda não terminou."; });
