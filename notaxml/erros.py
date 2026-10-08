class ErroNotaXML(Exception):
    """Erro base da aplicação."""


class ErroConfiguracao(ErroNotaXML):
    pass


class ErroCertificado(ErroNotaXML):
    pass


class ErroSefaz(ErroNotaXML):
    """Falha de comunicação ou rejeição retornada pela SEFAZ."""

    def __init__(self, mensagem: str, cstat: str | None = None):
        super().__init__(mensagem)
        self.cstat = cstat
