"""Interface web do notaxml (Flask)."""

import hmac
import io
import secrets
import zipfile
from datetime import date, datetime
from functools import partial

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file, session,
                   url_for)

from .. import operacoes
from ..armazenamento import Armazenamento, Filtro
from ..config import Config
from ..erros import ErroNotaXML
from ..manifestacao import EVENTOS
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


def _documento(valor) -> str:
    valor = valor or ""
    if len(valor) == 14:
        return f"{valor[:2]}.{valor[2:5]}.{valor[5:8]}/{valor[8:12]}-{valor[12:]}"
    if len(valor) == 11:
        return f"{valor[:3]}.{valor[3:6]}.{valor[6:9]}-{valor[9:]}"
    return valor


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


def criar_app(cfg: Config, gerenciador: GerenciadorTarefas | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)
    app.config["NOTAXML"] = cfg
    gerenciador = gerenciador or GerenciadorTarefas(cfg)
    app.extensions["notaxml_tarefas"] = gerenciador

    app.add_template_filter(_moeda, "moeda")
    app.add_template_filter(_data, "data")
    app.add_template_filter(partial(_data, com_hora=True), "data_hora")
    app.add_template_filter(_documento, "documento")
    app.add_template_filter(_chave, "chave")
    app.add_template_filter(lambda c: NOMES_EVENTOS.get(c or "", c or ""), "evento")

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

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    @app.context_processor
    def contexto():
        return {
            "cfg": cfg,
            "csrf_token": csrf_token,
            "tarefas": gerenciador,
            "eventos_manifestacao": ROTULOS_EVENTOS_MANIFESTACAO,
            "ambiente_nome": "Produção" if cfg.ambiente == 1 else "Homologação",
        }

    @app.before_request
    def proteger():
        if request.endpoint in ("static",):
            return None
        if cfg.web.senha and not session.get("autenticado") and request.endpoint != "login":
            return redirect(url_for("login", proximo=request.full_path))
        if request.method == "POST":
            enviado = request.form.get("csrf", "")
            if not session.get("csrf") or not hmac.compare_digest(enviado, session["csrf"]):
                abort(400, "Formulário expirado. Recarregue a página e tente de novo.")
        return None

    @app.after_request
    def cabecalhos(resposta):
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "DENY")
        resposta.headers.setdefault("Referrer-Policy", "same-origin")
        return resposta

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
        destino = request.form.get("voltar", "")
        return redirect(destino if destino.startswith("/") and not destino.startswith("//") else url_for("notas"))

    # ---- autenticação -------------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not cfg.web.senha:
            return redirect(url_for("notas"))
        if request.method == "POST":
            if hmac.compare_digest(request.form.get("senha", "").encode(), cfg.web.senha.encode()):
                session.clear()
                session["autenticado"] = True
                proximo = request.args.get("proximo", "")
                return redirect(proximo if proximo.startswith("/") and not proximo.startswith("//") else url_for("notas"))
            flash("Senha incorreta.", "erro")
        return render_template("login.html")

    @app.post("/sair")
    def sair():
        session.clear()
        return redirect(url_for("login"))

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
        return render_template("nota.html", nota=registro, eventos=b.eventos(chave))

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

    @app.get("/certificado")
    def certificado():
        return render_template("certificado.html", cert=gerenciador.certificado)

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

