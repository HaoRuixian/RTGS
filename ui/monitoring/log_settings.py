"""Dialog for configuring live observation logging output and file rotation."""

from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QPushButton,
                                 QCheckBox, QLabel, QHBoxLayout, QDialogButtonBox,
                                 QSpinBox, QListWidget, QGroupBox, QVBoxLayout, QRadioButton,
                                 QFrame, QTextEdit, QWidget, QListWidgetItem)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon, QColor
from PySide6.QtWidgets import QFileDialog, QStyle
from ui.responsive import adaptive_window_size
from core.global_config import get_global_config

# 定义全局样式
STYLESHEET = """
QDialog {
    background-color: #f5f7fa;
}

QGroupBox {
    font-weight: bold;
    border: 1px solid #d0d4d9;
    border-radius: 6px;
    margin-top: 0.9em;
    padding-top: 0.9em;
    padding-left: 10px;
    padding-right: 10px;
    padding-bottom: 8px;
    background-color: white;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 3px;
    color: #333;
    font-size: 11px;
}

QLineEdit, QSpinBox {
    border: 1px solid #d1d5da;
    border-radius: 3px;
    padding: 4px;
    background: white;
    height: 24px;
}

QLineEdit:focus, QSpinBox:focus {
    border: 1px solid #0366d6;
    background-color: #f0f8ff;
}

QPushButton#BrowseBtn {
    background-color: #f1f3f5;
    border: 1px solid #ced4da;
    border-radius: 3px;
    padding: 4px 10px;
    height: 24px;
}

QPushButton#BrowseBtn:hover {
    background-color: #e9ecef;
}

QListWidget {
    border: 1px solid #d1d5da;
    border-radius: 3px;
    background: white;
}

QListWidget::item {
    padding: 5px;
    border-bottom: 1px solid #f0f0f0;
}

QListWidget::item:selected {
    background-color: #e7f3ff;
    color: #0366d6;
}

/* 状态显示框 */
QTextEdit#LogInfo {
    background-color: #2b2b2b;
    color: #a9b7c6;
    border-radius: 4px;
    font-family: 'Consolas', 'Monaco', monospace;
    padding: 6px;
    font-size: 10px;
}

/* 标签文字大小 */
QLabel {
    color: #444;
    font-size: 10px;
}

QFormLayout {
    spacing: 2px;
}
"""

