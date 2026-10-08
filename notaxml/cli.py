import argparse
import csv
import getpass
import re
import sys
from contextlib import contextmanager

from .armazenamento import Armazenamento
from .certificado import Certificado
from .config import Config, carregar_config
from .distribuicao import DistribuicaoDFe
from .erros import ErroNotaXML
from .manifestacao import DESCRICAO_EVENTO, EVENTOS, Manifestacao
from .sincronizador import Sincronizador
from .soap import ClienteSefaz

TIPOS_DOCUMENTO = {
    "resNFe": "resumos de NF-e",
    "procNFe": "NF-e completas (XML)",
    "resEvento": "resumos de eventos",
    "procEventoNFe": "eventos",
}


def _carregar_certificado(cfg: Config) -> Certificado:
    senha = cfg.senha if cfg.senha is not None else getpass.getpass("Senha do certificado: ")
    cert = Certificado.carregar(cfg.certificado, senha)
    if cert.vencido:
        raise ErroNotaXML(f"O certificado venceu em {cert.valido_ate:%d/%m/%Y}.")
    return cert


@contextmanager
def _sessao(cfg: Config):
    cert = _carregar_certificado(cfg)
    banco = Armazenamento(cfg.pasta_dados)
    try:
        with ClienteSefaz(cert, cfg.verificar_ssl, cfg.timeout) as cliente:
            yield Sincronizador(
                DistribuicaoDFe(cliente, cfg.ambiente, cfg.cuf, cfg.documento),
                banco,
                Manifestacao(cliente, cert, cfg.ambiente, cfg.documento),
            )
    finally:
        banco.fechar()


def _validar_chaves(chaves: list[str]) -> list[str]:
    limpas = [re.sub(r"\D", "", c) for c in chaves]
    invalidas = [c for c in limpas if len(c) != 44]
    if invalidas:
        raise ErroNotaXML(f"Chave(s) de acesso inválida(s) (precisam de 44 dígitos): {', '.join(invalidas)}")
    return limpas


def _mostrar_manifestacao(resultados):
    for r in resultados:
        marca = "OK  " if r.sucesso else "ERRO"
        print(f"  [{marca}] {r.chave}: {r.cstat} - {r.motivo}")


def cmd_certificado(cfg: Config, args):
    cert = _carregar_certificado(cfg)
    print(f"Titular:     {cert.titular}")
    print(f"CNPJ:        {cert.cnpj or '(não identificado)'}")
    print(f"Válido até:  {cert.valido_ate:%d/%m/%Y %H:%M} UTC")
    if cert.cnpj and cert.cnpj[:8] != cfg.documento[:8]:
        print("AVISO: o CNPJ do certificado é de outra empresa (raiz diferente da configurada).")


def cmd_sincronizar(cfg: Config, args):
    ciencia = args.ciencia_automatica or cfg.ciencia_automatica
    with _sessao(cfg) as sinc:
        print("Consultando documentos novos na SEFAZ...")
        resumo = sinc.sincronizar(forcar=args.forcar)
        if resumo.bloqueado:
            print(f"Nada a fazer: a SEFAZ pede 1 hora de intervalo após alcançar o último NSU. "
                  f"Próxima consulta liberada em {resumo.proxima_consulta.astimezone():%d/%m/%Y %H:%M}. "
                  "(use --forcar por sua conta e risco)")
        else:
            print(f"Concluído: {resumo.consultas} consulta(s), último NSU {resumo.ult_nsu}.")
            for tipo, qtd in resumo.documentos.items():
                print(f"  {qtd} {TIPOS_DOCUMENTO.get(tipo, tipo)}")
            if not resumo.total:
                print("  Nenhum documento novo.")

        if ciencia:
            pendentes = sinc.banco.chaves_sem_manifestacao()
            if pendentes:
                print(f"Enviando Ciência da Operação para {len(pendentes)} nota(s)...")
                _mostrar_manifestacao(sinc.manifestar(pendentes, "ciencia"))
                print("O XML completo dessas notas chegará nas próximas sincronizações "
                      "(ou use 'notaxml baixar --pendentes').")


def cmd_manifestar(cfg: Config, args):
    chaves = _validar_chaves(args.chaves)
    with _sessao(cfg) as sinc:
        _mostrar_manifestacao(sinc.manifestar(chaves, args.evento, args.justificativa))


