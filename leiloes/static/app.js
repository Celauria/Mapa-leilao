// Monta DOM só com textContent: dados de terceiros (CSV/edital) nunca viram HTML.
const brl = v => v == null ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const cor = s => s >= 70 ? "#0f6b5c" : s >= 45 ? "#c98a1b" : "#b5462a";
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

const mapa = L.map("mapa").setView([-23.55, -46.63], 11);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap" }).addTo(mapa);
const camada = L.layerGroup().addTo(mapa);
const marcadores = {};

function ficha(im) {
  const box = el("div");
  box.append(el("strong", null, `${im.tipo || "Imóvel"} — ${im.bairro || ""}`));
  box.append(el("div", "meta", `${im.endereco || ""}, ${im.cidade || ""}/${im.uf || ""}`));
  box.append(el("div", null, `Preço ${brl(im.preco)} · Avaliação ${brl(im.valor_avaliacao)} · ${im.desconto ?? "—"}% off`));
  if (im.area_privativa) box.append(el("div", "meta", `${im.area_privativa} m² · R$ ${Math.round(im.preco / im.area_privativa).toLocaleString("pt-BR")}/m²`));
  box.append(el("div", "meta", im.modalidade || ""));
  if (im.edital) {
    box.append(el("div", null, im.edital.resumo || ""));
    JSON.parse(im.edital.alertas || "[]").forEach(a => box.append(el("div", "alerta", "⚠ " + a)));
  }
  if (im.link && /^https:\/\//.test(im.link)) {
    const a = el("a", null, "Abrir anúncio e edital"); a.href = im.link; a.target = "_blank"; a.rel = "noopener noreferrer";
    box.append(a);
  }
  return box;
}

function item(im) {
  const d = el("div", "item");
  const l1 = el("div", "linha");
  l1.append(el("span", "preco", brl(im.preco)));
  l1.append(el("span", "desc", im.desconto != null ? `-${im.desconto}%` : ""));
  const sc = el("span", "score", im.score); sc.style.background = cor(im.score); l1.append(sc);
  d.append(l1);
  d.append(el("div", null, `${im.tipo || "Imóvel"} · ${im.bairro || ""}, ${im.cidade || ""}`));
  d.append(el("div", "meta", im.modalidade || ""));
  if (im.motivos?.length) d.append(el("div", "motivos", im.motivos.join(" · ")));
  d.onclick = () => {
    document.querySelectorAll(".item.ativo").forEach(x => x.classList.remove("ativo"));
    d.classList.add("ativo");
    const m = marcadores[im.id];
    if (m) { mapa.setView(m.getLatLng(), 16); m.openPopup(); }
  };
  return d;
}

async function carregar() {
  const p = new URLSearchParams();
  ["uf", "cidade", "modalidade", "preco_max", "desconto_min", "busca"].forEach(id => {
    const v = document.getElementById(id).value; if (v) p.set(id, v);
  });
  const dados = await (await fetch("/api/imoveis?" + p)).json();
  camada.clearLayers();
  const lista = document.getElementById("lista"); lista.replaceChildren();
  const pts = [];
  dados.forEach(im => {
    lista.append(item(im));
    if (im.lat != null) {
      const m = L.circleMarker([im.lat, im.lon], { radius: 7, color: cor(im.score), fillOpacity: .8 }).bindPopup(ficha(im));
      m.addTo(camada); marcadores[im.id] = m; pts.push([im.lat, im.lon]);
    }
  });
  document.getElementById("contagem").textContent = `${dados.length} imóveis · ${pts.length} no mapa`;
  if (pts.length) mapa.fitBounds(pts, { padding: [30, 30], maxZoom: 14 });
}

async function opcoes() {
  const o = await (await fetch("/api/opcoes")).json();
  for (const [id, vals] of Object.entries(o)) {
    const s = document.getElementById(id);
    vals.forEach(v => { const op = el("option", null, v); op.value = v; s.append(op); });
  }
}

let t;
document.querySelectorAll("header select, header input").forEach(e =>
  e.addEventListener("input", () => { clearTimeout(t); t = setTimeout(carregar, 300); }));
opcoes().then(carregar);
