import importlib.util
import yaml
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QGroupBox, QFormLayout, 
                             QLineEdit, QCheckBox, QHBoxLayout, QPushButton, 
                             QFileDialog, QMessageBox, QStyle, QComboBox, QLabel,
                             QSpinBox, QScrollArea, QWidget, QDoubleSpinBox, QSizePolicy)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
from core.config_paths import CONFIG_ROOT, DEFAULT_STREAM_SAVE_NAME, STREAM_CONFIG_DIR, ensure_config_directories
from ui.responsive import adaptive_window_size

class ConfigDialog(QDialog):
    def __init__(self, parent=None, initial_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Data Source Settings")
        adaptive_window_size(self, target=(460, 600), minimum=(460, 520))
        self.settings = initial_settings or {}
        # Flag set when user clicked Connect (auto-connect requested)
        self.auto_connect = False
        # Flag set when user requested a disconnect without clearing saved settings
        self.disconnect_requested = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Create scroll area for better usability
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(10)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        
        # =====================================================================
        # OBS Stream Configuration
        # =====================================================================
        grp_obs = QGroupBox("Observation Stream (OBS)")
        fl_obs = QFormLayout()
        fl_obs.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        fl_obs.setRowWrapPolicy(QFormLayout.DontWrapRows)
        fl_obs.setFormAlignment(Qt.AlignHCenter | Qt.AlignTop)
        fl_obs.setLabelAlignment(Qt.AlignLeft)
        
        # Data source type selector
        self.obs_source = QComboBox()
        self.obs_source.addItems(["NTRIP Server", "Serial Port", "RINEX File"])
        obs_source_val = self.settings.get('OBS', {}).get('source', 'NTRIP Server')
        self.obs_source.setCurrentText(obs_source_val)
        self.obs_source.currentTextChanged.connect(self.on_obs_source_changed)
        fl_obs.addRow("Data Source:", self.obs_source)
        
        # NTRIP fields
        self.obs_h = QLineEdit(self.settings.get('OBS', {}).get('host',''))
        self.obs_p = QLineEdit(str(self.settings.get('OBS', {}).get('port','2101')))
        self.obs_m = QLineEdit(self.settings.get('OBS', {}).get('mountpoint',''))
        self.obs_u = QLineEdit(self.settings.get('OBS', {}).get('user',''))
        self.obs_pw = QLineEdit(self.settings.get('OBS', {}).get('password',''))
        self.obs_pw.setEchoMode(QLineEdit.EchoMode.Password)
        
        self.lbl_obs_host = QLabel("Host:")
        self.lbl_obs_port = QLabel("Port:")
        self.lbl_obs_mount = QLabel("Mountpoint:")
        self.lbl_obs_user = QLabel("User:")
        self.lbl_obs_pw = QLabel("Password:")
        
        # Set size policy for better resizing behavior
        self._set_size_policy_for_widgets([self.obs_h, self.obs_p, self.obs_m, self.obs_u, self.obs_pw])
        
        fl_obs.addRow(self.lbl_obs_host, self.obs_h)
        fl_obs.addRow(self.lbl_obs_port, self.obs_p)
        fl_obs.addRow(self.lbl_obs_mount, self.obs_m)
        fl_obs.addRow(self.lbl_obs_user, self.obs_u)
        fl_obs.addRow(self.lbl_obs_pw, self.obs_pw)
        
        # Serial port fields
        self.obs_port = QComboBox()
        self.obs_port.addItems(self._get_available_ports() or ["No ports found"])
        obs_port_setting = self.settings.get('OBS', {}).get('port', 'COM1')
        self.obs_port.setCurrentText(str(obs_port_setting))
        
        # Baud rate dropdown with common values
        self.obs_baudrate = QComboBox()
        common_baudrates = ["300", "1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
        self.obs_baudrate.addItems(common_baudrates)
        default_baudrate = str(self.settings.get('OBS', {}).get('baudrate', 115200))
        if default_baudrate in common_baudrates:
            self.obs_baudrate.setCurrentText(default_baudrate)
        else:
            self.obs_baudrate.setCurrentText("115200")
        
        # Data bits dropdown
        self.obs_databits = QComboBox()
        self.obs_databits.addItems(["5", "6", "7", "8"])
        databits_val = str(self.settings.get('OBS', {}).get('databits', 8))
        if databits_val in ["5", "6", "7", "8"]:
            self.obs_databits.setCurrentText(databits_val)
        else:
            self.obs_databits.setCurrentText("8")
        
        # Stop bits dropdown
        self.obs_stopbits = QComboBox()
        self.obs_stopbits.addItems(["1", "1.5", "2"])
        stopbits_val = str(self.settings.get('OBS', {}).get('stopbits', 1))
        if stopbits_val in ["1", "1.5", "2"]:
            self.obs_stopbits.setCurrentText(stopbits_val)
        else:
            self.obs_stopbits.setCurrentText("1")
        
        # Parity dropdown
        self.obs_parity = QComboBox()
        self.obs_parity.addItems(["None", "Even", "Odd", "Mark", "Space"])
        parity_val = self.settings.get('OBS', {}).get('parity', 'None')
        if parity_val in ["None", "Even", "Odd", "Mark", "Space"]:
            self.obs_parity.setCurrentText(parity_val)
        else:
            self.obs_parity.setCurrentText("None")
        
        # Flow control dropdown
        self.obs_flowctrl = QComboBox()
        self.obs_flowctrl.addItems(["None", "RTS/CTS", "XOn/XOff"])
        flowctrl_val = self.settings.get('OBS', {}).get('flowctrl', 'None')
        if flowctrl_val in ["None", "RTS/CTS", "XOn/XOff"]:
            self.obs_flowctrl.setCurrentText(flowctrl_val)
        else:
            self.obs_flowctrl.setCurrentText("None")
        
        self.lbl_obs_serial_port = QLabel("Serial Port:")
        self.lbl_obs_baudrate = QLabel("Baud Rate:")
        self.lbl_obs_databits = QLabel("Data Bits:")
        self.lbl_obs_stopbits = QLabel("Stop Bits:")
        self.lbl_obs_parity = QLabel("Parity:")
        self.lbl_obs_flowctrl = QLabel("Flow Control:")
        
        self._set_size_policy_for_widgets([self.obs_port, self.obs_baudrate, self.obs_databits, 
                                          self.obs_stopbits, self.obs_parity, self.obs_flowctrl])
        
        fl_obs.addRow(self.lbl_obs_serial_port, self.obs_port)
        fl_obs.addRow(self.lbl_obs_baudrate, self.obs_baudrate)
        fl_obs.addRow(self.lbl_obs_databits, self.obs_databits)
        fl_obs.addRow(self.lbl_obs_stopbits, self.obs_stopbits)
        fl_obs.addRow(self.lbl_obs_parity, self.obs_parity)
        fl_obs.addRow(self.lbl_obs_flowctrl, self.obs_flowctrl)

        self.obs_file_path = QLineEdit(self.settings.get('OBS', {}).get('file_path', ''))
        self.obs_file_path.setReadOnly(True)
        self.obs_file_browse = QPushButton("Browse...")
        self.obs_file_browse.clicked.connect(self.browse_obs_file)
        self.obs_file_row = QHBoxLayout()
        self.obs_file_row.addWidget(self.obs_file_path)
        self.obs_file_row.addWidget(self.obs_file_browse)
        self.lbl_obs_file = QLabel("RINEX File:")
        fl_obs.addRow(self.lbl_obs_file, self.obs_file_row)

        self.obs_replay_speed = QDoubleSpinBox()
        self.obs_replay_speed.setRange(0.1, 1000.0)
        self.obs_replay_speed.setDecimals(1)
        self.obs_replay_speed.setSingleStep(0.5)
        self.obs_replay_speed.setSuffix("x")
        self.obs_replay_speed.setValue(float(self.settings.get('OBS', {}).get('replay_speed', 1.0) or 1.0))
        self.lbl_obs_replay_speed = QLabel("Speed Multiplier:")
        fl_obs.addRow(self.lbl_obs_replay_speed, self.obs_replay_speed)

        self.obs_final_results_only = QCheckBox("Final products only (no live UI updates)")
        self.obs_final_results_only.setChecked(bool(self.settings.get('OBS', {}).get('final_results_only', False)))
        self.lbl_obs_final_results_only = QLabel("Replay Mode:")
        fl_obs.addRow(self.lbl_obs_final_results_only, self.obs_final_results_only)
        
        grp_obs.setLayout(fl_obs)
        scroll_layout.addWidget(grp_obs)
        
        # =====================================================================
        # EPH Stream Configuration (Optional)
        # =====================================================================
        self.chk_eph = QCheckBox("Enable Ephemeris Stream (EPH)")
        self.chk_eph.setChecked(self.settings.get('EPH_ENABLED', False))
        self.chk_eph.stateChanged.connect(self.on_eph_enabled_changed)
        scroll_layout.addWidget(self.chk_eph)
        
        grp_eph = QGroupBox("Ephemeris Stream (EPH)")
        fl_eph = QFormLayout()
        fl_eph.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        fl_eph.setRowWrapPolicy(QFormLayout.DontWrapRows)
        fl_eph.setFormAlignment(Qt.AlignHCenter | Qt.AlignTop)
        fl_eph.setLabelAlignment(Qt.AlignLeft)
        
        # Data source type selector for EPH
        self.eph_source = QComboBox()
        self.eph_source.addItems(["NTRIP Server", "Serial Port", "File"])
        eph_source_val = self.settings.get('EPH', {}).get('source', 'NTRIP Server')
        self.eph_source.setCurrentText(eph_source_val)
        self.eph_source.currentTextChanged.connect(self.on_eph_source_changed)
        fl_eph.addRow("Data Source:", self.eph_source)
        
        # NTRIP fields for EPH
        self.eph_h = QLineEdit(self.settings.get('EPH', {}).get('host',''))
        self.eph_p = QLineEdit(str(self.settings.get('EPH', {}).get('port','2101')))
        self.eph_m = QLineEdit(self.settings.get('EPH', {}).get('mountpoint',''))
        self.eph_u = QLineEdit(self.settings.get('EPH', {}).get('user',''))
        self.eph_pw = QLineEdit(self.settings.get('EPH', {}).get('password',''))
        self.eph_pw.setEchoMode(QLineEdit.EchoMode.Password)
        
        self.lbl_eph_host = QLabel("Host:")
        self.lbl_eph_port = QLabel("Port:")
        self.lbl_eph_mount = QLabel("Mountpoint:")
        self.lbl_eph_user = QLabel("User:")
        self.lbl_eph_pw = QLabel("Password:")
        
        self._set_size_policy_for_widgets([self.eph_h, self.eph_p, self.eph_m, self.eph_u, self.eph_pw])
        
        fl_eph.addRow(self.lbl_eph_host, self.eph_h)
        fl_eph.addRow(self.lbl_eph_port, self.eph_p)
        fl_eph.addRow(self.lbl_eph_mount, self.eph_m)
        fl_eph.addRow(self.lbl_eph_user, self.eph_u)
        fl_eph.addRow(self.lbl_eph_pw, self.eph_pw)
        
        # Serial port fields for EPH
        self.eph_port = QComboBox()
        self.eph_port.addItems(self._get_available_ports() or ["No ports found"])
        eph_port_setting = self.settings.get('EPH', {}).get('port', 'COM2')
        self.eph_port.setCurrentText(str(eph_port_setting))
        
        # Baud rate dropdown with common values
        self.eph_baudrate = QComboBox()
        common_baudrates = ["300", "1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
        self.eph_baudrate.addItems(common_baudrates)
        default_eph_baudrate = str(self.settings.get('EPH', {}).get('baudrate', 115200))
        if default_eph_baudrate in common_baudrates:
            self.eph_baudrate.setCurrentText(default_eph_baudrate)
        else:
            self.eph_baudrate.setCurrentText("115200")
        
        # Data bits dropdown
        self.eph_databits = QComboBox()
        self.eph_databits.addItems(["5", "6", "7", "8"])
        eph_databits_val = str(self.settings.get('EPH', {}).get('databits', 8))
        if eph_databits_val in ["5", "6", "7", "8"]:
            self.eph_databits.setCurrentText(eph_databits_val)
        else:
            self.eph_databits.setCurrentText("8")
        
        # Stop bits dropdown
        self.eph_stopbits = QComboBox()
        self.eph_stopbits.addItems(["1", "1.5", "2"])
        eph_stopbits_val = str(self.settings.get('EPH', {}).get('stopbits', 1))
        if eph_stopbits_val in ["1", "1.5", "2"]:
            self.eph_stopbits.setCurrentText(eph_stopbits_val)
        else:
            self.eph_stopbits.setCurrentText("1")
        
        # Parity dropdown
        self.eph_parity = QComboBox()
        self.eph_parity.addItems(["None", "Even", "Odd", "Mark", "Space"])
        eph_parity_val = self.settings.get('EPH', {}).get('parity', 'None')
        if eph_parity_val in ["None", "Even", "Odd", "Mark", "Space"]:
            self.eph_parity.setCurrentText(eph_parity_val)
        else:
            self.eph_parity.setCurrentText("None")
        
        # Flow control dropdown
        self.eph_flowctrl = QComboBox()
        self.eph_flowctrl.addItems(["None", "RTS/CTS", "XOn/XOff"])
        eph_flowctrl_val = self.settings.get('EPH', {}).get('flowctrl', 'None')
        if eph_flowctrl_val in ["None", "RTS/CTS", "XOn/XOff"]:
            self.eph_flowctrl.setCurrentText(eph_flowctrl_val)
        else:
            self.eph_flowctrl.setCurrentText("None")
        
        self.lbl_eph_serial_port = QLabel("Serial Port:")
        self.lbl_eph_baudrate = QLabel("Baud Rate:")
        self.lbl_eph_databits = QLabel("Data Bits:")
        self.lbl_eph_stopbits = QLabel("Stop Bits:")
        self.lbl_eph_parity = QLabel("Parity:")
        self.lbl_eph_flowctrl = QLabel("Flow Control:")
        
        self._set_size_policy_for_widgets([self.eph_port, self.eph_baudrate, self.eph_databits, 
                                          self.eph_stopbits, self.eph_parity, self.eph_flowctrl])
        
        fl_eph.addRow(self.lbl_eph_serial_port, self.eph_port)
        fl_eph.addRow(self.lbl_eph_baudrate, self.eph_baudrate)
        fl_eph.addRow(self.lbl_eph_databits, self.eph_databits)
        fl_eph.addRow(self.lbl_eph_stopbits, self.eph_stopbits)
        fl_eph.addRow(self.lbl_eph_parity, self.eph_parity)
        fl_eph.addRow(self.lbl_eph_flowctrl, self.eph_flowctrl)

        self.eph_file_path = QLineEdit(self.settings.get('EPH', {}).get('file_path', ''))
        self.eph_file_path.setReadOnly(True)
        self.eph_file_browse = QPushButton("Browse...")
        self.eph_file_browse.clicked.connect(self.browse_eph_file)
        self.eph_file_row = QHBoxLayout()
        self.eph_file_row.addWidget(self.eph_file_path)
        self.eph_file_row.addWidget(self.eph_file_browse)
        self.lbl_eph_file = QLabel("Ephemeris File:")
        fl_eph.addRow(self.lbl_eph_file, self.eph_file_row)

        self.eph_file_type = QComboBox()
        self.eph_file_type.addItems(["Auto Detect", "Broadcast RINEX", "Precise SP3"])
        eph_file_type = self.settings.get('EPH', {}).get('file_type', 'Auto Detect')
        self.eph_file_type.setCurrentText(eph_file_type if eph_file_type in ["Auto Detect", "Broadcast RINEX", "Precise SP3"] else "Auto Detect")
        self.lbl_eph_file_type = QLabel("File Type:")
        fl_eph.addRow(self.lbl_eph_file_type, self.eph_file_type)
        
        grp_eph.setLayout(fl_eph)
        grp_eph.setEnabled(self.chk_eph.isChecked())
        self.grp_eph = grp_eph
        scroll_layout.addWidget(grp_eph)
        
        # =====================================================================
        # General Settings
        # =====================================================================
        grp_general = QGroupBox("General Settings")
        fl_general = QFormLayout()
        fl_general.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        fl_general.setRowWrapPolicy(QFormLayout.DontWrapRows)
        fl_general.setFormAlignment(Qt.AlignHCenter | Qt.AlignTop)
        fl_general.setLabelAlignment(Qt.AlignLeft)
        
        # Receiver Approximate Position (ECEF X, Y, Z in meters) - using QLineEdit for display
        self.rec_pos_x = QLineEdit()
        # show empty string if approximate position is not configured
        apr = self.settings.get('APPROX_REC_POS', None)
        if apr is None:
            self.rec_pos_x.setText("")
            self.rec_pos_y = QLineEdit()
            self.rec_pos_y.setText("")
            self.rec_pos_z = QLineEdit()
            self.rec_pos_z.setText("")
        else:
            # existing list-like value
            try:
                self.rec_pos_x.setText(str(apr[0]))
                self.rec_pos_y = QLineEdit()
                self.rec_pos_y.setText(str(apr[1]))
                self.rec_pos_z = QLineEdit()
                self.rec_pos_z.setText(str(apr[2]))
            except Exception:
                # fallback to blanks on malformed data
                self.rec_pos_x.setText("")
                self.rec_pos_y = QLineEdit()
                self.rec_pos_y.setText("")
                self.rec_pos_z = QLineEdit()
                self.rec_pos_z.setText("")
        for widget in (self.rec_pos_x, self.rec_pos_y, self.rec_pos_z):
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        hlayout_pos = QHBoxLayout()
        hlayout_pos.addWidget(QLabel("X:"))
        hlayout_pos.addWidget(self.rec_pos_x)
        hlayout_pos.addWidget(QLabel("Y:"))
        hlayout_pos.addWidget(self.rec_pos_y)
        hlayout_pos.addWidget(QLabel("Z:"))
        hlayout_pos.addWidget(self.rec_pos_z)
        
        fl_general.addRow("Receiver Position (ECEF in m):", hlayout_pos)
        
        # GNSS System Filters
        self.target_systems = QLineEdit(",".join(self.settings.get('TARGET_SYSTEMS', ['G', 'R', 'E', 'C', 'J', 'S', 'I'])))
        self.target_systems.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        fl_general.addRow("Target Systems (comma-separated):", self.target_systems)
        
        grp_general.setLayout(fl_general)
        scroll_layout.addWidget(grp_general)
        
        # Add stretch to push content to the top
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        # Buttons
        btns = QHBoxLayout()
        b_load = QPushButton("Load File")
        b_load.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        open_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        if not open_icon.isNull():
            b_load.setIcon(open_icon)
        b_load.clicked.connect(self.load_file)
        
        b_save_config = QPushButton("Save Config")
        b_save_config.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        save_config_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        if not save_config_icon.isNull():
            b_save_config.setIcon(save_config_icon)
        b_save_config.clicked.connect(self.save_config_to_file)
        
        b_disconnect = QPushButton("Disconnect")
        b_disconnect.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        disconnect_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserStop)
        if not disconnect_icon.isNull():
            b_disconnect.setIcon(disconnect_icon)
        b_disconnect.clicked.connect(self.on_disconnect)

        b_connect = QPushButton("Connect")
        b_connect.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        connect_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
        if not connect_icon.isNull():
            b_connect.setIcon(connect_icon)
        # When Connect is clicked, mark auto_connect and accept dialog
        b_connect.clicked.connect(self.on_connect)
        btns.addWidget(b_load)
        btns.addWidget(b_save_config)
        btns.addStretch()
        btns.addWidget(b_disconnect)
        btns.addWidget(b_connect)
        layout.addLayout(btns)
        
        # Initialize visibility
        self.on_obs_source_changed()
        self.on_eph_enabled_changed()
        self.on_eph_source_changed()

    def _set_size_policy_for_widgets(self, widgets):
        """Helper function to set expanding size policy for widgets"""
        for widget in widgets:
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def on_obs_source_changed(self):
        """Update OBS field visibility based on source type"""
        is_ntrip = self.obs_source.currentText() == "NTRIP Server"
        is_serial = self.obs_source.currentText() == "Serial Port"
        is_file = self.obs_source.currentText() == "RINEX File"
        
        self.lbl_obs_host.setVisible(is_ntrip)
        self.obs_h.setVisible(is_ntrip)
        self.lbl_obs_port.setVisible(is_ntrip)
        self.obs_p.setVisible(is_ntrip)
        self.lbl_obs_mount.setVisible(is_ntrip)
        self.obs_m.setVisible(is_ntrip)
        self.lbl_obs_user.setVisible(is_ntrip)
        self.obs_u.setVisible(is_ntrip)
        self.lbl_obs_pw.setVisible(is_ntrip)
        self.obs_pw.setVisible(is_ntrip)
        
        self.lbl_obs_serial_port.setVisible(is_serial)
        self.obs_port.setVisible(is_serial)
        self.lbl_obs_baudrate.setVisible(is_serial)
        self.obs_baudrate.setVisible(is_serial)
        self.lbl_obs_databits.setVisible(is_serial)
        self.obs_databits.setVisible(is_serial)
        self.lbl_obs_stopbits.setVisible(is_serial)
        self.obs_stopbits.setVisible(is_serial)
        self.lbl_obs_parity.setVisible(is_serial)
        self.obs_parity.setVisible(is_serial)
        self.lbl_obs_flowctrl.setVisible(is_serial)
        self.obs_flowctrl.setVisible(is_serial)

        self.lbl_obs_file.setVisible(is_file)
        self.obs_file_path.setVisible(is_file)
        self.obs_file_browse.setVisible(is_file)
        self.lbl_obs_replay_speed.setVisible(is_file)
        self.obs_replay_speed.setVisible(is_file)
        self.lbl_obs_final_results_only.setVisible(is_file)
        self.obs_final_results_only.setVisible(is_file)

        if is_file:
            self.chk_eph.setChecked(True)
            self.chk_eph.setEnabled(False)
            self.eph_source.setCurrentText("File")
            self.eph_source.setEnabled(False)
        else:
            self.chk_eph.setEnabled(True)
            self.eph_source.setEnabled(True)

        self.on_eph_enabled_changed()
        self.on_eph_source_changed()

    def on_eph_enabled_changed(self):
        """Update EPH group visibility based on enable checkbox"""
        self.grp_eph.setEnabled(self.chk_eph.isChecked())

    def on_eph_source_changed(self):
        """Update EPH field visibility based on source type"""
        is_ntrip = self.eph_source.currentText() == "NTRIP Server"
        is_serial = self.eph_source.currentText() == "Serial Port"
        is_file = self.eph_source.currentText() == "File"
        
        self.lbl_eph_host.setVisible(is_ntrip)
        self.eph_h.setVisible(is_ntrip)
        self.lbl_eph_port.setVisible(is_ntrip)
        self.eph_p.setVisible(is_ntrip)
        self.lbl_eph_mount.setVisible(is_ntrip)
        self.eph_m.setVisible(is_ntrip)
        self.lbl_eph_user.setVisible(is_ntrip)
        self.eph_u.setVisible(is_ntrip)
        self.lbl_eph_pw.setVisible(is_ntrip)
        self.eph_pw.setVisible(is_ntrip)
        
        self.lbl_eph_serial_port.setVisible(is_serial)
        self.eph_port.setVisible(is_serial)
        self.lbl_eph_baudrate.setVisible(is_serial)
        self.eph_baudrate.setVisible(is_serial)
        self.lbl_eph_databits.setVisible(is_serial)
        self.eph_databits.setVisible(is_serial)
        self.lbl_eph_stopbits.setVisible(is_serial)
        self.eph_stopbits.setVisible(is_serial)
        self.lbl_eph_parity.setVisible(is_serial)
        self.eph_parity.setVisible(is_serial)
        self.lbl_eph_flowctrl.setVisible(is_serial)
        self.eph_flowctrl.setVisible(is_serial)

        self.lbl_eph_file.setVisible(is_file)
        self.eph_file_path.setVisible(is_file)
        self.eph_file_browse.setVisible(is_file)
        self.lbl_eph_file_type.setVisible(is_file)
        self.eph_file_type.setVisible(is_file)

    def _get_available_ports(self):
        """Get list of available serial ports"""
        try:
            import serial.tools.list_ports
            return [port.device for port in serial.tools.list_ports.comports()]
        except:
            return ["COM1", "COM2", "COM3"]

    def on_connect(self):
        """User pressed Connect: mark auto_connect and accept dialog."""
        try:
            self._validate_connect_settings()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Configuration", str(exc))
            return
        self.auto_connect = True
        self.disconnect_requested = False
        self.accept()

    def on_disconnect(self):
        """User pressed Disconnect: keep settings but stop active streams."""
        self.auto_connect = False
        self.disconnect_requested = True
        self.accept()

    def browse_obs_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Select RINEX Observation File",
            "",
            "RINEX Observation Files (*.rnx *.obs *.o *.O);;All Files (*.*)"
        )
        if not filepath:
            return
        self.obs_file_path.setText(filepath)
        self._apply_obs_file_metadata(filepath)

    def browse_eph_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Ephemeris File",
            "",
            "Ephemeris Files (*.rnx *.nav *.sp3 *.SP3);;All Files (*.*)"
        )
        if not filepath:
            return
        self.eph_file_path.setText(filepath)
        lower = filepath.lower()
        if lower.endswith(".sp3"):
            self.eph_file_type.setCurrentText("Precise SP3")
        elif lower.endswith((".rnx", ".nav")):
            self.eph_file_type.setCurrentText("Broadcast RINEX")

    def _apply_obs_file_metadata(self, filepath):
        try:
            from core.rinex_loader import read_rinex_observation_header

            metadata = read_rinex_observation_header(filepath)
        except Exception as exc:
            QMessageBox.warning(self, "RINEX Read Error", f"Failed to read RINEX header:\n{exc}")
            return

        coords = metadata.approx_position_ecef
        if coords and any(abs(float(value)) > 1e-6 for value in coords[:3]):
            self.rec_pos_x.setText(str(coords[0]))
            self.rec_pos_y.setText(str(coords[1]))
            self.rec_pos_z.setText(str(coords[2]))
        elif coords:
            QMessageBox.information(
                self,
                "Approximate Position Required",
                "The selected RINEX file contains APPROX POSITION XYZ = 0.\n"
                "Please enter receiver ECEF coordinates manually before connecting.",
            )

        if metadata.interval_seconds and metadata.interval_seconds > 0:
            speed_guess = float(self.obs_replay_speed.value() or 1.0)
            if speed_guess <= 0:
                self.obs_replay_speed.setValue(1.0)

    def _validate_connect_settings(self):
        obs_source = self.obs_source.currentText()
        if obs_source == "NTRIP Server" and not self.obs_h.text().strip():
            raise ValueError("Observation stream is missing the NTRIP host.")
        if obs_source == "Serial Port" and not self.obs_port.currentText().strip():
            raise ValueError("Observation stream is missing the serial port.")
        if obs_source == "RINEX File":
            if not self.obs_file_path.text().strip():
                raise ValueError("Please select a RINEX observation file.")
            if not self.eph_file_path.text().strip():
                raise ValueError("RINEX replay requires an ephemeris file for azimuth/elevation computation.")
            coords = []
            for field in (self.rec_pos_x, self.rec_pos_y, self.rec_pos_z):
                text = field.text().strip()
                if not text:
                    raise ValueError("RINEX replay requires a valid receiver ECEF position.")
                try:
                    coords.append(float(text))
                except ValueError as exc:
                    raise ValueError("Receiver ECEF coordinates must be numeric.") from exc
            if not any(abs(value) > 1e-6 for value in coords):
                raise ValueError(
                    "The RINEX header position is zero. Please enter receiver ECEF coordinates manually before connecting."
                )

        if self.chk_eph.isChecked():
            eph_source = self.eph_source.currentText()
            if eph_source == "NTRIP Server" and not self.eph_h.text().strip():
                raise ValueError("Ephemeris stream is missing the NTRIP host.")
            if eph_source == "Serial Port" and not self.eph_port.currentText().strip():
                raise ValueError("Ephemeris stream is missing the serial port.")
            if eph_source == "File" and not self.eph_file_path.text().strip():
                raise ValueError("Please select an ephemeris file.")

    def load_file(self):
        """Load configuration from file (supports .yaml, .yml, and legacy .py formats)"""
        ensure_config_directories()
        f, _ = QFileDialog.getOpenFileName(
            self, 
            "Select Config File", 
            str(CONFIG_ROOT), 
            "YAML Files (*.yaml *.yml);;Python Files (*.py);;All Files (*.*)"
        )
        if not f:
            return
            
        try:
            if f.lower().endswith(('.yaml', '.yml')):
                # Load from YAML file
                self._load_yaml_file(f)
            else:
                # Load from legacy Python file
                self._load_python_file(f)
            QMessageBox.information(self, "Success", f"Configuration loaded successfully from:\n{f}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load configuration:\n{str(e)}")

    def _load_yaml_file(self, filepath):
        """Load configuration from YAML file"""
        import yaml
        with open(filepath, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        if not config:
            raise ValueError("YAML file is empty or invalid")
        
        # Load OBS settings
        if 'obs_settings' in config:
            obs = config['obs_settings']
            if obs.get('source_type') == 'NTRIP Server':
                self.obs_source.setCurrentText('NTRIP Server')
                self.obs_h.setText(str(obs.get('host', '')))
                self.obs_p.setText(str(obs.get('port', '2101')))
                self.obs_m.setText(str(obs.get('mountpoint', '')))
                self.obs_u.setText(str(obs.get('user', '')))
                self.obs_pw.setText(str(obs.get('password', '')))
            elif obs.get('source_type') == 'Serial Port':
                self.obs_source.setCurrentText('Serial Port')
                self.obs_port.setCurrentText(str(obs.get('serial_port', 'COM1')))
                self.obs_baudrate.setCurrentText(str(obs.get('baudrate', 115200)))
                self.obs_databits.setCurrentText(str(obs.get('databits', 8)))
                self.obs_stopbits.setCurrentText(str(obs.get('stopbits', 1)))
                self.obs_parity.setCurrentText(str(obs.get('parity', 'None')))
                self.obs_flowctrl.setCurrentText(str(obs.get('flowctrl', 'None')))
            else:
                self.obs_source.setCurrentText('RINEX File')
                self.obs_file_path.setText(str(obs.get('file_path', '')))
                self.obs_replay_speed.setValue(float(obs.get('replay_speed', 1.0) or 1.0))
                self.obs_final_results_only.setChecked(bool(obs.get('final_results_only', False)))
                if not config.get('approx_rec_pos') and self.obs_file_path.text().strip():
                    self._apply_obs_file_metadata(self.obs_file_path.text().strip())
        
        # Load EPH settings
        if 'eph_settings' in config:
            eph = config['eph_settings']
            eph_enabled = eph.get('enabled', False)
            self.chk_eph.setChecked(eph_enabled)
            if eph_enabled:
                if eph.get('source_type') == 'NTRIP Server':
                    self.eph_source.setCurrentText('NTRIP Server')
                    self.eph_h.setText(str(eph.get('host', '')))
                    self.eph_p.setText(str(eph.get('port', '2101')))
                    self.eph_m.setText(str(eph.get('mountpoint', '')))
                    self.eph_u.setText(str(eph.get('user', '')))
                    self.eph_pw.setText(str(eph.get('password', '')))
                elif eph.get('source_type') == 'Serial Port':
                    self.eph_source.setCurrentText('Serial Port')
                    self.eph_port.setCurrentText(str(eph.get('serial_port', 'COM2')))
                    self.eph_baudrate.setCurrentText(str(eph.get('baudrate', 115200)))
                    self.eph_databits.setCurrentText(str(eph.get('databits', 8)))
                    self.eph_stopbits.setCurrentText(str(eph.get('stopbits', 1)))
                    self.eph_parity.setCurrentText(str(eph.get('parity', 'None')))
                    self.eph_flowctrl.setCurrentText(str(eph.get('flowctrl', 'None')))
                else:
                    self.eph_source.setCurrentText('File')
                    self.eph_file_path.setText(str(eph.get('file_path', '')))
                    eph_file_type = str(eph.get('file_type', 'Auto Detect'))
                    self.eph_file_type.setCurrentText(
                        eph_file_type if eph_file_type in ["Auto Detect", "Broadcast RINEX", "Precise SP3"] else "Auto Detect"
                    )
        
        # Load general settings
        if 'approx_rec_pos' in config and config['approx_rec_pos']:
            pos = config['approx_rec_pos']
            if len(pos) >= 3:
                self.rec_pos_x.setText(str(pos[0]))
                self.rec_pos_y.setText(str(pos[1]))
                self.rec_pos_z.setText(str(pos[2]))
        
        if 'target_systems' in config:
            systems = config['target_systems']
            if isinstance(systems, list):
                self.target_systems.setText(','.join(systems))
            else:
                self.target_systems.setText(str(systems))
        
        # Update visibility
        self.on_obs_source_changed()
        self.on_eph_enabled_changed()
        self.on_eph_source_changed()

    def _load_python_file(self, filepath):
        """Load configuration from legacy Python file format"""
        spec = importlib.util.spec_from_file_location("cfg", filepath)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        
        # Load OBS settings
        if hasattr(m, 'NTRIP_HOST'):
            self.obs_source.setCurrentText('NTRIP Server')
            self.obs_h.setText(str(m.NTRIP_HOST))
        if hasattr(m, 'NTRIP_PORT'): self.obs_p.setText(str(m.NTRIP_PORT))
        if hasattr(m, 'MOUNTPOINT'): self.obs_m.setText(str(m.MOUNTPOINT))
        if hasattr(m, 'USER'): self.obs_u.setText(str(m.USER))
        if hasattr(m, 'PASSWORD'): self.obs_pw.setText(str(m.PASSWORD))
        
        # Load EPH settings
        if hasattr(m, 'EPH_HOST'): 
            self.chk_eph.setChecked(True)
            self.eph_source.setCurrentText('NTRIP Server')
            self.eph_h.setText(str(m.EPH_HOST))
            self.eph_p.setText(str(m.EPH_PORT))
            self.eph_m.setText(str(m.EPH_MOUNTPOINT))
            self.eph_u.setText(str(m.EPH_USER))
            self.eph_pw.setText(str(m.EPH_PASSWORD))
                
        # Load general settings
        if hasattr(m, 'APPROX_REC_POS'):
            pos = m.APPROX_REC_POS
            if len(pos) >= 3:
                self.rec_pos_x.setText(str(pos[0]))
                self.rec_pos_y.setText(str(pos[1]))
                self.rec_pos_z.setText(str(pos[2]))
                    
        if hasattr(m, 'TARGET_SYSTEMS'):
            systems = m.TARGET_SYSTEMS
            if isinstance(systems, list):
                systems_str = ','.join(systems)
                self.target_systems.setText(systems_str)
            else:
                self.target_systems.setText(str(systems))

        self.on_obs_source_changed()
        self.on_eph_enabled_changed()
        self.on_eph_source_changed()

    def get_settings(self):
        """Return settings dictionary with both NTRIP and serial port configuration"""
        from core.global_config import update_connection_settings, update_general_settings
        
        # Update OBS settings
        obs_source_type = self.obs_source.currentText()
        obs_settings = {
            'source_type': obs_source_type,
            'host': self.obs_h.text(),
            'port': self.obs_p.text() if obs_source_type == "NTRIP Server" else (self.obs_port.currentText() if obs_source_type == "Serial Port" else ""),
            'serial_port': self.obs_port.currentText(),
            'baudrate': int(self.obs_baudrate.currentText()),
            'databits': int(self.obs_databits.currentText()),
            'stopbits': float(self.obs_stopbits.currentText()),
            'parity': self.obs_parity.currentText(),
            'flowctrl': self.obs_flowctrl.currentText(),
            'mountpoint': self.obs_m.text(),
            'user': self.obs_u.text(),
            'password': self.obs_pw.text(),
            'file_path': self.obs_file_path.text().strip(),
            'replay_speed': float(self.obs_replay_speed.value()),
            'file_type': 'Auto Detect',
            'final_results_only': bool(self.obs_final_results_only.isChecked()),
        }
        update_connection_settings('OBS', obs_settings)
        
        # Update EPH settings
        eph_enabled = self.chk_eph.isChecked()
        if eph_enabled:
            eph_source_type = self.eph_source.currentText()
            eph_settings = {
                'source_type': eph_source_type,
                'enabled': eph_enabled,
                'host': self.eph_h.text(),
                'port': self.eph_p.text() if eph_source_type == "NTRIP Server" else (self.eph_port.currentText() if eph_source_type == "Serial Port" else ""),
                'serial_port': self.eph_port.currentText(),
                'baudrate': int(self.eph_baudrate.currentText()),
                'databits': int(self.eph_databits.currentText()),
                'stopbits': float(self.eph_stopbits.currentText()),
                'parity': self.eph_parity.currentText(),
                'flowctrl': self.eph_flowctrl.currentText(),
                'mountpoint': self.eph_m.text(),
                'user': self.eph_u.text(),
                'password': self.eph_pw.text(),
                'file_path': self.eph_file_path.text().strip(),
                'replay_speed': 1.0,
                'file_type': self.eph_file_type.currentText(),
                'final_results_only': False,
            }
            update_connection_settings('EPH', eph_settings)
        else:
            # Update EPH to disabled state
            update_connection_settings('EPH', {'enabled': False})
        
        # Update general settings
        try:
            target_systems = [s.strip() for s in self.target_systems.text().split(',')]
        except:
            target_systems = ['G', 'R', 'E', 'C', 'J', 'S', 'I']
            
        # Read coordinates from QLineEdit
        # build approximate position; if any of the three fields are blank or
        # non-numeric we treat the whole setting as None (no prior estimate).
        coords = []
        for field in (self.rec_pos_x, self.rec_pos_y, self.rec_pos_z):
            text = field.text().strip()
            if text == "":
                coords = None
                break
            try:
                coords.append(float(text))
            except ValueError:
                coords = None
                break
        general_settings = {
            'approx_rec_pos': coords,
            'target_systems': target_systems
        }
        update_general_settings(general_settings)
        # determine return value for legacy settings API
        legacy_pos = None
        if coords is not None:
            legacy_pos = coords
        
        # Return the legacy settings format for backward compatibility
        return {
            'OBS': {
                'source': obs_source_type,
                'host': self.obs_h.text(),
                'port': self.obs_p.text() if obs_source_type == "NTRIP Server" else (self.obs_port.currentText() if obs_source_type == "Serial Port" else ""),
                'baudrate': int(self.obs_baudrate.currentText()),
                'databits': int(self.obs_databits.currentText()),
                'stopbits': float(self.obs_stopbits.currentText()),
                'parity': self.obs_parity.currentText(),
                'flowctrl': self.obs_flowctrl.currentText(),
                'mountpoint': self.obs_m.text(),
                'user': self.obs_u.text(),
                'password': self.obs_pw.text(),
                'file_path': self.obs_file_path.text().strip(),
                'replay_speed': float(self.obs_replay_speed.value()),
                'file_type': 'Auto Detect',
                'final_results_only': bool(self.obs_final_results_only.isChecked()),
            },
            'EPH_ENABLED': eph_enabled,
            'EPH': {
                'source': self.eph_source.currentText(),
                'host': self.eph_h.text(),
                'port': self.eph_p.text() if self.eph_source.currentText() == "NTRIP Server" else (self.eph_port.currentText() if self.eph_source.currentText() == "Serial Port" else ""),
                'baudrate': int(self.eph_baudrate.currentText()),
                'databits': int(self.eph_databits.currentText()),
                'stopbits': float(self.eph_stopbits.currentText()),
                'parity': self.eph_parity.currentText(),
                'flowctrl': self.eph_flowctrl.currentText(),
                'mountpoint': self.eph_m.text(),
                'user': self.eph_u.text(),
                'password': self.eph_pw.text(),
                'file_path': self.eph_file_path.text().strip(),
                'replay_speed': 1.0,
                'file_type': self.eph_file_type.currentText(),
                'final_results_only': False,
            },
            'APPROX_REC_POS': legacy_pos,
            'TARGET_SYSTEMS': target_systems
        }

    def save_config_to_file(self):
        """Save current configuration to a YAML file"""
        ensure_config_directories()
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save Configuration",
            str(STREAM_CONFIG_DIR / DEFAULT_STREAM_SAVE_NAME),
            "YAML Files (*.yaml);;YAML Files (*.yml)"
        )
        
        if not filepath:
            return
        
        # Ensure file has correct extension
        if not filepath.lower().endswith(('.yaml', '.yml')):
            filepath += '.yaml'
        
        try:
            # First, update the global config with current UI settings
            self.get_settings()
            
            # Then save the global config to file
            from core.global_config import save_config_to_file as save_global_config
            save_global_config(filepath)
            
            QMessageBox.information(
                self, 
                "Success", 
                f"Configuration saved successfully to:\n{filepath}"
            )
        except Exception as e:
            QMessageBox.warning(
                self, 
                "Error", 
                f"Failed to save configuration:\n{str(e)}"
            )
