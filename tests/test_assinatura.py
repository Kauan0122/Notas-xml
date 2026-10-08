import base64
import hashlib
import shutil
import subprocess

import copy

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from notaxml.assinatura import NS_DSIG
from notaxml.manifestacao import montar_evento, montar_lote
from notaxml.xmlutil import NS, parse

from .conftest import CHAVE, CNPJ


def _verificar(evento_xml: bytes, cert):
    """Verifica a assinatura de forma independente após serializar e reler o XML."""
    evento = parse(evento_xml).find(".//n:evento", namespaces=NS)
    inf = evento.find("n:infEvento", namespaces=NS)
    sig = evento.find(f"{{{NS_DSIG}}}Signature")
    signed_info = sig.find(f"{{{NS_DSIG}}}SignedInfo")
    digest = sig.findtext(f".//{{{NS_DSIG}}}DigestValue")
    assert digest == base64.b64encode(hashlib.sha1(etree.tostring(copy.deepcopy(inf), method="c14n")).digest()).decode()
    valor = base64.b64decode(sig.findtext(f"{{{NS_DSIG}}}SignatureValue"))
    cert.certificado.public_key().verify(valor, etree.tostring(copy.deepcopy(signed_info), method="c14n"),
                                         padding.PKCS1v15(), hashes.SHA1())


def test_evento_ciencia_assinado(certificado):
    evento = montar_evento(certificado, 1, CNPJ, CHAVE, "ciencia")
    xml = etree.tostring(montar_lote([evento], "1"))
    _verificar(xml, certificado)

    inf = parse(xml).find(".//n:infEvento", namespaces=NS)
    assert inf.get("Id") == f"ID210210{CHAVE}01"
    assert inf.findtext("n:cOrgao", namespaces=NS) == "91"
    assert inf.findtext("n:detEvento/n:descEvento", namespaces=NS) == "Ciencia da Operacao"
    assert b"\n" not in xml  # SEFAZ rejeita espaços/quebras entre tags


def test_nao_realizada_exige_justificativa(certificado):
    with pytest.raises(ValueError):
        montar_evento(certificado, 1, CNPJ, CHAVE, "nao-realizada", "curta")
    evento = montar_evento(certificado, 1, CNPJ, CHAVE, "nao-realizada", "Mercadoria nunca foi entregue")
    assert evento.findtext(".//n:xJust", namespaces=NS) == "Mercadoria nunca foi entregue"


@pytest.mark.skipif(not shutil.which("xmlsec1"), reason="xmlsec1 não instalado")
def test_assinatura_validada_pelo_xmlsec(certificado, tmp_path):
    evento = montar_evento(certificado, 1, CNPJ, CHAVE, "ciencia")
    arquivo = tmp_path / "evento.xml"
    arquivo.write_bytes(etree.tostring(evento))
    pem = tmp_path / "cert.pem"
    from cryptography.hazmat.primitives.serialization import Encoding
    pem.write_bytes(certificado.certificado.public_bytes(Encoding.PEM))
    r = subprocess.run(["xmlsec1", "--verify", "--insecure", "--id-attr:Id", "infEvento", "--pubkey-cert-pem", str(pem), str(arquivo)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
