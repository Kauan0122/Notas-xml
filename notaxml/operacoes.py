"""Operações de alto nível compartilhadas pela linha de comando e pela interface web."""

import csv
import re
from collections.abc import Callable
from contextlib import contextmanager

from .armazenamento import Armazenamento
from .certificado import Certificado
from .config import Config
from .distribuicao import DistribuicaoDFe
from .erros import ErroNotaXML
from .manifestacao import DESCRICAO_EVENTO, Manifestacao
from .sincronizador import Sincronizador
from .soap import ClienteSefaz

Log = Callable[[str], None]

TIPOS_DOCUMENTO = {
    "resNFe": "resumos de NF-e",
    "procNFe": "NF-e completas (XML)",
    "resEvento": "resumos de eventos",
    "procEventoNFe": "eventos",
}


def validar_chaves(chaves: list[str]) -> list[str]:
    limpas = [re.sub(r"\D", "", c) for c in chaves]
    invalidas = [c for c in limpas if len(c) != 44]
    if invalidas:
        raise ErroNotaXML(f"Chave(s) de acesso inválida(s) (precisam de 44 dígitos): {', '.join(invalidas)}")
    return limpas


def escrever_csv(arquivo, notas):
    """Grava a lista de notas em CSV no padrão do Excel brasileiro (separador ';', vírgula decimal)."""
    escritor = csv.writer(arquivo, delimiter=";")
    escritor.writerow(["chave", "emissao", "emitente_cnpj", "emitente", "valor", "situacao", "manifestacao", "xml"])
    for n in notas:
        escritor.writerow([n["chave"], n["emissao"], n["emitente_documento"], n["emitente_nome"],
                           f"{n['valor'] or 0:.2f}".replace(".", ","), n["situacao"],
                           DESCRICAO_EVENTO.get(n["manifestacao"] or "", ""), n["arquivo_xml"] or ""])


@contextmanager
def abrir_sincronizador(cfg: Config, certificado: Certificado, log: Log = print):
    banco = Armazenamento(cfg.pasta_dados)
    try:
        with ClienteSefaz(certificado, cfg.verificar_ssl, cfg.timeout) as cliente:
            yield Sincronizador(
                DistribuicaoDFe(cliente, cfg.ambiente, cfg.cuf, cfg.documento),
                banco,
                Manifestacao(cliente, certificado, cfg.ambiente, cfg.documento),
                log=log,
            )
    finally:
        banco.fechar()


def _mostrar_manifestacao(resultados, log: Log):
    for r in resultados:
        marca = "OK  " if r.sucesso else "ERRO"
        log(f"  [{marca}] {r.chave}: {r.cstat} - {r.motivo}")


def sincronizar(sinc: Sincronizador, log: Log, ciencia: bool = False, forcar: bool = False):
    log("Consultando documentos novos na SEFAZ...")
    resumo = sinc.sincronizar(forcar=forcar)
    if resumo.bloqueado:
        log("Nada a fazer: a SEFAZ pede 1 hora de intervalo após alcançar o último NSU. "
            f"Próxima consulta liberada em {resumo.proxima_consulta.astimezone():%d/%m/%Y %H:%M}.")
    else:
        log(f"Concluído: {resumo.consultas} consulta(s), último NSU {resumo.ult_nsu}.")
        for tipo, qtd in resumo.documentos.items():
            log(f"  {qtd} {TIPOS_DOCUMENTO.get(tipo, tipo)}")
        if not resumo.total:
            log("  Nenhum documento novo.")

    if ciencia:
        pendentes = sinc.banco.chaves_sem_manifestacao()
        if pendentes:
            log(f"Enviando Ciência da Operação para {len(pendentes)} nota(s)...")
            _mostrar_manifestacao(sinc.manifestar(pendentes, "ciencia"), log)
            log("O XML completo dessas notas chegará nas próximas sincronizações (ou use 'baixar XML').")
    return resumo


def manifestar(sinc: Sincronizador, log: Log, chaves: list[str], evento: str, justificativa: str | None = None):
    log(f"Enviando manifestação para {len(chaves)} nota(s)...")
    resultados = sinc.manifestar(chaves, evento, justificativa)
    _mostrar_manifestacao(resultados, log)
    return resultados


def baixar(sinc: Sincronizador, log: Log, chaves: list[str] | None = None):
    chaves = chaves or sinc.banco.chaves_aguardando_xml()
    if not chaves:
        log("Nenhuma nota aguardando XML.")
        return
    for chave in chaves:
        try:
            ok = sinc.baixar_por_chave(chave)
            log(f"  {chave}: {'XML completo baixado' if ok else 'apenas resumo disponível (manifeste a nota)'}")
        except ErroNotaXML as exc:
            log(f"  {chave}: {exc}")
            if getattr(exc, "cstat", None) == "656":
                break
