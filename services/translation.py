# Dictionary mappings
INDEPENDENT_VOWELS = {
    "100000": "අ",
    "001110": "ආ",
    "111011": "ඇ",
    "110111": "ඈ",
    "010100": "ඉ",
    "001010": "ඊ",
    "101001": "උ",
    "110011": "ඌ",
    "100010": "එ",
    "010001": "ඒ",
    "001100": "ඓ",
    "101101": "ඔ",
    "101010": "ඕ",
    "010101": "ඖ"
}

VOWEL_SIGNS = {
    "001110": "ා",
    "111011": "ැ",
    "110111": "ෑ",
    "010100": "ි",
    "001010": "ී",
    "101001": "ු",
    "110011": "ූ",
    "100010": "ෙ",
    "010001": "ේ",
    "001100": "ෛ",
    "101101": "ො",
    "101010": "ෝ",
    "010101": "ෞ"
}

MODIFIERS = {
    "001000": "ං"
}

VIRAMA = "000100"
NUM_INDICATOR = "001111"
WORD_SPACE = "000000"
SANYAKA_INDICATOR = "011000"

CONSONANTS = {
    "101000": "ක",
    "000101": "ඛ",
    "110110": "ග",
    "110001": "ඝ",
    "001101": "ඞ",
    "100100": "ච",
    "100001": "ඡ",
    "010110": "ජ",
    "001011": "ඣ",
    "010010": "ඤ",
    "011111": "ට",
    "010111": "ඨ",
    "110101": "ඩ",
    "111111": "ඪ",
    "101011": "ණ",
    "011110": "ත",
    "100111": "ථ",
    "100110": "ද",
    "011101": "ධ",
    "101110": "න",
    "111100": "ප",
    "100011": "ඵ",
    "110000": "බ",
    "000110": "භ",
    "101100": "ම",
    "101111": "ය",
    "111010": "ර",
    "111000": "ල",
    "111001": "ව",
    "100101": "ෂ",
    "111101": "ශ",
    "011100": "ස",
    "110010": "හ",
    "000111": "ළ",
    "110100": "ෆ",
    "111110": "ඥ"
}

DIGITS = {
    "100000": "1",
    "110000": "2",
    "100100": "3",
    "100110": "4",
    "100010": "5",
    "110100": "6",
    "110110": "7",
    "110010": "8",
    "010100": "9",
    "010110": "0"
}

PUNCTUATION = {
    "010000": ",",
    "011000": ";",
    "010010": ":",
    "010011": ".",
    "011010": "!",
    "011001": "?",
    "011011": "()",
    "001011": "\"",
    "001001": "-"
}



# Bit order is dots 1,2,3,4,5,6 (column-major), never row-major.
# Alphabet/punctuation cross-check: World Braille Usage 2013, pp. 134-135.
# Ambiguous punctuation needs book-specific context; overrides are explicit.
SANYAKA = {'ග': 'ඟ', 'ජ': 'ඦ', 'ඩ': 'ඬ', 'ද': 'ඳ', 'බ': 'ඹ'}


