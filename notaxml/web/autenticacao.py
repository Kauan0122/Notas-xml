"""Login por senha de acesso, com bloqueio de tentativas repetidas. Usado pela tela de configuração e pelo app."""

import hmac
import threading
import time
from collections.abc import Callable

from flask import Flask, flash, redirect, render_template, request, session, url_for

from .seguranca import destino_seguro

MAX_FALHAS = 5
JANELA_SEGUNDOS = 15 * 60
BLOQUEIO_SEGUNDOS = 15 * 60
DURACAO_SESSAO_SEGUNDOS = 12 * 3600


class LimitadorLogin:
    """Depois de MAX_FALHAS senhas erradas do mesmo endereço, bloqueia novas tentativas por um tempo."""

    def __init__(self, relogio: Callable[[], float] = time.monotonic):
        self._relogio = relogio
        self._trava = threading.Lock()
        self._falhas: dict[str, list[float]] = {}
        self._bloqueado_ate: dict[str, float] = {}

    def segundos_de_bloqueio(self, chave: str) -> int:
        with self._trava:
            restante = self._bloqueado_ate.get(chave, 0) - self._relogio()
            if restante <= 0:
                self._bloqueado_ate.pop(chave, None)
                return 0
            return int(restante) + 1

    def registrar_falha(self, chave: str):
        with self._trava:
            agora = self._relogio()
            recentes = [t for t in self._falhas.get(chave, []) if agora - t < JANELA_SEGUNDOS] + [agora]
            self._falhas[chave] = recentes
            if len(recentes) >= MAX_FALHAS:
                self._bloqueado_ate[chave] = agora + BLOQUEIO_SEGUNDOS
                self._falhas.pop(chave, None)
            if len(self._falhas) > 10_000:  # evita crescer sem limite sob ataque
                self._falhas.clear()

    def registrar_sucesso(self, chave: str):
        with self._trava:
            self._falhas.pop(chave, None)


def exige_login(app: Flask, senha: str | None, liberados: tuple[str, ...] = ("static", "login", "saude")):
    """Redireciona para /login quem não entrou (quando há senha de acesso configurada)."""
    @app.before_request
    def _guarda():
        if senha and request.endpoint not in liberados and not session.get("autenticado"):
            return redirect(url_for("login", proximo=request.full_path if request.method == "GET" else "/"))
        return None


def registrar_login(app: Flask, senha: str | None, limitador: LimitadorLogin | None = None,
                    destino_padrao: str = "/"):
    limitador = limitador or LimitadorLogin()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not senha:
            return redirect(destino_padrao)
        if request.method == "POST":
            origem = request.remote_addr or "?"
            espera = limitador.segundos_de_bloqueio(origem)
            if espera:
                flash(f"Muitas tentativas erradas. Tente de novo em {-(-espera // 60)} minuto(s).", "erro")
                return render_template("login.html"), 429
            if hmac.compare_digest(request.form.get("senha", "").encode(), senha.encode()):
                limitador.registrar_sucesso(origem)
                csrf = session.get("csrf")
                session.clear()
                if csrf:
                    session["csrf"] = csrf
                session["autenticado"] = True
                session.permanent = True
                return redirect(destino_seguro(request.args.get("proximo", ""), destino_padrao))
            limitador.registrar_falha(origem)
            flash("Senha incorreta.", "erro")
        return render_template("login.html")

    @app.post("/sair")
    def sair():
        session.clear()
        return redirect(url_for("login"))

    app.config["PERMANENT_SESSION_LIFETIME"] = DURACAO_SESSAO_SEGUNDOS
