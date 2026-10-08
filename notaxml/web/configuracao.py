"""Tela de configuração: dados da empresa e certificado, sem precisar editar o config.toml."""

from collections.abc import Callable
from pathlib import Path

from flask import flash, redirect, render_template, request, url_for

from .. import segredo
from ..certificado import Certificado
from ..config import AMBIENTES, ler_secoes, salvar_config
from ..documentos import cnpj_valido, cpf_valido, so_digitos
from ..erros import ErroNotaXML
from ..ufs import CODIGOS_UF

NOME_CERTIFICADO = "certificado.pfx"
TAMANHO_MAXIMO_PFX = 1024 * 1024


class ErroFormulario(Exception):
    pass


def _valores_atuais(secoes: dict, pasta_config: Path) -> dict:
    empresa, cert, sefaz = secoes.get("empresa", {}), secoes.get("certificado", {}), secoes.get("sefaz", {})
    arquivo = cert.get("arquivo")
    return {
        "cnpj": empresa.get("cnpj", ""),
        "uf": str(empresa.get("uf", "")).upper(),
        "ambiente": sefaz.get("ambiente", "producao"),
        "tem_certificado": bool(arquivo) and (pasta_config / arquivo).is_file(),
        "senha_lembrada": bool(cert.get("senha")),
        "ciencia_automatica": secoes.get("sincronizacao", {}).get("ciencia_automatica", False),
        "sincronizacao_automatica": secoes.get("web", {}).get("sincronizacao_automatica", True),
    }


def processar(form, arquivo_pfx, caminho_config: Path, pasta_dados_padrao: Path | None) -> str | None:
    """Valida e grava a configuração. Devolve a senha informada (para desbloquear o certificado já)."""
    secoes = ler_secoes(caminho_config)
    pasta = caminho_config.parent
    atual = _valores_atuais(secoes, pasta)
    senha = form.get("senha", "")
    lembrar = bool(form.get("lembrar")) and segredo.disponivel()

    certificado = None
    dados_pfx = arquivo_pfx.read(TAMANHO_MAXIMO_PFX + 1) if arquivo_pfx and arquivo_pfx.filename else None
    if dados_pfx is not None:
        if len(dados_pfx) > TAMANHO_MAXIMO_PFX:
            raise ErroFormulario("Arquivo grande demais para um certificado A1 (.pfx).")
        if not senha:
            raise ErroFormulario("Informe a senha do certificado.")
        certificado = Certificado.de_bytes(dados_pfx, senha)
    elif not atual["tem_certificado"]:
        raise ErroFormulario("Escolha o arquivo do certificado A1 (.pfx ou .p12).")
    elif senha:
        certificado = Certificado.carregar(pasta / secoes["certificado"]["arquivo"], senha)
    if certificado is not None and certificado.vencido:
        raise ErroFormulario(f"Este certificado venceu em {certificado.valido_ate:%d/%m/%Y}.")

    documento = (so_digitos(form.get("cnpj", "")) or (certificado.cnpj if certificado else "")
                 or so_digitos(str(atual["cnpj"])))
    if not (cnpj_valido(documento) or cpf_valido(documento)):
        raise ErroFormulario("CNPJ inválido. Confira os números.")
    if certificado and certificado.cnpj and certificado.cnpj[:8] != documento[:8]:
        raise ErroFormulario(f"O certificado é de outra empresa (CNPJ {certificado.cnpj}).")
    uf = form.get("uf", "").upper()
    if uf not in CODIGOS_UF:
        raise ErroFormulario("Escolha a UF da empresa.")
    ambiente = form.get("ambiente", "producao")
    if ambiente not in AMBIENTES:
        raise ErroFormulario("Ambiente inválido.")

    if dados_pfx is not None:
        destino = pasta / NOME_CERTIFICADO
        pasta.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados_pfx)
        destino.chmod(0o600)  # só o dono lê (no Windows a pasta do usuário já é privada)

    secoes.setdefault("empresa", {}).update(cnpj=documento, uf=uf)
    cert = secoes.setdefault("certificado", {})
    if dados_pfx is not None:
        cert["arquivo"] = NOME_CERTIFICADO
    if lembrar and senha:
        cert["senha"] = segredo.proteger(senha)
    elif not form.get("lembrar") or dados_pfx is not None:
        cert.pop("senha", None)  # nunca guarda senha em texto puro
    secoes.setdefault("sefaz", {})["ambiente"] = ambiente
    if "armazenamento" not in secoes and pasta_dados_padrao is not None:
        secoes["armazenamento"] = {"pasta": str(pasta_dados_padrao)}
    secoes.setdefault("sincronizacao", {})["ciencia_automatica"] = bool(form.get("ciencia_automatica"))
    secoes.setdefault("web", {})["sincronizacao_automatica"] = bool(form.get("sincronizacao_automatica"))

    ordem = ["empresa", "certificado", "sefaz", "armazenamento", "sincronizacao", "web"]
    salvar_config(caminho_config, {s: secoes[s] for s in ordem + [s for s in secoes if s not in ordem] if s in secoes})
    return senha or None


def registrar(app, caminho_config: Path, recarregar: Callable, pasta_dados_padrao: Path | None = None,
              ocupado: Callable[[], bool] = lambda: False):
    caminho_config = Path(caminho_config)

    @app.route("/configuracao", methods=["GET", "POST"])
    def configuracao():
        if request.method == "POST":
            if ocupado():
                flash("Aguarde a tarefa em andamento terminar antes de alterar a configuração.", "erro")
            else:
                try:
                    senha = processar(request.form, request.files.get("certificado"), caminho_config,
                                      pasta_dados_padrao)
                except (ErroFormulario, ErroNotaXML) as exc:
                    flash(str(exc), "erro")
                else:
                    recarregar(senha_certificado=senha)
                    flash("Configuração salva.", "ok")
                    return redirect(url_for("notas") if "notas" in app.view_functions else "/")
        valores = _valores_atuais(ler_secoes(caminho_config), caminho_config.parent)
        if request.method == "POST":  # mantém o que foi digitado após um erro
            valores.update({k: request.form.get(k, "") for k in ("cnpj", "uf", "ambiente")})
        return render_template("configuracao.html", valores=valores, ufs=sorted(CODIGOS_UF),
                               pode_lembrar=segredo.disponivel(), caminho_config=caminho_config)
