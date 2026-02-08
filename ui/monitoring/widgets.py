# ui/widgets.py
import numpy as np
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from matplotlib.ticker import ScalarFormatter, MaxNLocator
from collections import defaultdict
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QApplication
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar


from ui.gnss_colordef import get_sys_color, get_signal_color

class SkyplotWidget(FigureCanvas):
    def __init__(self, parent=None):
        palette = QApplication.palette()
        is_dark = palette.color(palette.ColorRole.Window).lightness() < 128
        
        self.theme = {
            'bg': "#161A23" if is_dark else "#FFFFFF",
            'fg': "#B1B6BC" if is_dark else "#0F172A",
            'grid': "#1D2435" if is_dark else "#CBD5E1",
            'accent': "#1D2E4A",
            'text_muted': "#94A3B8"
        }

        self.fig = Figure(figsize=(4, 4), dpi=100, facecolor=self.theme['bg'])
        self.ax = self.fig.add_subplot(111, projection='polar')
        
        super().__init__(self.fig)
        self.setParent(parent)
        self.init_plot()
        
        self.scatter_artists = []
        self.text_artists = []

    def init_plot(self):
        ax = self.ax
        ax.set_facecolor(self.theme['bg'])
        
        # 方向设置：北向上，顺时针
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        
        # 设置仰角范围 (0-90)
        ax.set_rlim(90, 0)
        ax.set_yticks([0, 30, 60, 90])
        ax.set_yticklabels(['90°', '60°', '30°', '0°'], 
                           fontsize=8, color=self.theme['text_muted'])
        
        # 设置方位角标签 (N, E, S, W)
        ax.set_thetagrids([0, 45, 90, 135, 180, 225, 270, 315], 
                          ['N', '45', 'E', '135', 'S', '225', 'W', '315'],
                          fontsize=9, fontweight='bold', color=self.theme['fg'])

        # 网格线美化
        ax.grid(True, color=self.theme['grid'], linestyle='--', linewidth=1, alpha=0.5)
        
        # 隐藏最外圈的圆框线
        ax.spines['polar'].set_visible(False)
        
        # 标题样式
        ax.set_title("SATELLITE SKYPLOT", pad=20, fontsize=10, 
                     fontweight='bold', color=self.theme['accent'], alpha=0.8)

        # 预先绘制一个半透明的底色
        ax.fill(np.linspace(0, 2*np.pi, 100), np.full(100, 90), 
                color=self.theme['accent'], alpha=0.03)

    def update_satellites(self, satellites, active_systems):
        while self.scatter_artists:
            self.scatter_artists.pop().remove()
        while self.text_artists:
            self.text_artists.pop().remove()
            
        satellites_snapshot = dict(satellites)
        
        for key, sat in satellites_snapshot.items():
            sys_type = key[0]
            if sys_type not in active_systems: continue

            el = getattr(sat, "el", getattr(sat, "elevation", None))
            az = getattr(sat, "az", getattr(sat, "azimuth", None))
            
            if el is not None and az is not None:
                color = get_sys_color(sys_type)
                
                # 绘制卫星点：增加边缘颜色使其更有立体感
                scatter = self.ax.scatter(
                    np.radians(az), el, 
                    c=color, s=120, 
                    alpha=0.9, 
                    edgecolors=self.theme['bg'], 
                    linewidth=1.5,
                    zorder=3
                )
                
                # 卫星编号文字：放在圆点中心或略偏移
                text = self.ax.text(
                    np.radians(az), el, key, 
                    fontsize=7, 
                    ha='center', va='center', 
                    fontweight='bold',
                    color='white' if self.theme['bg'] != "#FFFFFF" else 'black',
                    clip_on=True,
                    zorder=4
                )
                
                self.scatter_artists.append(scatter)
                self.text_artists.append(text)
        
        self.draw_idle()

