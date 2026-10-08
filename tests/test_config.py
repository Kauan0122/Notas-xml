import pytest

from notaxml.config import carregar_config
from notaxml.erros import ErroConfiguracao


def test_config(tmp_path, monkeypatch):
    monkeypatch.setenv("NFE_CERT_SENHA", "segredo")
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
