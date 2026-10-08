"""Arquivos XML no disco + índice SQLite das notas e do controle de NSU."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .xmlutil import NS, parse, texto

SITUACAO_RESUMO = {"1": "autorizada", "2": "denegada", "3": "cancelada"}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS estado (
    documento TEXT NOT NULL,
    ambiente INTEGER NOT NULL,
    ult_nsu TEXT NOT NULL DEFAULT '000000000000000',
    max_nsu TEXT,
    proxima_consulta TEXT,
    PRIMARY KEY (documento, ambiente)
);
CREATE TABLE IF NOT EXISTS notas (
    chave TEXT PRIMARY KEY,
    emitente_documento TEXT,
    emitente_nome TEXT,
    emissao TEXT,
    valor REAL,
    tipo_nf TEXT,
    situacao TEXT,
    protocolo TEXT,
    arquivo_resumo TEXT,
    arquivo_xml TEXT,
    manifestacao TEXT,
    manifestado_em TEXT,
    atualizado_em TEXT
);
CREATE TABLE IF NOT EXISTS eventos (
    chave TEXT NOT NULL,
    tipo TEXT NOT NULL,
    sequencia INTEGER NOT NULL,
    descricao TEXT,
    arquivo TEXT,
    PRIMARY KEY (chave, tipo, sequencia)
);
"""


def _agora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Estado:
    ult_nsu: str
    max_nsu: str | None
    proxima_consulta: datetime | None


