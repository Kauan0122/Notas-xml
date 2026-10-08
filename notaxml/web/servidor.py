"""Servidor web: escolhe entre a tela de configuração e o sistema completo, e troca sem reiniciar."""

import ipaddress
import secrets
import threading
import webbrowser
from pathlib import Path

from ..config import carregar_config
from ..erros import ErroNotaXML
from . import criar_app, criar_app_configuracao
from .tarefas import GerenciadorTarefas

ASSINATURA = b"notaxml"


class Aplicacao:
    """App WSGI que pode ser recarregado depois que a configuração muda."""

    def __init__(self, caminho_config: str | Path, pasta_dados_padrao: Path | None = None, desktop: bool = False):
        self.caminho_config = Path(caminho_config).resolve()
        self.pasta_dados_padrao = pasta_dados_padrao
        self.desktop = desktop
        self._chave_secreta = secrets.token_hex(32)  # a mesma entre recargas: ninguém perde a sessão
        self._trava = threading.Lock()
        self.app = None
        self.cfg = None
        self.gerenciador: GerenciadorTarefas | None = None
        self.recarregar()

    def recarregar(self, senha_certificado: str | None = None):
        with self._trava:
            anterior = self.gerenciador
            cfg, erro = None, None
            if self.caminho_config.is_file():
                try:
                    cfg = carregar_config(self.caminho_config)
                except ErroNotaXML as exc:
                    erro = str(exc)
            if cfg is None:
                self.cfg, self.gerenciador = None, None
                self.app = criar_app_configuracao(self.caminho_config, self.recarregar, self.pasta_dados_padrao, erro,
                                                  self._chave_secreta)
            else:
                gerenciador = GerenciadorTarefas(cfg)
                if gerenciador.certificado is None and senha_certificado:
                    try:
                        gerenciador.desbloquear(senha_certificado)
                    except ErroNotaXML as exc:
                        gerenciador.erro_certificado = str(exc)
                self.cfg, self.gerenciador = cfg, gerenciador
                self.app = criar_app(cfg, gerenciador, self.caminho_config, self.recarregar,
                                     self.pasta_dados_padrao, self.desktop, self._chave_secreta)
                if cfg.web.sincronizacao_automatica:
                    gerenciador.verificar_agenda()
                    gerenciador.iniciar_agendador()
            if anterior is not None:
                anterior.parar()

    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO") == "/saude":
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [ASSINATURA]
        return self.app(environ, start_response)


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
