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
    "010101": "ෞ",
    "000010": "ෘ"
}

MODIFIERS = {
    "001000": "ං",
    "000001": "ඃ"
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
    "000011": ";",
    "010010": ":",
    "010011": ".",
    "011010": "!",
    "011001": "?",
    "011011": "\"",
    "001011": "\"",
    "001001": "-"
}


def translate_codes(codes: list) -> str:
    """
    Person 1 calls this.
    Takes 6-bit binary strings and returns Sinhala Unicode text.
    """
    result = []
    i = 0
    number_mode   = False
    sanyaka_mode  = False
    virama_mode   = False
    last_was_cons = False

    while i < len(codes):
        code = codes[i]

        if code in ["001001", "000001"]:
            count = 1
            while i + count < len(codes) and codes[i + count] == code:
                count += 1
            if count > 1:
                result.append("-" * count)
                number_mode = False
                sanyaka_mode = False
                virama_mode = False
                last_was_cons = False
                i += count
                continue

        if code == "\n":
            result.append("\n")
            number_mode = False
            sanyaka_mode = False
            virama_mode = False
            last_was_cons = False
            i += 1
            continue

        if code == WORD_SPACE:
            result.append(" ")
            number_mode = False
            sanyaka_mode = False
            virama_mode = False
            last_was_cons = False
            i += 1
            continue

        if code == NUM_INDICATOR:
            if not last_was_cons and (i == 0 or codes[i-1] == WORD_SPACE or codes[i-1] == "\n"):
                number_mode = True
                sanyaka_mode = False
                virama_mode = False
                last_was_cons = False
                i += 1
                continue
            else:
                char = "ණ"
                sanyaka_mode = False
                result.append(char)
                if virama_mode:
                    result.append("්")
                    virama_mode = False
                    last_was_cons = False
                else:
                    last_was_cons = True
                i += 1
                continue

        if code == SANYAKA_INDICATOR:
            sanyaka_mode = True
            number_mode = False
            last_was_cons = False
            i += 1
            continue

        if number_mode:
            char = DIGITS.get(code)
            if char:
                result.append(char)
                i += 1
                continue
            else:
                number_mode = False

        if code == VIRAMA:
            virama_mode = True
            number_mode = False
            last_was_cons = False
            i += 1
            continue

        if last_was_cons and code in VOWEL_SIGNS:
            result.append(VOWEL_SIGNS[code])
            last_was_cons = False
            i += 1
            continue

        if code in MODIFIERS:
            result.append(MODIFIERS[code])
            last_was_cons = False
            i += 1
            continue

        if code == "010010":
            # Context-aware check: Colon usually appears at end of text or before space/newline
            is_colon = False
            if i + 1 >= len(codes):
                is_colon = True
            elif codes[i+1] in [WORD_SPACE, "\n"]:
                is_colon = True
                
            if is_colon:
                result.append(":")
                last_was_cons = False
                i += 1
                continue

        if code in CONSONANTS:
            char = CONSONANTS[code]
            if sanyaka_mode:
                if char == "ග": char = "ඟ"
                elif char == "ඩ": char = "ඬ"
                elif char == "ද": char = "ඳ"
                elif char == "බ": char = "ඹ"
                sanyaka_mode = False
                
            if len(result) > 0 and result[-1] == "්":
                if char == "ර" or char == "ය":
                    result.append("\u200D")
                    
            result.append(char)
            
            if virama_mode:
                result.append("්")
                virama_mode = False
                last_was_cons = False
            else:
                last_was_cons = True
                
            i += 1
            continue

        if code in INDEPENDENT_VOWELS:
            result.append(INDEPENDENT_VOWELS[code])
            last_was_cons = False
            i += 1
            continue
        
        if code in VOWEL_SIGNS:
            result.append(VOWEL_SIGNS[code])
            last_was_cons = False
            i += 1
            continue

        if code in PUNCTUATION:
            result.append(PUNCTUATION[code])
        else:
            result.append(f"[{code}]")
            
        last_was_cons = False
        i += 1

    return "".join(result)
