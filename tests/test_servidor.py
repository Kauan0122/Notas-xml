import re

import pytest
from werkzeug.test import Client

from notaxml.web.autenticacao import BLOQUEIO_SEGUNDOS, MAX_FALHAS, LimitadorLogin
from notaxml.web.servidor import Aplicacao, chave_de_sessao


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for nome in ("NOTAXML_WEB_SENHA", "NOTAXML_WEB_SENHA_FILE", "NOTAXML_HTTPS", "NOTAXML_PROXY"):
        monkeypatch.delenv(nome, raising=False)


def _de(app, ip):
    """Cliente de teste cujas requisições chegam do endereço `ip`."""
    def wsgi(environ, start_response):
        environ["REMOTE_ADDR"] = ip
        return app(environ, start_response)
    return Client(wsgi)


def _entrar(cliente, senha, **cabecalhos):
    html = cliente.get("/login", headers=cabecalhos).get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    return cliente.post("/login", data={"csrf": csrf, "senha": senha}, headers=cabecalhos)


def test_tela_de_primeiro_uso_exige_a_senha_de_acesso(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTAXML_WEB_SENHA", "rede-interna")
    app = Aplicacao(tmp_path / "config.toml")
    cliente = Client(app)

    r = cliente.get("/configuracao")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    r = cliente.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]  # direto para o login, sem passar pela configuração
    assert cliente.get("/saude").get_data() == b"notaxml"  # verificação de saúde não exige login

    assert _entrar(cliente, "errada").status_code == 200
    r = _entrar(cliente, "rede-interna")
    assert r.status_code == 302 and r.headers["Location"].endswith("/configuracao")
    assert "Bem-vindo ao NotaXML" in cliente.get("/configuracao").get_data(as_text=True)


def test_bloqueia_apos_varias_senhas_erradas(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTAXML_WEB_SENHA", "certa")
    cliente = _de(Aplicacao(tmp_path / "config.toml"), "10.0.0.5")
    for _ in range(MAX_FALHAS):
        assert _entrar(cliente, "errada").status_code == 200
    r = _entrar(cliente, "certa")  # mesmo com a senha certa, está bloqueado
    assert r.status_code == 429 and "Muitas tentativas" in r.get_data(as_text=True)

    outro = _de(Aplicacao(tmp_path / "config.toml"), "10.0.0.9")
    assert _entrar(outro, "certa").status_code == 302  # outro computador não é afetado


def test_limitador_libera_depois_do_prazo():
    agora = [1000.0]
    limitador = LimitadorLogin(relogio=lambda: agora[0])
    for _ in range(MAX_FALHAS):
        limitador.registrar_falha("a")
    assert limitador.segundos_de_bloqueio("a") > 0
    agora[0] += BLOQUEIO_SEGUNDOS + 1
    assert limitador.segundos_de_bloqueio("a") == 0
    limitador.registrar_falha("a")
    assert limitador.segundos_de_bloqueio("a") == 0  # contagem recomeçou


def test_sessao_sobrevive_ao_reinicio(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTAXML_WEB_SENHA", "certa")
    primeiro = Client(Aplicacao(tmp_path / "config.toml"))
    assert _entrar(primeiro, "certa").status_code == 302

    reiniciado = Aplicacao(tmp_path / "config.toml")  # processo novo, mesma pasta
    primeiro._use_cookies = True
    primeiro.application = reiniciado
    assert primeiro.get("/configuracao").status_code == 200  # continua logado

    chave = chave_de_sessao(tmp_path)
    assert len(chave) == 64 and (tmp_path / "chave_sessao").read_text().strip() == chave


def test_cookie_de_sessao_seguro(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTAXML_WEB_SENHA", "certa")
    monkeypatch.setenv("NOTAXML_HTTPS", "1")
    cliente = Client(Aplicacao(tmp_path / "config.toml"))
    r = _entrar(cliente, "certa")
    cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie


def test_ip_do_proxy_so_vale_quando_configurado(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTAXML_WEB_SENHA", "certa")

    # sem proxy configurado, o cabeçalho X-Forwarded-For é ignorado (não dá para burlar o bloqueio)
    app = Aplicacao(tmp_path / "a" / "config.toml")
    cliente = _de(app, "10.0.0.5")
    for i in range(MAX_FALHAS):
        _entrar(cliente, "errada", **{"X-Forwarded-For": f"9.9.9.{i}"})
    assert _entrar(cliente, "certa", **{"X-Forwarded-For": "8.8.8.8"}).status_code == 429

    # atrás de um proxy confiável, cada máquina da rede é contada separadamente
    monkeypatch.setenv("NOTAXML_PROXY", "1")
    app = Aplicacao(tmp_path / "b" / "config.toml")
    cliente = _de(app, "172.18.0.2")
    for _ in range(MAX_FALHAS):
        _entrar(cliente, "errada", **{"X-Forwarded-For": "192.168.0.10"})
    assert _entrar(cliente, "certa", **{"X-Forwarded-For": "192.168.0.10"}).status_code == 429
    assert _entrar(cliente, "certa", **{"X-Forwarded-For": "192.168.0.11"}).status_code == 302
