"""Genera le icone PNG del manifest PWA (icon-192.png, icon-512.png) dal
branding di icon.svg. Rieseguibile: `python static/icons/generate_icons.py`.

Riproduce l'icona SVG (quadrato arrotondato blu con orologio bianco) come PNG,
cosi' i riferimenti nel manifest sono validi su tutti i browser.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BLUE = (10, 132, 255, 255)  # #0A84FF
WHITE = (255, 255, 255, 255)


def draw_icon(size):
    # Disegna a 4x e riduce, per bordi piu' morbidi (anti-alias)
    scale = 4
    s = size * scale
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    k = s / 512.0  # fattore rispetto al viewBox originale
    stroke = max(1, int(24 * k))

    # Sfondo arrotondato
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(100 * k), fill=BLUE)

    # Cerchio (quadrante) bianco, solo contorno
    cx = cy = 256 * k
    r = 140 * k
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=WHITE, width=stroke)

    # Lancette: (256,156)->(256,256)->(336,296)
    pts = [(256 * k, 156 * k), (256 * k, 256 * k), (336 * k, 296 * k)]
    d.line(pts, fill=WHITE, width=stroke, joint='curve')
    # Estremi arrotondati
    rr = stroke / 2
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def main():
    for size in (192, 512):
        out = os.path.join(HERE, f'icon-{size}.png')
        draw_icon(size).save(out)
        print(f'Creato {out}')


if __name__ == '__main__':
    main()
