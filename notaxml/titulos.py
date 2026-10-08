"""Contas a pagar: títulos (parcelas) vindos das duplicatas das NF-e de compra, ou lançados à mão."""

import csv
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from lxml import etree

from .erros import ErroNotaXML
from .xmlutil import NS, texto

SITUACOES = ("aberto", "pago", "cancelado")


class ErroTitulo(ErroNotaXML):
    pass


@dataclass
class Duplicata:
    parcela: str
    vencimento: str  # AAAA-MM-DD
    valor: float


def ler_duplicatas(inf: etree._Element) -> list[Duplicata]:
    """Parcelas (cobr/dup) de uma infNFe. Parcelas sem vencimento ou valor (pagamento à vista) são ignoradas."""
    duplicatas, usados = [], set()
    for posicao, dup in enumerate(inf.iterfind("n:cobr/n:dup", namespaces=NS), start=1):
        vencimento, valor = texto(dup, "n:dVenc"), texto(dup, "n:vDup")
        if not vencimento or valor is None:
            continue
        try:
            date.fromisoformat(vencimento)
            numero = float(Decimal(valor))
        except (ValueError, InvalidOperation):
            continue
        parcela = texto(dup, "n:nDup") or str(posicao)
        while parcela in usados:  # fornecedor repetiu o número da parcela
            parcela += f"-{posicao}"
        usados.add(parcela)
        duplicatas.append(Duplicata(parcela, vencimento, numero))
    return duplicatas


def ler_valor(entrada: str) -> float:
    """Valor digitado no formato brasileiro ("1.234,56") ou simples ("1234.56")."""
    limpo = re.sub(r"[^\d,.\-]", "", entrada or "")
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(limpo)
    except InvalidOperation:
        raise ErroTitulo("Valor inválido. Use, por exemplo, 1.234,56.") from None
    if valor <= 0 or valor > Decimal("99999999.99"):
        raise ErroTitulo("O valor precisa ser maior que zero.")
    return float(round(valor, 2))


def ler_data(entrada: str, rotulo: str = "data") -> str:
    try:
        return date.fromisoformat((entrada or "").strip()).isoformat()
    except ValueError:
        raise ErroTitulo(f"Informe a {rotulo} no formato dia/mês/ano.") from None


@dataclass
class FiltroTitulos:
    situacao: str = ""  # aberto, pago, cancelado ("" = todas)
    texto: str = ""  # fornecedor, CNPJ, número da nota ou observação
    de: str = ""  # vencimento a partir de AAAA-MM-DD
    ate: str = ""
    ids: list[int] = field(default_factory=list)

    def sql(self) -> tuple[str, list]:
        condicoes, params = [], []
        if self.situacao in SITUACOES:
            condicoes.append("t.situacao = ?")
            params.append(self.situacao)
        if self.texto:
            condicoes.append("(n.emitente_nome LIKE ? OR n.emitente_documento LIKE ? OR n.numero LIKE ? "
                             "OR t.observacao LIKE ? OR t.chave LIKE ?)")
            params += [f"%{self.texto}%"] * 5
        if self.de:
            condicoes.append("t.vencimento >= ?")
            params.append(self.de)
        if self.ate:
            condicoes.append("t.vencimento <= ?")
            params.append(self.ate)
        if self.ids:
            condicoes.append(f"t.id IN ({', '.join('?' * len(self.ids))})")
            params += self.ids
        return ("WHERE " + " AND ".join(condicoes)) if condicoes else "", params


@dataclass
class Faixa:
    quantidade: int = 0
    valor: float = 0.0


@dataclass
class ResumoTitulos:
    vencidos: Faixa = field(default_factory=Faixa)
    hoje: Faixa = field(default_factory=Faixa)
    proximos_7_dias: Faixa = field(default_factory=Faixa)
    proximos_30_dias: Faixa = field(default_factory=Faixa)
    total_aberto: Faixa = field(default_factory=Faixa)

    @property
    def atencao(self) -> int:
        """Quantos títulos pedem atenção agora (vencidos ou vencendo hoje)."""
        return self.vencidos.quantidade + self.hoje.quantidade


def classificar(vencimento: str, hoje: date) -> str:
    """vencido, hoje, 7dias, 30dias ou depois."""
    dia = date.fromisoformat(vencimento)
    if dia < hoje:
        return "vencido"
    if dia == hoje:
        return "hoje"
    if dia <= hoje + timedelta(days=7):
        return "7dias"
    if dia <= hoje + timedelta(days=30):
        return "30dias"
    return "depois"


def escrever_csv(arquivo, titulos):
    escritor = csv.writer(arquivo, delimiter=";")
    escritor.writerow(["fornecedor", "cnpj", "nota", "parcela", "vencimento", "valor", "situacao", "pago_em",
                       "observacao", "chave"])
    for t in titulos:
        nota = f"{t['numero']}/{t['serie']}" if t["numero"] and t["serie"] else (t["numero"] or "")
        escritor.writerow([t["emitente_nome"] or "", t["emitente_documento"] or "", nota, t["parcela"],
                           date.fromisoformat(t["vencimento"]).strftime("%d/%m/%Y"),
                           f"{t['valor']:.2f}".replace(".", ","), t["situacao"],
                           date.fromisoformat(t["pago_em"]).strftime("%d/%m/%Y") if t["pago_em"] else "",
                           t["observacao"] or "", t["chave"]])
