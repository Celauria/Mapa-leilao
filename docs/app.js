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
const descReal = im => im.valor_avaliacao > 0 && im.preco != null ? (1 - im.preco / im.valor_avaliacao) * 100 : (im.desconto ?? 0);
const fmtDesc = d => d >= 0.5 ? `-${d.toFixed(0)}%` : d <= -0.5 ? `+${(-d).toFixed(0)}% acima` : "sem desconto";

function ficha(im) {
  const box = el("div");
  box.append(el("strong", null, `${im.tipo || "Imóvel"} — ${im.bairro || ""}`));
  box.append(el("div", "meta", `${im.endereco || ""}, ${im.cidade || ""}/${im.uf || ""}`));
  if (im.geo_precisao && !im.geo_precisao.startsWith("endereco"))
    box.append(el("div", "meta", `Posição aproximada (centro do ${im.geo_precisao === "cidade" ? "município" : "bairro"})`));
  const dr = descReal(im);
  box.append(el("div", null, `${brl(im.preco)} · avaliação ${brl(im.valor_avaliacao)} · ${dr >= 0.5 ? dr.toFixed(0) + "% de desconto" : fmtDesc(dr)}`));
  if (im.area_privativa) box.append(el("div", "meta", `${im.area_privativa} m² · ${brl(im.preco / im.area_privativa)}/m²`));
  box.append(el("div", "meta", `${im.modalidade || ""}${im.financiamento ? " · financiamento: " + im.financiamento : ""}`));
  if (/SFI/i.test(im.modalidade || "") && dr < 0.5)
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
  const p = el("span", "preco", brl(im.preco));
  if (diasDesde(im.primeira_vez) <= 1) p.append(el("span", "novo", "NOVO"));
  const dr = descReal(im);
  l1.append(p, el("span", dr >= 0.5 ? "desc" : "desc nulo", fmtDesc(dr)));
  const sc = el("span", "score", im.score); sc.style.background = cor(im.score); l1.append(sc);
  d.append(l1, el("div", null, `${im.tipo || "Imóvel"} · ${im.bairro || ""}, ${im.cidade || ""}/${im.uf}`));
  d.append(el("div", "meta", im.modalidade || ""));
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
  filtro:        (im, v) => im.filtro === v,
  cidade:        (im, v) => `${im.cidade}|${im.uf}` === v,
  modalidade:    (im, v) => im.modalidade === v,
  financiamento: (im, v) => (im.financiamento || "").trim() === v,
  desconto_min:  (im, v) => descReal(im) >= +v,
  preco_max:     (im, v) => +v <= 0 || (im.preco ?? 0) <= +v,
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
  const porEstado = contar(filtrar(vals, ["filtro", "cidade"]), im => im.filtro);
  const nEst = Object.values(porEstado).reduce((a, b) => a + b, 0);
  opcoes("filtro", `SP e SC (${fmt(nEst)})`, Object.keys(porEstado).sort()
    .map(f => ({ valor: f, rotulo: `${f.replace("Estado de ", "")} (${fmt(porEstado[f])})`, n: porEstado[f] })));

  const baseCid = filtrar(vals, ["cidade"]);
  const porCidade = contar(baseCid, im => im.cidade && `${im.cidade}|${im.uf}`);
  opcoes("cidade", `Cidade: todas (${fmt(baseCid.length)})`, Object.keys(porCidade).sort().map(k => {
    const [c, uf] = k.split("|");
    return { valor: k, rotulo: `${c}${vals.filtro ? "" : "/" + uf} (${porCidade[k]})`, n: porCidade[k] };
  }));
  if (vals.cidade && !porCidade[vals.cidade] && vals.filtro && !vals.cidade.endsWith("|" + vals.filtro.slice(-2))) {
    document.getElementById("cidade").value = "";  // cidade de outro estado: limpa
  }

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
  const chave = { score: im => -im.score, desconto: im => -descReal(im), preco: im => im.preco ?? 1e12,
                  recentes: im => -Date.parse((im.primeira_vez || "1970-01-01").replace(" ", "T") + "Z") }[ordem] || (im => -im.score);
  dados.sort((a, b) => chave(a) - chave(b));
  camada.clearLayers(); marcadores = {};
  const lista = document.getElementById("lista"); lista.replaceChildren();
  const pts = [];
  dados.slice(0, 600).forEach(im => lista.append(item(im)));
  dados.forEach(im => {
    if (im.lat == null) return;
    const m = L.circleMarker([im.lat, im.lon], { radius: 7, color: cor(im.score), fillOpacity: im.geo_precisao === "endereco" ? .85 : .35, dashArray: im.geo_precisao === "endereco" ? null : "3 3" }).bindPopup(() => ficha(im));
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

let t;
document.querySelectorAll(".filtros select, .filtros input").forEach(e =>
  e.addEventListener(e.tagName === "SELECT" ? "change" : "input", () => { clearTimeout(t); t = setTimeout(render, e.tagName === "SELECT" ? 0 : 300); }));

const botaoMais = document.getElementById("mais"), extras = document.getElementById("extras");
botaoMais.addEventListener("click", () => {
  extras.hidden = !extras.hidden;
  botaoMais.setAttribute("aria-expanded", String(!extras.hidden));
  botaoMais.textContent = extras.hidden ? "Mais filtros" : "Menos filtros";
  setTimeout(() => mapa.invalidateSize(), 50);
});
