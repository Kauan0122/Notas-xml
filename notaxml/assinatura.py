"""Assinatura XMLDSig no padrão da NF-e (enveloped, C14N, RSA-SHA1)."""

import base64
import copy
import hashlib

from lxml import etree

from .certificado import Certificado

NS_DSIG = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"


def _c14n(elemento: etree._Element) -> bytes:
    # Canoniza uma cópia isolada (que carrega os namespaces herdados): o C14N de subárvore do
    # libxml2 2.14 emite xmlns="" indevido em elementos aninhados, o que invalida a assinatura.
    return etree.tostring(copy.deepcopy(elemento), method="c14n", exclusive=False, with_comments=False)


def assinar(pai: etree._Element, referencia: etree._Element, certificado: Certificado) -> etree._Element:
    """Assina `referencia` (elemento com atributo Id) e anexa <Signature> como último filho de `pai`."""
    id_ref = referencia.get("Id")
    if not id_ref:
        raise ValueError("O elemento a ser assinado precisa do atributo Id.")

    digest = base64.b64encode(hashlib.sha1(_c14n(referencia)).digest()).decode()

    def d(parent, tag, **attrs):
        return etree.SubElement(parent, f"{{{NS_DSIG}}}{tag}", **attrs)

    assinatura = etree.SubElement(pai, f"{{{NS_DSIG}}}Signature", nsmap={None: NS_DSIG})
    signed_info = d(assinatura, "SignedInfo")
    d(signed_info, "CanonicalizationMethod", Algorithm=C14N)
    d(signed_info, "SignatureMethod", Algorithm=f"{NS_DSIG}rsa-sha1")
    ref = d(signed_info, "Reference", URI=f"#{id_ref}")
    transforms = d(ref, "Transforms")
    d(transforms, "Transform", Algorithm=f"{NS_DSIG}enveloped-signature")
    d(transforms, "Transform", Algorithm=C14N)
    d(ref, "DigestMethod", Algorithm=f"{NS_DSIG}sha1")
    d(ref, "DigestValue").text = digest

    valor = certificado.assinar_rsa_sha1(_c14n(signed_info))
    d(assinatura, "SignatureValue").text = base64.b64encode(valor).decode()
    x509_data = d(d(assinatura, "KeyInfo"), "X509Data")
    d(x509_data, "X509Certificate").text = certificado.der_base64()
    return assinatura
