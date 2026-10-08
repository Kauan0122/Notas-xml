import argparse
import getpass
import sys
from contextlib import contextmanager

from . import operacoes
from .armazenamento import Armazenamento
from .certificado import Certificado
from .config import Config, carregar_config
from .erros import ErroNotaXML
from .manifestacao import EVENTOS
from .operacoes import validar_chaves


def _carregar_certificado(cfg: Config) -> Certificado:
    senha = cfg.senha if cfg.senha is not None else getpass.getpass("Senha do certificado: ")
    cert = Certificado.carregar(cfg.certificado, senha)
    if cert.vencido:
        raise ErroNotaXML(f"O certificado venceu em {cert.valido_ate:%d/%m/%Y}.")
    return cert


@contextmanager
def _sessao(cfg: Config):
    with operacoes.abrir_sincronizador(cfg, _carregar_certificado(cfg)) as sinc:
        yield sinc


def cmd_certificado(cfg: Config, args):
    cert = _carregar_certificado(cfg)
    print(f"Titular:     {cert.titular}")
    print(f"CNPJ:        {cert.cnpj or '(não identificado)'}")
    print(f"Válido até:  {cert.valido_ate:%d/%m/%Y %H:%M} UTC")
    if cert.cnpj and cert.cnpj[:8] != cfg.documento[:8]:
        print("AVISO: o CNPJ do certificado é de outra empresa (raiz diferente da configurada).")


def cmd_sincronizar(cfg: Config, args):
    with _sessao(cfg) as sinc:
        operacoes.sincronizar(sinc, print, ciencia=args.ciencia_automatica or cfg.ciencia_automatica,
                              forcar=args.forcar)


def cmd_manifestar(cfg: Config, args):
    chaves = validar_chaves(args.chaves)
    with _sessao(cfg) as sinc:
        operacoes.manifestar(sinc, print, chaves, args.evento, args.justificativa)


def cmd_baixar(cfg: Config, args):
    with _sessao(cfg) as sinc:
        operacoes.baixar(sinc, print, validar_chaves(args.chaves) if args.chaves else None)


def cmd_listar(cfg: Config, args):
    banco = Armazenamento(cfg.pasta_dados)
    try:
        notas = banco.listar(somente_pendentes=args.pendentes)
    finally:
        banco.fechar()

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as arquivo:
            operacoes.escrever_csv(arquivo, notas)
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


def cmd_web(cfg: Config, args):
    import ipaddress
    import threading
    import webbrowser

    from waitress import serve

    from .web import criar_app

    host = args.host or cfg.web.host
    porta = args.porta or cfg.web.porta
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if not local and not cfg.web.senha:
        raise ErroNotaXML("Para abrir a interface na rede (host diferente de 127.0.0.1), defina uma senha de "
                          "acesso em [web] senha ou na variável NOTAXML_WEB_SENHA.")

    app = criar_app(cfg)
    tarefas = app.extensions["notaxml_tarefas"]
    if cfg.web.sincronizacao_automatica:
        tarefas.verificar_agenda()
        tarefas.iniciar_agendador()

    endereco = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{porta}"
    print(f"NotaXML rodando em {endereco}  (Ctrl+C para encerrar)")
    if tarefas.certificado is None:
        print("Certificado bloqueado: informe a senha na tela 'Certificado' ou defina NFE_CERT_SENHA.")
    if not args.sem_navegador:
        threading.Timer(1.0, webbrowser.open, args=(endereco,)).start()
    serve(app, host=host, port=porta, threads=8, ident="notaxml")


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

    p = subs.add_parser("web", help="abre a interface no navegador")
    p.add_argument("--host", help="endereço (padrão: [web] host do config, 127.0.0.1)")
    p.add_argument("--porta", type=int, help="porta (padrão: [web] porta do config, 8000)")
    p.add_argument("--sem-navegador", action="store_true", help="não abre o navegador automaticamente")
    p.set_defaults(func=cmd_web)
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
