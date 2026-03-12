# ui/dialogs.py
import importlib.util
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QGroupBox, QFormLayout, 
                             QLineEdit, QCheckBox, QHBoxLayout, QPushButton, 
                             QFileDialog, QMessageBox, QStyle, QComboBox, QLabel,
                             QSpinBox, QScrollArea, QWidget)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt

class ConfigDialog(QDialog):
    def __init__(self, parent=None, initial_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Data Source Settings")
        self.resize(500, 700)
        self.settings = initial_settings or {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # =====================================================================
        # OBS Stream Configuration
        # =====================================================================
        grp_obs = QGroupBox("Observation Stream (OBS)")
        fl_obs = QFormLayout()
        
        # Data source type selector
        self.obs_source = QComboBox()
        self.obs_source.addItems(["NTRIP Server", "Serial Port"])
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
        
        fl_obs.addRow(self.lbl_obs_host, self.obs_h)
        fl_obs.addRow(self.lbl_obs_port, self.obs_p)
        fl_obs.addRow(self.lbl_obs_mount, self.obs_m)
        fl_obs.addRow(self.lbl_obs_user, self.obs_u)
        fl_obs.addRow(self.lbl_obs_pw, self.obs_pw)
        
        # Serial port fields
        self.obs_port = QComboBox()
        self.obs_port.addItems(self._get_available_ports() or ["No ports found"])
        self.obs_port.setCurrentText(str(self.settings.get('OBS', {}).get('port', 'COM1')))
        
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
        
        fl_obs.addRow(self.lbl_obs_serial_port, self.obs_port)
        fl_obs.addRow(self.lbl_obs_baudrate, self.obs_baudrate)
        fl_obs.addRow(self.lbl_obs_databits, self.obs_databits)
        fl_obs.addRow(self.lbl_obs_stopbits, self.obs_stopbits)
        fl_obs.addRow(self.lbl_obs_parity, self.obs_parity)
        fl_obs.addRow(self.lbl_obs_flowctrl, self.obs_flowctrl)
        
        grp_obs.setLayout(fl_obs)
        layout.addWidget(grp_obs)
        
        # =====================================================================
        # EPH Stream Configuration (Optional)
        # =====================================================================
        self.chk_eph = QCheckBox("Enable Ephemeris Stream (EPH)")
        self.chk_eph.setChecked(self.settings.get('EPH_ENABLED', False))
        self.chk_eph.stateChanged.connect(self.on_eph_enabled_changed)
        layout.addWidget(self.chk_eph)
        
        grp_eph = QGroupBox("Ephemeris Stream (EPH)")
        fl_eph = QFormLayout()
        
        # Data source type selector for EPH
        self.eph_source = QComboBox()
        self.eph_source.addItems(["NTRIP Server", "Serial Port"])
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
        
        fl_eph.addRow(self.lbl_eph_host, self.eph_h)
        fl_eph.addRow(self.lbl_eph_port, self.eph_p)
        fl_eph.addRow(self.lbl_eph_mount, self.eph_m)
        fl_eph.addRow(self.lbl_eph_user, self.eph_u)
        fl_eph.addRow(self.lbl_eph_pw, self.eph_pw)
        
        # Serial port fields for EPH
        self.eph_port = QComboBox()
        self.eph_port.addItems(self._get_available_ports() or ["No ports found"])
        self.eph_port.setCurrentText(str(self.settings.get('EPH', {}).get('port', 'COM2')))
        
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
        
        fl_eph.addRow(self.lbl_eph_serial_port, self.eph_port)
        fl_eph.addRow(self.lbl_eph_baudrate, self.eph_baudrate)
        fl_eph.addRow(self.lbl_eph_databits, self.eph_databits)
        fl_eph.addRow(self.lbl_eph_stopbits, self.eph_stopbits)
        fl_eph.addRow(self.lbl_eph_parity, self.eph_parity)
        fl_eph.addRow(self.lbl_eph_flowctrl, self.eph_flowctrl)
        
        grp_eph.setLayout(fl_eph)
        grp_eph.setEnabled(self.chk_eph.isChecked())
        self.grp_eph = grp_eph
        layout.addWidget(grp_eph)
        
        # Buttons
        btns = QHBoxLayout()
        b_load = QPushButton("Load File")
        open_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        if not open_icon.isNull():
            b_load.setIcon(open_icon)
        b_load.clicked.connect(self.load_file)
        
        b_save = QPushButton("Connect")
        save_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        if not save_icon.isNull():
            b_save.setIcon(save_icon)
        b_save.clicked.connect(self.accept)
        btns.addWidget(b_load)
        btns.addStretch()
        btns.addWidget(b_save)
        layout.addLayout(btns)
        
        # Initialize visibility
        self.on_obs_source_changed()
        self.on_eph_enabled_changed()
        self.on_eph_source_changed()

    def on_obs_source_changed(self):
        """Update OBS field visibility based on source type"""
        is_ntrip = self.obs_source.currentText() == "NTRIP Server"
        
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
        
        self.lbl_obs_serial_port.setVisible(not is_ntrip)
        self.obs_port.setVisible(not is_ntrip)
        self.lbl_obs_baudrate.setVisible(not is_ntrip)
        self.obs_baudrate.setVisible(not is_ntrip)

    def on_eph_enabled_changed(self):
        """Update EPH group visibility based on enable checkbox"""
        self.grp_eph.setEnabled(self.chk_eph.isChecked())

    def on_eph_source_changed(self):
        """Update EPH field visibility based on source type"""
        is_ntrip = self.eph_source.currentText() == "NTRIP Server"
        
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
        
        self.lbl_eph_serial_port.setVisible(not is_ntrip)
        self.eph_port.setVisible(not is_ntrip)
        self.lbl_eph_baudrate.setVisible(not is_ntrip)
        self.eph_baudrate.setVisible(not is_ntrip)

    def _get_available_ports(self):
        """Get list of available serial ports"""
        try:
            import serial.tools.list_ports
            return [port.device for port in serial.tools.list_ports.comports()]
        except:
            return ["COM1", "COM2", "COM3"]

    def load_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Config", "", "Python (*.py)")
        if f:
            try:
                spec = importlib.util.spec_from_file_location("cfg", f)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                if hasattr(m, 'NTRIP_HOST'): self.obs_h.setText(str(m.NTRIP_HOST))
                if hasattr(m, 'NTRIP_PORT'): self.obs_p.setText(str(m.NTRIP_PORT))
                if hasattr(m, 'MOUNTPOINT'): self.obs_m.setText(str(m.MOUNTPOINT))
                if hasattr(m, 'USER'): self.obs_u.setText(str(m.USER))
                if hasattr(m, 'PASSWORD'): self.obs_pw.setText(str(m.PASSWORD))
                if hasattr(m, 'EPH_HOST'): 
                    self.chk_eph.setChecked(True)
                    self.eph_h.setText(str(m.EPH_HOST))
                    self.eph_m.setText(str(m.EPH_MOUNTPOINT))
                    self.eph_u.setText(str(m.EPH_USER))
                    self.eph_pw.setText(str(m.EPH_PASSWORD))
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def get_settings(self):
        """Return settings dictionary with both NTRIP and serial port configuration"""
        return {
            'OBS': {
                'source': self.obs_source.currentText(),
                'host': self.obs_h.text(),
                'port': self.obs_p.text() if self.obs_source.currentText() == "NTRIP Server" else self.obs_port.currentText(),
                'baudrate': int(self.obs_baudrate.currentText()),
                'databits': int(self.obs_databits.currentText()),
                'stopbits': float(self.obs_stopbits.currentText()),
                'parity': self.obs_parity.currentText(),
                'flowctrl': self.obs_flowctrl.currentText(),
                'mountpoint': self.obs_m.text(),
                'user': self.obs_u.text(),
                'password': self.obs_pw.text()
            },
            'EPH_ENABLED': self.chk_eph.isChecked(),
            'EPH': {
                'source': self.eph_source.currentText(),
                'host': self.eph_h.text(),
                'port': self.eph_p.text() if self.eph_source.currentText() == "NTRIP Server" else self.eph_port.currentText(),
                'baudrate': int(self.eph_baudrate.currentText()),
                'databits': int(self.eph_databits.currentText()),
                'stopbits': float(self.eph_stopbits.currentText()),
                'parity': self.eph_parity.currentText(),
                'flowctrl': self.eph_flowctrl.currentText(),
                'mountpoint': self.eph_m.text(),
                'user': self.eph_u.text(),
                'password': self.eph_pw.text()
            }
        }
