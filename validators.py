"""Validazione input condivisa fra app.py e i moduli di route (blueprint).

Ogni funzione ritorna una tupla (valore_normalizzato, errore): se errore non e'
None, il valore non e' valido. Nessuna dipendenza dal resto dell'applicazione.
"""
import re


def validate_string(value, field_name, max_length=100, required=True):
    """Valida una stringa: lunghezza, caratteri pericolosi"""
    if value is None or str(value).strip() == '':
        if required:
            return None, f'{field_name} e\' obbligatorio'
        return '', None

    value = str(value).strip()

    if len(value) > max_length:
        return None, f'{field_name} troppo lungo (max {max_length} caratteri)'

    # Blocca caratteri pericolosi (tag HTML, script injection)
    if re.search(r'<[^>]*script|javascript:|on\w+\s*=', value, re.IGNORECASE):
        return None, f'{field_name} contiene caratteri non validi'

    return value, None


def validate_number(value, field_name, min_val=0, max_val=None, required=True):
    """Valida un valore numerico"""
    if value is None or value == '':
        if required:
            return None, f'{field_name} e\' obbligatorio'
        return 0, None

    try:
        num = float(value)
    except (ValueError, TypeError):
        return None, f'{field_name} deve essere un numero valido'

    if num < min_val:
        return None, f'{field_name} deve essere almeno {min_val}'

    if max_val is not None and num > max_val:
        return None, f'{field_name} non puo\' superare {max_val}'

    return num, None


def validate_integer(value, field_name, min_val=0, max_val=None, required=True):
    """Valida un valore intero"""
    if value is None or value == '':
        if required:
            return None, f'{field_name} e\' obbligatorio'
        return 0, None

    try:
        num = int(value)
    except (ValueError, TypeError):
        return None, f'{field_name} deve essere un numero intero'

    if num < min_val:
        return None, f'{field_name} deve essere almeno {min_val}'

    if max_val is not None and num > max_val:
        return None, f'{field_name} non puo\' superare {max_val}'

    return num, None