class Armazenamento:
    def __init__(self, pasta: str | Path):
        self.pasta = Path(pasta)
        self.pasta_xml = self.pasta / "xml"
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.pasta / "notas.db")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(ESQUEMA)

    def fechar(self):
        self.db.close()

    # ---- controle de NSU ------------------------------------------------

    def estado(self, documento: str, ambiente: int) -> Estado:
        linha = self.db.execute(
            "SELECT ult_nsu, max_nsu, proxima_consulta FROM estado WHERE documento=? AND ambiente=?",
            (documento, ambiente),
        ).fetchone()
        if linha is None:
            return Estado("000000000000000", None, None)
        proxima = datetime.fromisoformat(linha["proxima_consulta"]) if linha["proxima_consulta"] else None
        return Estado(linha["ult_nsu"], linha["max_nsu"], proxima)

    def salvar_nsu(self, documento: str, ambiente: int, ult_nsu: str, max_nsu: str | None):
        with self.db:
            self.db.execute(
                """INSERT INTO estado (documento, ambiente, ult_nsu, max_nsu) VALUES (?, ?, ?, ?)
                   ON CONFLICT(documento, ambiente) DO UPDATE SET ult_nsu=excluded.ult_nsu, max_nsu=excluded.max_nsu""",
                (documento, ambiente, ult_nsu, max_nsu),
            )

    def aguardar(self, documento: str, ambiente: int, minutos: int = 60) -> datetime:
        proxima = _agora() + timedelta(minutes=minutos)
        with self.db:
            self.db.execute(
                """INSERT INTO estado (documento, ambiente, proxima_consulta) VALUES (?, ?, ?)
                   ON CONFLICT(documento, ambiente) DO UPDATE SET proxima_consulta=excluded.proxima_consulta""",
                (documento, ambiente, proxima.isoformat()),
            )
        return proxima

    # ---- documentos -----------------------------------------------------

    def _gravar(self, relativo: str, xml: bytes) -> str:
        destino = self.pasta_xml / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(xml)
        return str(destino.relative_to(self.pasta))

    @staticmethod
    def _pasta_mes(chave: str) -> str:
        # posições 3-6 da chave de acesso = AAMM da emissão
        return f"20{chave[2:4]}-{chave[4:6]}"

    def _upsert_nota(self, chave: str, **campos):
        campos = {k: v for k, v in campos.items() if v is not None}
        campos["atualizado_em"] = _agora().isoformat(timespec="seconds")
        colunas = ["chave", *campos]
        atualizacao = ", ".join(f"{c}=excluded.{c}" for c in campos)
        with self.db:
            self.db.execute(
                f"INSERT INTO notas ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))}) "
                f"ON CONFLICT(chave) DO UPDATE SET {atualizacao}",
                (chave, *campos.values()),
            )

    def guardar(self, tipo: str, xml: bytes) -> str | None:
        """Grava um documento recebido da SEFAZ. Devolve a chave da NF-e relacionada."""
        raiz = parse(xml)
        if tipo == "resNFe":
            return self._guardar_resumo(raiz, xml)
        if tipo == "procNFe":
            return self._guardar_nfe(raiz, xml)
        if tipo in ("procEventoNFe", "resEvento"):
            return self._guardar_evento(raiz, xml, resumo=tipo == "resEvento")
        self._gravar(f"outros/{tipo}-{_agora():%Y%m%d%H%M%S%f}.xml", xml)
        return None

    def _guardar_resumo(self, raiz, xml: bytes) -> str:
        chave = texto(raiz, "n:chNFe")
        arquivo = self._gravar(f"resumos/{chave}-resumo.xml", xml)
        self._upsert_nota(
            chave,
            emitente_documento=texto(raiz, "n:CNPJ") or texto(raiz, "n:CPF"),
            emitente_nome=texto(raiz, "n:xNome"),
            emissao=texto(raiz, "n:dhEmi"),
            valor=float(texto(raiz, "n:vNF") or 0),
            tipo_nf=texto(raiz, "n:tpNF"),
            situacao=SITUACAO_RESUMO.get(texto(raiz, "n:cSitNFe") or ""),
            protocolo=texto(raiz, "n:nProt"),
            arquivo_resumo=arquivo,
        )
        return chave

    def _guardar_nfe(self, raiz, xml: bytes) -> str:
        inf = raiz.find(".//n:infNFe", namespaces=NS)
        chave = texto(raiz, ".//n:protNFe/n:infProt/n:chNFe") or (inf.get("Id", "")[3:] if inf is not None else "")
        arquivo = self._gravar(f"nfe/{self._pasta_mes(chave)}/{chave}-nfe.xml", xml)
        cstat = texto(raiz, ".//n:protNFe/n:infProt/n:cStat")
        self._upsert_nota(
            chave,
            emitente_documento=texto(inf, "n:emit/n:CNPJ") or texto(inf, "n:emit/n:CPF"),
            emitente_nome=texto(inf, "n:emit/n:xNome"),
            emissao=texto(inf, "n:ide/n:dhEmi") or texto(inf, "n:ide/n:dEmi"),
            valor=float(texto(inf, "n:total/n:ICMSTot/n:vNF") or 0),
            tipo_nf=texto(inf, "n:ide/n:tpNF"),
            situacao="autorizada" if cstat in ("100", "150") else ("denegada" if cstat else None),
            protocolo=texto(raiz, ".//n:protNFe/n:infProt/n:nProt"),
            arquivo_xml=arquivo,
        )
        return chave

    def _guardar_evento(self, raiz, xml: bytes, resumo: bool) -> str:
        base = raiz if resumo else raiz.find(".//n:evento/n:infEvento", namespaces=NS)
        chave = texto(base, "n:chNFe")
        tipo = texto(base, "n:tpEvento")
        sequencia = int(texto(base, "n:nSeqEvento") or 1)
        descricao = texto(base, "n:xEvento") or texto(base, "n:detEvento/n:descEvento")
        sufixo = "-resumo" if resumo else ""
        arquivo = self._gravar(f"eventos/{chave}-{tipo}-{sequencia:02d}{sufixo}.xml", xml)
        with self.db:
            if resumo:
                # não sobrescreve o XML completo do evento com o resumo
                self.db.execute(
                    "INSERT OR IGNORE INTO eventos (chave, tipo, sequencia, descricao, arquivo) VALUES (?, ?, ?, ?, ?)",
                    (chave, tipo, sequencia, descricao, arquivo),
                )
            else:
                self.db.execute(
                    "INSERT OR REPLACE INTO eventos (chave, tipo, sequencia, descricao, arquivo) VALUES (?, ?, ?, ?, ?)",
                    (chave, tipo, sequencia, descricao, arquivo),
                )
        if tipo in ("110111", "110112"):  # cancelamento
            self._upsert_nota(chave, situacao="cancelada")
        return chave

    # ---- manifestação ---------------------------------------------------

    def registrar_manifestacao(self, chave: str, tipo_evento: str):
        self._upsert_nota(chave, manifestacao=tipo_evento, manifestado_em=_agora().isoformat(timespec="seconds"))

    def chaves_sem_manifestacao(self) -> list[str]:
        linhas = self.db.execute(
            "SELECT chave FROM notas WHERE arquivo_xml IS NULL AND manifestacao IS NULL "
            "AND COALESCE(situacao, '') NOT IN ('cancelada', 'denegada') ORDER BY emissao"
        )
        return [linha["chave"] for linha in linhas]

    def chaves_aguardando_xml(self) -> list[str]:
        linhas = self.db.execute(
            "SELECT chave FROM notas WHERE arquivo_xml IS NULL AND manifestacao IN ('210210', '210200') "
            "AND COALESCE(situacao, '') NOT IN ('cancelada', 'denegada') ORDER BY emissao"
        )
        return [linha["chave"] for linha in linhas]

    def listar(self, somente_pendentes: bool = False) -> list[sqlite3.Row]:
        filtro = "WHERE arquivo_xml IS NULL" if somente_pendentes else ""
        return self.db.execute(f"SELECT * FROM notas {filtro} ORDER BY emissao DESC").fetchall()
