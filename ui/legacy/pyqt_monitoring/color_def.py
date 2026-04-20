"""Legacy PyQt6 color palette preserved for the archived monitoring UI."""

def get_sys_color(sys_char):
    """
    Return a display color for a GNSS constellation.
    """
    colors = {
        'G': '#4CAF50',  # GPS
        'R': '#F44336',  # GLONASS
        'E': '#2196F3',  # Galileo
        'C': '#9C27B0',  # BeiDou
        'J': '#FF9800',  # QZSS
        'S': '#9E9E9E',  # SBAS
        'I': '#009688',  # IRNSS / NavIC
    }
    return colors.get(sys_char, '#000000')


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
            return '#1976D2'
        if suffix in ['W', 'P', 'Y']:
            return '#0D47A1'
        if suffix in ['L', 'X', 'Z']:
            return '#42A5F5'
        if suffix in ['I', 'B', 'E']:
            return '#90CAF9'
        return '#2196F3'

    if band == '2':
        if suffix in ['C', 'I']:
            return '#E53935'
        if suffix in ['W', 'P', 'Y']:
            return '#B71C1C'
        if suffix in ['L', 'S', 'X']:
            return '#FF6F00'
        if suffix in ['Q']:
            return '#FFB74D'
        if suffix in ['D']:
            return '#D32F2F'
        return '#F44336'

    if band == '5':
        if suffix in ['Q', 'X']:
            return '#388E3C'
        if suffix in ['I', 'D', 'A']:
            return '#1B5E20'
        if suffix in ['P']:
            return '#66BB6A'
        if suffix in ['B', 'C', 'Z']:
            return '#A5D6A7'
        return '#4CAF50'

    if band == '6':
        if suffix in ['I', 'S']:
            return '#7B1FA2'
        if suffix in ['Q', 'L']:
            return '#BA68C8'
        if suffix in ['X', 'E', 'Z']:
            return '#9C27B0'
        return '#9C27B0'

    if band == '7':
        if suffix in ['Q']:
            return '#F57C00'
        if suffix in ['I', 'D']:
            return '#FFB300'
        if suffix in ['X', 'P', 'Z']:
            return '#FFC107'
        if suffix in ['A', 'B']:
            return '#FFD54F'
        return '#FFC107'

    if band == '9':
        if suffix in ['A']:
            return '#00897B'
        if suffix in ['B', 'C']:
            return '#26A69A'
        if suffix in ['X']:
            return '#4DB6AC'
        return '#80CBC4'

    return '#9E9E9E'
