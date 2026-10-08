"""Interface web do notaxml (Flask)."""

import io
import os
import secrets
import subprocess
import sys
import zipfile
from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for

from . import configuracao
from .autenticacao import LimitadorLogin, exige_login, registrar_login
from .seguranca import cabecalhos, csrf_token, destino_seguro, verificar_csrf

from .. import operacoes
from ..armazenamento import Armazenamento, Filtro
from .. import __version__
from ..config import Config, ConfigWeb
from ..danfe import gerar_danfe
from ..erros import ErroNotaXML
from ..manifestacao import EVENTOS
from ..titulos import ErroTitulo, FiltroTitulos, classificar, escrever_csv, ler_data, ler_valor
from .tarefas import GerenciadorTarefas

POR_PAGINA = 100

NOMES_EVENTOS = {
    "210210": "Ciência da Operação",
    "210200": "Confirmação da Operação",
    "210220": "Desconhecimento da Operação",
    "210240": "Operação não Realizada",
    "110111": "Cancelamento",
    "110110": "Carta de Correção",
    "110112": "Cancelamento por substituição",
}
ROTULOS_EVENTOS_MANIFESTACAO = {nome: NOMES_EVENTOS[codigo] for nome, (codigo, _) in EVENTOS.items()}


# ---- filtros de template ---------------------------------------------------

def _moeda(valor) -> str:
    texto = f"{valor or 0:,.2f}"
    return "R$ " + texto.replace(",", "_").replace(".", ",").replace("_", ".")


def _data(valor, com_hora=False) -> str:
    if not valor:
        return ""
    try:
        dt = datetime.fromisoformat(str(valor))
    except ValueError:
        return str(valor)
    if com_hora:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M") if dt.tzinfo else dt.strftime("%d/%m/%Y %H:%M")
    return dt.strftime("%d/%m/%Y")


def _data_curta(valor) -> str:
    """dd/mm no ano corrente (como a hora no WhatsApp); dd/mm/aa nos outros anos."""
    try:
        dia = datetime.fromisoformat(str(valor))
    except ValueError:
        return str(valor or "")
    return dia.strftime("%d/%m") if dia.year == date.today().year else dia.strftime("%d/%m/%y")


def _hora_curta(valor) -> str:
    """Só a hora se for hoje (18:29); senão dd/mm hh:mm. Converte para o fuso do aparelho."""
    try:
        momento = datetime.fromisoformat(str(valor))
    except ValueError:
        return str(valor or "")
    if momento.tzinfo:
        momento = momento.astimezone()
    return momento.strftime("%H:%M") if momento.date() == date.today() else momento.strftime("%d/%m %H:%M")


EVENTOS_CURTOS = {"210210": "Ciência", "210200": "Confirmada", "210220": "Desconhecida", "210240": "Não realizada"}


def _documento(valor) -> str:
    valor = valor or ""
    if len(valor) == 14:
        return f"{valor[:2]}.{valor[2:5]}.{valor[5:8]}/{valor[8:12]}-{valor[12:]}"
    if len(valor) == 11:
        return f"{valor[:3]}.{valor[3:6]}.{valor[6:9]}-{valor[9:]}"
    return valor


_PALAVRAS_IGNORADAS = {"de", "da", "do", "dos", "das", "e", "ltda", "me", "sa", "epp", "eireli", "s", "a"}


def _iniciais(nome) -> str:
    """Duas letras para o avatar (ex.: "ATACADAO DE EMBALAGENS SA" -> "AE")."""
    palavras = [p for p in (nome or "").replace("-", " ").split() if p.lower().strip(".,") not in _PALAVRAS_IGNORADAS]
    letras = "".join(p[0] for p in palavras[:2] if p[0].isalnum())
    return (letras or (nome or "?")[:1]).upper()


def _matiz(nome) -> int:
    """Cor do avatar (matiz de 0 a 359), sempre a mesma para o mesmo nome."""
    return sum(ord(c) * (i + 1) for i, c in enumerate(nome or "")) * 37 % 360


def _chave(valor) -> str:
    return " ".join(valor[i:i + 4] for i in range(0, len(valor or ""), 4))


