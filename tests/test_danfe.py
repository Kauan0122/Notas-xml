import pytest

from notaxml.danfe import ErroDanfe, gerar_danfe

from .nfe_exemplo import CHAVE_COMPLETA, nfe_completa


def test_nfe_exemplo_tem_chave_valida():
    assert len(CHAVE_COMPLETA) == 44 and CHAVE_COMPLETA.isdigit()


def test_gera_pdf():
    pdf = gerar_danfe(nfe_completa().encode())
    assert pdf.startswith(b"%PDF") and len(pdf) > 3000


def test_marca_dagua_de_cancelada_altera_o_pdf():
    xml = nfe_completa().encode()
    assert gerar_danfe(xml, cancelada=True) != gerar_danfe(xml, cancelada=False)


def test_aceita_xml_com_bom():
    assert gerar_danfe(b"\xef\xbb\xbf" + nfe_completa().encode()).startswith(b"%PDF")


@pytest.mark.parametrize("lixo", [b"", b"isto nao e xml", b"<resNFe xmlns='http://www.portalfiscal.inf.br/nfe'/>"])
def test_xml_invalido_gera_erro_amigavel(lixo):
    with pytest.raises(ErroDanfe, match="Não foi possível gerar o DANFE"):
        gerar_danfe(lixo)
