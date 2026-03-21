def get_sys_color(sys_char):
    """
    Return a display color for a GNSS constellation.
    """
    colors = {
        'G': '#5E8C61',  # GPS
        'R': '#B05E5E',  # GLONASS
        'E': '#5B84B1',  # Galileo
        'C': '#8E77A4',  # BeiDou
        'J': '#C48D4D',  # QZSS
        'S': '#7F8C8D',  # SBAS
        'I': '#3E8E7E',  # IRNSS / NavIC
    }
    return colors.get(sys_char, '#555555')


def get_signal_color(sig_code):
    """
    Return a display color for a signal code based on band and suffix.
    """
    code = str(sig_code).upper()
    band = '1'
    suffix = ''

    if '1' in code:
        band = '1'
    elif '2' in code:
        band = '2'
    elif '5' in code:
        band = '5'
    elif '6' in code:
        band = '6'
    elif '7' in code or '8' in code:
        band = '7'
    elif '9' in code:
        band = '9'

    for char in code:
        if char.isalpha():
            suffix = char
            break

    if band == '1':
        if suffix in ['C', 'S', 'A', 'D']:
            return '#4A90E2'
        if suffix in ['W', 'P', 'Y']:
            return '#34495E'
        if suffix in ['L', 'X', 'Z']:
            return '#85ADDB'
        if suffix in ['I', 'B', 'E']:
            return '#A9C1D9'
        return '#5D8AA8'

    if band == '2':
        if suffix in ['C', 'I']:
            return '#D96459'
        if suffix in ['W', 'P', 'Y']:
            return '#8C4646'
        if suffix in ['L', 'S', 'X']:
            return '#E39E82'
        if suffix in ['Q']:
            return '#F2C1B0'
        return '#C06C84'

    if band == '5':
        if suffix in ['Q', 'X']:
            return '#73956F'
        if suffix in ['I', 'D', 'A']:
            return '#4A6741'
        if suffix in ['P']:
            return '#9CB380'
        if suffix in ['B', 'C', 'Z']:
            return '#C5D1B3'
        return '#86A697'

    if band == '6':
        if suffix in ['I', 'S']:
            return '#7D6E83'
        if suffix in ['Q', 'L']:
            return '#B0A4B5'
        if suffix in ['X', 'E', 'Z']:
            return '#5E548E'
        return '#9B89B3'

    if band == '7':
        if suffix in ['Q']:
            return '#D4A373'
        if suffix in ['I', 'D']:
            return '#E9C46A'
        if suffix in ['X', 'P', 'Z']:
            return '#B5838D'
        if suffix in ['A', 'B']:
            return '#F4E1D2'
        return '#CCAC93'

    if band == '9':
        if suffix in ['A']:
            return '#2A9D8F'
        if suffix in ['B', 'C']:
            return '#52B69A'
        if suffix in ['X']:
            return '#76C893'
        return '#95D5B2'

    return '#95A5A6'
