// Mapa estático: lê imoveis.json (gerado diariamente pelo GitHub Actions) e filtra no aparelho.
// O DOM é montado só com textContent: dados de terceiros nunca viram HTML.
const brl = v => v == null ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const cor = s => s >= 70 ? "#0f6b5c" : s >= 45 ? "#c98a1b" : "#b5462a";
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

const mapa = L.map("mapa", { tap: true }).setView([-24.5, -48.5], 6);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap" }).addTo(mapa);
const camada = L.layerGroup().addTo(mapa);
let TODOS = [], marcadores = {};

// Desconto real sobre a avaliação. A Caixa publica 0% quando o preço fica acima dela;
// aqui o valor negativo aparece, para não esconder isso.
const descReal = im => im.valor_avaliacao > 0 && im.preco != null ? (1 - im.preco / im.valor_avaliacao) * 100 : im.desconto;
const fmtDesc = d => d == null ? "" : d >= 0.5 ? `-${d.toFixed(0)}%` : d <= -0.5 ? `+${(-d).toFixed(0)}% acima` : "sem desconto";
const hoje = () => new Date().toISOString().slice(0, 10);
// menor valor pelo qual ainda pode sair (2ª praça futura costuma ser mais barata)
const precoMin = im => Math.min(...[im.preco, im.praca2_valor && (im.praca2_data || "") >= hoje() ? im.praca2_valor : null].filter(v => v));
const dataBR = d => d ? `${d.slice(8, 10)}/${d.slice(5, 7)} ${d.slice(11, 16)}` : "";

const m2 = v => v ? `${v.toLocaleString("pt-BR", { maximumFractionDigits: 0 })} m²` : null;
const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
// "2 quartos · 1 vaga · 42 m²" — só o que a Caixa informou
function caracteristicas(im, completo = false) {
  const p = [];
  if (im.quartos) p.push(plural(im.quartos, "quarto", "quartos"));
  if (im.vagas != null && im.quartos) p.push(im.vagas ? plural(im.vagas, "vaga", "vagas") : "sem vaga");
  if (im.area_privativa) p.push(completo ? `${m2(im.area_privativa)} privativos` : m2(im.area_privativa));
  if (completo && im.area_total && im.area_total !== im.area_privativa) p.push(`${m2(im.area_total)} totais`);
  if (im.area_terreno && (completo || !im.area_privativa)) p.push(`terreno ${m2(im.area_terreno)}`);
  return p.join(" · ");
}

// ---- Custo total e parcela (premissas editáveis, salvas só neste aparelho) ----
const PADRAO = { itbi: 3, cartorio: 1.5, comissao: 5, entrada: 20, juros: 11.5, prazo: 420 };
let PREM = { ...PADRAO };
try { PREM = { ...PADRAO, ...JSON.parse(localStorage.getItem("premissas") || "{}") }; } catch (e) {}
const pct = v => v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
const ehLeilao = im => /leil/i.test(im.modalidade || "");

function custos(im) {
  const preco = precoMin(im) || im.preco || 0;
  const itens = [["Lance / preço", preco], [`ITBI (~${pct(PREM.itbi)}%)`, preco * PREM.itbi / 100],
                 [`Cartório e registro (~${pct(PREM.cartorio)}%)`, preco * PREM.cartorio / 100]];
  if (ehLeilao(im)) itens.push([`Comissão do leiloeiro (${pct(PREM.comissao)}%)`, preco * PREM.comissao / 100]);
  const total = itens.reduce((a, [, v]) => a + v, 0);
  let fin = null;
  if ((im.financiamento || "").trim() === "Sim") {
    const entrada = preco * PREM.entrada / 100, financiado = preco - entrada, n = PREM.prazo, i = Math.pow(1 + PREM.juros / 100, 1 / 12) - 1;
    fin = { entrada, primeira: financiado / n + financiado * i, ultima: financiado / n * (1 + i),
            precisaNaMao: entrada + total - preco };
  }
  return { itens, total, fin };
}

