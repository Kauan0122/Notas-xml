import io
import re
import sys

import pytest

from notaxml import segredo
from notaxml.config import carregar_config, ler_secoes, salvar_config
from notaxml.documentos import cnpj_valido, cpf_valido
from notaxml.web.servidor import Aplicacao

from .conftest import gerar_pfx

CNPJ_VALIDO = "11222333000181"


@pytest.fixture
def aplicacao(tmp_path):
    app = Aplicacao(tmp_path / "config" / "config.toml", pasta_dados_padrao=tmp_path / "xmls")
    yield app
    if app.gerenciador:
        app.gerenciador.parar()


def _cliente(aplicacao):
    from werkzeug.test import Client
    return Client(aplicacao)


def _csrf(cliente, caminho="/configuracao"):
    html = cliente.get(caminho).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def _enviar(cliente, **campos):
    dados = {"csrf": _csrf(cliente), "uf": "SP", "ambiente": "producao", **campos}
    return cliente.post("/configuracao", data=dados, content_type="multipart/form-data")


def test_validacao_de_documentos():
    assert cnpj_valido("11.222.333/0001-81") and not cnpj_valido("11.222.333/0001-82")
    assert cpf_valido("529.982.247-25") and not cpf_valido("111.111.111-11")


def test_primeiro_uso_redireciona_para_configuracao(aplicacao):
    cliente = _cliente(aplicacao)
    r = cliente.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/configuracao")
    assert "Bem-vindo ao NotaXML" in cliente.get("/configuracao").get_data(as_text=True)
    assert cliente.get("/saude").get_data() == b"notaxml"


def test_configuracao_completa_libera_o_sistema(aplicacao, tmp_path):
    cliente = _cliente(aplicacao)
    pfx = gerar_pfx(CNPJ_VALIDO)

    r = _enviar(cliente, certificado=(io.BytesIO(pfx), "empresa.pfx"), senha="errada")
    assert "senha incorreta" in r.get_data(as_text=True)
    assert aplicacao.cfg is None

    # CNPJ em branco: vem do certificado
    r = _enviar(cliente, certificado=(io.BytesIO(pfx), "empresa.pfx"), senha="1234",
                sincronizacao_automatica="", ciencia_automatica="1")
    assert r.status_code == 302
    assert aplicacao.cfg is not None and aplicacao.cfg.documento == CNPJ_VALIDO
    assert aplicacao.gerenciador.certificado is not None  # desbloqueado com a senha digitada
    assert aplicacao.cfg.pasta_dados == tmp_path / "xmls"
    assert aplicacao.cfg.ciencia_automatica is True

    secoes = ler_secoes(aplicacao.caminho_config)
    assert "senha" not in secoes["certificado"] or secoes["certificado"]["senha"].startswith("dpapi:")
    assert (aplicacao.caminho_config.parent / "certificado.pfx").read_bytes() == pfx

    html = cliente.get("/").get_data(as_text=True)
    assert "Notas recebidas" in html and "Configurações" in html
    assert "Configuração salva" in html  # a sessão sobrevive à troca de app


def test_certificado_de_outra_empresa_e_recusado(aplicacao):
    r = _enviar(_cliente(aplicacao), certificado=(io.BytesIO(gerar_pfx(CNPJ_VALIDO)), "a.pfx"), senha="1234",
                cnpj="04.252.011/0001-10")
    assert "outra empresa" in r.get_data(as_text=True) and aplicacao.cfg is None


def test_certificado_vencido_e_recusado(aplicacao):
    r = _enviar(_cliente(aplicacao), certificado=(io.BytesIO(gerar_pfx(CNPJ_VALIDO, validade_dias=-1)), "a.pfx"),
                senha="1234")
    assert "venceu" in r.get_data(as_text=True)


def test_alterar_configuracao_mantem_certificado(aplicacao):
    cliente = _cliente(aplicacao)
    _enviar(cliente, certificado=(io.BytesIO(gerar_pfx(CNPJ_VALIDO)), "a.pfx"), senha="1234")
    r = _enviar(cliente, uf="MG")
    assert r.status_code == 302
    assert aplicacao.cfg.uf == "MG" and aplicacao.cfg.certificado.is_file()


def test_config_invalida_volta_para_tela_de_configuracao(tmp_path):
    caminho = tmp_path / "config.toml"
    caminho.write_text("isto não é toml [", encoding="utf-8")
    app = Aplicacao(caminho)
    html = _cliente(app).get("/configuracao").get_data(as_text=True)
    assert "Não foi possível ler a configuração" in html


def test_salvar_config_escapa_caminhos_windows(tmp_path):
    caminho = tmp_path / "config.toml"
    salvar_config(caminho, {"empresa": {"cnpj": CNPJ_VALIDO, "uf": "SP"},
                            "certificado": {"arquivo": "certificado.pfx"},
                            "armazenamento": {"pasta": r"C:\Users\José\Documents\NotaXML"}})
    assert ler_secoes(caminho)["armazenamento"]["pasta"] == r"C:\Users\José\Documents\NotaXML"
    assert carregar_config(caminho).documento == CNPJ_VALIDO


@pytest.mark.skipif(sys.platform != "win32", reason="cofre de senhas do Windows (DPAPI)")
def test_segredo_dpapi_ida_e_volta(tmp_path):
    protegido = segredo.proteger("senha com acentuação ç")
    assert protegido.startswith("dpapi:") and "senha" not in protegido
    assert segredo.revelar(protegido) == "senha com acentuação ç"

    caminho = tmp_path / "config.toml"
    salvar_config(caminho, {"empresa": {"cnpj": CNPJ_VALIDO, "uf": "SP"},
                            "certificado": {"arquivo": "c.pfx", "senha": protegido}})
    assert carregar_config(caminho).senha == "senha com acentuação ç"


def test_segredo_fora_do_windows_nao_quebra(tmp_path, monkeypatch):
    monkeypatch.setattr(segredo, "disponivel", lambda: False)
    caminho = tmp_path / "config.toml"
    salvar_config(caminho, {"empresa": {"cnpj": CNPJ_VALIDO, "uf": "SP"},
                            "certificado": {"arquivo": "c.pfx", "senha": "dpapi:AAAA"}})
    assert carregar_config(caminho).senha is None  # a interface pede a senha


@pytest.mark.skipif(sys.platform != "win32", reason="cofre de senhas do Windows (DPAPI)")
def test_senha_de_acesso_web_pode_ficar_no_cofre_do_windows(tmp_path):
    from notaxml.config import ler_config_web

    caminho = tmp_path / "config.toml"
    salvar_config(caminho, {"web": {"senha": segredo.proteger("senha-de-acesso")}})
    assert ler_config_web(caminho).senha == "senha-de-acesso"
