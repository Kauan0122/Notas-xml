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