function blocoCusto(im) {
  const { itens, total, fin } = custos(im);
  const b = el("div", "custo");
  itens.forEach(([r, v]) => { const l = el("div"); l.append(el("span", null, r), el("span", null, brl(v))); b.append(l); });
  const t = el("div", "total"); t.append(el("span", null, "Custo total estimado"), el("strong", null, brl(total))); b.append(t);
  if (fin) {
    const f = el("div"); f.append(el("span", null, `Entrada (${pct(PREM.entrada)}%) + custos`), el("span", null, brl(fin.precisaNaMao))); b.append(f);
    const p = el("div"); p.append(el("span", null, `1ª parcela (SAC, TR + ${pct(PREM.juros)}% a.a., ${PREM.prazo} meses)`), el("strong", null, brl(fin.primeira))); b.append(p);
    b.append(el("div", "meta", `As parcelas caem até ~${brl(fin.ultima)} no fim. Sujeito à aprovação de crédito.`));
  }
  return b;
}

function ficha(im) {
  const box = el("div");
  box.append(el("strong", null, `${im.tipo || "Imóvel"} — ${im.bairro || ""}`));
  box.append(el("div", "meta", `${im.endereco || ""}, ${im.cidade || ""}/${im.uf || ""}`));
  if (im.geo_precisao && !im.geo_precisao.startsWith("endereco"))
    box.append(el("div", "meta", `Posição aproximada (centro do ${im.geo_precisao === "cidade" ? "município" : "bairro"})`));
  const dr = descReal(im);
  if (im.praca1_valor) {
    const pr = el("div", "pracas");
    [[im.praca2_valor ? "1º leilão" : "Lance inicial", im.praca1_valor, im.praca1_data], ["2º leilão", im.praca2_valor, im.praca2_data]]
      .filter(([, v]) => v).forEach(([rot, v, d]) => {
        const l = el("div", (d || "") < hoje() ? "passou" : null);
        l.append(el("span", null, `${rot} · ${dataBR(d)}`), el("strong", null, brl(v)));
        pr.append(l);
      });
    box.append(pr);
    if (dr != null) box.append(el("div", "meta", im.praca2_valor
      ? (dr >= 0.5 ? `2º leilão ${dr.toFixed(0)}% abaixo do 1º` : `2º leilão ${fmtDesc(dr).replace("acima", "acima do 1º")}`)
      : (dr >= 0.5 ? `${dr.toFixed(0)}% de desconto (informado pelo leiloeiro)` : fmtDesc(dr))));
  } else {
    box.append(el("div", null, `${brl(im.preco)} · avaliação ${brl(im.valor_avaliacao)} · ${dr >= 0.5 ? dr.toFixed(0) + "% de desconto" : fmtDesc(dr)}`));
  }
  const car = caracteristicas(im, true);
  if (car) box.append(el("div", "carac", car));
  if (im.mercado_m2) {
    const area = im.area_total || im.area_privativa;
    const onde = im.mercado_nivel === "rua" ? "nesta rua" : "neste bairro";
    const linha = el("div", "dica", `Vendas reais ${onde} (ITBI, 12 meses): mediana ${brl(im.mercado_m2)}/m² em ${im.mercado_n} vendas`);
    if (area) {
      const d = (1 - (precoMin(im) / area) / im.mercado_m2) * 100;
      linha.append(el("strong", null, ` · este sai ${Math.abs(d).toFixed(0)}% ${d >= 0 ? "abaixo" : "acima"}`));
    }
    box.append(linha);
  }
  const areaRef = im.area_privativa || im.area_terreno;
  if (areaRef) box.append(el("div", "meta", `${brl(im.preco / areaRef)}/m² ${im.area_privativa ? "privativo" : "de terreno"}`));
  box.append(el("div", "meta", `${im.banco ? im.banco + " · " : ""}${im.modalidade || ""}${im.financiamento ? " · financiamento: " + im.financiamento : ""}`));
  box.append(blocoCusto(im));
  if (/SFI/i.test(im.modalidade || "") && (dr ?? 0) < 0.5)
    box.append(el("div", "dica", "1º leilão parte da avaliação. Se não houver lance, o 2º leilão costuma partir do valor da dívida, às vezes bem menor — confira datas e valores no edital."));
  if (im.edital) {
    box.append(el("div", null, im.edital.resumo || ""));
    (im.edital.alertas || []).forEach(a => box.append(el("div", "alerta", "⚠ " + a)));
  }
  if (im.link && /^https:\/\//.test(im.link)) {
    const a = el("a", null, "Abrir anúncio e edital"); a.href = im.link; a.target = "_blank"; a.rel = "noopener noreferrer";
    box.append(a);
  }
  return box;
}

