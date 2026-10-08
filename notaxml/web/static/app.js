(function () {
  "use strict";

  // ---- seleção de notas -------------------------------------------------
  const marcarTodas = document.getElementById("marcar-todas");
  const caixas = Array.from(document.querySelectorAll("input.marcar"));
  const barra = document.getElementById("barra-acoes");
  const contador = document.getElementById("qtd-selecionadas");

  function atualizarSelecao() {
    const marcadas = caixas.filter((c) => c.checked).length;
    if (contador) contador.textContent = marcadas;
    if (barra) barra.classList.toggle("visivel", marcadas > 0);
    if (marcarTodas) {
      marcarTodas.checked = marcadas > 0 && marcadas === caixas.length;
      marcarTodas.indeterminate = marcadas > 0 && marcadas < caixas.length;
    }
  }
  if (marcarTodas) {
    marcarTodas.addEventListener("change", () => {
      caixas.forEach((c) => { c.checked = marcarTodas.checked; });
      atualizarSelecao();
    });
  }
  caixas.forEach((c) => c.addEventListener("change", atualizarSelecao));
  atualizarSelecao();

  // ---- teclado aberto (celular): esconde abas e botão redondo para sobrar espaço
  const campoDeTexto = "input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=submit]), select, textarea";
  document.addEventListener("focusin", (e) => { if (e.target.matches && e.target.matches(campoDeTexto)) document.body.classList.add("teclado"); });
  document.addEventListener("focusout", () => {
    setTimeout(() => {
      const ativo = document.activeElement;
      if (!(ativo && ativo.matches && ativo.matches(campoDeTexto))) document.body.classList.remove("teclado");
    }, 60);
  });

  // ---- filtros recolhidos no celular
  const botaoFiltros = document.getElementById("alternar-filtros");
  if (botaoFiltros) {
    botaoFiltros.addEventListener("click", () => {
      const formulario = botaoFiltros.closest("form");
      const aberto = formulario.classList.toggle("aberto");
      botaoFiltros.setAttribute("aria-expanded", aberto ? "true" : "false");
    });
  }

  // ---- lista estilo WhatsApp (celular): toque abre a nota; segurar a linha seleciona; depois, tocar alterna ----
  const movel = () => window.matchMedia("(max-width: 760px)").matches;
  const linhas = Array.from(document.querySelectorAll(".lista-conversas tbody tr")).filter((tr) => tr.querySelector("input.marcar"));
  let emSelecao = false;
  function alternarLinha(tr) {
    const caixa = tr.querySelector("input.marcar");
    caixa.checked = !caixa.checked;
    tr.classList.toggle("selecionada", caixa.checked);
    caixa.dispatchEvent(new Event("change", { bubbles: true }));
    emSelecao = linhas.some((l) => l.querySelector("input.marcar").checked);
  }
  linhas.forEach((tr) => {
    let temporizador = null;
    let segurou = false;
    const cancelar = () => clearTimeout(temporizador);
    tr.addEventListener("touchstart", () => {
      if (!movel()) return;
      segurou = false;
      temporizador = setTimeout(() => {
        segurou = true;
        alternarLinha(tr);
        if (navigator.vibrate) navigator.vibrate(15);
      }, 450);
    }, { passive: true });
    ["touchmove", "touchend", "touchcancel"].forEach((evento) => tr.addEventListener(evento, cancelar, { passive: true }));
    tr.addEventListener("contextmenu", (e) => { if (movel()) e.preventDefault(); });
    tr.addEventListener("click", (e) => {
      if (!movel()) return;
      if (segurou) { segurou = false; e.preventDefault(); return; }
      if (e.target.closest("input, button, select")) return;
      if (emSelecao) { e.preventDefault(); alternarLinha(tr); return; }
      const link = tr.querySelector("a.emitente");
      if (link) { e.preventDefault(); window.location.href = link.href; }
    });
  });
  // marcar todas / limpar também reflete na aparência das linhas
  if (marcarTodas) {
    marcarTodas.addEventListener("change", () => {
      linhas.forEach((tr) => tr.classList.toggle("selecionada", tr.querySelector("input.marcar").checked));
      emSelecao = linhas.some((l) => l.querySelector("input.marcar").checked);
    });
  }

  // ---- justificativa obrigatória para "Operação não realizada" ---------
  const evento = document.getElementById("evento");
  const justificativa = document.getElementById("justificativa");
  if (evento && justificativa) {
    const alternar = () => {
      const exige = evento.value === "nao-realizada";
      justificativa.classList.toggle("oculto", !exige);
      justificativa.required = exige;
      justificativa.minLength = exige ? 15 : 0;
    };
    evento.addEventListener("change", alternar);
    alternar();
  }

  // Confirmação antes de enviar eventos à SEFAZ (são definitivos).
  document.querySelectorAll('button[value="manifestar"]').forEach((botao) => {
    botao.addEventListener("click", (e) => {
      const rotulo = evento ? evento.options[evento.selectedIndex].text : "manifestação";
      if (!confirm(`Enviar "${rotulo}" para a SEFAZ? Esse evento fica registrado na nota.`)) e.preventDefault();
    });
  });

  // ---- painel de andamento --------------------------------------------
  const painel = document.getElementById("painel-tarefa");
  if (!painel) return;
  const nome = document.getElementById("tarefa-nome");
  const situacao = document.getElementById("tarefa-situacao");
  const log = document.getElementById("tarefa-log");
  const botaoDetalhes = document.getElementById("tarefa-alternar");
  const rotulos = { executando: "em andamento…", concluida: "concluída", erro: "terminou com erro" };

  function mostrarDetalhes(mostrar) {
    log.classList.toggle("oculto", !mostrar);
    botaoDetalhes.textContent = mostrar ? "ocultar" : "detalhes";
  }
  botaoDetalhes.addEventListener("click", () => mostrarDetalhes(log.classList.contains("oculto")));

  function aplicar(t) {
    if (!t) return;
    painel.classList.remove("oculto");
    painel.dataset.situacao = t.situacao;
    nome.textContent = t.nome;
    situacao.textContent = rotulos[t.situacao] || t.situacao;
    const perto = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
    log.textContent = t.linhas.join("\n");
    if (perto) log.scrollTop = log.scrollHeight;
  }

  let acompanhando = painel.dataset.situacao === "executando";
  mostrarDetalhes(acompanhando || !log.classList.contains("oculto"));
  situacao.textContent = rotulos[painel.dataset.situacao] || "";

  async function consultar() {
    try {
      const resposta = await fetch(painel.dataset.url, { headers: { Accept: "application/json" } });
      const t = await resposta.json();
      if (t && t.situacao === "executando") {
        if (String(t.id) !== painel.dataset.id) mostrarDetalhes(true); // começou outra (ex.: automática)
        painel.dataset.id = t.id;
        acompanhando = true;
      } else if (t && acompanhando) {
        acompanhando = false;
        if (!caixas.some((c) => c.checked)) {
          // terminou: recarrega para mostrar as notas novas (sem perder uma seleção em andamento)
          try { sessionStorage.setItem("notaxml-detalhes", "1"); } catch (_) { /* sem armazenamento */ }
          window.location.reload();
          return;
        }
        aplicar(t);
        situacao.textContent += " — recarregue a página para ver as novidades";
        setTimeout(consultar, 15000);
        return;
      }
      aplicar(t);
    } catch (_) { /* servidor reiniciando; tenta de novo */ }
    setTimeout(consultar, acompanhando ? 1500 : 15000);
  }
  try {
    if (sessionStorage.getItem("notaxml-detalhes")) {
      sessionStorage.removeItem("notaxml-detalhes");
      mostrarDetalhes(true);
    }
  } catch (_) { /* armazenamento indisponível */ }
  setTimeout(consultar, acompanhando ? 1000 : 15000);
})();
