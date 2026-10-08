"""Gera o ícone do executável (empacotamento/notaxml.ico). Requer Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TAMANHO = 256
AZUL = (29, 78, 216, 255)


def gerar(destino: Path):
    img = Image.new("RGBA", (TAMANHO, TAMANHO), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(img)
    desenho.rounded_rectangle((8, 8, TAMANHO - 8, TAMANHO - 8), radius=48, fill=AZUL)
    # "folha" de nota fiscal
    desenho.rounded_rectangle((70, 46, 186, 210), radius=10, fill=(255, 255, 255, 255))
    for y in (84, 110, 136):
        desenho.rectangle((92, y, 164, y + 10), fill=(191, 208, 245, 255))
    try:
        fonte = ImageFont.load_default(size=40)
    except TypeError:  # Pillow antigo
        fonte = ImageFont.load_default()
    desenho.text((128, 182), "XML", fill=AZUL, font=fonte, anchor="mm")
    img.save(destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    gerar(Path(__file__).with_name("notaxml.ico"))