function diasDesde(iso) { return iso ? (Date.now() - Date.parse(iso.replace(" ", "T") + "Z")) / 864e5 : 999; }

function item(im) {
  const d = el("div", "item");
  const l1 = el("div", "linha");
  const pm = precoMin(im);
  const p = el("span", "preco", pm < im.preco ? `${brl(pm)}*` : brl(im.preco));
  if (pm < im.preco) p.title = "valor do 2º leilão";
  if (diasDesde(im.primeira_vez) <= 1) p.append(el("span", "novo", "NOVO"));
  const dr = descReal(im);
  l1.append(p, el("span", (dr ?? 0) >= 0.5 ? "desc" : "desc nulo", fmtDesc(dr)));
  const sc = el("span", "score", im.score); sc.style.background = cor(im.score); l1.append(sc);
  d.append(l1, el("div", null, `${im.tipo || "Imóvel"} · ${im.bairro || ""}, ${im.cidade || ""}/${im.uf}`));
  const car = caracteristicas(im);
  if (car) d.append(el("div", "carac", car));
  const meta = el("div", "meta", im.modalidade || "");
  if (im.banco && im.banco !== "Caixa") meta.append(el("span", "banco", im.banco));
  if (im.praca2_valor && (im.praca2_data || "") >= hoje()) meta.append(` · 2º leilão ${dataBR(im.praca2_data).slice(0, 5)}`);
  d.append(meta);
  if (im.motivos?.length) d.append(el("div", "motivos", im.motivos.join(" · ")));
  d.onclick = ev => {
    if (ev.target.closest("a")) return;  // link do anúncio dentro da ficha
    document.querySelectorAll(".item.ativo").forEach(x => x.classList.remove("ativo"));
    d.classList.add("ativo");
    const m = marcadores[im.id];
    if (m) { mapa.setView(m.getLatLng(), 15); m.openPopup(); return; }
    // Sem posição no mapa: abre/fecha a ficha dentro da própria lista.
    const aberta = d.querySelector(".ficha");
    if (aberta) { aberta.remove(); return; }
    const f = ficha(im); f.className = "ficha";
    f.prepend(el("div", "dica", "Ainda sem posição no mapa — a localização é calculada aos poucos a cada coleta."));
    d.append(f);
  };
  return d;
}

// Cada filtro é um teste. As opções de cada seletor são contadas aplicando todos os
// OUTROS filtros (busca facetada): o que não existe com a seleção atual some da lista.
const TESTES = {
  banco:         (im, v) => (im.banco || "Caixa") === v,
  filtro:        (im, v) => im.filtro === v,
  cidade:        (im, v) => `${im.cidade}|${im.uf}` === v,
  bairro:        (im, v) => (im.bairro || "") === v,
  modalidade:    (im, v) => im.modalidade === v,
  tipo:          (im, v) => im.tipo === v,
  quartos:       (im, v) => (im.quartos || 0) >= +v,
  vagas:         (im, v) => +v === 0 ? im.vagas === 0 : (im.vagas || 0) >= +v,
  financiamento: (im, v) => (im.financiamento || "").trim() === v,
  desconto_min:  (im, v) => (descReal(im) ?? -Infinity) >= +v,
  preco_max:     (im, v) => +v <= 0 || precoMin(im) <= +v,
  periodo:       (im, v) => diasDesde(im.primeira_vez) <= +v,
  busca:         (im, v) => norm(`${im.bairro} ${im.endereco} ${im.tipo} ${im.cidade}`).includes(norm(v)),
};
const valores = () => Object.fromEntries(Object.keys(TESTES)
  .map(id => [id, document.getElementById(id).value]).filter(([, v]) => v !== ""));