class MultiSignalBarWidget(FigureCanvas):
    def __init__(self, parent=None):
        palette = QApplication.palette()
        is_dark = palette.color(palette.ColorRole.Window).lightness() < 128
        
        self.theme = {
            'bg': "#161A23" if is_dark else "#FFFFFF",
            'fg': "#E2E8F0" if is_dark else "#0F172A",
            'grid': "#1A1E29" if is_dark else "#CBD5E1",
            'muted': "#000000"
        }

        # 增加 figsize 的高度比例，为底部图例留出空间
        self.fig = Figure(figsize=(8, 5), dpi=100, facecolor=self.theme['bg'])
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        
        # 预留底部空间给 X 轴标签和图例
        self.fig.subplots_adjust(bottom=0.25, top=0.92, left=0.07, right=0.97)
        
        self.bar_artists = []
        self.init_plot()

    def init_plot(self):
        ax = self.ax
        ax.set_facecolor(self.theme['bg'])
        ax.set_ylim(0, 60)
        ax.set_ylabel("SNR (dB-Hz)", color=self.theme['muted'], fontsize=10, fontweight='bold')
        
        # 绘制背景色带（增强学术感：区分强弱信号）
        ax.axhspan(0, 30, color='#FF0000', alpha=0.05)   # 弱信号区
        ax.axhspan(30, 45, color='#FFA500', alpha=0.03)  # 中等信号
        ax.axhspan(45, 60, color='#00FF00', alpha=0.05)  # 强信号区

        ax.grid(True, axis='y', color=self.theme['grid'], linestyle='--', alpha=0.4)
        
        # 隐藏上方和右侧边框
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(self.theme['grid'])
        ax.spines['bottom'].set_color(self.theme['grid'])
        
        ax.tick_params(colors=self.theme['muted'], labelsize=9)

    def update_data(self, satellites, active_systems):
        self.ax.clear()
        self.init_plot() # 重新初始化背景和设置
        self.bar_artists.clear()
        
        satellites_snapshot = dict(satellites)
        valid_sats = {k: v for k, v in satellites_snapshot.items() if k[0] in active_systems}
        sorted_keys = sorted(valid_sats.keys())
        
        if not sorted_keys:
            self.ax.text(0.5, 0.5, "Waiting for GNSS data...", 
                         ha='center', va='center', transform=self.ax.transAxes,
                         color=self.theme['muted'], fontsize=12)
            self.draw_idle()
            return

        # 假设每个卫星占据 0.8 的单位宽度，根据信号数量平分
        num_sats = len(sorted_keys)
        x_indices = np.arange(num_sats)
        
        # 收集数据
        sig_plot_data = defaultdict(list)
        all_signals = set()
        
        # 找出每个卫星拥有的最大信号数量，以确定基础柱宽
        max_sigs_in_any_sat = 1
        for sat in valid_sats.values():
            valid_count = len([c for c, s in sat.signals.items() if getattr(s, 'snr', 0) > 0])
            max_sigs_in_any_sat = max(max_sigs_in_any_sat, valid_count)

        # 计算柱宽：保证在卫星很多时，柱子依然有最小宽度
        # 0.8 是组间距比例，max_sigs 决定组内细分
        total_group_width = 0.8
        bar_width = total_group_width / max(max_sigs_in_any_sat, 1)
        # 限制最小宽度，防止卫星过多时看不见
        bar_width = max(bar_width, 0.05) 

        # 2. 分配位置
        for i, k in enumerate(sorted_keys):
            sat = valid_sats[k]
            # 获取 SNR > 0 的有效信号
            sigs = {c: s.snr for c, s in sat.signals.items() if getattr(s, 'snr', 0) > 0}
            sorted_codes = sorted(sigs.keys())
            
            n_sigs = len(sorted_codes)
            # 计算该组信号的起始偏移位置，使其居中对齐刻度
            start_offset = - (n_sigs * bar_width) / 2 + (bar_width / 2)
            
            for j, code in enumerate(sorted_codes):
                offset = start_offset + j * bar_width
                sig_plot_data[code].append((i + offset, sigs[code]))
                all_signals.add(code)

        # 3. 绘制
        sorted_all_signals = sorted(list(all_signals))
        legend_handles = []
        
        for code in sorted_all_signals:
            points = sig_plot_data[code]
            x_vals = [p[0] for p in points]
            y_vals = [p[1] for p in points]
            
            color = get_signal_color(code)
            
            # 使用更细的边框，颜色深一点，看起来更精致
            bars = self.ax.bar(x_vals, y_vals, width=bar_width, color=color, 
                             alpha=0.85, edgecolor=self.theme['bg'], linewidth=0.3,
                             label=code)
            legend_handles.append(bars)

        # 4. 更新坐标轴标签
        self.ax.set_xticks(x_indices)
        self.ax.set_xticklabels(sorted_keys, rotation=90, color=self.theme['fg'], fontsize=8)
        
        # 5. 改进图例布局：放置在 Axes 之外的底部
        if legend_handles:
            # 根据信号数量动态调整列数
            ncol = min(len(legend_handles), 10)
            self.ax.legend(
                loc='upper center', 
                bbox_to_anchor=(0.5, -0.18), # 关键：将图例移出绘图区，放置在下方
                ncol=ncol, 
                fontsize=8, 
                frameon=False,
                handletextpad=0.4,
                columnspacing=1.0,
                labelcolor=self.theme['muted']
            )

        self.draw_idle()


