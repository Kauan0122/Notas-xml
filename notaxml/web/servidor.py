"""Servidor web: escolhe entre a tela de configuração e o sistema completo, e troca sem reiniciar."""

import ipaddress
import os
import secrets
import threading
import tomllib
import webbrowser
from pathlib import Path

from werkzeug.middleware.proxy_fix import ProxyFix

from ..config import carregar_config, ler_config_web
from ..erros import ErroNotaXML
from . import criar_app, criar_app_configuracao
from .autenticacao import LimitadorLogin
from .tarefas import GerenciadorTarefas

ASSINATURA = b"notaxml"
NOME_ARQUIVO_CHAVE = "chave_sessao"


def chave_de_sessao(pasta: Path) -> str:
    """Chave que assina os cookies de sessão. Fica em arquivo para o login sobreviver a reinícios."""
    arquivo = pasta / NOME_ARQUIVO_CHAVE
    try:
        if arquivo.is_file():
            chave = arquivo.read_text(encoding="utf-8").strip()
            if len(chave) >= 32:
                return chave
        pasta.mkdir(parents=True, exist_ok=True)
        chave = secrets.token_hex(32)
        descritor = os.open(arquivo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descritor, "w", encoding="utf-8") as saida:
            saida.write(chave)
        return chave
    except OSError:
        return secrets.token_hex(32)  # pasta somente leitura: vale só até reiniciar


class Aplicacao:
    """App WSGI que pode ser recarregado depois que a configuração muda."""

    def __init__(self, caminho_config: str | Path, pasta_dados_padrao: Path | None = None, desktop: bool = False,
                 opcoes_rede: bool = False):
        self.caminho_config = Path(caminho_config).resolve()
        self.pasta_dados_padrao = pasta_dados_padrao
        self.desktop = desktop
        self._token_cookie = os.environ.get("NOTAXML_ACESSO_LOCAL") or None  # definido pelo app Android
        self.opcoes_rede = opcoes_rede  # mostra, em Configurações, a opção de abrir o acesso para a rede
        self._chave_secreta = chave_de_sessao(self.caminho_config.parent)
        self._limitador = LimitadorLogin()  # o mesmo entre recargas: trocar a configuração não zera o bloqueio
        self.opcoes_web = ler_config_web(self.caminho_config)
        self._wsgi = self._montar_wsgi()
        self._trava = threading.Lock()
        self.app = None
        self.cfg = None
        self.gerenciador: GerenciadorTarefas | None = None
        self.recarregar()

    def _montar_wsgi(self):
        if self.opcoes_web.atras_de_proxy:
            # confia no cabeçalho X-Forwarded-* de UM proxy (o nosso): o IP real alimenta o bloqueio de tentativas
            return ProxyFix(self._despachar, x_for=1, x_proto=1, x_host=1)
        return self._despachar

    def _erro_a_mostrar(self, exc: ErroNotaXML) -> str | None:
        """Arquivo ilegível ou com dados da empresa inválidos é erro; só com opções do servidor é primeiro uso."""
        try:
            secoes = tomllib.loads(self.caminho_config.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return str(exc)
        return str(exc) if "empresa" in secoes else None

    def recarregar(self, senha_certificado: str | None = None):
        with self._trava:
            anterior = self.gerenciador
            self.opcoes_web = ler_config_web(self.caminho_config)
            self._wsgi = self._montar_wsgi()
            cfg, erro = None, None
            if self.caminho_config.is_file():
                try:
                    cfg = carregar_config(self.caminho_config)
                except ErroNotaXML as exc:
                    erro = self._erro_a_mostrar(exc)
            if cfg is None:
                self.cfg, self.gerenciador = None, None
                self.app = criar_app_configuracao(self.caminho_config, self.recarregar, self.pasta_dados_padrao, erro,
                                                  self._chave_secreta, self.opcoes_web, self._limitador,
                                                  self.opcoes_rede, self._token_cookie)
            else:
                gerenciador = GerenciadorTarefas(cfg)
                if gerenciador.certificado is None and senha_certificado:
                    try:
                        gerenciador.desbloquear(senha_certificado)
                    except ErroNotaXML as exc:
                        gerenciador.erro_certificado = str(exc)
                self.cfg, self.gerenciador = cfg, gerenciador
                self.app = criar_app(cfg, gerenciador, self.caminho_config, self.recarregar,
                                     self.pasta_dados_padrao, self.desktop, self._chave_secreta, self._limitador,
                                     self.opcoes_rede, self._token_cookie)
                if cfg.web.sincronizacao_automatica:
                    gerenciador.verificar_agenda()
                    gerenciador.iniciar_agendador()
            if anterior is not None:
                anterior.parar()

    def _despachar(self, environ, start_response):
        if environ.get("PATH_INFO") == "/saude":
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [ASSINATURA]
        return self.app(environ, start_response)

    def __call__(self, environ, start_response):
        return self._wsgi(environ, start_response)


def host_local(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def rodar(aplicacao: Aplicacao, host: str, porta: int, abrir_navegador: bool = True):
    from waitress import serve

    endereco = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{porta}"
    print(f"NotaXML rodando em {endereco}")
    if aplicacao.cfg is None:
        print("Primeiro uso: complete a configuração no navegador.")
    elif aplicacao.gerenciador.certificado is None:
        print("Certificado bloqueado: informe a senha na tela 'Certificado'.")
    if abrir_navegador:
        threading.Timer(1.0, webbrowser.open, args=(endereco,)).start()
    serve(aplicacao, host=host, port=porta, threads=8, ident="notaxml")