const filtrar = (vals, exceto = []) => TODOS.filter(im =>
  Object.entries(vals).every(([id, v]) => exceto.includes(id) || TESTES[id](im, v)));
const contar = (lista, chave) => lista.reduce((c, im) => { const k = chave(im); if (k) c[k] = (c[k] || 0) + 1; return c; }, {});
const fmt = n => n.toLocaleString("pt-BR");

// Recria as opções de um seletor mantendo a escolha atual (mesmo com 0 resultados).
function opcoes(id, rotuloTodos, itens) {
  const sel = document.getElementById(id), atual = sel.value;
  const lista = [{ valor: "", rotulo: rotuloTodos }, ...itens.filter(i => i.n > 0 || i.valor === atual)];
  sel.replaceChildren(...lista.map(i => { const o = el("option", null, i.rotulo); o.value = i.valor; return o; }));
  sel.value = atual;
}

function atualizarOpcoes(vals) {
  // Estado: ignora também a cidade, para dar para trocar de estado com uma cidade escolhida.
  const porBanco = contar(filtrar(vals, ["banco"]), im => im.banco || "Caixa");
  opcoes("banco", "Banco: todos", Object.entries(porBanco).sort((a, b) => b[1] - a[1])
    .map(([b, n]) => ({ valor: b, rotulo: `${b} (${fmt(n)})`, n })));

  const porEstado = contar(filtrar(vals, ["filtro", "cidade", "bairro"]), im => im.filtro);
  const nEst = Object.values(porEstado).reduce((a, b) => a + b, 0);
  opcoes("filtro", `SP e SC (${fmt(nEst)})`, Object.keys(porEstado).sort()
    .map(f => ({ valor: f, rotulo: `${f.replace("Estado de ", "")} (${fmt(porEstado[f])})`, n: porEstado[f] })));

  const baseCid = filtrar(vals, ["cidade", "bairro"]);
  const porCidade = contar(baseCid, im => im.cidade && `${im.cidade}|${im.uf}`);
  opcoes("cidade", `Cidade: todas (${fmt(baseCid.length)})`, Object.keys(porCidade).sort().map(k => {
    const [c, uf] = k.split("|");
    return { valor: k, rotulo: `${c}${vals.filtro ? "" : "/" + uf} (${porCidade[k]})`, n: porCidade[k] };
  }));
  if (vals.cidade && !porCidade[vals.cidade] && vals.filtro && !vals.cidade.endsWith("|" + vals.filtro.slice(-2))) {
    document.getElementById("cidade").value = "";  // cidade de outro estado: limpa
  }

  // Bairro: só faz sentido com uma cidade escolhida; lista os bairros dela.
  const selBairro = document.getElementById("bairro");
  const cidadeAtual = document.getElementById("cidade").value;
  if (!cidadeAtual) {
    selBairro.replaceChildren(Object.assign(el("option", null, "Bairro: escolha a cidade"), { value: "" }));
    selBairro.disabled = true;
  } else {
    const baseBai = filtrar({ ...vals, cidade: cidadeAtual }, ["bairro"]);
    const porBairro = contar(baseBai, im => im.bairro);
    if (vals.bairro && !porBairro[vals.bairro]) selBairro.value = "";  // bairro de outra cidade
    opcoes("bairro", `Bairro: todos (${fmt(baseBai.length)})`, Object.keys(porBairro).sort()
      .map(b => ({ valor: b, rotulo: `${b} (${porBairro[b]})`, n: porBairro[b] })));
    selBairro.disabled = false;
  }

  const porTipo = contar(filtrar(vals, ["tipo"]), im => im.tipo);
  opcoes("tipo", "Tipo: todos", Object.entries(porTipo).sort((a, b) => b[1] - a[1])
    .map(([t, n]) => ({ valor: t, rotulo: `${t} (${fmt(n)})`, n })));

  const porMod = contar(filtrar(vals, ["modalidade"]), im => im.modalidade);
  opcoes("modalidade", "Modalidade: todas", Object.entries(porMod).sort((a, b) => b[1] - a[1])
    .map(([m, n]) => ({ valor: m, rotulo: `${m.replace(" - Edital Único", "")} (${fmt(n)})`, n })));

  const porFin = contar(filtrar(vals, ["financiamento"]), im => (im.financiamento || "").trim());
  opcoes("financiamento", "Financiamento: todos", [
    { valor: "Sim", rotulo: `Aceita financiamento (${fmt(porFin["Sim"] || 0)})`, n: porFin["Sim"] || 0 },
    { valor: "Não", rotulo: `Só à vista (${fmt(porFin["Não"] || 0)})`, n: porFin["Não"] || 0 },
  ]);
}