def _filtro_da_requisicao(origem) -> Filtro:
    def data_valida(nome):
        valor = origem.get(nome, "").strip()
        try:
            return date.fromisoformat(valor).isoformat() if valor else ""
        except ValueError:
            return ""

    pendencia = origem.get("pendencia", "")
    situacao = origem.get("situacao", "")
    return Filtro(
        texto=origem.get("q", "").strip(),
        situacao=situacao if situacao in ("autorizada", "cancelada", "denegada") else "",
        pendencia=pendencia if pendencia in ("sem_xml", "sem_manifestacao") else "",
        inicio=data_valida("de"),
        fim=data_valida("ate"),
    )


def _filtro_titulos(origem) -> FiltroTitulos:
    def data_valida(nome):
        try:
            return date.fromisoformat(origem.get(nome, "").strip()).isoformat()
        except ValueError:
            return ""

    situacao = origem.get("situacao", "aberto")  # sem escolha, mostra o que está em aberto
    return FiltroTitulos(situacao=situacao if situacao in ("aberto", "pago", "cancelado") else "",
                         texto=origem.get("q", "").strip(), de=data_valida("de"), ate=data_valida("ate"))


def _flask(chave_secreta: str | None, https: bool = False) -> Flask:
    app = Flask(__name__)
    app.secret_key = chave_secreta or secrets.token_hex(32)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = https  # com HTTPS o cookie nunca trafega em conexão aberta
    app.after_request(cabecalhos)
    app.add_template_filter(_moeda, "moeda")
    app.add_template_filter(_data, "data")
    app.add_template_filter(partial(_data, com_hora=True), "data_hora")
    app.add_template_filter(_documento, "documento")
    app.add_template_filter(_chave, "chave")
    app.add_template_filter(_iniciais, "iniciais")
    app.add_template_filter(_data_curta, "data_curta")
    app.add_template_filter(_hora_curta, "hora_curta")
    app.add_template_filter(lambda c: EVENTOS_CURTOS.get(c or "", ""), "evento_curto")
    app.add_template_filter(_matiz, "matiz")
    app.add_template_filter(lambda c: NOMES_EVENTOS.get(c or "", c or ""), "evento")
    return app


def criar_app_configuracao(caminho_config: Path, recarregar: Callable, pasta_dados_padrao: Path | None = None,
                           erro: str | None = None, chave_secreta: str | None = None,
                           opcoes_web: ConfigWeb | None = None, limitador: LimitadorLogin | None = None,
                           opcoes_rede: bool = False, token_cookie: str | None = None) -> Flask:
    """App usado enquanto não existe configuração válida: só mostra a tela de configuração."""
    opcoes_web = opcoes_web or ConfigWeb()
    app = _flask(chave_secreta, opcoes_web.https)

    @app.context_processor
    def contexto():
        return {"cfg": None, "csrf_token": csrf_token, "tarefas": None, "erro_config": erro, "versao": __version__}

    exige_login(app, opcoes_web.senha, token_cookie=token_cookie)  # primeiro: quem não entrou vai ao login
    registrar_login(app, opcoes_web.senha, limitador, destino_padrao="/configuracao")

    @app.before_request
    def proteger():
        if request.endpoint not in ("static", "configuracao", "login", "sair"):
            return redirect(url_for("configuracao"))
        verificar_csrf()
        return None

    configuracao.registrar(app, caminho_config, recarregar, pasta_dados_padrao, opcoes_rede=opcoes_rede)
    return app


