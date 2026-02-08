def get_sys_color(sys_char):
    """
    Return a predefined color (hex string) based on satellite system identifier.

    Parameters
    ----------
    sys_char : str
        Single-character system identifier:
        'G' = GPS, 'R' = GLONASS, 'E' = Galileo,
        'C' = BeiDou, 'J' = QZSS, 'S' = SBAS.

    Returns
    -------
    str
        Hex color code associated with the satellite system.
    """
    colors = {
        'G': '#5E8C61', # GPS - 森林绿 
        'R': '#B05E5E', # GLONASS - 铁锈红 
        'E': '#5B84B1', # Galileo - 钢青色 
        'C': '#8E77A4', # BeiDou - 灰紫色
        'J': '#C48D4D', # QZSS - 赭石色
        'S': '#7F8C8D'  # SBAS - 冷灰色
    }
    return colors.get(sys_char, '#555555')


def get_signal_color(sig_code):
    """
    Determine display color for a GNSS signal based on its frequency band
    and signal suffix (e.g., L1C, L2P, E5aQ).

    Parameters
    ----------
    sig_code : str or int
        Signal code containing frequency-band information (1, 2, 5, 6, 7/8)
        and a suffix letter identifying the modulation (e.g., C, P, Q, X).

    Logic
    -----
    - Extract the frequency band by checking digits (1/2/5/6/7/8).
    - Extract the first alphabetic character as the signal suffix.
    - Assign color based on band–suffix combinations commonly used in GNSS:
        L1 / B1 / E1
        L2 / G2 / E2
        L5 / E5 / B2
        L6 / B3
        E7 / E8 / B2a / B2b, etc.

    Returns
    -------
    str
        Hex color code representing this signal type for visualization.
    """
    code = str(sig_code).upper()
    band = '1'
    suffix = ''

    if '1' in code: band = '1'
    elif '2' in code: band = '2'
    elif '5' in code: band = '5'
    elif '6' in code: band = '6'
    elif '7' in code or '8' in code: band = '7'

    for char in code:
        if char.isalpha():
            suffix = char
            break

    # --- 蓝灰色系 (L1 / B1 / E1) ---
    if band == '1':
        if suffix in ['C', 'S', 'A']: return '#4A90E2'  # 柔和蓝
        if suffix in ['W', 'P', 'Y']: return '#34495E'  # 深蓝灰
        if suffix in ['L', 'X', 'Z']: return '#85ADDB'  # 浅钢蓝
        if suffix in ['I']:           return '#A9C1D9'  # 苍蓝
        return '#5D8AA8'

    # --- 砖红/陶土色系 (L2 / G2 / B2) ---
    elif band == '2':
        if suffix in ['C', 'I']:      return '#D96459'  # 柔和红
        if suffix in ['W', 'P', 'Y']: return '#8C4646'  # 深砖红
        if suffix in ['L', 'S', 'X']: return '#E39E82'  # 珊瑚色
        if suffix in ['Q']:           return '#F2C1B0'  # 浅陶色
        return '#C06C84'

    # --- 鼠尾草/橄榄绿系 (L5 / E5 / B2) ---
    elif band == '5':
        if suffix in ['Q', 'X']:      return '#73956F'  # 灰绿
        if suffix in ['I', 'D']:      return '#4A6741'  # 深苔藓绿
        if suffix in ['P']:           return '#9CB380'  # 浅橄榄
        if suffix in ['A']:           return '#C5D1B3'  # 苍绿
        return '#86A697'

    # --- 暮紫/板岩色系 (L6 / B3) ---
    elif band == '6':
        if suffix in ['I']:           return '#7D6E83'  # 灰紫
        if suffix in ['Q']:           return '#B0A4B5'  # 浅灰紫
        if suffix in ['X']:           return '#5E548E'  # 中紫
        return '#9B89B3'

    # --- 琥珀/麦秆色系 (E7 / E8 / B2) ---
    elif band == '7':
        if suffix in ['Q']:           return '#D4A373'  # 褐黄
        if suffix in ['I']:           return '#E9C46A'  # 芥末黄
        if suffix in ['X']:           return '#B5838D'  # 灰粉金
        if suffix in ['A', 'B']:      return '#F4E1D2'  # 极浅杏色
        return '#CCAC93'

    return '#95A5A6'  # 默认铝灰色
