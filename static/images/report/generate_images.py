#!/usr/bin/env python3
"""
Script per generare le immagini placeholder per i report.
Queste immagini possono essere sostituite con quelle ufficiali.
"""

from PIL import Image, ImageDraw, ImageFont
import os

# Directory di output
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

def create_logo_roma():
    """Crea il logo ROMA con lo stemma"""
    width, height = 200, 80
    img = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Testo ROMA
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except:
        font = ImageFont.load_default()

    draw.text((10, 25), "ROMA", fill=(139, 69, 19), font=font)

    # Stemma stilizzato (rombo rosso/giallo)
    draw.polygon([(160, 10), (180, 40), (160, 70), (140, 40)], fill=(178, 34, 34))
    draw.polygon([(155, 25), (170, 40), (155, 55), (140, 40)], fill=(255, 215, 0))

    img.save(os.path.join(OUTPUT_DIR, 'logo_roma.png'), 'PNG')
    print("Creato: logo_roma.png")

def create_stemma_municipio():
    """Crea lo stemma del Municipio V"""
    width, height = 100, 100
    img = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Stemma stilizzato
    draw.ellipse([10, 10, 90, 90], fill=(178, 34, 34), outline=(139, 69, 19), width=2)
    draw.ellipse([25, 25, 75, 75], fill=(255, 215, 0))

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except:
        font = ImageFont.load_default()

    draw.text((40, 38), "V", fill=(139, 69, 19), font=font)

    img.save(os.path.join(OUTPUT_DIR, 'stemma_municipio.png'), 'PNG')
    print("Creato: stemma_municipio.png")

def create_logo_arca():
    """Crea il logo Arca di Noè"""
    width, height = 150, 150
    img = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Sfondo arancione
    draw.rectangle([10, 30, 140, 140], fill=(255, 165, 0), outline=(139, 90, 0), width=2)

    # Testo "cooperativa sociale"
    try:
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except:
        font_small = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_large = ImageFont.load_default()

    draw.text((15, 10), "cooperativa sociale", fill=(139, 90, 0), font=font_small)

    # Testo ARCA
    draw.text((35, 40), "ARCA", fill=(0, 0, 139), font=font_medium)

    # Figure stilizzate (persone)
    draw.line([(75, 70), (75, 100)], fill=(0, 0, 139), width=3)
    draw.ellipse([65, 55, 85, 70], fill=(0, 0, 139))
    draw.line([(60, 80), (90, 80)], fill=(0, 0, 139), width=2)
    draw.line([(65, 100), (55, 115)], fill=(0, 0, 139), width=2)
    draw.line([(85, 100), (95, 115)], fill=(0, 0, 139), width=2)

    # Testo diNoè
    draw.text((40, 118), "diNoè", fill=(139, 90, 0), font=font_large)

    img.save(os.path.join(OUTPUT_DIR, 'logo_arca.png'), 'PNG')
    print("Creato: logo_arca.png")

def create_certificazioni():
    """Crea il banner delle certificazioni SOCOTEC + UKAS"""
    width, height = 250, 80
    img = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except:
        font = ImageFont.load_default()
        font_bold = ImageFont.load_default()

    # SOCOTEC box
    draw.rectangle([10, 10, 120, 70], outline=(0, 100, 150), width=2)
    draw.ellipse([30, 20, 70, 50], fill=(0, 150, 200))
    draw.text((35, 52), "SOCOTEC", fill=(0, 100, 150), font=font)
    draw.text((25, 62), "ISO 9001", fill=(100, 100, 100), font=font)

    # UKAS box
    draw.rectangle([130, 10, 240, 70], fill=(100, 50, 120), outline=(80, 30, 100), width=2)
    draw.text((155, 25), "UKAS", fill=(255, 255, 255), font=font_bold)
    draw.text((140, 40), "MANAGEMENT", fill=(255, 255, 255), font=font)
    draw.text((150, 52), "SYSTEMS", fill=(255, 255, 255), font=font)
    draw.text((170, 65), "0063", fill=(255, 255, 255), font=font)

    img.save(os.path.join(OUTPUT_DIR, 'certificazioni.png'), 'PNG')
    print("Creato: certificazioni.png")

def create_header_completo():
    """Crea l'header completo con tutti i loghi"""
    width, height = 800, 120
    img = Image.new('RGBA', (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    try:
        font_roma = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", 32)
        font_municipio = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except:
        font_roma = ImageFont.load_default()
        font_municipio = ImageFont.load_default()

    # Logo ROMA (sinistra)
    draw.text((50, 40), "ROMA", fill=(139, 69, 19), font=font_roma)

    # Stemma (centro-sinistra)
    draw.polygon([(200, 30), (230, 60), (200, 90), (170, 60)], fill=(178, 34, 34))
    draw.polygon([(200, 40), (220, 60), (200, 80), (180, 60)], fill=(255, 215, 0))

    # Municipio V (centro)
    draw.text((350, 45), "Municipio V", fill=(0, 0, 0), font=font_municipio)

    # Logo Arca (destra) - simplified
    draw.rectangle([650, 20, 750, 100], fill=(255, 165, 0), outline=(139, 90, 0), width=2)
    try:
        font_arca = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except:
        font_arca = ImageFont.load_default()
    draw.text((665, 50), "ARCA", fill=(0, 0, 139), font=font_arca)
    draw.text((660, 70), "di Noè", fill=(139, 90, 0), font=font_arca)

    img.save(os.path.join(OUTPUT_DIR, 'header_completo.png'), 'PNG')
    print("Creato: header_completo.png")

def create_footer_completo():
    """Crea il footer completo con logo e certificazioni"""
    width, height = 800, 100
    img = Image.new('RGBA', (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
    except:
        font = ImageFont.load_default()
        font_bold = ImageFont.load_default()

    # Logo Arca (sinistra)
    draw.rectangle([20, 10, 90, 90], fill=(255, 165, 0), outline=(139, 90, 0), width=2)
    draw.text((30, 40), "ARCA", fill=(0, 0, 139), font=font_bold)
    draw.text((28, 55), "di Noè", fill=(139, 90, 0), font=font)

    # Certificazioni (destra)
    # SOCOTEC
    draw.ellipse([620, 20, 670, 70], fill=(0, 150, 200))
    draw.text((680, 30), "SOCOTEC", fill=(0, 100, 150), font=font_bold)
    draw.text((680, 45), "ISO 9001", fill=(100, 100, 100), font=font)

    # UKAS
    draw.rectangle([730, 20, 790, 80], fill=(100, 50, 120))
    draw.text((745, 35), "UKAS", fill=(255, 255, 255), font=font_bold)
    draw.text((740, 50), "0063", fill=(255, 255, 255), font=font)

    img.save(os.path.join(OUTPUT_DIR, 'footer_completo.png'), 'PNG')
    print("Creato: footer_completo.png")

if __name__ == '__main__':
    print("Generazione immagini report...")
    create_logo_roma()
    create_stemma_municipio()
    create_logo_arca()
    create_certificazioni()
    create_header_completo()
    create_footer_completo()
    print("\nTutte le immagini sono state create in:", OUTPUT_DIR)
    print("\nNOTA: Queste sono immagini placeholder. Sostituiscile con i loghi ufficiali.")
