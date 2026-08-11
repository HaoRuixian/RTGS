"""Compact, tabbed positioning-engine settings dialog."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.global_config import get_positioning_settings, update_positioning_settings


DEFAULTS = {
    "cutoff_elevation_deg": 10.0,
    "min_satellites": 4,
    "max_pdop": 10.0,
    "ionosphere_option": "IFLC",
    "troposphere_model": "Sastamoinen",
    "gnss_systems": ["G", "R", "E", "C", "J", "I"],
    "prefer_gps_only": False,
    "allow_gps_fallback": False,
    "require_ssr_corrections": True,
    "weight_mode": "elevation",
    "code_sigma_m": 1.0,
    "system_code_weight_factors": {"R": 5.0},
    "ppp_use_station_apriori": False,
    "ppp_use_config_initial_position": False,
    "ppp_independent_mode": False,
    "ppp_observation_model": "IFLC",
    "ppp_station_apriori_sigma_m": 0.05,
    "ppp_initial_position_sigma_m": 100.0,
    "ppp_spp_bootstrap_sigma_m": 100.0,
    "ppp_initial_clock_sigma_m": 1000.0,
    "ppp_initial_ambiguity_sigma_m": 1000.0,
    "ppp_initial_ionosphere_sigma_m": 30.0,
    "ppp_ionosphere_process_noise_mps": 0.001,
    "ppp_position_process_noise_mps": 0.0,
    "ppp_trop_process_noise_mps": 5e-5,
    "ppp_estimate_trop_gradients": True,
    "ppp_initial_trop_gradient_sigma_m": 0.01,
    "ppp_trop_gradient_process_noise_mps": 1e-5,
    "ppp_zwd_correlation_time_s": 7 * 86400.0,
    "ppp_precise_model_enabled": True,
    "ppp_apply_phase_windup": True,
    "ppp_use_ssr_yaw": True,
    "ppp_apply_shapiro_delay": True,
    "ppp_apply_solid_earth_tide": True,
    "ppp_apply_ocean_loading": True,
    "ppp_antex_file": "",
    "ppp_blq_file": "",
    "ppp_receiver_antenna": "",
    "ppp_station_id": "",
    "ppp_antenna_eccentricity_neu_m": [0.0, 0.0, 0.0],
    "ppp_auto_ssr_apc_reference": True,
    "ppp_ssr_apc_reference": False,
    "ppp_postfit_enabled": True,
    "ppp_max_code_postfit_residual_m": 3.0,
    "ppp_max_phase_postfit_residual_m": 0.03,
    "ppp_ar_enabled": True,
    "ppp_ar_systems": ["G", "E", "C", "J"],
    "ppp_ar_min_epochs": 30,
    "ppp_ar_min_satellites": 5,
    "ppp_ar_min_elevation_deg": 10.0,
    "ppp_ar_max_wl_fraction": 0.15,
    "ppp_ar_max_nl_fraction": 0.12,
    "ppp_ar_max_wl_sigma_cycles": 0.20,
    "ppp_ar_max_nl_sigma_cycles": 0.20,
    "ppp_ar_ratio_threshold": 3.0,
    "ppp_ar_constraint_sigma_m": 0.0001,
    "ppp_ar_max_position_shift_m": 0.50,
    "ppp_ar_require_mw_consistency": True,
    "ppp_ar_require_full_group": True,
    "rtk_type": "single_base",
    "rtk_network_protocol": "VRS",
    "rtk_rover_mode": "kinematic",
    "rtk_rover_format": "rtcm3",
    "rtk_base_format": "rtcm3",
    "rtk_frequency": "l1+l2",
    "rtk_dynamics": True,
    "rtk_ar_mode": "fix-and-hold",
    "rtk_glonass_ar_mode": "autocal",
    "rtk_bds_ar": True,
    "rtk_ar_ratio_threshold": 3.0,
    "rtk_ar_lock_count": 5,
    "rtk_ar_min_fix": 10,
    "rtk_ar_outage_count": 5,
    "rtk_max_correction_age_s": 10.0,
    "rtk_cycle_slip_threshold_m": 0.05,
    "rtk_filter_iterations": 1,
    "rtk_base_position_source": "rtcm",
    "rtk_base_position": [0.0, 0.0, 0.0],
    "rtk_gga_mode": "auto",
    "rtk_gga_position": [0.0, 0.0, 0.0],
    "rtk_gga_cycle_ms": 5000,
    "use_smoothing": False,
    "smoothing_window": 10,
    "random_walk": 0.0,
    "uncertain_std_pos": 5.0,
    "fixed_std_pos": 2.5,
}


class PositioningConfigDialog(QDialog):
    """Configure shared SPP/PPP parameters without a tall scrolling form."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Positioning Settings")
        self.setMinimumSize(820, 650)
        self.resize(900, 700)
        self.settings = {**DEFAULTS, **get_positioning_settings()}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)

        title = QLabel("Positioning engine")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("Settings are shared by live streams and RINEX replay.")
        subtitle.setProperty("class", "muted")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_systems_tab(), "Constellations")
        self.tabs.addTab(self._build_corrections_tab(), "Corrections / PPP")
        self.tabs.addTab(self._build_rtk_tab(), "RTK / Network")
        self.tabs.addTab(self._build_quality_tab(), "Quality")
        root.addWidget(self.tabs, 1)
        root.addLayout(self._build_buttons())

    def _form(self) -> QFormLayout:
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        return form

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        return page, layout

    def _double_spin(self, key, minimum, maximum, step, suffix="", decimals=3):
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setValue(float(self.settings.get(key, DEFAULTS[key])))
        return spin

    def _build_general_tab(self):
        page, layout = self._page()

        solve_group = QGroupBox("Solver limits")
        solve = self._form()
        self.cutoff_spin = self._double_spin("cutoff_elevation_deg", 0.0, 90.0, 0.5, " deg", 1)
        self.min_sats_spin = QSpinBox()
        self.min_sats_spin.setRange(2, 32)
        self.min_sats_spin.setValue(int(self.settings["min_satellites"]))
        self.max_pdop_spin = self._double_spin("max_pdop", 0.1, 100.0, 0.5, decimals=1)
        solve.addRow("Elevation mask", self.cutoff_spin)
        solve.addRow("Minimum satellites", self.min_sats_spin)
        solve.addRow("Maximum PDOP", self.max_pdop_spin)
        solve_group.setLayout(solve)
        layout.addWidget(solve_group)

        processing_group = QGroupBox("Observation processing")
        processing = self._form()
        self.weight_mode = QComboBox()
        self.weight_mode.addItem("Elevation angle", "elevation")
        self.weight_mode.addItem("Signal-to-noise ratio", "snr")
        self.weight_mode.addItem("Equal weight", "equal")
        self.weight_mode.setCurrentIndex(max(0, self.weight_mode.findData(self.settings["weight_mode"])))
        self.use_smoothing = QCheckBox("Enable position smoothing")
        self.use_smoothing.setChecked(bool(self.settings["use_smoothing"]))
        self.smoothing_window = QSpinBox()
        self.smoothing_window.setRange(1, 1000)
        self.smoothing_window.setValue(max(1, int(self.settings["smoothing_window"])))
        self.random_walk = self._double_spin("random_walk", 0.0, 100.0, 0.1, " m/sqrt(s)", 3)
        processing.addRow("Weighting", self.weight_mode)
        processing.addRow("", self.use_smoothing)
        processing.addRow("Smoothing window", self.smoothing_window)
        processing.addRow("Random walk", self.random_walk)
        processing_group.setLayout(processing)
        layout.addWidget(processing_group)
        layout.addStretch()
        return page

    def _build_systems_tab(self):
        page, layout = self._page()
        systems_group = QGroupBox("Enabled constellations")
        grid = QGridLayout(systems_group)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(12)
        enabled = set(self.settings["gnss_systems"])
        definitions = [
            ("G", "GPS"), ("R", "GLONASS"), ("E", "Galileo"),
            ("C", "BeiDou"), ("J", "QZSS"), ("I", "NavIC"),
        ]
        self.system_checks = {}
        for index, (code, label) in enumerate(definitions):
            checkbox = QCheckBox(f"{label}  ({code})")
            checkbox.setChecked(code in enabled)
            self.system_checks[code] = checkbox
            grid.addWidget(checkbox, index // 3, index % 3)
        self.gnss_gps = self.system_checks["G"]
        self.gnss_glonass = self.system_checks["R"]
        self.gnss_galileo = self.system_checks["E"]
        self.gnss_beidou = self.system_checks["C"]
        self.gnss_qzss = self.system_checks["J"]
        self.gnss_irnss = self.system_checks["I"]
        layout.addWidget(systems_group)

        behavior_group = QGroupBox("Selection behavior")
        behavior = QVBoxLayout(behavior_group)
        self.prefer_gps_only = QCheckBox("Prefer GPS-only for basic SPP")
        self.allow_gps_fallback = QCheckBox("Allow GPS fallback when multi-GNSS fails")
        self.prefer_gps_only.setChecked(bool(self.settings["prefer_gps_only"]))
        self.allow_gps_fallback.setChecked(bool(self.settings["allow_gps_fallback"]))
        behavior.addWidget(self.prefer_gps_only)
        behavior.addWidget(self.allow_gps_fallback)
        layout.addWidget(behavior_group)
        layout.addStretch()
        return page

    def _build_corrections_tab(self):
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)
        models_group = QGroupBox("Atmospheric and precise corrections")
        models = self._form()
        self.iono_option = QComboBox()
        self.iono_option.addItem("Dual-frequency ionosphere-free", "IFLC")
        self.iono_option.addItem("Single-frequency with TGD", "SINGLE")
        self.iono_option.setCurrentIndex(max(0, self.iono_option.findData(self.settings["ionosphere_option"])))
        self.tropo_model = QComboBox()
        self.tropo_model.addItem("Saastamoinen", "Sastamoinen")
        self.tropo_model.addItem("Height-based HMSL", "HMSL")
        self.tropo_model.addItem("No correction", "None")
        self.tropo_model.setCurrentIndex(max(0, self.tropo_model.findData(self.settings["troposphere_model"])))
        self.require_ssr_corrections = QCheckBox("Require SSR orbit and clock corrections")
        self.require_ssr_corrections.setChecked(bool(self.settings["require_ssr_corrections"]))
        models.addRow("Ionosphere", self.iono_option)
        models.addRow("Troposphere", self.tropo_model)
        models.addRow("", self.require_ssr_corrections)
        models_group.setLayout(models)
        layout.addWidget(models_group, 0, 0)

        ppp_group = QGroupBox("PPP filter initialization")
        ppp = self._form()
        self.ppp_use_station_apriori = QCheckBox(
            "Use RTCM station coordinates"
        )
        self.ppp_use_station_apriori.setChecked(bool(self.settings["ppp_use_station_apriori"]))
        self.ppp_use_config_initial_position = QCheckBox(
            "Use configured coordinate as initial state"
        )
        self.ppp_use_config_initial_position.setChecked(
            bool(self.settings["ppp_use_config_initial_position"])
        )
        self.ppp_station_sigma = self._double_spin("ppp_station_apriori_sigma_m", 0.001, 100.0, 0.01, " m", 3)
        self.ppp_initial_position_sigma = self._double_spin(
            "ppp_initial_position_sigma_m", 0.001, 1000.0, 0.01, " m", 3
        )
        self.ppp_station_sigma.setEnabled(self.ppp_use_station_apriori.isChecked())
        self.ppp_use_station_apriori.toggled.connect(self.ppp_station_sigma.setEnabled)
        self.ppp_clock_sigma = self._double_spin("ppp_initial_clock_sigma_m", 1.0, 100000.0, 10.0, " m", 1)
        self.ppp_ambiguity_sigma = self._double_spin("ppp_initial_ambiguity_sigma_m", 1.0, 100000.0, 10.0, " m", 1)
        ppp.addRow("", self.ppp_use_station_apriori)
        ppp.addRow("Station sigma", self.ppp_station_sigma)
        ppp.addRow("", self.ppp_use_config_initial_position)
        ppp.addRow("Initial position sigma", self.ppp_initial_position_sigma)
        ppp.addRow("Clock sigma", self.ppp_clock_sigma)
        ppp.addRow("Ambiguity sigma", self.ppp_ambiguity_sigma)
        ppp_group.setLayout(ppp)
        layout.addWidget(ppp_group, 1, 0)

        ar_group = QGroupBox("PPP ambiguity resolution")
        ar = self._form()
        self.ppp_ar_enabled = QCheckBox("Enable SSR phase-bias integer fixing")
        self.ppp_ar_enabled.setChecked(bool(self.settings["ppp_ar_enabled"]))
        self.ppp_ar_min_epochs = QSpinBox()
        self.ppp_ar_min_epochs.setRange(5, 3600)
        self.ppp_ar_min_epochs.setValue(int(self.settings["ppp_ar_min_epochs"]))
        self.ppp_ar_min_satellites = QSpinBox()
        self.ppp_ar_min_satellites.setRange(4, 30)
        self.ppp_ar_min_satellites.setValue(int(self.settings["ppp_ar_min_satellites"]))
        self.ppp_ar_ratio = self._double_spin("ppp_ar_ratio_threshold", 1.0, 20.0, 0.1, "", 2)
        self.ppp_ar_nl_fraction = self._double_spin("ppp_ar_max_nl_fraction", 0.001, 0.49, 0.01, " cycle", 3)
        ar.addRow("", self.ppp_ar_enabled)
        ar.addRow("Minimum epochs", self.ppp_ar_min_epochs)
        ar.addRow("Minimum satellites", self.ppp_ar_min_satellites)
        ar.addRow("Ratio threshold", self.ppp_ar_ratio)
        ar.addRow("NL fraction limit", self.ppp_ar_nl_fraction)
        ar_group.setLayout(ar)
        layout.addWidget(ar_group, 2, 0)

        model_group = QGroupBox("Precise observation model")
        model_layout = QVBoxLayout(model_group)
        model_layout.setSpacing(8)
        self.ppp_precise_model_enabled = QCheckBox("Enable precise physical corrections")
        self.ppp_precise_model_enabled.setChecked(bool(self.settings["ppp_precise_model_enabled"]))
        model_layout.addWidget(self.ppp_precise_model_enabled)

        switches = QGridLayout()
        switches.setHorizontalSpacing(12)
        switches.setVerticalSpacing(6)
        self.ppp_apply_phase_windup = QCheckBox("Phase wind-up")
        self.ppp_use_ssr_yaw = QCheckBox("SSR yaw attitude")
        self.ppp_apply_shapiro = QCheckBox("Shapiro delay")
        self.ppp_apply_solid_tide = QCheckBox("Solid Earth tide")
        self.ppp_apply_ocean_loading = QCheckBox("Ocean loading")
        self.ppp_auto_ssr_apc_reference = QCheckBox("Auto-detect SSRA APC")
        self.ppp_ssr_apc_reference = QCheckBox("SSR orbit referenced to APC")
        checks = [
            (self.ppp_apply_phase_windup, "ppp_apply_phase_windup"),
            (self.ppp_use_ssr_yaw, "ppp_use_ssr_yaw"),
            (self.ppp_apply_shapiro, "ppp_apply_shapiro_delay"),
            (self.ppp_apply_solid_tide, "ppp_apply_solid_earth_tide"),
            (self.ppp_apply_ocean_loading, "ppp_apply_ocean_loading"),
            (self.ppp_auto_ssr_apc_reference, "ppp_auto_ssr_apc_reference"),
            (self.ppp_ssr_apc_reference, "ppp_ssr_apc_reference"),
        ]
        for index, (checkbox, key) in enumerate(checks):
            checkbox.setChecked(bool(self.settings[key]))
            switches.addWidget(checkbox, index // 2, index % 2)
        model_layout.addLayout(switches)

        files = self._form()
        antex_editor, self.ppp_antex_file, self.ppp_antex_browse = self._file_editor(
            self.settings["ppp_antex_file"],
            "Select ANTEX calibration",
            "ANTEX files (*.atx *.antex);;All files (*)",
        )
        blq_editor, self.ppp_blq_file, self.ppp_blq_browse = self._file_editor(
            self.settings["ppp_blq_file"],
            "Select BLQ ocean loading file",
            "BLQ files (*.blq);;All files (*)",
        )
        self.ppp_receiver_antenna = QLineEdit(str(self.settings["ppp_receiver_antenna"]))
        self.ppp_station_id = QLineEdit(str(self.settings["ppp_station_id"]))
        eccentricity_editor, self.ppp_antenna_eccentricity = self._coordinate_editor(
            self.settings["ppp_antenna_eccentricity_neu_m"]
        )
        files.addRow("ANTEX", antex_editor)
        files.addRow("BLQ", blq_editor)
        files.addRow("Receiver antenna", self.ppp_receiver_antenna)
        files.addRow("BLQ station", self.ppp_station_id)
        files.addRow("Antenna N / E / U", eccentricity_editor)
        model_layout.addLayout(files)
        layout.addWidget(model_group, 0, 1, 3, 1)

        self.ppp_precise_model_enabled.toggled.connect(self._update_model_controls)
        self.ppp_apply_phase_windup.toggled.connect(self._update_model_controls)
        self.ppp_apply_ocean_loading.toggled.connect(self._update_model_controls)
        self.ppp_auto_ssr_apc_reference.toggled.connect(self._update_model_controls)
        self._update_model_controls()
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(3, 1)
        return page

    def _file_editor(self, value: str, caption: str, file_filter: str):
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        editor = QLineEdit(str(value or ""))
        button = QToolButton()
        button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        button.setToolTip(caption)
        button.clicked.connect(lambda: self._choose_file(editor, caption, file_filter))
        row.addWidget(editor, 1)
        row.addWidget(button)
        return container, editor, button

    def _choose_file(self, editor: QLineEdit, caption: str, file_filter: str):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            caption,
            editor.text().strip(),
            file_filter,
        )
        if path:
            editor.setText(path)

    def _update_model_controls(self):
        enabled = self.ppp_precise_model_enabled.isChecked()
        for checkbox in (
            self.ppp_apply_phase_windup,
            self.ppp_apply_shapiro,
            self.ppp_apply_solid_tide,
            self.ppp_apply_ocean_loading,
            self.ppp_auto_ssr_apc_reference,
        ):
            checkbox.setEnabled(enabled)
        self.ppp_ssr_apc_reference.setEnabled(
            enabled and not self.ppp_auto_ssr_apc_reference.isChecked()
        )
        self.ppp_use_ssr_yaw.setEnabled(
            enabled and self.ppp_apply_phase_windup.isChecked()
        )
        for widget in (
            self.ppp_antex_file,
            self.ppp_antex_browse,
            self.ppp_receiver_antenna,
            *self.ppp_antenna_eccentricity,
        ):
            widget.setEnabled(enabled)
        ocean_enabled = enabled and self.ppp_apply_ocean_loading.isChecked()
        for widget in (self.ppp_blq_file, self.ppp_blq_browse, self.ppp_station_id):
            widget.setEnabled(ocean_enabled)

    def _build_quality_tab(self):
        page, layout = self._page()
        status_group = QGroupBox("Solution classification")
        status = self._form()
        self.uncertain_std = self._double_spin("uncertain_std_pos", 0.1, 100.0, 0.1, " m", 2)
        self.fixed_std = self._double_spin("fixed_std_pos", 0.1, 100.0, 0.1, " m", 2)
        status.addRow("Unfixed standard deviation", self.uncertain_std)
        status.addRow("Fixed standard deviation", self.fixed_std)
        status_group.setLayout(status)
        layout.addWidget(status_group)

        process_group = QGroupBox("PPP process noise")
        process = self._form()
        self.ppp_position_noise = self._double_spin("ppp_position_process_noise_mps", 0.0, 10.0, 0.001, " m/s", 6)
        self.ppp_trop_noise = self._double_spin(
            "ppp_trop_process_noise_mps", 0.0, 1.0, 0.000001, " m/sqrt(s)", 8
        )
        self.ppp_zwd_correlation = self._double_spin(
            "ppp_zwd_correlation_time_s", 0.0, 2592000.0, 3600.0, " s", 0
        )
        process.addRow("Position", self.ppp_position_noise)
        process.addRow("ZWD random walk", self.ppp_trop_noise)
        process.addRow("ZWD correlation", self.ppp_zwd_correlation)
        process_group.setLayout(process)
        layout.addWidget(process_group)

        residual_group = QGroupBox("Post-fit residual validation")
        residual = self._form()
        self.ppp_postfit_enabled = QCheckBox("Iteratively remove the largest residual")
        self.ppp_postfit_enabled.setChecked(bool(self.settings["ppp_postfit_enabled"]))
        self.ppp_code_postfit_limit = self._double_spin(
            "ppp_max_code_postfit_residual_m", 0.01, 100.0, 0.1, " m", 3
        )
        self.ppp_phase_postfit_limit = self._double_spin(
            "ppp_max_phase_postfit_residual_m", 0.001, 10.0, 0.005, " m", 3
        )
        residual.addRow("", self.ppp_postfit_enabled)
        residual.addRow("Code residual", self.ppp_code_postfit_limit)
        residual.addRow("Phase residual", self.ppp_phase_postfit_limit)
        residual_group.setLayout(residual)
        layout.addWidget(residual_group)
        layout.addStretch()
        return page

    @staticmethod
    def _triplet(values) -> list[float]:
        try:
            result = [float(item) for item in values][:3]
        except (TypeError, ValueError):
            return [0.0, 0.0, 0.0]
        return result if len(result) == 3 else [0.0, 0.0, 0.0]

    def _coordinate_editor(self, values) -> tuple[QWidget, list[QLineEdit]]:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        editors = []
        for value in self._triplet(values):
            editor = QLineEdit(f"{value:.9f}" if value else "0")
            editor.setAlignment(Qt.AlignmentFlag.AlignRight)
            editors.append(editor)
            row.addWidget(editor)
        return container, editors

    def _build_rtk_tab(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        engine_group = QGroupBox("RTK engine")
        engine = self._form()
        self.rtk_type = QComboBox()
        self.rtk_type.addItem("Single-base RTK", "single_base")
        self.rtk_type.addItem("Network RTK", "network")
        self.rtk_type.setCurrentIndex(max(0, self.rtk_type.findData(self.settings["rtk_type"])))
        self.rtk_network_protocol = QComboBox()
        self.rtk_network_protocol.addItem("VRS", "VRS")
        self.rtk_network_protocol.addItem("FKP", "FKP")
        self.rtk_network_protocol.addItem("MAC", "MAC")
        self.rtk_network_protocol.setCurrentIndex(
            max(0, self.rtk_network_protocol.findData(self.settings["rtk_network_protocol"]))
        )
        self.rtk_rover_mode = QComboBox()
        self.rtk_rover_mode.addItem("Kinematic", "kinematic")
        self.rtk_rover_mode.addItem("Static", "static")
        self.rtk_rover_mode.addItem("Static start", "static-start")
        self.rtk_rover_mode.setCurrentIndex(max(0, self.rtk_rover_mode.findData(self.settings["rtk_rover_mode"])))
        self.rtk_frequency = QComboBox()
        self.rtk_frequency.addItem("L1", "l1")
        self.rtk_frequency.addItem("L1 + L2", "l1+l2")
        self.rtk_frequency.addItem("L1 + L2 + L5", "l1+l2+l5")
        self.rtk_frequency.addItem("Four frequencies", "l1+l2+l5+l6")
        self.rtk_frequency.setCurrentIndex(max(0, self.rtk_frequency.findData(self.settings["rtk_frequency"])))
        self.rtk_dynamics = QCheckBox("Enable rover dynamics model")
        self.rtk_dynamics.setChecked(bool(self.settings["rtk_dynamics"]))
        engine.addRow("Architecture", self.rtk_type)
        engine.addRow("Network protocol", self.rtk_network_protocol)
        engine.addRow("Rover mode", self.rtk_rover_mode)
        engine.addRow("Frequencies", self.rtk_frequency)
        engine.addRow("", self.rtk_dynamics)
        engine_group.setLayout(engine)
        grid.addWidget(engine_group, 0, 0)

        input_group = QGroupBox("Raw input formats")
        input_form = self._form()
        self.rtk_rover_format = QComboBox()
        self.rtk_base_format = QComboBox()
        formats = [
            ("RTCM 3", "rtcm3"),
            ("u-blox UBX", "ubx"),
            ("Unicore", "unicore"),
            ("NovAtel OEM4/OEM7", "oem4"),
            ("Septentrio SBF", "sbf"),
            ("RINEX", "rinex"),
        ]
        for label, value in formats:
            self.rtk_rover_format.addItem(label, value)
            self.rtk_base_format.addItem(label, value)
        self.rtk_rover_format.setCurrentIndex(
            max(0, self.rtk_rover_format.findData(self.settings["rtk_rover_format"]))
        )
        self.rtk_base_format.setCurrentIndex(
            max(0, self.rtk_base_format.findData(self.settings["rtk_base_format"]))
        )
        input_form.addRow("Rover", self.rtk_rover_format)
        input_form.addRow("Base / corrections", self.rtk_base_format)
        input_group.setLayout(input_form)
        grid.addWidget(input_group, 0, 1)

        ambiguity_group = QGroupBox("Integer ambiguity resolution")
        ambiguity = self._form()
        self.rtk_ar_mode = QComboBox()
        self.rtk_ar_mode.addItem("Continuous", "continuous")
        self.rtk_ar_mode.addItem("Fix and hold", "fix-and-hold")
        self.rtk_ar_mode.addItem("Instantaneous", "instantaneous")
        self.rtk_ar_mode.addItem("Disabled", "off")
        self.rtk_ar_mode.setCurrentIndex(max(0, self.rtk_ar_mode.findData(self.settings["rtk_ar_mode"])))
        self.rtk_glonass_ar = QComboBox()
        self.rtk_glonass_ar.addItem("Auto-calibrate", "autocal")
        self.rtk_glonass_ar.addItem("On", "on")
        self.rtk_glonass_ar.addItem("Fix and hold", "fix-and-hold")
        self.rtk_glonass_ar.addItem("Off", "off")
        self.rtk_glonass_ar.setCurrentIndex(
            max(0, self.rtk_glonass_ar.findData(self.settings["rtk_glonass_ar_mode"]))
        )
        self.rtk_bds_ar = QCheckBox("Enable BeiDou ambiguity resolution")
        self.rtk_bds_ar.setChecked(bool(self.settings["rtk_bds_ar"]))
        self.rtk_ratio = self._double_spin("rtk_ar_ratio_threshold", 1.0, 20.0, 0.1, decimals=2)
        self.rtk_lock_count = QSpinBox()
        self.rtk_lock_count.setRange(0, 1000)
        self.rtk_lock_count.setValue(int(self.settings["rtk_ar_lock_count"]))
        self.rtk_min_fix = QSpinBox()
        self.rtk_min_fix.setRange(1, 1000)
        self.rtk_min_fix.setValue(int(self.settings["rtk_ar_min_fix"]))
        ambiguity.addRow("Mode", self.rtk_ar_mode)
        ambiguity.addRow("GLONASS", self.rtk_glonass_ar)
        ambiguity.addRow("Ratio threshold", self.rtk_ratio)
        ambiguity.addRow("Lock epochs", self.rtk_lock_count)
        ambiguity.addRow("Hold after fixes", self.rtk_min_fix)
        ambiguity.addRow("", self.rtk_bds_ar)
        ambiguity_group.setLayout(ambiguity)
        grid.addWidget(ambiguity_group, 1, 0)

        reference_group = QGroupBox("Reference station and network GGA")
        reference = self._form()
        self.rtk_base_position_source = QComboBox()
        self.rtk_base_position_source.addItem("Read RTCM 1005/1006", "rtcm")
        self.rtk_base_position_source.addItem("Configured LLH", "llh")
        self.rtk_base_position_source.addItem("Configured ECEF XYZ", "xyz")
        self.rtk_base_position_source.setCurrentIndex(
            max(0, self.rtk_base_position_source.findData(self.settings["rtk_base_position_source"]))
        )
        base_editor, self.rtk_base_position = self._coordinate_editor(self.settings["rtk_base_position"])
        self.rtk_gga_mode = QComboBox()
        self.rtk_gga_mode.addItem("Automatic", "auto")
        self.rtk_gga_mode.addItem("Configured LLH", "configured")
        self.rtk_gga_mode.addItem("Rover single solution", "single")
        self.rtk_gga_mode.addItem("Disabled", "off")
        self.rtk_gga_mode.setCurrentIndex(max(0, self.rtk_gga_mode.findData(self.settings["rtk_gga_mode"])))
        gga_editor, self.rtk_gga_position = self._coordinate_editor(self.settings["rtk_gga_position"])
        self.rtk_gga_cycle = QSpinBox()
        self.rtk_gga_cycle.setRange(1000, 60000)
        self.rtk_gga_cycle.setSingleStep(1000)
        self.rtk_gga_cycle.setSuffix(" ms")
        self.rtk_gga_cycle.setValue(int(self.settings["rtk_gga_cycle_ms"]))
        self.rtk_max_age = self._double_spin("rtk_max_correction_age_s", 0.1, 120.0, 0.5, " s", 1)
        reference.addRow("Base coordinates", self.rtk_base_position_source)
        reference.addRow("Position 1 / 2 / 3", base_editor)
        reference.addRow("Network GGA", self.rtk_gga_mode)
        reference.addRow("GGA lat / lon / h", gga_editor)
        reference.addRow("GGA cycle", self.rtk_gga_cycle)
        reference.addRow("Maximum correction age", self.rtk_max_age)
        reference_group.setLayout(reference)
        grid.addWidget(reference_group, 1, 1)

        self.rtk_type.currentIndexChanged.connect(self._update_rtk_controls)
        self.rtk_base_position_source.currentIndexChanged.connect(self._update_rtk_controls)
        self.rtk_gga_mode.currentIndexChanged.connect(self._update_rtk_controls)
        self._update_rtk_controls()
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return page

    def _update_rtk_controls(self):
        network = self.rtk_type.currentData() == "network"
        self.rtk_network_protocol.setEnabled(network)
        self.rtk_gga_mode.setEnabled(network)
        self.rtk_gga_cycle.setEnabled(network and self.rtk_gga_mode.currentData() != "off")
        gga_coordinates = network and self.rtk_gga_mode.currentData() in {"auto", "configured"}
        for editor in self.rtk_gga_position:
            editor.setEnabled(gga_coordinates)
        base_coordinates = self.rtk_base_position_source.currentData() != "rtcm"
        for editor in self.rtk_base_position:
            editor.setEnabled(base_coordinates)

    @staticmethod
    def _read_coordinates(editors: list[QLineEdit]) -> list[float]:
        values = []
        for editor in editors:
            try:
                values.append(float(editor.text().strip()))
            except ValueError:
                values.append(0.0)
        return values

    def _build_buttons(self):
        row = QHBoxLayout()
        reset = QPushButton("Reset defaults")
        reset.clicked.connect(self.on_reset_defaults)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save settings")
        save.setObjectName("PrimaryButton")
        save.setDefault(True)
        save.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        save.clicked.connect(self.on_accept)
        row.addWidget(reset)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(save)
        return row

    def on_reset_defaults(self):
        self.cutoff_spin.setValue(DEFAULTS["cutoff_elevation_deg"])
        self.min_sats_spin.setValue(DEFAULTS["min_satellites"])
        self.max_pdop_spin.setValue(DEFAULTS["max_pdop"])
        self.iono_option.setCurrentIndex(self.iono_option.findData(DEFAULTS["ionosphere_option"]))
        self.tropo_model.setCurrentIndex(self.tropo_model.findData(DEFAULTS["troposphere_model"]))
        for code, checkbox in self.system_checks.items():
            checkbox.setChecked(code in DEFAULTS["gnss_systems"])
        self.prefer_gps_only.setChecked(DEFAULTS["prefer_gps_only"])
        self.allow_gps_fallback.setChecked(DEFAULTS["allow_gps_fallback"])
        self.require_ssr_corrections.setChecked(DEFAULTS["require_ssr_corrections"])
        self.weight_mode.setCurrentIndex(self.weight_mode.findData(DEFAULTS["weight_mode"]))
        self.use_smoothing.setChecked(DEFAULTS["use_smoothing"])
        self.smoothing_window.setValue(DEFAULTS["smoothing_window"])
        self.random_walk.setValue(DEFAULTS["random_walk"])
        self.uncertain_std.setValue(DEFAULTS["uncertain_std_pos"])
        self.fixed_std.setValue(DEFAULTS["fixed_std_pos"])
        self.ppp_use_station_apriori.setChecked(DEFAULTS["ppp_use_station_apriori"])
        self.ppp_use_config_initial_position.setChecked(
            DEFAULTS["ppp_use_config_initial_position"]
        )
        self.ppp_station_sigma.setValue(DEFAULTS["ppp_station_apriori_sigma_m"])
        self.ppp_initial_position_sigma.setValue(
            DEFAULTS["ppp_initial_position_sigma_m"]
        )
        self.ppp_clock_sigma.setValue(DEFAULTS["ppp_initial_clock_sigma_m"])
        self.ppp_ambiguity_sigma.setValue(DEFAULTS["ppp_initial_ambiguity_sigma_m"])
        self.ppp_position_noise.setValue(DEFAULTS["ppp_position_process_noise_mps"])
        self.ppp_trop_noise.setValue(DEFAULTS["ppp_trop_process_noise_mps"])
        self.ppp_zwd_correlation.setValue(DEFAULTS["ppp_zwd_correlation_time_s"])
        self.ppp_precise_model_enabled.setChecked(DEFAULTS["ppp_precise_model_enabled"])
        self.ppp_apply_phase_windup.setChecked(DEFAULTS["ppp_apply_phase_windup"])
        self.ppp_use_ssr_yaw.setChecked(DEFAULTS["ppp_use_ssr_yaw"])
        self.ppp_apply_shapiro.setChecked(DEFAULTS["ppp_apply_shapiro_delay"])
        self.ppp_apply_solid_tide.setChecked(DEFAULTS["ppp_apply_solid_earth_tide"])
        self.ppp_apply_ocean_loading.setChecked(DEFAULTS["ppp_apply_ocean_loading"])
        self.ppp_auto_ssr_apc_reference.setChecked(DEFAULTS["ppp_auto_ssr_apc_reference"])
        self.ppp_ssr_apc_reference.setChecked(DEFAULTS["ppp_ssr_apc_reference"])
        self.ppp_antex_file.setText(DEFAULTS["ppp_antex_file"])
        self.ppp_blq_file.setText(DEFAULTS["ppp_blq_file"])
        self.ppp_receiver_antenna.setText(DEFAULTS["ppp_receiver_antenna"])
        self.ppp_station_id.setText(DEFAULTS["ppp_station_id"])
        for editor, value in zip(
            self.ppp_antenna_eccentricity,
            DEFAULTS["ppp_antenna_eccentricity_neu_m"],
        ):
            editor.setText(str(value))
        self.ppp_postfit_enabled.setChecked(DEFAULTS["ppp_postfit_enabled"])
        self.ppp_code_postfit_limit.setValue(DEFAULTS["ppp_max_code_postfit_residual_m"])
        self.ppp_phase_postfit_limit.setValue(DEFAULTS["ppp_max_phase_postfit_residual_m"])
        self.ppp_ar_enabled.setChecked(DEFAULTS["ppp_ar_enabled"])
        self.ppp_ar_min_epochs.setValue(DEFAULTS["ppp_ar_min_epochs"])
        self.ppp_ar_min_satellites.setValue(DEFAULTS["ppp_ar_min_satellites"])
        self.ppp_ar_ratio.setValue(DEFAULTS["ppp_ar_ratio_threshold"])
        self.ppp_ar_nl_fraction.setValue(DEFAULTS["ppp_ar_max_nl_fraction"])
        self.rtk_type.setCurrentIndex(self.rtk_type.findData(DEFAULTS["rtk_type"]))
        self.rtk_network_protocol.setCurrentIndex(self.rtk_network_protocol.findData(DEFAULTS["rtk_network_protocol"]))
        self.rtk_rover_mode.setCurrentIndex(self.rtk_rover_mode.findData(DEFAULTS["rtk_rover_mode"]))
        self.rtk_rover_format.setCurrentIndex(self.rtk_rover_format.findData(DEFAULTS["rtk_rover_format"]))
        self.rtk_base_format.setCurrentIndex(self.rtk_base_format.findData(DEFAULTS["rtk_base_format"]))
        self.rtk_frequency.setCurrentIndex(self.rtk_frequency.findData(DEFAULTS["rtk_frequency"]))
        self.rtk_dynamics.setChecked(DEFAULTS["rtk_dynamics"])
        self.rtk_ar_mode.setCurrentIndex(self.rtk_ar_mode.findData(DEFAULTS["rtk_ar_mode"]))
        self.rtk_glonass_ar.setCurrentIndex(self.rtk_glonass_ar.findData(DEFAULTS["rtk_glonass_ar_mode"]))
        self.rtk_bds_ar.setChecked(DEFAULTS["rtk_bds_ar"])
        self.rtk_ratio.setValue(DEFAULTS["rtk_ar_ratio_threshold"])
        self.rtk_lock_count.setValue(DEFAULTS["rtk_ar_lock_count"])
        self.rtk_min_fix.setValue(DEFAULTS["rtk_ar_min_fix"])
        self.rtk_base_position_source.setCurrentIndex(
            self.rtk_base_position_source.findData(DEFAULTS["rtk_base_position_source"])
        )
        for editor, value in zip(self.rtk_base_position, DEFAULTS["rtk_base_position"]):
            editor.setText(str(value))
        self.rtk_gga_mode.setCurrentIndex(self.rtk_gga_mode.findData(DEFAULTS["rtk_gga_mode"]))
        for editor, value in zip(self.rtk_gga_position, DEFAULTS["rtk_gga_position"]):
            editor.setText(str(value))
        self.rtk_gga_cycle.setValue(DEFAULTS["rtk_gga_cycle_ms"])
        self.rtk_max_age.setValue(DEFAULTS["rtk_max_correction_age_s"])

    def on_accept(self):
        update_positioning_settings(self.get_settings())
        self.accept()

    def get_settings(self):
        systems = [code for code, checkbox in self.system_checks.items() if checkbox.isChecked()]
        return {
            "cutoff_elevation_deg": float(self.cutoff_spin.value()),
            "min_satellites": int(self.min_sats_spin.value()),
            "max_pdop": float(self.max_pdop_spin.value()),
            "ionosphere_option": self.iono_option.currentData(),
            "troposphere_model": self.tropo_model.currentData(),
            "gnss_systems": systems or ["G"],
            "prefer_gps_only": self.prefer_gps_only.isChecked(),
            "allow_gps_fallback": self.allow_gps_fallback.isChecked(),
            "require_ssr_corrections": self.require_ssr_corrections.isChecked(),
            "weight_mode": self.weight_mode.currentData(),
            "code_sigma_m": float(self.settings.get("code_sigma_m", 1.0)),
            "system_code_weight_factors": dict(self.settings.get("system_code_weight_factors", {"R": 5.0})),
            "use_smoothing": self.use_smoothing.isChecked(),
            "smoothing_window": int(self.smoothing_window.value()),
            "random_walk": float(self.random_walk.value()),
            "uncertain_std_pos": float(self.uncertain_std.value()),
            "fixed_std_pos": float(self.fixed_std.value()),
            "ppp_use_station_apriori": self.ppp_use_station_apriori.isChecked(),
            "ppp_use_config_initial_position": self.ppp_use_config_initial_position.isChecked(),
            "ppp_independent_mode": bool(
                self.settings.get("ppp_independent_mode", False)
            ),
            "ppp_observation_model": str(
                self.settings.get("ppp_observation_model", "IFLC")
            ),
            "ppp_station_apriori_sigma_m": float(self.ppp_station_sigma.value()),
            "ppp_initial_position_sigma_m": float(self.ppp_initial_position_sigma.value()),
            "ppp_spp_bootstrap_sigma_m": float(
                self.settings.get("ppp_spp_bootstrap_sigma_m", 100.0)
            ),
            "ppp_initial_clock_sigma_m": float(self.ppp_clock_sigma.value()),
            "ppp_initial_ambiguity_sigma_m": float(self.ppp_ambiguity_sigma.value()),
            "ppp_initial_ionosphere_sigma_m": float(
                self.settings.get("ppp_initial_ionosphere_sigma_m", 30.0)
            ),
            "ppp_ionosphere_process_noise_mps": float(
                self.settings.get("ppp_ionosphere_process_noise_mps", 0.001)
            ),
            "ppp_position_process_noise_mps": float(self.ppp_position_noise.value()),
            "ppp_trop_process_noise_mps": float(self.ppp_trop_noise.value()),
            "ppp_estimate_trop_gradients": bool(
                self.settings.get("ppp_estimate_trop_gradients", True)
            ),
            "ppp_initial_trop_gradient_sigma_m": float(
                self.settings.get("ppp_initial_trop_gradient_sigma_m", 0.01)
            ),
            "ppp_trop_gradient_process_noise_mps": float(
                self.settings.get("ppp_trop_gradient_process_noise_mps", 1e-5)
            ),
            "ppp_zwd_correlation_time_s": float(self.ppp_zwd_correlation.value()),
            "ppp_precise_model_enabled": self.ppp_precise_model_enabled.isChecked(),
            "ppp_apply_phase_windup": self.ppp_apply_phase_windup.isChecked(),
            "ppp_use_ssr_yaw": self.ppp_use_ssr_yaw.isChecked(),
            "ppp_apply_shapiro_delay": self.ppp_apply_shapiro.isChecked(),
            "ppp_apply_solid_earth_tide": self.ppp_apply_solid_tide.isChecked(),
            "ppp_apply_ocean_loading": self.ppp_apply_ocean_loading.isChecked(),
            "ppp_antex_file": self.ppp_antex_file.text().strip(),
            "ppp_blq_file": self.ppp_blq_file.text().strip(),
            "ppp_receiver_antenna": self.ppp_receiver_antenna.text().strip(),
            "ppp_station_id": self.ppp_station_id.text().strip().upper(),
            "ppp_antenna_eccentricity_neu_m": self._read_coordinates(
                self.ppp_antenna_eccentricity
            ),
            "ppp_auto_ssr_apc_reference": self.ppp_auto_ssr_apc_reference.isChecked(),
            "ppp_ssr_apc_reference": self.ppp_ssr_apc_reference.isChecked(),
            "ppp_postfit_enabled": self.ppp_postfit_enabled.isChecked(),
            "ppp_max_code_postfit_residual_m": float(self.ppp_code_postfit_limit.value()),
            "ppp_max_phase_postfit_residual_m": float(self.ppp_phase_postfit_limit.value()),
            "ppp_ar_enabled": self.ppp_ar_enabled.isChecked(),
            "ppp_ar_systems": list(self.settings.get("ppp_ar_systems", ["G", "E", "C", "J"])),
            "ppp_ar_min_epochs": int(self.ppp_ar_min_epochs.value()),
            "ppp_ar_min_satellites": int(self.ppp_ar_min_satellites.value()),
            "ppp_ar_min_elevation_deg": float(self.settings.get("ppp_ar_min_elevation_deg", 10.0)),
            "ppp_ar_max_wl_fraction": float(self.settings.get("ppp_ar_max_wl_fraction", 0.15)),
            "ppp_ar_max_nl_fraction": float(self.ppp_ar_nl_fraction.value()),
            "ppp_ar_max_wl_sigma_cycles": float(self.settings.get("ppp_ar_max_wl_sigma_cycles", 0.20)),
            "ppp_ar_max_nl_sigma_cycles": float(self.settings.get("ppp_ar_max_nl_sigma_cycles", 0.20)),
            "ppp_ar_ratio_threshold": float(self.ppp_ar_ratio.value()),
            "ppp_ar_constraint_sigma_m": float(self.settings.get("ppp_ar_constraint_sigma_m", 0.0001)),
            "ppp_ar_max_position_shift_m": float(self.settings.get("ppp_ar_max_position_shift_m", 0.50)),
            "ppp_ar_require_mw_consistency": bool(
                self.settings.get("ppp_ar_require_mw_consistency", True)
            ),
            "ppp_ar_require_full_group": bool(
                self.settings.get("ppp_ar_require_full_group", True)
            ),
            "rtk_type": self.rtk_type.currentData(),
            "rtk_network_protocol": self.rtk_network_protocol.currentData(),
            "rtk_rover_mode": self.rtk_rover_mode.currentData(),
            "rtk_rover_format": self.rtk_rover_format.currentData(),
            "rtk_base_format": self.rtk_base_format.currentData(),
            "rtk_frequency": self.rtk_frequency.currentData(),
            "rtk_dynamics": self.rtk_dynamics.isChecked(),
            "rtk_ar_mode": self.rtk_ar_mode.currentData(),
            "rtk_glonass_ar_mode": self.rtk_glonass_ar.currentData(),
            "rtk_bds_ar": self.rtk_bds_ar.isChecked(),
            "rtk_ar_ratio_threshold": float(self.rtk_ratio.value()),
            "rtk_ar_lock_count": int(self.rtk_lock_count.value()),
            "rtk_ar_min_fix": int(self.rtk_min_fix.value()),
            "rtk_ar_outage_count": int(self.settings.get("rtk_ar_outage_count", 5)),
            "rtk_max_correction_age_s": float(self.rtk_max_age.value()),
            "rtk_cycle_slip_threshold_m": float(self.settings.get("rtk_cycle_slip_threshold_m", 0.05)),
            "rtk_filter_iterations": int(self.settings.get("rtk_filter_iterations", 1)),
            "rtk_base_position_source": self.rtk_base_position_source.currentData(),
            "rtk_base_position": self._read_coordinates(self.rtk_base_position),
            "rtk_gga_mode": self.rtk_gga_mode.currentData(),
            "rtk_gga_position": self._read_coordinates(self.rtk_gga_position),
            "rtk_gga_cycle_ms": int(self.rtk_gga_cycle.value()),
        }
