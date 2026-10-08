import ssl

import requests
from lxml import etree
from requests.adapters import HTTPAdapter

from .certificado import Certificado
from .erros import ErroSefaz
from .xmlutil import parse

NS_SOAP12 = "http://www.w3.org/2003/05/soap-envelope"


def montar_envelope(conteudo: etree._Element) -> bytes:
    envelope = etree.Element(f"{{{NS_SOAP12}}}Envelope", nsmap={"soap12": NS_SOAP12})
    etree.SubElement(envelope, f"{{{NS_SOAP12}}}Body").append(conteudo)
    return etree.tostring(envelope, encoding="utf-8", xml_declaration=True)


class _AdaptadorTLS(HTTPAdapter):
    """Usa um SSLContext próprio (certificado do cliente + autoridades do sistema operacional)."""

    def __init__(self, contexto: ssl.SSLContext, **kwargs):
        self._contexto = contexto
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._contexto
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._contexto
        return super().proxy_manager_for(*args, **kwargs)


def _contexto_sistema(cert: str, chave: str) -> ssl.SSLContext | None:
    """Contexto TLS que confia nas autoridades do sistema (no Windows, inclui a ICP-Brasil)."""
    try:
        import truststore
    except ImportError:
        return None
    contexto = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    contexto.load_cert_chain(cert, chave)
    return contexto


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
        contexto = _contexto_sistema(cert, chave) if self.verificar_ssl is True else None
        if contexto is not None:
            self._sessao.mount("https://", _AdaptadorTLS(contexto))
        else:
            # cadeia informada em ca_bundle (ou verificação desligada): caminho padrão do requests
            self._sessao.cert = (cert, chave)
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
                # explícito na chamada: na sessão, REQUESTS_CA_BUNDLE do ambiente teria prioridade
                verify=self.verificar_ssl,
            )
        except requests.exceptions.SSLError as exc:
            raise ErroSefaz(
                "Falha de SSL ao conectar na SEFAZ. Verifique se o certificado é válido e, se o erro for "
                "na verificação do servidor, configure 'ca_bundle' com a cadeia ICP-Brasil (veja o README). "
                f"Detalhe: {exc}"
            ) from exc
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise ErroSefaz(
                "Não foi possível conectar à SEFAZ. Verifique a internet e se o firewall/antivírus libera o "
                f"acesso a {url.split('/')[2]}; a SEFAZ também pode estar fora do ar. Detalhe: {exc}"
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
