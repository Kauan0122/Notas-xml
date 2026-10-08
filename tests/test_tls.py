"""Conexão TLS mútua contra um servidor local que exige certificado do cliente."""

import datetime
import http.server
import ssl
import sys
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from lxml import etree

from notaxml.certificado import Certificado
from notaxml.erros import ErroSefaz
from notaxml.soap import ClienteSefaz


def _emitir(cn, emissor=None, ca=False, servidor=False, cliente=False):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, cn)])
    chave_emissor, cert_emissor = emissor or (chave, None)
    agora = datetime.datetime.now(datetime.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(nome)
         .issuer_name(cert_emissor.subject if cert_emissor else nome).public_key(chave.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(agora - datetime.timedelta(days=1)).not_valid_after(agora + datetime.timedelta(days=30))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave.public_key()), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(chave_emissor.public_key()),
                        critical=False))
    if ca:
        b = b.add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
    if servidor:
        b = (b.add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
             .add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False))
    if cliente:
        b = b.add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
    return chave, b.sign(chave_emissor, hashes.SHA256())


def _pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("tls")
    ac = _emitir("AC de teste", ca=True)
    chave_srv, cert_srv = _emitir("localhost", ac, servidor=True)
    chave_cli, cert_cli = _emitir("EMPRESA:11222333000181", ac, cliente=True)
    (pasta / "srv.pem").write_bytes(_pem(cert_srv))
    (pasta / "srv.key").write_bytes(chave_srv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (pasta / "ac.pem").write_bytes(_pem(ac[1]))

    class Tratador(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            titular = self.connection.getpeercert()["subject"][0][0][1]
            corpo = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
                     f"<ok>{titular}</ok></s:Body></s:Envelope>").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Tratador)
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.load_cert_chain(pasta / "srv.pem", pasta / "srv.key")
    contexto.verify_mode = ssl.CERT_REQUIRED
    contexto.load_verify_locations(pasta / "ac.pem")
    srv.socket = contexto.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"https://localhost:{srv.server_port}/", "ac": str(pasta / "ac.pem"),
           "cert": Certificado(chave_cli, cert_cli, [])}
    srv.shutdown()


@pytest.fixture(autouse=True)
def sem_proxy(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "")  # o ca_bundle configurado precisa prevalecer


def test_ca_bundle_e_certificado_do_cliente(servidor):
    with ClienteSefaz(servidor["cert"], servidor["ac"]) as cliente:
        resposta = cliente.chamar(servidor["url"], "acao", etree.Element("x"))
    assert resposta.text == "EMPRESA:11222333000181"


def test_servidor_desconhecido_e_recusado(servidor):
    with pytest.raises(ErroSefaz, match="SSL"):
        with ClienteSefaz(servidor["cert"], True) as cliente:
            cliente.chamar(servidor["url"], "acao", etree.Element("x"))


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows o repositório do sistema não lê SSL_CERT_FILE")
def test_autoridades_do_sistema(servidor, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", servidor["ac"])
    with ClienteSefaz(servidor["cert"], True) as cliente:
        assert cliente.chamar(servidor["url"], "acao", etree.Element("x")).text == "EMPRESA:11222333000181"
