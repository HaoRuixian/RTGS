from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QPushButton,
                                 QCheckBox, QLabel, QHBoxLayout, QDialogButtonBox,
                                 QSpinBox, QListWidget, QGroupBox, QVBoxLayout, QRadioButton,
                                 QFrame, QTextEdit, QWidget, QListWidgetItem)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon, QColor
from PySide6.QtWidgets import QFileDialog, QStyle

# 定义全局样式
STYLESHEET = """
QDialog {
    background-color: #f5f7fa;
}

QGroupBox {
    font-weight: bold;
    border: 2px solid #e1e4e8;
    border-radius: 8px;
    margin-top: 1.2em;
    padding-top: 1.2em;
    background-color: white;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #444;
}

QLineEdit, QSpinBox {
    border: 1px solid #d1d5da;
    border-radius: 4px;
    padding: 6px;
    background: white;
}

QLineEdit:focus, QSpinBox:focus {
    border: 2px solid #0366d6;
}

QPushButton#BrowseBtn {
    background-color: #f1f3f5;
    border: 1px solid #ced4da;
    border-radius: 4px;
    padding: 5px 12px;
}

QPushButton#BrowseBtn:hover {
    background-color: #e9ecef;
}

QListWidget {
    border: 1px solid #d1d5da;
    border-radius: 4px;
    background: white;
}

QListWidget::item {
    padding: 8px;
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
    border-radius: 6px;
    font-family: 'Consolas', 'Monaco', monospace;
    padding: 8px;
}
"""

class LogSettingsDialog(QDialog):
    recording_toggled = Signal(bool)

    def __init__(self, parent=None, settings=None, is_recording=False):
        super().__init__(parent)
        self.setWindowTitle("Data Logging Config")
        self.setModal(True)
        self.resize(550, 700)
        self.is_recording = is_recording
        self.setStyleSheet(STYLESHEET)

        # 主布局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(15)
        self.main_layout.setContentsMargins(20, 20, 20, 20)

        # --- 1. 存储设置 ---
        storage_group = QGroupBox("Storage Settings")
        storage_layout = QFormLayout()
        storage_layout.setVerticalSpacing(12)
        
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
        self.split_spin = QSpinBox()
        self.split_spin.setRange(1, 1440)
        self.split_spin.setSuffix(" min")
        
        self.sample_spin = QSpinBox()
        self.sample_spin.setRange(1, 3600)
        self.sample_spin.setSuffix(" s")
        
        h_intervals.addWidget(QLabel("Split:"))
        h_intervals.addWidget(self.split_spin)
        h_intervals.addSpacing(20)
        h_intervals.addWidget(QLabel("Interval:"))
        h_intervals.addWidget(self.sample_spin)
        storage_layout.addRow("Timing:", h_intervals)
        
        storage_group.setLayout(storage_layout)
        self.main_layout.addWidget(storage_group)

        # --- 2. 格式与字段 ---
        format_group = QGroupBox("Format & Data Fields")
        format_vbox = QVBoxLayout()
        
        h_radio = QHBoxLayout()
        self.radio_csv = QRadioButton("CSV")
        self.radio_binary = QRadioButton("Binary RTCM")
        self.radio_rinex = QRadioButton("RINEX")
        h_radio.addWidget(self.radio_csv)
        h_radio.addWidget(self.radio_binary)
        h_radio.addWidget(self.radio_rinex)
        format_vbox.addLayout(h_radio)

        # 字段列表
        self.fields_container = QWidget()
        fields_vbox = QVBoxLayout(self.fields_container)
        fields_vbox.setContentsMargins(0, 5, 0, 0)
        self.fields_label = QLabel("Select fields to include in CSV:")
        self.fields_label.setStyleSheet("color: #666; font-size: 11px;")
        
        self.fields_list = QListWidget()
        self.fields_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        default_fields = ["PRN", "Sys", "El(°)", "Az(°)", "Freq", "SNR (dBHz)", "Pseudorange (m)", "Phase (cyc)", "Doppler (Hz)"]
        for f in default_fields:
            item = QListWidgetItem(f)
            self.fields_list.addItem(item)
            item.setSelected(True)
        
        fields_vbox.addWidget(self.fields_label)
        fields_vbox.addWidget(self.fields_list)
        format_vbox.addWidget(self.fields_container)
        
        format_group.setLayout(format_vbox)
        self.main_layout.addWidget(format_group)

        # --- 3. 录制控制区域 ---
        control_section = QVBoxLayout()
        
        # 录制状态显示
        self.status_bar = QFrame()
        self.status_bar.setFixedHeight(4)
        self.status_bar.setStyleSheet("background-color: #e1e4e8; border-radius: 2px;")
        control_section.addWidget(self.status_bar)

        self.btn_start_stop = QPushButton("Start Recording")
        self.btn_start_stop.setMinimumHeight(50)
        self.btn_start_stop.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.btn_start_stop.clicked.connect(self.toggle_recording)
        control_section.addWidget(self.btn_start_stop)

        self.recording_info = QTextEdit()
        self.recording_info.setObjectName("LogInfo")
        self.recording_info.setMaximumHeight(120)
        self.recording_info.setReadOnly(True)
        self.recording_info.setPlaceholderText("Recording logs will appear here...")
        control_section.addWidget(self.recording_info)
        
        self.main_layout.addLayout(control_section)

        # --- 4. 底部关闭按钮 ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        self.main_layout.addWidget(self.button_box)

        # 信号连接
        self.radio_csv.toggled.connect(self.on_format_changed)
        
        # 初始化状态
        self.radio_csv.setChecked(True)
        if settings: self.load_settings(settings)
        self.update_recording_state()

    def on_format_changed(self):
        """显示或隐藏字段选择器并平滑调整窗口高度"""
        is_csv = self.radio_csv.isChecked()
        self.fields_container.setVisible(is_csv)
        self.adjustSize()

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d: self.dir_edit.setText(d)

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
            self.status_bar.setStyleSheet("background-color: #28a745; border-radius: 2px;") # 录制时进度条变绿（或闪烁）
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
            self.status_bar.setStyleSheet("background-color: #e1e4e8; border-radius: 2px;")
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
        self.fields_list.setEnabled(enabled)

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

    def get_settings(self):
        fmt = "csv"
        if self.radio_binary.isChecked(): fmt = "binary"
        elif self.radio_rinex.isChecked(): fmt = "rinex"
        
        return {
            "directory": self.dir_edit.text(),
            "split_minutes": self.split_spin.value(),
            "sample_interval": self.sample_spin.value(),
            "format": fmt,
            "fields": [it.text() for it in self.fields_list.selectedItems()]
        }