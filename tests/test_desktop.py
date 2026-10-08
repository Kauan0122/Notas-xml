import re
import sys

import pytest
from werkzeug.test import Client

from notaxml import desktop
from notaxml.config import ler_config_web, ler_secoes, salvar_config
from notaxml.erros import ErroNotaXML
from notaxml.web.servidor import Aplicacao


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for nome in ("NOTAXML_WEB_SENHA", "NOTAXML_WEB_SENHA_FILE"):
        monkeypatch.delenv(nome, raising=False)


def test_modo_servidor_define_senha_e_abre_para_a_rede(tmp_path):
    config = tmp_path / "config.toml"
    desktop.configurar_servidor(config, pedir_senha=lambda: "senha-bem-longa")

    web = ler_config_web(config)
    assert web.host == "0.0.0.0" and web.senha == "senha-bem-longa"
    if sys.platform != "win32":  # no Windows ela é criptografada pelo cofre do sistema
        assert ler_secoes(config)["web"]["senha"] == "senha-bem-longa"


def test_modo_servidor_nao_pede_senha_de_novo_e_preserva_a_configuracao(tmp_path):
    config = tmp_path / "config.toml"
    salvar_config(config, {"empresa": {"cnpj": "11222333000181", "uf": "SP"},
                           "certificado": {"arquivo": "certificado.pfx"},
                           "web": {"senha": "ja-definida-123", "porta": 8123, "sincronizacao_automatica": True}})

    def nao_deveria_pedir():
        raise AssertionError("pediu a senha de novo")

    desktop.configurar_servidor(config, pedir_senha=nao_deveria_pedir)
    secoes = ler_secoes(config)
    assert secoes["empresa"]["cnpj"] == "11222333000181"
    assert secoes["web"]["porta"] == 8123 and secoes["web"]["host"] == "0.0.0.0"
    assert secoes["web"]["sincronizacao_automatica"] is True


def test_respeita_host_ja_configurado(tmp_path):
    config = tmp_path / "config.toml"
    salvar_config(config, {"web": {"host": "192.168.0.50", "senha": "senha-bem-longa"}})
    desktop.configurar_servidor(config, pedir_senha=lambda: "x")
    assert ler_config_web(config).host == "192.168.0.50"


def test_sem_terminal_nao_consegue_pedir_a_senha(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    with pytest.raises(ErroNotaXML, match="senha de acesso"):
        desktop._pedir_senha()


def test_primeiro_uso_em_modo_servidor_exige_login_e_nao_mostra_erro(tmp_path):
    config = tmp_path / "config.toml"
    desktop.configurar_servidor(config, pedir_senha=lambda: "senha-bem-longa")  # config só com [web]
    cliente = Client(Aplicacao(config))

    r = cliente.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    html = cliente.get("/login").get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    assert cliente.post("/login", data={"csrf": csrf, "senha": "senha-bem-longa"}).status_code == 302

    pagina = cliente.get("/configuracao").get_data(as_text=True)
    assert "Bem-vindo ao NotaXML" in pagina and "Não foi possível ler a configuração" not in pagina


def test_argumentos():
    assert desktop._argumentos([]).servidor is False
    args = desktop._argumentos(["--servidor", "--redefinir-senha"])
    assert args.servidor and args.redefinir_senha


def test_porta_livre_e_escolha(monkeypatch):
    import socket
    ocupada = socket.socket()
    ocupada.bind(("127.0.0.1", 0))
    porta = ocupada.getsockname()[1]
    try:
        assert desktop._porta_livre(porta) is False
        escolhida = desktop._escolher_porta(porta)
        assert escolhida is not None and escolhida != porta  # pula para a próxima livre
    finally:
        ocupada.close()