def cmd_baixar(cfg: Config, args):
    with _sessao(cfg) as sinc:
        chaves = _validar_chaves(args.chaves) if args.chaves else sinc.banco.chaves_aguardando_xml()
        if not chaves:
            print("Nenhuma nota aguardando XML.")
            return
        for chave in chaves:
            try:
                ok = sinc.baixar_por_chave(chave)
                print(f"  {chave}: {'XML completo baixado' if ok else 'apenas resumo disponível (manifeste a nota)'}")
            except ErroNotaXML as exc:
                print(f"  {chave}: {exc}")
                if getattr(exc, "cstat", None) == "656":
                    break


def cmd_listar(cfg: Config, args):
    banco = Armazenamento(cfg.pasta_dados)
    try:
        notas = banco.listar(somente_pendentes=args.pendentes)
    finally:
        banco.fechar()

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";")
            escritor.writerow(["chave", "emissao", "emitente_cnpj", "emitente", "valor", "situacao",
                               "manifestacao", "xml"])
            for n in notas:
                escritor.writerow([n["chave"], n["emissao"], n["emitente_documento"], n["emitente_nome"],
                                   f"{n['valor'] or 0:.2f}".replace(".", ","), n["situacao"],
                                   DESCRICAO_EVENTO.get(n["manifestacao"] or "", ""), n["arquivo_xml"] or ""])
        print(f"{len(notas)} nota(s) exportada(s) para {args.csv}")
        return

    if not notas:
        print("Nenhuma nota encontrada. Rode 'notaxml sincronizar' primeiro.")
        return
    print(f"{'Emissão':10}  {'Emitente':30}  {'Valor':>13}  {'Situação':10}  {'XML':3}  Chave")
    for n in notas:
        print(f"{(n['emissao'] or '')[:10]:10}  {(n['emitente_nome'] or '')[:30]:30}  "
              f"{n['valor'] or 0:>13,.2f}  {(n['situacao'] or '')[:10]:10}  "
              f"{'sim' if n['arquivo_xml'] else 'não':3}  {n['chave']}")
    print(f"\n{len(notas)} nota(s). XMLs em: {cfg.pasta_dados / 'xml'}")


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notaxml", description="Baixa NF-e da SEFAZ (Distribuição DF-e).")
    parser.add_argument("-c", "--config", default="config.toml", help="arquivo de configuração (padrão: config.toml)")
    subs = parser.add_subparsers(dest="comando", required=True)

    subs.add_parser("certificado", help="mostra os dados do certificado e testa a senha").set_defaults(func=cmd_certificado)

    p = subs.add_parser("sincronizar", help="baixa todos os documentos novos disponíveis na SEFAZ")
    p.add_argument("--ciencia-automatica", action="store_true",
                   help="envia Ciência da Operação para notas que só têm resumo (libera o XML completo)")
    p.add_argument("--forcar", action="store_true", help="ignora o intervalo mínimo de 1 hora (risco de bloqueio 656)")
    p.set_defaults(func=cmd_sincronizar)

    p = subs.add_parser("manifestar", help="envia manifestação do destinatário")
    p.add_argument("chaves", nargs="+", help="chave(s) de acesso de 44 dígitos")
    p.add_argument("-e", "--evento", choices=list(EVENTOS), default="ciencia")
    p.add_argument("-j", "--justificativa", help="obrigatória para 'nao-realizada' (15 a 255 caracteres)")
    p.set_defaults(func=cmd_manifestar)

    p = subs.add_parser("baixar", help="baixa o XML de notas específicas pela chave de acesso")
    p.add_argument("chaves", nargs="*", help="chave(s) de acesso; sem chaves, usa as notas já manifestadas sem XML")
    p.set_defaults(func=cmd_baixar)

    p = subs.add_parser("listar", help="lista as notas baixadas")
    p.add_argument("--pendentes", action="store_true", help="somente notas sem XML completo")
    p.add_argument("--csv", metavar="ARQUIVO", help="exporta a lista para CSV (abre no Excel)")
    p.set_defaults(func=cmd_listar)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = criar_parser().parse_args(argv)
    try:
        cfg = carregar_config(args.config)
        args.func(cfg, args)
    except (ErroNotaXML, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
