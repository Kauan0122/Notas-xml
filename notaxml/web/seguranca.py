import hmac
import secrets

from flask import abort, request, session


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def verificar_csrf():
    if request.method == "POST":
        enviado = request.form.get("csrf", "")
        if not session.get("csrf") or not hmac.compare_digest(enviado, session["csrf"]):
            abort(400, "Formulário expirado. Recarregue a página e tente de novo.")


def destino_seguro(destino: str, padrao: str) -> str:
    """Só permite redirecionar para caminhos internos (evita redirecionamento para outro site)."""
    return destino if destino.startswith("/") and not destino.startswith(("//", "/\\")) else padrao


def cabecalhos(resposta):
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    return resposta
