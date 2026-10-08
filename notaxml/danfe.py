"""DANFE em PDF a partir do XML completo da NF-e (procNFe)."""

import io

from .erros import ErroNotaXML


class ErroDanfe(ErroNotaXML):
    pass


def gerar_danfe(xml: bytes, cancelada: bool = False) -> bytes:
    """Gera o PDF do DANFE. `cancelada` acrescenta a marca d'água "CANCELADA"."""
    from brazilfiscalreport.danfe import Danfe, DanfeConfig

    try:
        texto = xml.decode("utf-8-sig")
        danfe = Danfe(xml=texto, config=DanfeConfig(watermark_cancelled=cancelada))
        saida = io.BytesIO()
        danfe.output(saida)
    except Exception as exc:  # noqa: BLE001 - a biblioteca levanta tipos variados para XML inválido
        raise ErroDanfe(f"Não foi possível gerar o DANFE deste XML: {exc}") from exc
    return saida.getvalue()
