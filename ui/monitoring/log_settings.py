from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QPushButton,
                                 QCheckBox, QLabel, QHBoxLayout, QDialogButtonBox,
                                 QSpinBox, QListWidget, QGroupBox, QVBoxLayout, QRadioButton,
                                 QFrame, QTextEdit)
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog


class LogSettingsDialog(QDialog):
    """Dialog to configure logging options and control recording.

    Options:
    - output directory
    - file split interval (minutes)
    - sampling interval (seconds)
    - selected fields to save
    - save format selection (CSV, Binary RTCM, RINEX)
    
    Features:
    - Start/Stop recording button
    - Recording status display
    - Settings locked during recording
    """

    recording_toggled = Signal(bool)

    def __init__(self, parent=None, settings=None, is_recording=False):
        super().__init__(parent)
        self.setWindowTitle("Logging Settings")
        self.setModal(True)
        self.resize(600, 500)
        self.is_recording = is_recording

        form = QFormLayout(self)

        # Output directory
        self.dir_edit = QLineEdit()
        self.btn_browse = QPushButton("Browse")
        self.btn_browse.clicked.connect(self.browse)
        h = QHBoxLayout()
        h.addWidget(self.dir_edit)
        h.addWidget(self.btn_browse)
        form.addRow("Output directory:", h)

        # Split interval
        self.split_spin = QSpinBox()
        self.split_spin.setRange(1, 24 * 60)
        self.split_spin.setSuffix(" min")
        self.split_spin.setMinimumHeight(30)  # Increase height
        form.addRow("Split every:", self.split_spin)

        # Sampling interval
        self.sample_spin = QSpinBox()
        self.sample_spin.setRange(1, 3600)
        self.sample_spin.setSuffix(" s")
        self.sample_spin.setMinimumHeight(30)  # Increase height
        form.addRow("Sample interval:", self.sample_spin)

        # Save format group box
        format_group = QGroupBox("Save Format")
        format_layout = QVBoxLayout()
        
        self.radio_csv = QRadioButton("CSV Format (select fields)")
        self.radio_binary = QRadioButton("Binary RTCM Format")
        self.radio_rinex = QRadioButton("RINEX Format (not implemented yet)")
        
        format_layout.addWidget(self.radio_csv)
        format_layout.addWidget(self.radio_binary)
        format_layout.addWidget(self.radio_rinex)
        format_group.setLayout(format_layout)
        form.addRow(format_group)

        # Fields selection (only shown for CSV format)
        self.fields_label = QLabel("Fields to save:")
        form.addRow(self.fields_label)
        self.fields_list = QListWidget()
        self.fields_list.setSelectionMode(self.fields_list.SelectionMode.MultiSelection)
        default_fields = [
            "PRN",
            "Sys",
            "El(°)",
            "Az(°)",
            "Freq",
            "SNR",
            "Pseudorange (m)",
            "Phase (cyc)",
        ]
        for f in default_fields:
            self.fields_list.addItem(f)
            item = self.fields_list.findItems(f, Qt.MatchFlag.MatchExactly)[0]
            item.setSelected(True)
        form.addRow(self.fields_list)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        form.addRow(separator)

        # Recording control section
        self.recording_label = QLabel("Recording Status:")
        form.addRow(self.recording_label)
        
        # Start/Stop button
        self.btn_start_stop = QPushButton("Start Recording")
        self.btn_start_stop.clicked.connect(self.toggle_recording)
        self.btn_start_stop.setMinimumHeight(40)
        
        # Add Qt standard icons
        from PySide6.QtWidgets import QStyle
        self.start_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.stop_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        self.btn_start_stop.setIcon(self.start_icon)
        
        self.btn_start_stop.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        form.addRow(self.btn_start_stop)

        # Recording info display
        self.recording_info = QTextEdit()
        self.recording_info.setMaximumHeight(100)
        self.recording_info.setReadOnly(True)
        self.recording_info.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                font-family: Consolas, monospace;
                font-size: 9pt;
            }
        """)
        form.addRow("Recording Info:", self.recording_info)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        # Connect format radio buttons to update UI
        self.radio_csv.toggled.connect(self.on_format_changed)
        self.radio_binary.toggled.connect(self.on_format_changed)
        self.radio_rinex.toggled.connect(self.on_format_changed)

        # Load settings if provided
        if settings:
            self.dir_edit.setText(settings.get("directory", ""))
            self.split_spin.setValue(settings.get("split_minutes", 60))
            self.sample_spin.setValue(settings.get("sample_interval", 1))
            
            # Handle format selection
            format_type = settings.get("format", "csv")
            if format_type == "csv":
                self.radio_csv.setChecked(True)
            elif format_type == "binary":
                self.radio_binary.setChecked(True)
            elif format_type == "rinex":
                self.radio_rinex.setChecked(True)
            
            # Load selected fields
            sel = settings.get("fields", default_fields)
            for i in range(self.fields_list.count()):
                it = self.fields_list.item(i)
                it.setSelected(it.text() in sel)
        else:
            # Default to CSV format
            self.radio_csv.setChecked(True)

        # Update UI state based on initial format selection
        self.on_format_changed()
        
        # Update recording state
        self.update_recording_state()

    def on_format_changed(self):
        """Update UI elements based on selected format."""
        is_csv = self.radio_csv.isChecked()
        
        # Show/hide fields selection for CSV format
        self.fields_label.setVisible(is_csv)
        self.fields_list.setVisible(is_csv)
        
        # Adjust window size to fit content
        if is_csv:
            self.resize(520, 500)
        else:
            self.resize(520, 360)

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self.dir_edit.setText(d)

    def toggle_recording(self):
        """Toggle recording state and emit signal."""
        self.is_recording = not self.is_recording
        self.recording_toggled.emit(self.is_recording)
        self.update_recording_state()

    def update_recording_state(self):
        """Update UI based on recording state."""
        if self.is_recording:
            self.btn_start_stop.setText("Stop Recording")
            self.btn_start_stop.setIcon(self.stop_icon)
            self.btn_start_stop.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    font-weight: bold;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #da190b;
                }
                QPushButton:pressed {
                    background-color: #c1170a;
                }
            """)
            # Disable settings during recording
            self.dir_edit.setEnabled(False)
            self.btn_browse.setEnabled(False)
            self.split_spin.setEnabled(False)
            self.sample_spin.setEnabled(False)
            self.radio_csv.setEnabled(False)
            self.radio_binary.setEnabled(False)
            self.radio_rinex.setEnabled(False)
            self.fields_list.setEnabled(False)
        else:
            self.btn_start_stop.setText("Start Recording")
            self.btn_start_stop.setIcon(self.start_icon)
            self.btn_start_stop.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    font-weight: bold;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3d8b40;
                }
            """)

    def update_recording_info(self, info_text):
        """Update the recording information display."""
        self.recording_info.setText(info_text)

    def get_settings(self):
        # Determine selected format
        if self.radio_csv.isChecked():
            format_type = "csv"
        elif self.radio_binary.isChecked():
            format_type = "binary"
        elif self.radio_rinex.isChecked():
            format_type = "rinex"
        else:
            format_type = "csv"  # default fallback
        
        fields = [it.text() for it in self.fields_list.selectedItems()] if self.radio_csv.isChecked() else []
        
        return {
            "directory": self.dir_edit.text(),
            "split_minutes": int(self.split_spin.value()),
            "sample_interval": int(self.sample_spin.value()),
            "format": format_type,
            "fields": fields,
        }