class PlotSNRWidget(QWidget):
    """
    修改后的绘图组件：
    1. 继承自 QWidget 而不是 FigureCanvas，以便同时容纳工具栏(Toolbar)和画布(Canvas)。
    2. 支持 sin(Elevation) 模式。
    3. 解决了 Title 和 Legend 重叠问题。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 1. 创建垂直布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 2. 初始化 Matplotlib 画布
        self.fig = Figure(figsize=(5, 4), dpi=100, facecolor='#ffffff')
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        
        # 设置布局调整，预留顶部空间给 Legend 和 Title
        # top=0.85 留出 15% 的顶部空间
        self.fig.subplots_adjust(bottom=0.15, top=0.85, left=0.12, right=0.95)

        # 3. 初始化导航工具栏 (实现缩放、平移的关键)
        self.toolbar = NavigationToolbar(self.canvas, self)

        # 4. 添加到布局：工具栏在上，画布在下
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        
        # 设置策略，让画布尽可能扩展
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def update_plot(self, prn, data, mode, signal: str = None):
        """
        mode: "Time Sequence", "Elevation", "sin(Elevation)"
        优化：只更新数据，不重建坐标轴
        """
        # 删除旧的绘图对象
        for line in self.ax.lines:
            line.remove()
        for collection in self.ax.collections:
            collection.remove()
        
        if not data:
            self.canvas.draw_idle()
            return

        # --- 数据预处理：过滤高度角 <= 0 的数据 ---
        # 如果是高度角相关模式，我们通常不看地平线以下的数据
        valid_data = []
        for d in data:
            # 如果模式是高度角相关，且高度角为 None、0 或负，则跳过
            if ("Elevation" in mode or "sin" in mode):
                el = d.get('el')
                if el is None or el <= 0:
                    continue
            valid_data.append(d)
        
        # 如果过滤完没数据了，直接返回
        if not valid_data:
            self.canvas.draw_idle()
            return

        # 提取所有出现的信号（可选按单个 signal 过滤）
        all_sigs = set()
        for d in valid_data:
            all_sigs.update(d['snr'].keys())
        sorted_sigs = sorted(all_sigs)
        if signal and signal != "All":
            # 如果所选 signal 不在出现的集合中，仍然保留但会导致无点绘制
            sorted_sigs = [signal]

        # 提取基础列表
        times = [d['time'] for d in valid_data]
        els = [d['el'] for d in valid_data] # 角度制

        # --- 绘图逻辑 ---
        plotted_any = False
        all_y_vals = []
        for sig in sorted_sigs:
            vals = [d['snr'].get(sig, np.nan) for d in valid_data]
            # 收集用于 autoscale 的 y 值（去掉 nan）
            clean_vals = [v for v in vals if v is not None and not (isinstance(v, float) and np.isnan(v))]
            if clean_vals:
                all_y_vals.extend(clean_vals)
                plotted_any = True
            color = get_signal_color(sig) # 确保你有引入这个函数

            if "Time" in mode:
                self.ax.plot(times, vals, '.-', markersize=3, label=sig, color=color, linewidth=1)

            elif "sin" in mode:
                x_vals = np.sin(np.radians(els))
                self.ax.plot(x_vals, vals, '.-', markersize=3, label=sig, color=color, linewidth=1, alpha=0.8)

            else:
                # Elevation mode: draw line+points for readability
                self.ax.plot(els, vals, '.-', markersize=3, label=sig, color=color, linewidth=1, alpha=0.8)

        # --- 更新 X 轴格式（不重建）---
        if "Time" in mode:
            # Use date formatter and auto locator for time axis
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            try:
                self.ax.xaxis_date(True)
            except Exception:
                pass
            self.ax.set_xlabel("Time")

        elif "sin" in mode:
            # Numeric axis for sin(Elevation)
            self.ax.xaxis.set_major_formatter(ScalarFormatter())
            self.ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
            try:
                self.ax.xaxis_date(False)
            except Exception:
                pass
            self.ax.set_xlabel("sin(Elevation)")

        else:
            # Elevation numeric axis
            self.ax.xaxis.set_major_formatter(ScalarFormatter())
            self.ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
            try:
                self.ax.xaxis_date(False)
            except Exception:
                pass
            self.ax.set_xlabel("Elevation (°)")
        # --- 更新通用属性（不重建）---
        self.ax.set_ylabel("SNR (dB-Hz)")

        # Autoscale Y based on plotted data (with small padding)
        try:
            if plotted_any and all_y_vals:
                y_min = float(np.min(all_y_vals))
                y_max = float(np.max(all_y_vals))
                if y_min == y_max:
                    # Single value - provide a small range
                    pad = 3.0
                else:
                    pad = max(3.0, 0.08 * (y_max - y_min))
                self.ax.set_ylim(max(0.0, y_min - pad), y_max + pad)
            else:
                # No data: set a reasonable default
                self.ax.set_ylim(0, 60)
        except Exception:
            self.ax.set_ylim(0, 60)

        # Autoscale X depending on mode
        try:
            if "Time" in mode and times:
                # If only a single time point, expand a little around it
                if len(times) == 1:
                    t = mdates.date2num(times[0])
                    delta = 1.0 / (24*60*60) * 5  # 5 seconds
                    self.ax.set_xlim(t - delta, t + delta)
                else:
                    self.ax.set_xlim(mdates.date2num(times[0]), mdates.date2num(times[-1]))
            elif ("sin" in mode) and els:
                x_vals = np.sin(np.radians(els))
                xmin, xmax = np.min(x_vals), np.max(x_vals)
                if xmin == xmax:
                    self.ax.set_xlim(xmin - 0.01, xmax + 0.01)
                else:
                    self.ax.set_xlim(xmin, xmax)
            elif els:
                xmin, xmax = np.min(els), np.max(els)
                if xmin == xmax:
                    self.ax.set_xlim(xmin - 1.0, xmax + 1.0)
                else:
                    self.ax.set_xlim(xmin, xmax)
        except Exception:
            pass

        self.ax.set_title(f"Satellite: {prn}", y=1.12, fontsize=10, fontweight='bold')
        
        # 网格只设置一次，不需要每次更新
        if not hasattr(self, '_grid_initialized'):
            self.ax.grid(True, linestyle=':', alpha=0.6)
            self._grid_initialized = True

        # 更新图例
        if self.ax.legend_:
            self.ax.legend_.remove()
        self.ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.02), 
                       ncol=6, fontsize='small', frameon=False)
        
        # 性能优化：使用draw_idle而不是draw，更高效
        self.canvas.draw_idle()


class SatelliteNumWidget(FigureCanvas):
    """Real-time satellite count statistics over time."""
    
    def __init__(self, parent=None):
        palette = QApplication.palette()
        is_dark = palette.color(palette.ColorRole.Window).lightness() < 128
        
        self.theme = {
            'bg': "#161A23" if is_dark else "#FFFFFF",
            'fg': "#B1B6BC" if is_dark else "#0F172A",
            'grid': "#1D2435" if is_dark else "#CBD5E1",
            'text': "#E2E8F0" if is_dark else "#1E293B",
            'text_muted': "#94A3B8"
        }
        
        self.fig = Figure(figsize=(5, 2.2), dpi=100, facecolor=self.theme['bg'])
        self.ax = self.fig.add_subplot(111)
        
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumHeight(150)
        
        # 系统配置
        self.systems = {
            'G': 'GPS',
            'R': 'GLONASS',
            'E': 'Galileo',
            'C': 'BeiDou',
            'J': 'QZSS',
            'S': 'SBAS'
        }
        self.colors = {sys: get_sys_color(sys) for sys in self.systems.keys()}
        
        # 时间序列存储（保持最近60秒的数据）- 必须在init_plot()之前定义
        self.time_history = []
        self.sat_history = {sys: [] for sys in self.systems.keys()}
        self.max_history = 60*60  
        
        # 初始化图表
        self.init_plot()
        
    def init_plot(self):
        """初始化图表"""
        ax = self.ax
        ax.set_facecolor(self.theme['bg'])
        
        # 设置X轴（时间）
        ax.set_xlim(0, self.max_history)
        ax.set_xlabel("Time (s)", fontsize=9, color=self.theme['text_muted'])
        
        # 设置Y轴
        ax.set_ylabel("Count", fontsize=9, color=self.theme['text_muted'])
        ax.set_ylim(0, 40)
        ax.tick_params(colors=self.theme['text_muted'], labelsize=8)
        
        # 网格
        ax.grid(True, linestyle=':', alpha=0.3, color=self.theme['grid'])
        ax.set_axisbelow(True)
        
        # 移除顶部和右侧spine
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(self.theme['grid'])
        ax.spines['bottom'].set_color(self.theme['grid'])
        
        self.fig.tight_layout()
        
    def update_data(self, satellites_dict, active_systems):
        """
        更新统计数据
        
        Args:
            satellites_dict: {PRN: SatData, ...}
            active_systems: set of active system chars {'G', 'R', 'E', ...}
        """
        from datetime import datetime
        
        # 统计各系统卫星数
        sys_counts = {sys: 0 for sys in self.systems.keys()}
        total_count = 0
        
        for prn, sat in satellites_dict.items():
            sys_char = prn[0]
            if sys_char in sys_counts:
                sys_counts[sys_char] += 1
                total_count += 1
        
        # 添加时间点到历史
        current_time = datetime.now()
        self.time_history.append(current_time)
        for sys in self.systems.keys():
            self.sat_history[sys].append(sys_counts[sys])
        
        # 限制历史长度
        if len(self.time_history) > self.max_history:
            self.time_history.pop(0)
            for sys in self.systems.keys():
                self.sat_history[sys].pop(0)
        
        # 清空但保留坐标轴配置，重新绘制（不调用init_plot）
        self.ax.clear()
        self.ax.set_facecolor(self.theme['bg'])
        self.ax.set_xlabel("Time (s)", fontsize=9, color=self.theme['text_muted'])
        self.ax.set_ylabel("Count", fontsize=9, color=self.theme['text_muted'])
        self.ax.tick_params(colors=self.theme['text_muted'], labelsize=8)
        self.ax.grid(True, linestyle=':', alpha=0.3, color=self.theme['grid'])
        self.ax.set_axisbelow(True)
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        self.ax.spines['left'].set_color(self.theme['grid'])
        self.ax.spines['bottom'].set_color(self.theme['grid'])
        
        # 绘制每个系统的折线
        active_sys_list = [sys for sys in self.systems.keys() if sys in active_systems]
        
        if len(self.time_history) > 0:
            x_time = np.arange(len(self.time_history))
            
            # 使用面积图展示，自下而上堆叠
            bottom = np.zeros(len(self.time_history))
            
            for sys in active_sys_list:
                counts = np.array(self.sat_history[sys])
                
                # 绘制面积（填充）
                self.ax.fill_between(x_time, bottom, bottom + counts, 
                                    label=self.systems[sys],
                                    color=self.colors[sys], 
                                    alpha=0.2, edgecolor='none')
                
                # 在上边界绘制折线
                self.ax.plot(x_time, bottom + counts,
                           color=self.colors[sys],
                           linewidth=0.5, alpha=0.9)
                
                bottom += counts
            
            # 计算最大值并设置Y轴范围
            max_total = np.max(bottom) if len(bottom) > 0 else 10
            y_max = max(40, int(max_total * 1.2))
            self.ax.set_ylim(0, y_max)
            
            # 设置X轴范围
            self.ax.set_xlim(0, len(x_time))
            
            # 设置Y轴刻度
            step = max(5, int(y_max / 8))
            y_ticks = range(0, y_max + 1, step)
            self.ax.set_yticks(y_ticks)
                        
            # 在右下角显示总数
            total_text = f'Total: {int(bottom[-1])}'
            self.ax.text(0.98, 0.05, total_text, transform=self.ax.transAxes,
                        fontsize=7, fontweight='bold', color=self.theme['text'],
                        horizontalalignment='right',
                        bbox=dict(boxstyle='round', facecolor=self.theme['grid'], 
                                 alpha=0.8, edgecolor='none', pad=1.5))
        else:
            self.ax.set_ylim(0, 40)
        
        self.fig.tight_layout()
        self.draw_idle()