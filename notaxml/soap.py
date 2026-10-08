import requests
from lxml import etree

from .certificado import Certificado
from .erros import ErroSefaz
from .xmlutil import parse

NS_SOAP12 = "http://www.w3.org/2003/05/soap-envelope"


def montar_envelope(conteudo: etree._Element) -> bytes:
    envelope = etree.Element(f"{{{NS_SOAP12}}}Envelope", nsmap={"soap12": NS_SOAP12})
    etree.SubElement(envelope, f"{{{NS_SOAP12}}}Body").append(conteudo)
    return etree.tostring(envelope, encoding="utf-8", xml_declaration=True)


class ClienteSefaz:
    """Cliente SOAP 1.2 com TLS mútuo usando o certificado A1. Use como context manager."""

    def __init__(self, certificado: Certificado, verificar_ssl: bool | str = True, timeout: int = 60):
        self.certificado = certificado
        self.verificar_ssl = verificar_ssl
        self.timeout = timeout
        self._pem = None
        self._sessao: requests.Session | None = None

    def __enter__(self):
        self._pem = self.certificado.arquivos_pem()
        cert, chave = self._pem.__enter__()
        self._sessao = requests.Session()
        self._sessao.cert = (cert, chave)
        self._sessao.verify = self.verificar_ssl
        return self

    def __exit__(self, *exc):
        if self._sessao is not None:
            self._sessao.close()
        if self._pem is not None:
            self._pem.__exit__(*exc)

    def chamar(self, url: str, acao: str, conteudo: etree._Element) -> etree._Element:
        """Envia `conteudo` dentro do Body e devolve o primeiro elemento do Body da resposta."""
        if self._sessao is None:
            raise RuntimeError("Use ClienteSefaz dentro de um bloco 'with'.")
        try:
            resposta = self._sessao.post(
                url,
                data=montar_envelope(conteudo),
                headers={"Content-Type": f'application/soap+xml; charset=utf-8; action="{acao}"'},
                timeout=self.timeout,
            )
        except requests.exceptions.SSLError as exc:
            raise ErroSefaz(
                "Falha de SSL ao conectar na SEFAZ. Verifique se o certificado é válido e, se o erro for "
                "na verificação do servidor, configure 'ca_bundle' com a cadeia ICP-Brasil (veja o README). "
                f"Detalhe: {exc}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ErroSefaz(f"Falha de comunicação com a SEFAZ: {exc}") from exc

        try:
            raiz = parse(resposta.content)
        except etree.XMLSyntaxError as exc:
            raise ErroSefaz(f"Resposta inválida da SEFAZ (HTTP {resposta.status_code}): {resposta.text[:500]}") from exc

        corpo = raiz.find(f"{{{NS_SOAP12}}}Body")
        if corpo is None or len(corpo) == 0:
            raise ErroSefaz(f"Resposta SOAP sem corpo (HTTP {resposta.status_code}).")
        fault = corpo.find(f"{{{NS_SOAP12}}}Fault")
        if fault is not None:
            motivo = " ".join(t.strip() for t in fault.itertext() if t.strip())
            raise ErroSefaz(f"SOAP Fault da SEFAZ: {motivo}")
        return corpo[0]
