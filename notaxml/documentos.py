import re


def so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _digitos_verificadores(base: str, pesos: list[int]) -> str:
    soma = sum(int(d) * p for d, p in zip(base, pesos))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(cnpj: str) -> bool:
    cnpj = so_digitos(cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    dv1 = _digitos_verificadores(cnpj[:12], pesos)
    dv2 = _digitos_verificadores(cnpj[:12] + dv1, [6, *pesos])
    return cnpj[12:] == dv1 + dv2


def cpf_valido(cpf: str) -> bool:
    cpf = so_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    dv1 = _digitos_verificadores(cpf[:9], list(range(10, 1, -1)))
    dv2 = _digitos_verificadores(cpf[:9] + dv1, list(range(11, 1, -1)))
    return cpf[9:] == dv1 + dv2
