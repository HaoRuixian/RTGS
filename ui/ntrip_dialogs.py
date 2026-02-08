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
        self.obs_port.setCurrentText(self.settings.get('OBS', {}).get('port', 'COM1'))
        
        self.obs_baudrate = QSpinBox()
        self.obs_baudrate.setMinimum(300)
        self.obs_baudrate.setMaximum(921600)
        self.obs_baudrate.setValue(int(self.settings.get('OBS', {}).get('baudrate', 115200)))
        
        self.lbl_obs_serial_port = QLabel("Serial Port:")
        self.lbl_obs_baudrate = QLabel("Baud Rate:")
        
        fl_obs.addRow(self.lbl_obs_serial_port, self.obs_port)
        fl_obs.addRow(self.lbl_obs_baudrate, self.obs_baudrate)
        
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
        self.eph_port.setCurrentText(self.settings.get('EPH', {}).get('port', 'COM2'))
        
        self.eph_baudrate = QSpinBox()
        self.eph_baudrate.setMinimum(300)
        self.eph_baudrate.setMaximum(921600)
        self.eph_baudrate.setValue(int(self.settings.get('EPH', {}).get('baudrate', 115200)))
        
        self.lbl_eph_serial_port = QLabel("Serial Port:")
        self.lbl_eph_baudrate = QLabel("Baud Rate:")
        
        fl_eph.addRow(self.lbl_eph_serial_port, self.eph_port)
        fl_eph.addRow(self.lbl_eph_baudrate, self.eph_baudrate)
        
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
                'baudrate': self.obs_baudrate.value(),
                'mountpoint': self.obs_m.text(),
                'user': self.obs_u.text(),
                'password': self.obs_pw.text()
            },
            'EPH_ENABLED': self.chk_eph.isChecked(),
            'EPH': {
                'source': self.eph_source.currentText(),
                'host': self.eph_h.text(),
                'port': self.eph_p.text() if self.eph_source.currentText() == "NTRIP Server" else self.eph_port.currentText(),
                'baudrate': self.eph_baudrate.value(),
                'mountpoint': self.eph_m.text(),
                'user': self.eph_u.text(),
                'password': self.eph_pw.text()
            }
        }