function render() {
  let vals = valores();
  atualizarOpcoes(vals);
  vals = valores();  // a cidade pode ter sido limpa acima
  const dados = filtrar(vals);
  const ordem = document.getElementById("ordem").value;
  const chave = { score: im => -im.score, desconto: im => -(descReal(im) ?? -1e9), preco: im => precoMin(im) || 1e12,
                  recentes: im => -Date.parse((im.primeira_vez || "1970-01-01").replace(" ", "T") + "Z") }[ordem] || (im => -im.score);
  dados.sort((a, b) => chave(a) - chave(b));
  camada.clearLayers(); marcadores = {};
  const lista = document.getElementById("lista"); lista.replaceChildren();
  const pts = [];
  dados.slice(0, 600).forEach(im => lista.append(item(im)));
  dados.forEach(im => {
    if (im.lat == null) return;
    const m = L.circleMarker([im.lat, im.lon], { radius: 7, color: cor(im.score), fillOpacity: im.geo_precisao === "endereco" ? .85 : .35, dashArray: im.geo_precisao === "endereco" ? null : "3 3" }).bindPopup(() => ficha(im), { maxHeight: Math.max(220, mapa.getSize().y - 70), autoPanPadding: [10, 10] });
    m.addTo(camada); marcadores[im.id] = m; pts.push([im.lat, im.lon]);
  });
  document.getElementById("contagem").textContent = `${fmt(dados.length)} imóveis · ${fmt(pts.length)} no mapa`;
  if (pts.length) mapa.fitBounds(pts, { padding: [24, 24], maxZoom: 14 });
}

fetch("imoveis.json", { cache: "no-cache" }).then(r => r.json()).then(j => {
  TODOS = j.imoveis || [];
  document.title = `Leilões · ${new Date(j.atualizado).toLocaleDateString("pt-BR")}`;
  render();
}).catch(() => { document.getElementById("contagem").textContent = "sem dados ainda — aguarde a 1ª execução"; });

["filtro", "cidade"].forEach(id => document.getElementById(id).addEventListener("change", () => {
  document.getElementById("bairro").value = "";
}));

let t;
document.querySelectorAll(".filtros select, .filtros input").forEach(e =>
  e.addEventListener(e.tagName === "SELECT" ? "change" : "input", () => { clearTimeout(t); t = setTimeout(render, e.tagName === "SELECT" ? 0 : 300); }));

const prem = document.getElementById("premissas");
Object.keys(PADRAO).forEach(k => {
  const inp = document.getElementById("p_" + k);
  inp.value = PREM[k];
  inp.addEventListener("change", () => {
    const v = parseFloat(inp.value);
    PREM[k] = isFinite(v) && v >= 0 ? v : PADRAO[k]; inp.value = PREM[k];
    try { localStorage.setItem("premissas", JSON.stringify(PREM)); } catch (e) {}
    mapa.closePopup(); document.querySelectorAll(".ficha").forEach(f => f.remove());
  });
});

const botaoMais = document.getElementById("mais"), extras = document.getElementById("extras");
botaoMais.addEventListener("click", () => {
  extras.hidden = !extras.hidden;
  prem.hidden = extras.hidden;
  botaoMais.setAttribute("aria-expanded", String(!extras.hidden));
  botaoMais.textContent = extras.hidden ? "Mais filtros" : "Menos filtros";
  setTimeout(() => mapa.invalidateSize(), 50);
});
