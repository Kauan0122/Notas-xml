import pytest

from notaxml.config import carregar_config
from notaxml.erros import ErroConfiguracao


def test_config(tmp_path, monkeypatch):
    monkeypatch.setenv("NFE_CERT_SENHA", "segredo")
    (tmp_path / "icp.pem").write_text("pem")
    arquivo = tmp_path / "config.toml"
    arquivo.write_text('[empresa]\ncnpj = "12.345.678/0001-99"\nuf = "mg"\n[certificado]\narquivo = "a.pfx"\n'
                       '[sefaz]\nambiente = "homologacao"\nca_bundle = "icp.pem"\n', encoding="utf-8")
    cfg = carregar_config(arquivo)
    assert cfg.documento == "12345678000199"
    assert cfg.cuf == 31 and cfg.ambiente == 2 and cfg.senha == "segredo"
    assert cfg.certificado == tmp_path / "a.pfx"
    assert cfg.verificar_ssl == str(tmp_path / "icp.pem")
    assert cfg.pasta_dados == tmp_path / "dados"


def test_config_cnpj_invalido(tmp_path):
    arquivo = tmp_path / "config.toml"
    arquivo.write_text('[empresa]\ncnpj = "123"\nuf = "SP"\n', encoding="utf-8")
    with pytest.raises(ErroConfiguracao):
        carregar_config(arquivo)


def test_ca_bundle_inexistente_e_recusado(tmp_path):
    arquivo = tmp_path / "config.toml"
    arquivo.write_text('[empresa]\ncnpj = "12345678000199"\nuf = "SP"\n[certificado]\narquivo = "a.pfx"\n'
                       '[sefaz]\nca_bundle = "nao-existe.pem"\n', encoding="utf-8")
    with pytest.raises(ErroConfiguracao, match="ca_bundle"):
        carregar_config(arquivo)


def test_segredos_por_variavel_e_por_arquivo(tmp_path, monkeypatch):
    from notaxml.config import segredo_do_ambiente

    monkeypatch.delenv("NOTAXML_WEB_SENHA", raising=False)
    monkeypatch.delenv("NOTAXML_WEB_SENHA_FILE", raising=False)
    assert segredo_do_ambiente("NOTAXML_WEB_SENHA") is None

    arquivo = tmp_path / "segredo.txt"
    arquivo.write_text("do-arquivo\n", encoding="utf-8")
    monkeypatch.setenv("NOTAXML_WEB_SENHA_FILE", str(arquivo))
    assert segredo_do_ambiente("NOTAXML_WEB_SENHA") == "do-arquivo"

    monkeypatch.setenv("NOTAXML_WEB_SENHA", "da-variavel")  # a variável direta tem prioridade
    assert segredo_do_ambiente("NOTAXML_WEB_SENHA") == "da-variavel"

    monkeypatch.delenv("NOTAXML_WEB_SENHA")
    monkeypatch.setenv("NOTAXML_WEB_SENHA_FILE", str(tmp_path / "nao-existe"))
    with pytest.raises(ErroConfiguracao, match="_FILE"):
        segredo_do_ambiente("NOTAXML_WEB_SENHA")
