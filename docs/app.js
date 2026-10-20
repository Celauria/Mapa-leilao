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

function ficha(im) {
  const box = el("div");
  box.append(el("strong", null, `${im.tipo || "Imóvel"} — ${im.bairro || ""}`));
  box.append(el("div", "meta", `${im.endereco || ""}, ${im.cidade || ""}/${im.uf || ""}`));
  if (im.geo_precisao && !im.geo_precisao.startsWith("endereco"))
    box.append(el("div", "meta", `Posição aproximada (centro do ${im.geo_precisao === "cidade" ? "município" : "bairro"})`));
  box.append(el("div", null, `${brl(im.preco)} · avaliação ${brl(im.valor_avaliacao)} · ${im.desconto ?? "—"}% off`));
  if (im.area_privativa) box.append(el("div", "meta", `${im.area_privativa} m² · ${brl(im.preco / im.area_privativa)}/m²`));
  box.append(el("div", "meta", `${im.modalidade || ""}${im.financiamento ? " · financiamento: " + im.financiamento : ""}`));
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
  l1.append(p, el("span", "desc", im.desconto != null ? `-${im.desconto}%` : ""));
  const sc = el("span", "score", im.score); sc.style.background = cor(im.score); l1.append(sc);
  d.append(l1, el("div", null, `${im.tipo || "Imóvel"} · ${im.bairro || ""}, ${im.cidade || ""}/${im.uf}`));
  d.append(el("div", "meta", im.modalidade || ""));
  if (im.motivos?.length) d.append(el("div", "motivos", im.motivos.join(" · ")));
  d.onclick = () => {
    document.querySelectorAll(".item.ativo").forEach(x => x.classList.remove("ativo"));
    d.classList.add("ativo");
    const m = marcadores[im.id];
    if (m) { mapa.setView(m.getLatLng(), 15); m.openPopup(); }
  };
  return d;
}

function render() {
  const v = id => document.getElementById(id).value;
  const filtro = v("filtro"), cidade = v("cidade"), pmax = +v("preco_max") || Infinity,
        dmin = +v("desconto_min") || 0, periodo = +v("periodo") || 0, busca = norm(v("busca"));
  const dados = TODOS.filter(im =>
    (!filtro || im.filtro === filtro) && (!cidade || im.cidade === cidade) &&
    (im.preco ?? 0) <= pmax && (im.desconto ?? 0) >= dmin &&
    (!periodo || diasDesde(im.primeira_vez) <= periodo) &&
    (!busca || norm(`${im.bairro} ${im.endereco} ${im.tipo} ${im.cidade}`).includes(busca)));
  camada.clearLayers(); marcadores = {};
  const lista = document.getElementById("lista"); lista.replaceChildren();
  const pts = [];
  dados.slice(0, 600).forEach(im => lista.append(item(im)));
  dados.forEach(im => {
    if (im.lat == null) return;
    const m = L.circleMarker([im.lat, im.lon], { radius: 7, color: cor(im.score), fillOpacity: im.geo_precisao === "endereco" ? .85 : .35, dashArray: im.geo_precisao === "endereco" ? null : "3 3" }).bindPopup(() => ficha(im));
    m.addTo(camada); marcadores[im.id] = m; pts.push([im.lat, im.lon]);
  });
  document.getElementById("contagem").textContent = `${dados.length} imóveis · ${pts.length} no mapa`;
  if (pts.length) mapa.fitBounds(pts, { padding: [24, 24], maxZoom: 14 });
}

function preencher(id, valores) {
  const s = document.getElementById(id);
  [...new Set(valores)].filter(Boolean).sort().forEach(x => { const o = el("option", null, x); o.value = x; s.append(o); });
}

fetch("imoveis.json", { cache: "no-cache" }).then(r => r.json()).then(j => {
  TODOS = j.imoveis || [];
  preencher("filtro", TODOS.map(i => i.filtro));
  preencher("cidade", TODOS.map(i => i.cidade));
  document.title = `Leilões · ${new Date(j.atualizado).toLocaleDateString("pt-BR")}`;
  render();
}).catch(() => { document.getElementById("contagem").textContent = "sem dados ainda — aguarde a 1ª execução"; });

let t;
document.querySelectorAll(".filtros select, .filtros input").forEach(e =>
  e.addEventListener("input", () => { clearTimeout(t); t = setTimeout(render, 250); }));
