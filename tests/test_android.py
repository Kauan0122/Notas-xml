import re
import ssl

import pytest
from werkzeug.test import Client

from notaxml import android, soap
from notaxml.web.autenticacao import COOKIE_ACESSO_LOCAL
from notaxml.web.servidor import Aplicacao

SEGREDO = "segredo-aleatorio-do-aplicativo-0123456789"


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for nome in ("NOTAXML_WEB_SENHA", "NOTAXML_WEB_SENHA_FILE", "NOTAXML_ACESSO_LOCAL"):
        monkeypatch.delenv(nome, raising=False)


def test_so_o_aplicativo_com_o_segredo_entra(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTAXML_WEB_SENHA", SEGREDO)
    monkeypatch.setenv("NOTAXML_ACESSO_LOCAL", SEGREDO)
    cliente = Client(Aplicacao(tmp_path / "config.toml"))

    # outro aplicativo do celular que alcança 127.0.0.1: sem cookie, cai no login
    r = cliente.get("/configuracao")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    cliente.set_cookie(COOKIE_ACESSO_LOCAL, "palpite-errado")
    assert cliente.get("/configuracao").status_code == 302

    # o aplicativo apresenta o segredo no cookie e entra sem digitar a senha
    cliente.set_cookie(COOKIE_ACESSO_LOCAL, SEGREDO)
    pagina = cliente.get("/configuracao")
    assert pagina.status_code == 200 and "Bem-vindo ao NotaXML" in pagina.get_data(as_text=True)
    assert 'name="acesso_rede"' not in pagina.get_data(as_text=True)  # no celular não há acesso pela rede

    cliente.delete_cookie(COOKIE_ACESSO_LOCAL)  # a sessão continua válida
    assert cliente.get("/configuracao").status_code == 200


def test_sem_token_configurado_o_cookie_nao_vale(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTAXML_WEB_SENHA", SEGREDO)
    cliente = Client(Aplicacao(tmp_path / "config.toml"))
    cliente.set_cookie(COOKIE_ACESSO_LOCAL, "")
    assert cliente.get("/configuracao").status_code == 302


def test_cookie_nao_contorna_o_login_de_quem_usa_senha_digitada(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTAXML_WEB_SENHA", "outra-senha-digitada")
    monkeypatch.setenv("NOTAXML_ACESSO_LOCAL", SEGREDO)
    cliente = Client(Aplicacao(tmp_path / "config.toml"))
    html = cliente.get("/login").get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    assert cliente.post("/login", data={"csrf": csrf, "senha": "outra-senha-digitada"}).status_code == 302


def test_autoteste_das_bibliotecas(capsys):
    assert android.autoteste() is True
    assert "NOTAXML-AUTOTESTE: ok" in capsys.readouterr().out


def test_autoteste_informa_a_falha(monkeypatch, capsys):
    import builtins

    original = builtins.__import__

    def sem_lxml(nome, *args, **kwargs):
        if nome == "lxml.etree":
            raise ImportError("sem biblioteca nativa")
        return original(nome, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sem_lxml)
    assert android.autoteste() is False
    assert "NOTAXML-AUTOTESTE: FALHA lxml.etree" in capsys.readouterr().out


def test_contexto_tls_sem_truststore_usa_as_autoridades_do_sistema(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import serialization

    from .conftest import gerar_pfx
    from notaxml.certificado import Certificado

    cert = Certificado.de_bytes(gerar_pfx(), "1234")
    with cert.arquivos_pem() as (arquivo_cert, arquivo_chave):
        monkeypatch.setitem(__import__("sys").modules, "truststore", None)  # import levanta ImportError
        contexto = soap._contexto_sistema(arquivo_cert, arquivo_chave)
    assert isinstance(contexto, ssl.SSLContext) and contexto.verify_mode == ssl.CERT_REQUIRED
    assert contexto.check_hostname is True
    assert serialization  # (importação usada só para garantir que a biblioteca está disponível)