def criar_app(cfg: Config, gerenciador: GerenciadorTarefas | None = None, caminho_config: Path | None = None,
              recarregar: Callable | None = None, pasta_dados_padrao: Path | None = None,
              desktop: bool = False, chave_secreta: str | None = None,
              limitador: LimitadorLogin | None = None, opcoes_rede: bool = False,
              token_cookie: str | None = None) -> Flask:
    app = _flask(chave_secreta, cfg.web.https)
    app.config["NOTAXML"] = cfg
    gerenciador = gerenciador or GerenciadorTarefas(cfg)
    app.extensions["notaxml_tarefas"] = gerenciador


    # ---- infraestrutura -----------------------------------------------------

    def banco() -> Armazenamento:
        if "banco" not in g:
            g.banco = Armazenamento(cfg.pasta_dados)
        return g.banco

    @app.teardown_appcontext
    def fechar_banco(_exc):
        b = g.pop("banco", None)
        if b is not None:
            b.fechar()

    @app.context_processor
    def contexto():
        return {
            "cfg": cfg,
            "csrf_token": csrf_token,
            "tarefas": gerenciador,
            "eventos_manifestacao": ROTULOS_EVENTOS_MANIFESTACAO,
            "ambiente_nome": "Produção" if cfg.ambiente == 1 else "Homologação",
            "configuravel": caminho_config is not None,
            "desktop": desktop,
            "versao": __version__,
            "pagar_atencao": banco().resumo_titulos(date.today()).atencao,
            "faixa_vencimento": lambda vencimento: classificar(vencimento, date.today()),
        }

    @app.before_request
    def proteger():
        if request.endpoint in ("static",):
            return None
        verificar_csrf()
        return None

    exige_login(app, cfg.web.senha, token_cookie=token_cookie)
    registrar_login(app, cfg.web.senha, limitador, destino_padrao="/")

    if caminho_config is not None and recarregar is not None:
        configuracao.registrar(app, caminho_config, recarregar, pasta_dados_padrao, lambda: gerenciador.ocupado,
                               opcoes_rede)

    if desktop:
        @app.post("/abrir-pasta")
        def abrir_pasta():
            pasta = Path(cfg.pasta_dados) / "xml"
            pasta.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(pasta)  # noqa: S606 - pasta local do próprio usuário
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(pasta)])
            return voltar()

    def iniciar_tarefa(nome, funcao, *args, **kwargs):
        try:
            gerenciador.iniciar(nome, funcao, *args, **kwargs)
            flash(f"{nome} iniciada. Acompanhe o andamento no painel.", "info")
        except ErroNotaXML as exc:
            flash(str(exc), "erro")

    def chaves_do_formulario() -> list[str]:
        try:
            return operacoes.validar_chaves(request.form.getlist("chave"))
        except ErroNotaXML as exc:
            flash(str(exc), "erro")
            return []

    def voltar():
        return redirect(destino_seguro(request.form.get("voltar", ""), url_for("notas")))

    # ---- páginas ------------------------------------------------------------

    @app.get("/")
    def notas():
        filtro = _filtro_da_requisicao(request.args)
        pagina = max(1, request.args.get("pagina", 1, type=int))
        b = banco()
        totais = b.totais(filtro)
        lista = b.buscar(filtro, POR_PAGINA, (pagina - 1) * POR_PAGINA)
        paginas = max(1, -(-totais["quantidade"] // POR_PAGINA))
        return render_template(
            "notas.html", notas=lista, totais=totais, geral=b.totais(Filtro()), filtro=filtro,
            pagina=pagina, paginas=paginas, args=request.args.to_dict(),
            estado=b.estado(cfg.documento, cfg.ambiente),
        )

    @app.get("/nota/<chave>")
    def nota(chave):
        b = banco()
        registro = b.nota(chave)
        if registro is None:
            abort(404)
        return render_template("nota.html", nota=registro, eventos=b.eventos(chave), titulos=b.titulos_por_chave(chave))

    def _pdf_da_nota(registro) -> bytes:
        caminho = banco().caminho(registro["arquivo_xml"])
        return gerar_danfe(caminho.read_bytes(), cancelada=registro["situacao"] == "cancelada")

    @app.get("/nota/<chave>/danfe.pdf")
    def danfe(chave):
        registro = banco().nota(chave)
        if registro is None or not registro["arquivo_xml"] or not banco().caminho(registro["arquivo_xml"]).is_file():
            abort(404, "O XML completo desta nota ainda não foi baixado, então não dá para gerar o DANFE.")
        try:
            pdf = _pdf_da_nota(registro)
        except ErroNotaXML as exc:
            abort(400, str(exc))
        return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name=f"DANFE-{chave}.pdf",
                         as_attachment=bool(request.args.get("baixar")))

    @app.get("/nota/<chave>/<tipo>.xml")
    def baixar_arquivo(chave, tipo):
        registro = banco().nota(chave)
        coluna = {"nfe": "arquivo_xml", "resumo": "arquivo_resumo"}.get(tipo)
        if registro is None or coluna is None or not registro[coluna]:
            abort(404)
        caminho = banco().caminho(registro[coluna])
        if not caminho.is_file():
            abort(404)
        return send_file(caminho, mimetype="application/xml", as_attachment=True, download_name=caminho.name)

    @app.get("/nota/<chave>/evento/<tipo>/<int:sequencia>.xml")
    def baixar_evento(chave, tipo, sequencia):
        registro = banco().evento(chave, tipo, sequencia)
        if registro is None or not registro["arquivo"]:
            abort(404)
        caminho = banco().caminho(registro["arquivo"])
        if not caminho.is_file():
            abort(404)
        return send_file(caminho, mimetype="application/xml", as_attachment=True, download_name=caminho.name)

    # ---- contas a pagar -----------------------------------------------------

    @app.get("/pagar")
    def pagar():
        b = banco()
        filtro = _filtro_titulos(request.args)
        hoje = date.today()
        lista = b.titulos(filtro)
        datas = {"hoje": hoje.isoformat(), "ontem": (hoje - timedelta(days=1)).isoformat(),
                 "em7": (hoje + timedelta(days=7)).isoformat(), "em30": (hoje + timedelta(days=30)).isoformat()}
        return render_template("pagar.html", titulos=lista, resumo=b.resumo_titulos(hoje), filtro=filtro,
                               datas=datas, total=round(sum(t["valor"] for t in lista), 2),
                               args=request.args.to_dict(), hoje=hoje)

    @app.get("/pagar.csv")
    def pagar_csv():
        texto = io.StringIO()
        escrever_csv(texto, banco().titulos(_filtro_titulos(request.args)))
        return send_file(io.BytesIO(texto.getvalue().encode("utf-8-sig")), mimetype="text/csv", as_attachment=True,
                         download_name=f"contas-a-pagar-{datetime.now():%Y%m%d-%H%M}.csv")

    @app.post("/pagar/acao")
    def pagar_acao():
        try:
            ids = [int(i) for i in request.form.getlist("id")]
        except ValueError:
            abort(400)
        if not ids:
            flash("Selecione ao menos um título.", "erro")
            return voltar()
        b, acao = banco(), request.form.get("acao")
        try:
            if acao == "pagar":
                em = date.fromisoformat(ler_data(request.form.get("data_pagamento") or date.today().isoformat(),
                                                 "data do pagamento"))
                flash(f"{b.marcar_pago(ids, em)} título(s) marcado(s) como pago(s).", "ok")
            elif acao == "reabrir":
                flash(f"{b.reabrir(ids)} título(s) reaberto(s).", "ok")
            elif acao == "excluir":
                flash(f"{b.excluir_titulos_manuais(ids)} lançamento(s) manual(is) excluído(s). "
                      "Parcelas que vieram da nota não podem ser excluídas (use Reabrir/Cancelado).", "ok")
            else:
                abort(400)
        except ErroTitulo as exc:
            flash(str(exc), "erro")
        return voltar()

    @app.post("/nota/<chave>/titulo")
    def adicionar_titulo(chave):
        try:
            banco().adicionar_titulo(chave, ler_data(request.form.get("vencimento", ""), "data de vencimento"),
                                     ler_valor(request.form.get("valor", "")), request.form.get("observacao"))
            flash("Parcela lançada.", "ok")
        except ErroTitulo as exc:
            flash(str(exc), "erro")
        return voltar()

    @app.get("/certificado")
    def certificado():
        return render_template("certificado.html", cert=gerenciador.certificado)

    @app.post("/certificado/testar")
    def testar_conexao():
        iniciar_tarefa("Teste de conexão", operacoes.testar_conexao)
        return redirect(url_for("notas"))

    @app.post("/certificado")
    def desbloquear_certificado():
        try:
            gerenciador.desbloquear(request.form.get("senha", ""))
            flash("Certificado desbloqueado. A senha fica só na memória enquanto o sistema estiver aberto.", "ok")
        except ErroNotaXML as exc:
            flash(str(exc), "erro")
        return redirect(url_for("certificado"))

    # ---- exportação ---------------------------------------------------------

    def _zip(notas_selecionadas):
        memoria = io.BytesIO()
        quantidade = 0
        with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as arquivo_zip:
            for n in notas_selecionadas:
                if n["arquivo_xml"]:
                    caminho = banco().caminho(n["arquivo_xml"])
                    if caminho.is_file():
                        arquivo_zip.write(caminho, caminho.name)
                        quantidade += 1
        if not quantidade:
            flash("Nenhuma das notas escolhidas tem XML completo para baixar.", "erro")
            return None
        memoria.seek(0)
        nome = f"nfe-{datetime.now():%Y%m%d-%H%M}.zip"
        return send_file(memoria, mimetype="application/zip", as_attachment=True, download_name=nome)

    def _zip_danfes(notas_selecionadas):
        memoria = io.BytesIO()
        gerados, falhas = 0, 0
        with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as arquivo_zip:
            for n in notas_selecionadas:
                if not n["arquivo_xml"] or not banco().caminho(n["arquivo_xml"]).is_file():
                    continue
                try:
                    arquivo_zip.writestr(f"DANFE-{n['chave']}.pdf", _pdf_da_nota(n))
                    gerados += 1
                except ErroNotaXML:
                    falhas += 1
        if not gerados:
            flash("Nenhuma das notas escolhidas tem XML completo para gerar o DANFE.", "erro")
            return None
        if falhas:
            flash(f"{falhas} nota(s) não puderam gerar o DANFE e ficaram fora do ZIP.", "erro")
        memoria.seek(0)
        return send_file(memoria, mimetype="application/zip", as_attachment=True,
                         download_name=f"danfe-{datetime.now():%Y%m%d-%H%M}.zip")

    @app.get("/exportar.zip")
    def exportar_zip():
        resposta = _zip(banco().buscar(_filtro_da_requisicao(request.args)))
        return resposta or redirect(url_for("notas", **request.args))

    @app.get("/exportar.csv")
    def exportar_csv():
        texto = io.StringIO()
        operacoes.escrever_csv(texto, banco().buscar(_filtro_da_requisicao(request.args)))
        dados = io.BytesIO(texto.getvalue().encode("utf-8-sig"))
        return send_file(dados, mimetype="text/csv", as_attachment=True,
                         download_name=f"notas-{datetime.now():%Y%m%d-%H%M}.csv")

    # ---- ações na SEFAZ -----------------------------------------------------

    @app.post("/acoes/sincronizar")
    def acao_sincronizar():
        iniciar_tarefa("Sincronização", operacoes.sincronizar,
                       ciencia=bool(request.form.get("ciencia")), forcar=bool(request.form.get("forcar")))
        return voltar()

    @app.post("/acoes/selecionadas")
    def acao_selecionadas():
        chaves = chaves_do_formulario()
        if not chaves:
            flash("Selecione ao menos uma nota.", "erro")
            return voltar()
        acao = request.form.get("acao")
        if acao == "zip":
            return _zip(banco().buscar(Filtro(chaves=chaves))) or voltar()
        if acao == "danfe":
            return _zip_danfes(banco().buscar(Filtro(chaves=chaves))) or voltar()
        if acao == "baixar":
            iniciar_tarefa("Download de XML", operacoes.baixar, chaves)
            return voltar()
        if acao == "manifestar":
            evento = request.form.get("evento", "")
            justificativa = request.form.get("justificativa", "").strip() or None
            if evento not in EVENTOS:
                flash("Escolha o tipo de manifestação.", "erro")
            elif evento == "nao-realizada" and not (justificativa and 15 <= len(justificativa) <= 255):
                flash("'Operação não realizada' exige justificativa de 15 a 255 caracteres.", "erro")
            else:
                iniciar_tarefa("Manifestação", operacoes.manifestar, chaves, evento, justificativa)
            return voltar()
        abort(400)

    @app.post("/acoes/baixar-pendentes")
    def acao_baixar_pendentes():
        iniciar_tarefa("Download de XML", operacoes.baixar)
        return voltar()

    @app.get("/tarefa")
    def tarefa():
        atual = gerenciador.ultima()
        return jsonify(atual.como_dict() if atual else None)

    @app.errorhandler(400)
    @app.errorhandler(404)
    def erro(exc):
        return render_template("erro.html", erro=exc), exc.code

    return app

