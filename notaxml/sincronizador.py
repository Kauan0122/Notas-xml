"""Regras de negócio: puxar documentos novos da SEFAZ e guardar."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .armazenamento import Armazenamento
from .distribuicao import (
    CSTAT_CONSUMO_INDEVIDO,
    CSTAT_DOCUMENTOS_LOCALIZADOS,
    CSTAT_NENHUM_DOCUMENTO,
    DistribuicaoDFe,
)
from .erros import ErroSefaz
from .manifestacao import EVENTOS, Manifestacao, ResultadoEvento

# Limite de segurança de consultas por execução (cada consulta traz até 50 documentos).
MAX_CONSULTAS_POR_EXECUCAO = 200


@dataclass
class ResumoSincronizacao:
    documentos: dict[str, int] = field(default_factory=dict)
    consultas: int = 0
    ult_nsu: str = ""
    max_nsu: str = ""
    proxima_consulta: datetime | None = None
    bloqueado: bool = False

    @property
    def total(self) -> int:
        return sum(self.documentos.values())


class Sincronizador:
    def __init__(self, distribuicao: DistribuicaoDFe, armazenamento: Armazenamento,
                 manifestacao: Manifestacao | None = None, log: Callable[[str], None] = print):
        self.dist = distribuicao
        self.banco = armazenamento
        self.manifestacao = manifestacao
        self.log = log

    @property
    def _chave_estado(self):
        return self.dist.documento, self.dist.ambiente

    def sincronizar(self, forcar: bool = False) -> ResumoSincronizacao:
        """Consulta a SEFAZ a partir do último NSU salvo até alcançar o maxNSU.

        A SEFAZ exige aguardar 1 hora após receber "nenhum documento" (137) ou alcançar o maxNSU;
        consultas antes disso podem gerar bloqueio por consumo indevido (656).
        """
        estado = self.banco.estado(*self._chave_estado)
        resumo = ResumoSincronizacao(ult_nsu=estado.ult_nsu)
        agora = datetime.now(timezone.utc)
        if estado.proxima_consulta and estado.proxima_consulta > agora and not forcar:
            resumo.proxima_consulta = estado.proxima_consulta
            resumo.bloqueado = True
            return resumo

        ult_nsu = estado.ult_nsu
        while resumo.consultas < MAX_CONSULTAS_POR_EXECUCAO:
            ret = self.dist.consultar_nsu(ult_nsu)
            resumo.consultas += 1

            if ret.cstat == CSTAT_CONSUMO_INDEVIDO:
                resumo.proxima_consulta = self.banco.aguardar(*self._chave_estado)
                raise ErroSefaz(f"Consumo indevido (656): {ret.motivo}. Aguarde 1 hora antes de consultar de novo.",
                                ret.cstat)
            if ret.cstat not in (CSTAT_NENHUM_DOCUMENTO, CSTAT_DOCUMENTOS_LOCALIZADOS):
                raise ErroSefaz(f"SEFAZ rejeitou a consulta: {ret.cstat} - {ret.motivo}", ret.cstat)

            for doc in ret.documentos:
                self.banco.guardar(doc.tipo, doc.xml)
                resumo.documentos[doc.tipo] = resumo.documentos.get(doc.tipo, 0) + 1

            if ret.ult_nsu:
                ult_nsu = ret.ult_nsu
                self.banco.salvar_nsu(*self._chave_estado, ret.ult_nsu, ret.max_nsu)
            resumo.ult_nsu, resumo.max_nsu = ult_nsu, ret.max_nsu
            if ret.documentos:
                self.log(f"  NSU {ult_nsu} de {ret.max_nsu}: {len(ret.documentos)} documento(s)")

            if ret.cstat == CSTAT_NENHUM_DOCUMENTO or not ret.max_nsu or int(ult_nsu) >= int(ret.max_nsu):
                resumo.proxima_consulta = self.banco.aguardar(*self._chave_estado)
                break
        return resumo

    def manifestar(self, chaves: list[str], tipo: str, justificativa: str | None = None) -> list[ResultadoEvento]:
        if self.manifestacao is None:
            raise RuntimeError("Manifestação não configurada.")
        resultados = self.manifestacao.enviar(chaves, tipo, justificativa)
        for r in resultados:
            if r.sucesso:
                self.banco.registrar_manifestacao(r.chave, r.tipo or EVENTOS[tipo][0])
            if r.xml_proc:
                self.banco.guardar("procEventoNFe", r.xml_proc)
        return resultados

    def baixar_por_chave(self, chave: str) -> bool:
        """Consulta uma NF-e específica pela chave (exige manifestação prévia para trazer o XML completo)."""
        ret = self.dist.consultar_chave(chave)
        if ret.cstat == CSTAT_CONSUMO_INDEVIDO:
            self.banco.aguardar(*self._chave_estado)
            raise ErroSefaz(f"Consumo indevido (656): {ret.motivo}. Aguarde 1 hora.", ret.cstat)
        if ret.cstat != CSTAT_DOCUMENTOS_LOCALIZADOS:
            raise ErroSefaz(f"{ret.cstat} - {ret.motivo}", ret.cstat)
        completo = False
        for doc in ret.documentos:
            self.banco.guardar(doc.tipo, doc.xml)
            completo = completo or doc.tipo == "procNFe"
        return completo
