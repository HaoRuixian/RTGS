import importlib.util
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QGroupBox, QFormLayout, 
                             QLineEdit, QCheckBox, QHBoxLayout, QPushButton, 
                             QFileDialog, QMessageBox, QStyle, QComboBox, QLabel,
                             QSpinBox, QScrollArea, QWidget, QDoubleSpinBox, QSizePolicy)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt

class ConfigDialog(QDialog):
    def __init__(self, parent=None, initial_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Data Source Settings")
        self.resize(500, 800)  # Reduced default height
        self.settings = initial_settings or {}
        self.setMinimumSize(450, 500)  # Reduced minimum size
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
        
        self.obs_baudrate = QSpinBox()
        self.obs_baudrate.setMinimum(300)
        self.obs_baudrate.setMaximum(921600)
        self.obs_baudrate.setValue(int(self.settings.get('OBS', {}).get('baudrate', 115200)))
        
        self.lbl_obs_serial_port = QLabel("Serial Port:")
        self.lbl_obs_baudrate = QLabel("Baud Rate:")
        
        self._set_size_policy_for_widgets([self.obs_port, self.obs_baudrate])
        
        fl_obs.addRow(self.lbl_obs_serial_port, self.obs_port)
        fl_obs.addRow(self.lbl_obs_baudrate, self.obs_baudrate)
        
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
        
        self.eph_baudrate = QSpinBox()
        self.eph_baudrate.setMinimum(300)
        self.eph_baudrate.setMaximum(921600)
        self.eph_baudrate.setValue(int(self.settings.get('EPH', {}).get('baudrate', 115200)))
        
        self.lbl_eph_serial_port = QLabel("Serial Port:")
        self.lbl_eph_baudrate = QLabel("Baud Rate:")
        
        self._set_size_policy_for_widgets([self.eph_port, self.eph_baudrate])
        
        fl_eph.addRow(self.lbl_eph_serial_port, self.eph_port)
        fl_eph.addRow(self.lbl_eph_baudrate, self.eph_baudrate)
        
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
        self.rec_pos_x.setText(str(self.settings.get('APPROX_REC_POS', [0, 0, 0])[0]))
        self.rec_pos_x.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        self.rec_pos_y = QLineEdit()
        self.rec_pos_y.setText(str(self.settings.get('APPROX_REC_POS', [0, 0, 0])[1]))
        self.rec_pos_y.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        self.rec_pos_z = QLineEdit()
        self.rec_pos_z.setText(str(self.settings.get('APPROX_REC_POS', [0, 0, 0])[2]))
        self.rec_pos_z.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        hlayout_pos = QHBoxLayout()
        hlayout_pos.addWidget(QLabel("X:"))
        hlayout_pos.addWidget(self.rec_pos_x)
        hlayout_pos.addWidget(QLabel("Y:"))
        hlayout_pos.addWidget(self.rec_pos_y)
        hlayout_pos.addWidget(QLabel("Z:"))
        hlayout_pos.addWidget(self.rec_pos_z)
        
        fl_general.addRow("Receiver Position (ECEF in m):", hlayout_pos)
        
        # GNSS System Filters
        self.target_systems = QLineEdit(",".join(self.settings.get('TARGET_SYSTEMS', ['G', 'R', 'E', 'C'])))
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
        
        b_save = QPushButton("Connect")
        b_save.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
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

    def _set_size_policy_for_widgets(self, widgets):
        """Helper function to set expanding size policy for widgets"""
        for widget in widgets:
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

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
                
                # Load OBS settings
                if hasattr(m, 'NTRIP_HOST'): self.obs_h.setText(str(m.NTRIP_HOST))
                if hasattr(m, 'NTRIP_PORT'): self.obs_p.setText(str(m.NTRIP_PORT))
                if hasattr(m, 'MOUNTPOINT'): self.obs_m.setText(str(m.MOUNTPOINT))
                if hasattr(m, 'USER'): self.obs_u.setText(str(m.USER))
                if hasattr(m, 'PASSWORD'): self.obs_pw.setText(str(m.PASSWORD))
                
                # Load EPH settings
                if hasattr(m, 'EPH_HOST'): 
                    self.chk_eph.setChecked(True)
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
                        
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def get_settings(self):
        """Return settings dictionary with both NTRIP and serial port configuration"""
        from core.global_config import update_connection_settings, update_general_settings
        
        # Update OBS settings
        obs_source_type = self.obs_source.currentText()
        obs_settings = {
            'source_type': obs_source_type,
            'host': self.obs_h.text(),
            'port': self.obs_p.text() if obs_source_type == "NTRIP Server" else self.obs_port.currentText(),
            'serial_port': self.obs_port.currentText(),
            'baudrate': self.obs_baudrate.value(),
            'mountpoint': self.obs_m.text(),
            'user': self.obs_u.text(),
            'password': self.obs_pw.text()
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
                'port': self.eph_p.text() if eph_source_type == "NTRIP Server" else self.eph_port.currentText(),
                'serial_port': self.eph_port.currentText(),
                'baudrate': self.eph_baudrate.value(),
                'mountpoint': self.eph_m.text(),
                'user': self.eph_u.text(),
                'password': self.eph_pw.text()
            }
            update_connection_settings('EPH', eph_settings)
        else:
            # Update EPH to disabled state
            update_connection_settings('EPH', {'enabled': False})
        
        # Update general settings
        try:
            target_systems = [s.strip() for s in self.target_systems.text().split(',')]
        except:
            target_systems = ['G', 'R', 'E', 'C']
            
        # Read coordinates from QLineEdit
        try:
            coord_x = float(self.rec_pos_x.text())
        except ValueError:
            coord_x = 0.0
            
        try:
            coord_y = float(self.rec_pos_y.text())
        except ValueError:
            coord_y = 0.0
            
        try:
            coord_z = float(self.rec_pos_z.text())
        except ValueError:
            coord_z = 0.0
        
        general_settings = {
            'approx_rec_pos': [coord_x, coord_y, coord_z],
            'target_systems': target_systems
        }
        update_general_settings(general_settings)
        
        # Return the legacy settings format for backward compatibility
        return {
            'OBS': {
                'source': obs_source_type,
                'host': self.obs_h.text(),
                'port': self.obs_p.text() if obs_source_type == "NTRIP Server" else self.obs_port.currentText(),
                'baudrate': self.obs_baudrate.value(),
                'mountpoint': self.obs_m.text(),
                'user': self.obs_u.text(),
                'password': self.obs_pw.text()
            },
            'EPH_ENABLED': eph_enabled,
            'EPH': {
                'source': self.eph_source.currentText(),
                'host': self.eph_h.text(),
                'port': self.eph_p.text() if self.eph_source.currentText() == "NTRIP Server" else self.eph_port.currentText(),
                'baudrate': self.eph_baudrate.value(),
                'mountpoint': self.eph_m.text(),
                'user': self.eph_u.text(),
                'password': self.eph_pw.text()
            },
            'APPROX_REC_POS': [coord_x, coord_y, coord_z],
            'TARGET_SYSTEMS': target_systems
        }