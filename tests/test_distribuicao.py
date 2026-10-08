from lxml import etree

from notaxml.distribuicao import interpretar_retorno, montar_pedido
from notaxml.soap import montar_envelope
from notaxml.xmlutil import NS, parse

from .conftest import CHAVE, CNPJ, proc_nfe, res_nfe, ret_dist


def test_pedido_por_nsu():
    pedido = montar_pedido(1, 35, CNPJ, ult_nsu="123")
    xml = etree.tostring(pedido).decode()
    assert xml == (
        '<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01"><tpAmb>1</tpAmb>'
        f'<cUFAutor>35</cUFAutor><CNPJ>{CNPJ}</CNPJ><distNSU><ultNSU>000000000000123</ultNSU></distNSU></distDFeInt>'
    )


def test_pedido_por_chave_e_cpf():
    pedido = montar_pedido(2, 31, "12345678901", chave=CHAVE)
    assert pedido.findtext("n:CPF", namespaces=NS) == "12345678901"
    assert pedido.findtext("n:consChNFe/n:chNFe", namespaces=NS) == CHAVE


def test_envelope_soap12():
    envelope = parse(montar_envelope(montar_pedido(1, 35, CNPJ, ult_nsu="0")))
    assert envelope.tag == "{http://www.w3.org/2003/05/soap-envelope}Envelope"


def test_interpretar_retorno_descompacta_documentos():
    ret = parse(ret_dist("138", "000000000000002", "000000000000010", [
        ("000000000000001", "resNFe_v1.01.xsd", res_nfe()),
        ("000000000000002", "procNFe_v4.00.xsd", proc_nfe()),
    ]).encode())
    r = interpretar_retorno(ret)
    assert (r.cstat, r.ult_nsu, r.max_nsu) == ("138", "000000000000002", "000000000000010")
    assert [d.tipo for d in r.documentos] == ["resNFe", "procNFe"]
    assert parse(r.documentos[1].xml).tag.endswith("nfeProc")