def translate_detailed(codes, *, overrides=None):
    """Return text plus indexed warnings. overrides maps token index to text.

    Prefix virama follows this project's existing convention. This is an
    uncontracted literary decoder, not a complete Sinhala/Nemeth translator.
    Ambiguous letters default to letters and are reported, not silently guessed.
    """
    import unicodedata
    codes = list(codes)
    overrides = overrides or {}
    result, warnings = [], []
    number = consonant = paren = quote = False
    i = 0

    def warn(index, reason):
        warnings.append({'index': index, 'code': codes[index], 'reason': reason})

    def emit_cons(char, dead=False):
        if result and result[-1].endswith('්') and char in ('ර', 'ය'):
            result.append('\u200d')
        result.append(char + ('්' if dead else ''))

    while i < len(codes):
        code = codes[i]
        following = codes[i+1] if i+1 < len(codes) else None
        if i in overrides:
            result.append(str(overrides[i]))
            number = consonant = False
            i += 1
            continue
        if code in (WORD_SPACE, '\n'):
            result.append(' ' if code == WORD_SPACE else '\n')
            number = consonant = False
            i += 1
            continue
        if not isinstance(code, str) or len(code) != 6 or set(code) - {'0', '1'}:
            warn(i, 'Invalid or uncertain cell')
            result.append('�')
            number = consonant = False
            i += 1
            continue
        if code == NUM_INDICATOR:
            number = following in DIGITS
            consonant = False
            if not number:
                warn(i, 'Number sign is not followed by a digit')
                result.append('�')
            i += 1
            continue
        if number and code in DIGITS:
            result.append(DIGITS[code])
            i += 1
            continue
        number = False
        # Sinhala visarga is dots 3-3; a single dot 3 is anusvara.
        if code == '001000' and following == '001000' and i+1 not in overrides:
            result.append('ඃ')
            consonant = False
            i += 2
            continue
        # Vocalic r/l use a two-cell sequence: dot 5 or 6, then r or l.
        if code in ('000010', '000001') and following in ('111010', '111000') and i+1 not in overrides:
            if following == '111010':
                char = ('ෘ' if code == '000010' else 'ෲ') if consonant else ('ඍ' if code == '000010' else 'ඎ')
            elif consonant and code == '000010':
                char = 'ෟ'
            elif consonant:
                warn(i, 'Long vocalic l sign needs manual review')
                char = '�'
            else:
                char = 'ඏ' if code == '000010' else 'ඐ'
            result.append(char)
            consonant = False
            i += 2
            continue
        if code == VIRAMA:
            # Consume only an adjacent consonant (optionally sanyaka-prefixed).
            j = i + 1
            nasal = j < len(codes) and codes[j] == SANYAKA_INDICATOR
            if nasal:
                j += 1
            char = CONSONANTS.get(codes[j]) if j < len(codes) else None
            if char and (not nasal or char in SANYAKA) and not any(k in overrides for k in range(i+1,j+1)):
                emit_cons(SANYAKA[char] if nasal else char, dead=True)
                i = j+1
            else:
                warn(i, 'Unresolved virama prefix; not applied to a later consonant')
                result.append('�')
                i += 1
            consonant = False
            continue
        if code == SANYAKA_INDICATOR:
            char = CONSONANTS.get(following)
            if char in SANYAKA and i+1 not in overrides:
                warn(i, 'Sanyaka/semicolon ambiguity: interpreted as sanyaka prefix')
                emit_cons(SANYAKA[char])
                consonant = True
                i += 2
            else:
                result.append(';')
                consonant = False
                i += 1
            continue
        if consonant and code in VOWEL_SIGNS:
            result.append(VOWEL_SIGNS[code])
            consonant = False
        elif code in MODIFIERS:
            result.append(MODIFIERS[code])
            consonant = False
        elif code == '011011':
            result.append(')' if paren else '(')
            paren = not paren
            consonant = False
        elif code == '001011' and quote:
            result.append('”')
            quote = False
            consonant = False
            warn(i, 'Closing quote/ඣ ambiguity: interpreted as closing quote')
        elif code == '011001' and (i == 0 or codes[i-1] in (WORD_SPACE, '\n')) and '001011' in codes[i+1:]:
            result.append('“')
            quote = True
            consonant = False
            warn(i, 'Opening quote/question mark ambiguity: interpreted as opening quote')
        elif code in CONSONANTS:
            if code in ('010010', '001011'):
                warn(i, 'Letter/punctuation ambiguity: kept letter; use an indexed override if needed')
            emit_cons(CONSONANTS[code])
            consonant = True
        elif code in INDEPENDENT_VOWELS:
            result.append(INDEPENDENT_VOWELS[code])
            consonant = False
        elif code in PUNCTUATION:
            result.append(PUNCTUATION[code])
            consonant = False
        else:
            warn(i, 'Unsupported cell or detached vowel sign')
            result.append('�')
            consonant = False
        i += 1
    if paren or quote:
        warnings.append({'index': None, 'code': None, 'reason': 'Unclosed bracket or quote'})
    return {'text': unicodedata.normalize('NFC', ''.join(result)), 'warnings': warnings}


def translate_codes(codes: list) -> str:
    """Backward-compatible pipeline entry point."""
    return translate_detailed(codes)['text']