class LogSettingsDialog(QDialog):
    recording_toggled = Signal(bool)

    def __init__(self, parent=None, settings=None, is_recording=False):
        super().__init__(parent)
        self.setWindowTitle("Logging Configuration")
        self.setModal(True)
        adaptive_window_size(self, target=(680, 700), minimum=(500, 550))
        self.is_recording = is_recording
        self.setStyleSheet(STYLESHEET)

        # 主布局 - 更加紧凑的边距和间距
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(10)
        self.main_layout.setContentsMargins(15, 15, 15, 15)

        # --- 1. 存储设置 ---
        storage_group = QGroupBox("Storage Settings")
        storage_layout = QFormLayout()
        storage_layout.setVerticalSpacing(8)
        storage_layout.setHorizontalSpacing(10)
        
        # 目录
        self.dir_edit = QLineEdit()
        self.btn_browse = QPushButton("Browse")
        self.btn_browse.setObjectName("BrowseBtn")
        self.btn_browse.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.btn_browse.clicked.connect(self.browse)
        
        h_dir = QHBoxLayout()
        h_dir.addWidget(self.dir_edit)
        h_dir.addWidget(self.btn_browse)
        storage_layout.addRow("Save To:", h_dir)

        # 时间设置
        h_intervals = QHBoxLayout()
        h_intervals.setSpacing(8)
        self.split_spin = QSpinBox()
        self.split_spin.setRange(1, 1440)
        self.split_spin.setSuffix(" min")
        self.split_spin.setMaximumWidth(90)
        
        self.sample_spin = QSpinBox()
        self.sample_spin.setRange(1, 3600)
        self.sample_spin.setSuffix(" s")
        self.sample_spin.setMaximumWidth(90)
        
        h_intervals.addWidget(QLabel("Split:"))
        h_intervals.addWidget(self.split_spin)
        h_intervals.addSpacing(15)
        h_intervals.addWidget(QLabel("Interval:"))
        h_intervals.addWidget(self.sample_spin)
        h_intervals.addStretch()
        storage_layout.addRow("Timing:", h_intervals)
        
        storage_group.setLayout(storage_layout)
        self.main_layout.addWidget(storage_group)

        # --- 2. 格式与字段 ---
        format_group = QGroupBox("Format & Data Fields")
        format_vbox = QVBoxLayout()
        format_vbox.setSpacing(8)
        format_vbox.setContentsMargins(5, 5, 5, 5)
        
        h_radio = QHBoxLayout()
        h_radio.setSpacing(15)
        self.radio_csv = QRadioButton("CSV")
        self.radio_binary = QRadioButton("Binary RTCM")
        self.radio_rinex = QRadioButton("RINEX OBS")
        self.radio_rinex_nav = QRadioButton("RINEX NAV")
        self.radio_sp3 = QRadioButton("SP3 Precise")
        h_radio.addWidget(self.radio_csv)
        h_radio.addWidget(self.radio_binary)
        h_radio.addWidget(self.radio_rinex)
        h_radio.addWidget(self.radio_rinex_nav)
        h_radio.addWidget(self.radio_sp3)
        h_radio.addStretch()
        format_vbox.addLayout(h_radio)

        # CSV字段列表
        self.fields_container = QWidget()
        fields_vbox = QVBoxLayout(self.fields_container)
        fields_vbox.setContentsMargins(0, 3, 0, 0)
        fields_vbox.setSpacing(4)
        self.fields_label = QLabel("CSV Fields:")
        self.fields_label.setStyleSheet("color: #666; font-size: 10px; font-weight: bold;")
        
        self.fields_list = QListWidget()
        self.fields_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.fields_list.setMaximumHeight(95)
        default_fields = ["UTC Time", "PRN", "Sys", "El(°)", "Az(°)", "Freq", "SNR (dBHz)", "Pseudorange (m)", "Phase (cyc)", "Doppler (Hz)"]
        for f in default_fields:
            item = QListWidgetItem(f)
            self.fields_list.addItem(item)
            item.setSelected(True)
        
        fields_vbox.addWidget(self.fields_label)
        fields_vbox.addWidget(self.fields_list)
        format_vbox.addWidget(self.fields_container)
        
        # RINEX配置容器
        self.rinex_container = QWidget()
        rinex_vbox = QVBoxLayout(self.rinex_container)
        rinex_vbox.setContentsMargins(0, 3, 0, 0)
        rinex_vbox.setSpacing(6)
        
        # RINEX参数配置
        rinex_form = QFormLayout()
        rinex_form.setVerticalSpacing(6)
        rinex_form.setHorizontalSpacing(10)
        
        # Station ID - 从mountpoint自动生成，显示为标签
        self.station_label = QLabel("RTGS00")
        self.station_label.setStyleSheet("font-family: monospace; font-weight: bold;")
        rinex_form.addRow("Station ID (4+2):", self.station_label)
        
        # Country Code - 可编辑
        self.country_code_input = QLineEdit()
        self.country_code_input.setMaxLength(3)
        self.country_code_input.setPlaceholderText("e.g., CHN")
        self.country_code_input.setText("CHN")
        self.country_code_input.setMaximumWidth(80)
        rinex_form.addRow("Country Code:", self.country_code_input)
        
        # Data Type - 可编辑
        self.datatype_input = QLineEdit()
        self.datatype_input.setMaxLength(2)
        self.datatype_input.setPlaceholderText("e.g., MO")
        self.datatype_input.setText("MO")
        self.datatype_input.setMaximumWidth(80)
        rinex_form.addRow("Data Type:", self.datatype_input)
        
        rinex_vbox.addLayout(rinex_form)
        format_vbox.addWidget(self.rinex_container)
        
        format_group.setLayout(format_vbox)
        self.main_layout.addWidget(format_group)

        # --- 3. 录制控制区域 ---
        control_section = QGroupBox("Recording Control")
        control_layout = QVBoxLayout(control_section)
        control_layout.setContentsMargins(10, 8, 10, 8)
        control_layout.setSpacing(6)
        
        # 录制按钮
        self.btn_start_stop = QPushButton("Start Recording")
        self.btn_start_stop.setMinimumHeight(36)
        self.btn_start_stop.setMaximumWidth(150)
        self.btn_start_stop.clicked.connect(self.toggle_recording)
        control_layout.addWidget(self.btn_start_stop)
        
        # 录制日志信息
        self.recording_info = QTextEdit()
        self.recording_info.setObjectName("LogInfo")
        self.recording_info.setMaximumHeight(80)
        self.recording_info.setReadOnly(True)
        self.recording_info.setFont(QFont("Courier", 8))
        self.recording_info.setPlaceholderText("Recording logs will appear here...")
        control_layout.addWidget(self.recording_info)
        
        self.main_layout.addWidget(control_section)

        # --- 4. 底部关闭按钮 ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        self.button_box.layout().setContentsMargins(0, 4, 0, 0)
        self.main_layout.addWidget(self.button_box)

        # 信号连接
        self.radio_csv.toggled.connect(self.on_format_changed)
        self.radio_binary.toggled.connect(self.on_format_changed)
        self.radio_rinex.toggled.connect(self.on_format_changed)
        self.radio_rinex_nav.toggled.connect(self.on_format_changed)
        self.radio_sp3.toggled.connect(self.on_format_changed)
        
        # 自动同步RINEX参数
        self.split_spin.valueChanged.connect(self._update_rinex_period)
        self.sample_spin.valueChanged.connect(self._update_rinex_interval)
        
        # 初始化状态
        self.radio_csv.setChecked(True)
        if settings: self.load_settings(settings)
        self._update_station_id()  # 初始化station ID
        self.update_recording_state()

    def on_format_changed(self):
        """显示或隐藏字段选择器和RINEX配置面板"""
        is_csv = self.radio_csv.isChecked()
        is_rinex = self.radio_rinex.isChecked()
        
        self.fields_container.setVisible(is_csv)
        self.rinex_container.setVisible(is_rinex)
        self.adjustSize()

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d: self.dir_edit.setText(d)
    
    def _update_station_id(self):
        """从OBS配置的mountpoint自动生成station ID（4+2）"""
        try:
            config = get_global_config()
            mountpoint = getattr(config.obs_settings, 'mountpoint', '')
            
            if mountpoint:
                # 从mountpoint名称中提取前4个字符作为station code
                station_code = (mountpoint[:4] if len(mountpoint) >= 4 else mountpoint).upper().ljust(4, 'X')
                # 第5-6位为receiver number，默认为00
                receiver_no = "00"
            else:
                station_code = "RTGS"
                receiver_no = "00"
            
            station_id = f"{station_code}{receiver_no}"
            self.station_label.setText(station_id)
        except Exception:
            self.station_label.setText("RTGS00")
    
    def _update_rinex_period(self, value):
        """同步RINEX Period和Split值"""
        # Split值单位为分钟，应该转换为RINEX Period格式（01D表示1天）
        if value >= 1440:  # 1440分钟 = 1天
            period = "01D"
        elif value >= 60:  # 60分钟 = 1小时
            hours = value // 60
            period = f"{hours:02d}H"
        else:  # 分钟
            period = f"{value:02d}M"
        # 这里不需要存储period，因为它从split自动计算
    
    def _update_rinex_interval(self, value):
        """同步RINEX Interval和Timing Interval值"""
        # Sample_spin值单位为秒，应该转换为RINEX Interval格式（30S表示30秒）
        # 这里不需要存储interval，因为它从sample_spin自动计算
        pass

    def toggle_recording(self):
        self.is_recording = not self.is_recording
        self.recording_toggled.emit(self.is_recording)
        self.update_recording_state()

    def update_recording_state(self):
        """核心美化逻辑：根据录制状态改变 UI 风格"""
        if self.is_recording:
            # 录制中样式 (红色/停止)
            style = """
                QPushButton {
                    background-color: #ebedef;
                    color: #d73a49;
                    border: 2px solid #d73a49;
                    border-radius: 6px;
                }
                QPushButton:hover { background-color: #ffeef0; }
            """
            self.btn_start_stop.setText(" STOP RECORDING")
            self.btn_start_stop.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
            self.set_widgets_enabled(False)
        else:
            # 停止中样式 (绿色/开始)
            style = """
                QPushButton {
                    background-color: #2ea44f;
                    color: white;
                    border: none;
                    border-radius: 6px;
                }
                QPushButton:hover { background-color: #2c974b; }
                QPushButton:pressed { background-color: #298e46; }
            """
            self.btn_start_stop.setText(" START RECORDING")
            self.btn_start_stop.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.set_widgets_enabled(True)
        
        self.btn_start_stop.setStyleSheet(style)

    def set_widgets_enabled(self, enabled):
        """批量控制设置组件的可编辑性"""
        self.dir_edit.setEnabled(enabled)
        self.btn_browse.setEnabled(enabled)
        self.split_spin.setEnabled(enabled)
        self.sample_spin.setEnabled(enabled)
        self.radio_csv.setEnabled(enabled)
        self.radio_binary.setEnabled(enabled)
        self.radio_rinex.setEnabled(enabled)
        self.radio_rinex_nav.setEnabled(enabled)
        self.radio_sp3.setEnabled(enabled)
        self.fields_list.setEnabled(enabled)
        self.country_code_input.setEnabled(enabled)
        self.datatype_input.setEnabled(enabled)

    def update_recording_info(self, text):
        self.recording_info.append(f"> {text}")
        # 自动滚动到底部
        self.recording_info.verticalScrollBar().setValue(
            self.recording_info.verticalScrollBar().maximum()
        )

    def load_settings(self, s):
        self.dir_edit.setText(s.get("directory", ""))
        self.split_spin.setValue(s.get("split_minutes", 60))
        self.sample_spin.setValue(s.get("sample_interval", 1))
        fmt = s.get("format", "csv")
        if fmt == "csv": self.radio_csv.setChecked(True)
        elif fmt == "binary": self.radio_binary.setChecked(True)
        elif fmt == "rinex": self.radio_rinex.setChecked(True)
        elif fmt == "rinex_nav": self.radio_rinex_nav.setChecked(True)
        elif fmt == "sp3": self.radio_sp3.setChecked(True)
        
        # Load RINEX options
        rinex_opts = s.get("rinex_options", {})
        self.country_code_input.setText(rinex_opts.get("country_code", "CHN"))
        self.datatype_input.setText(rinex_opts.get("datatype", "MO"))

    def get_settings(self):
        fmt = "csv"
        if self.radio_binary.isChecked(): fmt = "binary"
        elif self.radio_rinex.isChecked(): fmt = "rinex"
        elif self.radio_rinex_nav.isChecked(): fmt = "rinex_nav"
        elif self.radio_sp3.isChecked(): fmt = "sp3"
        
        settings = {
            "directory": self.dir_edit.text(),
            "split_minutes": self.split_spin.value(),
            "sample_interval": self.sample_spin.value(),
            "format": fmt,
            "fields": [it.text() for it in self.fields_list.selectedItems()]
        }
        
        # Add RINEX options
        if fmt == "rinex":
            # 从station_label中提取station code和receiver number（自动生成）
            station_id = self.station_label.text()
            station_code = station_id[:4] if len(station_id) >= 4 else "RTGS"
            receiver_number = station_id[4:6] if len(station_id) >= 6 else "00"
            
            # 从split自动生成period
            split_min = self.split_spin.value()
            if split_min >= 1440:
                period = "01D"
            elif split_min >= 60:
                hours = split_min // 60
                period = f"{hours:02d}H"
            else:
                period = f"{split_min:02d}M"
            
            # 从sample_spin生成interval
            sample_sec = self.sample_spin.value()
            if sample_sec >= 60:
                minutes = sample_sec // 60
                interval = f"{minutes:02d}M"
            else:
                interval = f"{sample_sec:02d}S"
            
            settings["rinex_options"] = {
                "station_code": station_code,
                "receiver_number": receiver_number,
                "country_code": self.country_code_input.text() or "CHN",
                "period": period,
                "interval": interval,
                "datatype": self.datatype_input.text() or "MO"
            }
        
        return settings
