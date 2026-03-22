"""GUI editor for reflectometry YAML configuration."""

from __future__ import annotations

from pathlib import Path
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QHeaderView,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import yaml

from core.reflectometry.config import DEFAULT_CONFIG_YAML, config_to_dict, load_config
from core.reflectometry.services.products import classify_environment
from ui.responsive import adaptive_window_size


class ReflectometryConfigDialog(QDialog):
    """Edit, import, and export IR YAML config from the GUI."""

    SYSTEM_OPTIONS = [
        ("G", "GPS"),
        ("R", "GLONASS"),
        ("E", "Galileo"),
        ("C", "BeiDou"),
        ("J", "QZSS"),
        ("S", "SBAS"),
        ("I", "IRNSS"),
    ]

    def __init__(self, config_path: str | Path, parent=None, initial_yaml_text: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reflectometry IR Config")
        adaptive_window_size(self, target=(960, 680), minimum=(700, 520))
        self.project_root = Path(__file__).resolve().parents[2]
        self.config_path = self._resolve_path(config_path)
        self.current_path = self.config_path
        self.current_yaml_text = initial_yaml_text if initial_yaml_text is not None else self._read_initial_yaml(self.current_path)
        self.config = self._load_config_from_text(self.current_yaml_text)
        self._building_form = False
        self._loading_zone_editor = False
        self.monument_height_value = 0.0
        self.system_checks: dict[str, QCheckBox] = {}
        self._setup_ui()
        self._load_config_to_form()

    def _setup_ui(self) -> None:
        self.setObjectName("reflectometryConfigDialog")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("configTabs")
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)

        self.tabs.addTab(self._build_tab_page(self._build_station_section(), self._build_geometry_section()), "Station")
        self.tabs.addTab(self._build_tab_page(self._build_input_section()), "Scope")
        self.tabs.addTab(self._build_tab_page(self._build_processing_section()), "Processing")
        self.tabs.addTab(self._build_tab_page(self._build_products_section()), "Products")

        yaml_tab = QWidget()
        yaml_layout = QVBoxLayout(yaml_tab)
        yaml_layout.setContentsMargins(0, 0, 0, 0)
        yaml_card = self._build_card("YAML Editor", "Import or fine-tune the reflectometry configuration directly.")
        yaml_card_layout = yaml_card.layout()
        self.yaml_editor = QPlainTextEdit()
        self.yaml_editor.setPlaceholderText("Paste or edit reflectometry YAML configuration here.")
        self.yaml_editor.textChanged.connect(self._on_yaml_text_changed)
        yaml_card_layout.addWidget(self.yaml_editor)
        yaml_layout.addWidget(yaml_card)
        self.tabs.addTab(yaml_tab, "YAML")
        layout.addWidget(self.tabs)

        button_bar = QHBoxLayout()
        self.path_label = QLabel(str(self.current_path))
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        button_bar.addWidget(self.path_label)
        button_bar.addStretch()

        btn_import = QPushButton("Import YAML")
        btn_import.clicked.connect(self.import_yaml)
        button_bar.addWidget(btn_import)

        btn_export = QPushButton("Export YAML")
        btn_export.clicked.connect(self.export_yaml)
        button_bar.addWidget(btn_export)

        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self._accept_if_valid)
        button_bar.addWidget(btn_apply)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        button_bar.addWidget(btn_cancel)

        layout.addLayout(button_bar)
        self._apply_dialog_styles()

    def _build_tab_page(self, *sections: QWidget) -> QWidget:
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(8, 8, 8, 8)
        container_layout.setSpacing(10)
        for section in sections:
            container_layout.addWidget(section)
        container_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(container)
        return scroll

    def _build_card(self, title: str, description: str | None = None) -> QFrame:
        card = QFrame()
        card.setObjectName("configCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        layout.addWidget(title_label)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("cardDescription")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        return card

    def _build_station_section(self) -> QWidget:
        card = self._build_card(
            "Station",
            "Basic station metadata, site environment, and reflector-height search range.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        _configure_form_layout(form)

        self.station_id_edit = QLineEdit()
        self.latitude_spin = _float_spin(-90.0, 90.0, 6)
        self.longitude_spin = _float_spin(-180.0, 180.0, 6)
        self.height_spin = _float_spin(-1000.0, 10000.0, 3)
        self.antenna_height_spin = _float_spin(0.0, 100.0, 3)
        self.min_height_spin = _float_spin(0.0, 100.0, 3)
        self.max_height_spin = _float_spin(0.0, 100.0, 3)
        self.environment_combo = QComboBox()
        self.environment_combo.setEditable(True)
        self.environment_combo.addItems(["unknown", "coastal", "riverbank", "snowfield", "inland", "custom"])
        self.environment_combo.currentTextChanged.connect(self._on_environment_changed)
        self.surface_combo = QComboBox()
        self.surface_combo.setEditable(True)
        self.surface_combo.addItems(["sea", "river", "snow", "soil", "ice", "mixed", "custom"])

        for widget in [
            self.station_id_edit,
            self.latitude_spin,
            self.longitude_spin,
            self.height_spin,
            self.antenna_height_spin,
            self.min_height_spin,
            self.max_height_spin,
            self.surface_combo,
        ]:
            _connect_change(widget, self._sync_form_to_yaml)

        form.addRow("Station ID", self.station_id_edit)
        form.addRow("Latitude (deg)", self.latitude_spin)
        form.addRow("Longitude (deg)", self.longitude_spin)
        form.addRow("Height (m)", self.height_spin)
        form.addRow("Antenna Height (m)", self.antenna_height_spin)
        form.addRow("Min Reflector Height (m)", self.min_height_spin)
        form.addRow("Max Reflector Height (m)", self.max_height_spin)
        form.addRow("Environment", self.environment_combo)
        form.addRow("Surface", self.surface_combo)
        card.layout().addWidget(form_widget)
        return card

    def _build_input_section(self) -> QWidget:
        card = self._build_card(
            "Systems And Signals",
            "Reflectometry analyzes all enabled constellations and frequencies by default. "
            "Only excluded systems or signals are listed here.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        _configure_form_layout(form)

        self.exclude_signals_edit = QLineEdit()
        self.exclude_signals_edit.setPlaceholderText("Example: 2W,7Q")
        systems_row = QHBoxLayout()
        systems_row.setSpacing(10)
        for sys_char, label in self.SYSTEM_OPTIONS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            self.system_checks[sys_char] = checkbox
            _connect_change(checkbox, self._sync_form_to_yaml)
            systems_row.addWidget(checkbox)
        systems_row.addStretch()

        for widget in [self.exclude_signals_edit]:
            _connect_change(widget, self._sync_form_to_yaml)

        form.addRow("Enabled Systems", _wrap_layout(systems_row))
        form.addRow("Exclude Signals", self.exclude_signals_edit)
        info_label = QLabel(
            "Advanced offline source selection and time-window settings are kept in the YAML tab."
        )
        info_label.setObjectName("cardDescription")
        info_label.setWordWrap(True)
        card.layout().addWidget(form_widget)
        card.layout().addWidget(info_label)
        return card

    def _build_processing_section(self) -> QWidget:
        card = self._build_card(
            "Processing And QC",
            "Control realtime arc solving cadence and optional SNR preprocessing.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        _configure_form_layout(form)

        self.min_arc_seconds_spin = _float_spin(0.0, 20000.0, 1)
        self.min_pnr_spin = _float_spin(0.0, 100.0, 2)
        self.live_arc_window_spin = _float_spin(1.0, 1440.0, 0)
        self.live_interval_spin = _float_spin(1.0, 3600.0, 0)
        self.detrend_order_spin = _float_spin(1.0, 10.0, 0)
        self.smoothing_method_combo = QComboBox()
        self.smoothing_method_combo.addItems(["none", "moving_average", "savgol"])
        self.smoothing_window_spin = _float_spin(1.0, 101.0, 0)
        self.output_dir_edit = QLineEdit()

        for widget in [
            self.min_arc_seconds_spin,
            self.min_pnr_spin,
            self.live_arc_window_spin,
            self.live_interval_spin,
            self.detrend_order_spin,
            self.smoothing_method_combo,
            self.smoothing_window_spin,
            self.output_dir_edit,
        ]:
            _connect_change(widget, self._sync_form_to_yaml)
        self.smoothing_method_combo.currentTextChanged.connect(self._update_processing_control_state)

        form.addRow("Live Arc Window (min)", self.live_arc_window_spin)
        form.addRow("Live Analysis Interval (s)", self.live_interval_spin)
        form.addRow("Min Arc Duration (s)", self.min_arc_seconds_spin)
        form.addRow("Detrend Order", self.detrend_order_spin)
        form.addRow("Smoothing", self.smoothing_method_combo)
        form.addRow("Smoothing Window", self.smoothing_window_spin)
        form.addRow("Min Peak/Noise", self.min_pnr_spin)
        form.addRow("Output Dir", self.output_dir_edit)
        card.layout().addWidget(form_widget)
        return card

    def _build_geometry_section(self) -> QWidget:
        card = self._build_card(
            "Reflection Zones",
            "Each row is one independent reflector area. An observation is kept when it falls inside any zone below.",
        )
        usage_label = QLabel(
            "Azimuth windows format: `150-220;240-300`. Cross-north windows can be written as `330-20`. "
            "If a station has multiple reflection areas, add multiple rows."
        )
        usage_label.setObjectName("cardDescription")
        usage_label.setWordWrap(True)
        card.layout().addWidget(usage_label)

        self.zone_table = QTableWidget(0, 4)
        self.zone_table.setHorizontalHeaderLabels(["Zone", "Min El (deg)", "Max El (deg)", "Azimuth Windows"])
        self.zone_table.verticalHeader().setVisible(False)
        self.zone_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.zone_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.zone_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.zone_table.setAlternatingRowColors(True)
        self.zone_table.setWordWrap(False)
        self.zone_table.setMinimumHeight(140)
        header = self.zone_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.zone_table.itemSelectionChanged.connect(self._on_zone_selection_changed)
        card.layout().addWidget(self.zone_table)

        detail_frame = QFrame()
        detail_frame.setObjectName("configInsetCard")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(10)

        detail_title = QLabel("Selected Zone")
        detail_title.setObjectName("cardTitle")
        detail_layout.addWidget(detail_title)

        detail_form_widget = QWidget()
        detail_form = QFormLayout(detail_form_widget)
        _configure_form_layout(detail_form)

        self.zone_name_edit = QLineEdit()
        self.zone_name_edit.setPlaceholderText("zone_1")
        self.zone_name_edit.setClearButtonEnabled(True)
        self.zone_min_el_spin = _float_spin(0.0, 90.0, 2)
        self.zone_max_el_spin = _float_spin(0.0, 90.0, 2)
        self.zone_windows_edit = QLineEdit()
        self.zone_windows_edit.setPlaceholderText("150-220;240-300;330-20")
        self.zone_windows_edit.setClearButtonEnabled(True)
        self.zone_windows_edit.setMinimumWidth(320)
        self.zone_windows_hint = QLabel(
            "Use `start-end;start-end`. If the sector crosses north, enter `330-20`."
        )
        self.zone_windows_hint.setObjectName("cardDescription")
        self.zone_windows_hint.setWordWrap(True)

        for widget in [
            self.zone_name_edit,
            self.zone_min_el_spin,
            self.zone_max_el_spin,
            self.zone_windows_edit,
        ]:
            _connect_change(widget, self._on_zone_editor_changed)

        detail_form.addRow("Zone Name", self.zone_name_edit)
        detail_form.addRow("Min Elevation (deg)", self.zone_min_el_spin)
        detail_form.addRow("Max Elevation (deg)", self.zone_max_el_spin)
        detail_form.addRow("Azimuth Windows", self.zone_windows_edit)
        detail_layout.addWidget(detail_form_widget)
        detail_layout.addWidget(self.zone_windows_hint)
        card.layout().addWidget(detail_frame)

        zone_button_row = QHBoxLayout()
        self.btn_add_zone = QPushButton("Add Zone")
        self.btn_add_zone.clicked.connect(self._add_zone_row)
        zone_button_row.addWidget(self.btn_add_zone)
        self.btn_remove_zone = QPushButton("Remove Zone")
        self.btn_remove_zone.clicked.connect(self._remove_selected_zone_rows)
        zone_button_row.addWidget(self.btn_remove_zone)
        zone_button_row.addStretch()
        card.layout().addLayout(zone_button_row)
        return card

    def _build_products_section(self) -> QWidget:
        card = self._build_card(
            "Products",
            "Product options follow the selected environment automatically, while keeping reflector height always enabled.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        _configure_form_layout(form)

        self.enable_height_chk = QCheckBox("Reflector Height")
        self.enable_height_chk.setChecked(True)
        self.enable_height_chk.setEnabled(False)
        self.enable_sea_level_chk = QCheckBox("Sea Level")
        self.enable_snow_depth_chk = QCheckBox("Snow Depth")
        self.sea_level_ref_spin = _float_spin(-100.0, 1000.0, 3)
        self.snow_ref_spin = _float_spin(-100.0, 1000.0, 3)
        self.product_policy_label = QLabel()
        self.product_policy_label.setWordWrap(True)

        for widget in [
            self.enable_sea_level_chk,
            self.enable_snow_depth_chk,
            self.sea_level_ref_spin,
            self.snow_ref_spin,
        ]:
            _connect_change(widget, self._sync_form_to_yaml)

        product_row = QHBoxLayout()
        product_row.addWidget(self.enable_height_chk)
        product_row.addWidget(self.enable_sea_level_chk)
        product_row.addWidget(self.enable_snow_depth_chk)
        product_row.addStretch()
        self.sea_level_ref_label = QLabel("Sea Level Reference")
        self.snow_ref_label = QLabel("Snow Reference Height")
        form.addRow("Policy", self.product_policy_label)
        form.addRow("Enabled", _wrap_layout(product_row))
        form.addRow(self.sea_level_ref_label, self.sea_level_ref_spin)
        form.addRow(self.snow_ref_label, self.snow_ref_spin)
        card.layout().addWidget(form_widget)
        return card

    def _on_zone_selection_changed(self) -> None:
        self._load_selected_zone_into_editor()

    def _set_zone_rows(self, zones: list[dict[str, object]]) -> None:
        self.zone_table.blockSignals(True)
        try:
            self.zone_table.setRowCount(0)
            for zone in zones:
                self._append_zone_row(
                    name=str(zone.get("name") or f"zone_{self.zone_table.rowCount() + 1}"),
                    min_elevation_deg=float(zone.get("min_elevation_deg", 5.0)),
                    max_elevation_deg=float(zone.get("max_elevation_deg", 30.0)),
                    azimuth_windows=str(zone.get("azimuth_windows") or "0-360"),
                )
            if self.zone_table.rowCount() == 0:
                self._append_zone_row("zone_1", 5.0, 30.0, "0-360")
        finally:
            self.zone_table.blockSignals(False)
        self._ensure_zone_selection()

    def _append_zone_row(
        self,
        name: str,
        min_elevation_deg: float,
        max_elevation_deg: float,
        azimuth_windows: str,
    ) -> None:
        row_index = self.zone_table.rowCount()
        self.zone_table.insertRow(row_index)
        values = [
            name,
            f"{float(min_elevation_deg):g}",
            f"{float(max_elevation_deg):g}",
            azimuth_windows,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if column == 3:
                item.setToolTip(str(value))
            self.zone_table.setItem(row_index, column, item)

    def _add_zone_row(self) -> None:
        next_index = self.zone_table.rowCount() + 1
        default_min = 5.0
        default_max = 30.0
        default_windows = "0-360"
        if self.zone_table.rowCount() > 0:
            default_min = _table_float(self.zone_table.item(self.zone_table.rowCount() - 1, 1), default_min)
            default_max = _table_float(self.zone_table.item(self.zone_table.rowCount() - 1, 2), default_max)
            default_windows = _table_text(self.zone_table.item(self.zone_table.rowCount() - 1, 3), default_windows)
        self.zone_table.blockSignals(True)
        try:
            self._append_zone_row(f"zone_{next_index}", default_min, default_max, default_windows)
        finally:
            self.zone_table.blockSignals(False)
        self._ensure_zone_selection(self.zone_table.rowCount() - 1)
        self._sync_form_to_yaml()

    def _remove_selected_zone_rows(self) -> None:
        selected_rows = sorted({index.row() for index in self.zone_table.selectionModel().selectedRows()}, reverse=True)
        if not selected_rows and self.zone_table.rowCount() > 0:
            selected_rows = [self.zone_table.rowCount() - 1]
        self.zone_table.blockSignals(True)
        try:
            for row in selected_rows:
                self.zone_table.removeRow(row)
            if self.zone_table.rowCount() == 0:
                self._append_zone_row("zone_1", 5.0, 30.0, "0-360")
        finally:
            self.zone_table.blockSignals(False)
        self._ensure_zone_selection(min(selected_rows[-1] if selected_rows else 0, self.zone_table.rowCount() - 1))
        self._sync_form_to_yaml()

    def _zones_from_table(self) -> list[dict[str, object]]:
        zones: list[dict[str, object]] = []
        for row in range(self.zone_table.rowCount()):
            name = _table_text(self.zone_table.item(row, 0), f"zone_{row + 1}")
            min_elevation_deg = _table_float(self.zone_table.item(row, 1), 5.0)
            max_elevation_deg = _table_float(self.zone_table.item(row, 2), 30.0)
            azimuth_windows = _parse_angle_windows(_table_text(self.zone_table.item(row, 3), "0-360"))
            if not azimuth_windows:
                azimuth_windows = [[0.0, 360.0]]
            zones.append(
                {
                    "name": name,
                    "min_elevation_deg": min_elevation_deg,
                    "max_elevation_deg": max_elevation_deg,
                    "azimuth_windows": azimuth_windows,
                }
            )
        return zones

    def _ensure_zone_selection(self, preferred_row: int | None = None) -> None:
        if self.zone_table.rowCount() == 0:
            self._load_selected_zone_into_editor()
            return
        row = preferred_row if preferred_row is not None else 0
        row = max(0, min(row, self.zone_table.rowCount() - 1))
        self.zone_table.selectRow(row)
        self._load_selected_zone_into_editor()

    def _selected_zone_row(self) -> int | None:
        selection_model = self.zone_table.selectionModel()
        if selection_model is not None:
            selected_rows = selection_model.selectedRows()
            if selected_rows:
                return selected_rows[0].row()
        if self.zone_table.rowCount() == 0:
            return None
        return 0

    def _load_selected_zone_into_editor(self) -> None:
        row = self._selected_zone_row()
        has_row = row is not None
        for widget in [
            self.zone_name_edit,
            self.zone_min_el_spin,
            self.zone_max_el_spin,
            self.zone_windows_edit,
        ]:
            widget.setEnabled(has_row)
        if row is None:
            return

        self._loading_zone_editor = True
        try:
            self.zone_name_edit.setText(_table_text(self.zone_table.item(row, 0), f"zone_{row + 1}"))
            self.zone_min_el_spin.setValue(_table_float(self.zone_table.item(row, 1), 5.0))
            self.zone_max_el_spin.setValue(_table_float(self.zone_table.item(row, 2), 30.0))
            self.zone_windows_edit.setText(_table_text(self.zone_table.item(row, 3), "0-360"))
        finally:
            self._loading_zone_editor = False

    def _on_zone_editor_changed(self, _value=None) -> None:
        if self._building_form or self._loading_zone_editor:
            return
        row = self._selected_zone_row()
        if row is None:
            return

        min_el = self.zone_min_el_spin.value()
        max_el = self.zone_max_el_spin.value()
        if min_el >= max_el:
            if self.sender() is self.zone_min_el_spin:
                max_el = min(90.0, min_el + 0.5)
                self.zone_max_el_spin.blockSignals(True)
                self.zone_max_el_spin.setValue(max_el)
                self.zone_max_el_spin.blockSignals(False)
            else:
                min_el = max(0.0, max_el - 0.5)
                self.zone_min_el_spin.blockSignals(True)
                self.zone_min_el_spin.setValue(min_el)
                self.zone_min_el_spin.blockSignals(False)

        row_values = [
            self.zone_name_edit.text().strip() or f"zone_{row + 1}",
            f"{min_el:g}",
            f"{max_el:g}",
            self.zone_windows_edit.text().strip() or "0-360",
        ]
        self.zone_table.blockSignals(True)
        try:
            for column, value in enumerate(row_values):
                item = self.zone_table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.zone_table.setItem(row, column, item)
                item.setText(value)
                if column == 3:
                    item.setToolTip(value)
        finally:
            self.zone_table.blockSignals(False)
        self._sync_form_to_yaml()

    def _update_processing_control_state(self, _value=None) -> None:
        smoothing_enabled = self.smoothing_method_combo.currentText().strip().lower() != "none"
        self.smoothing_window_spin.setEnabled(smoothing_enabled)

    def _load_config_to_form(self) -> None:
        self._building_form = True
        try:
            data = config_to_dict(self.config)
            self.station_id_edit.setText(data["station"]["station_id"])
            self.latitude_spin.setValue(float(data["station"]["receiver_position"]["latitude_deg"] or 0.0))
            self.longitude_spin.setValue(float(data["station"]["receiver_position"]["longitude_deg"] or 0.0))
            self.height_spin.setValue(float(data["station"]["receiver_position"]["height_m"] or 0.0))
            self.antenna_height_spin.setValue(float(data["station"]["antenna_height"]))
            self.monument_height_value = float(data["station"]["monument_height"] or 0.0)
            _set_combo_value(self.environment_combo, str(data["station"]["environment_type"]))
            _set_combo_value(self.surface_combo, str(data["station"]["reflector_surface_type"]))
            self.min_height_spin.setValue(float(data["ir"]["min_reflector_height"]))
            self.max_height_spin.setValue(float(data["ir"]["max_reflector_height"]))

            enabled_systems = _enabled_systems_from_config(data["input"])
            for sys_char, checkbox in self.system_checks.items():
                checkbox.setChecked(sys_char in enabled_systems)
            self.exclude_signals_edit.setText(",".join(data["input"].get("exclude_signals", [])))

            self.live_arc_window_spin.setValue(float(data["processing"].get("live_arc_window_minutes", 20)))
            self.live_interval_spin.setValue(float(data["processing"].get("live_analysis_interval_seconds", 20)))
            self.detrend_order_spin.setValue(float(data["processing"].get("detrend_order", 2)))
            _set_combo_value(self.smoothing_method_combo, str(data["processing"].get("smoothing_method", "none")))
            self.smoothing_window_spin.setValue(float(data["processing"].get("smoothing_window", 5)))
            self.min_arc_seconds_spin.setValue(float(data["qc"]["min_arc_duration"]))
            self.min_pnr_spin.setValue(float(data["qc"]["min_peak_to_noise_ratio"]))
            self.output_dir_edit.setText(str(data["output"]["output_dir"]))
            zones = []
            for index, zone in enumerate(data["geometry"].get("reflection_zones", []), start=1):
                zones.append(
                    {
                        "name": zone.get("name") or f"zone_{index}",
                        "min_elevation_deg": zone.get("min_elevation_deg", data["processing"]["min_elevation_deg"]),
                        "max_elevation_deg": zone.get("max_elevation_deg", data["processing"]["max_elevation_deg"]),
                        "azimuth_windows": _format_angle_windows(zone.get("azimuth_windows", [])),
                    }
                )
            self._set_zone_rows(zones)

            self.enable_height_chk.setChecked(bool(data["products"]["enable_reflector_height"]))
            self.enable_sea_level_chk.setChecked(bool(data["products"]["enable_sea_level"]))
            self.enable_snow_depth_chk.setChecked(bool(data["products"]["enable_snow_depth"]))
            self.sea_level_ref_spin.setValue(float(data["products"]["sea_level_reference"] or 0.0))
            self.snow_ref_spin.setValue(float(data["products"]["snow_depth_reference_height"] or 0.0))
            self._apply_environment_policy(sync_yaml=False)
        finally:
            self._building_form = False

        self._update_processing_control_state()
        self._sync_form_to_yaml()
        self._set_yaml_editor_text(self.current_yaml_text)
        self.path_label.setText(str(self.current_path))

    def _sync_form_to_yaml(self) -> None:
        if self._building_form:
            return
        source_text = self.yaml_editor.toPlainText().strip() or self.current_yaml_text
        try:
            data = yaml.safe_load(source_text) or {}
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        data.setdefault("station", {})
        data.setdefault("station", {}).setdefault("receiver_position", {})
        data.setdefault("input", {})
        data.setdefault("input", {}).setdefault("time_window", {})
        data.setdefault("processing", {})
        data.setdefault("ir", {})
        data.setdefault("qc", {})
        data.setdefault("products", {})
        data.setdefault("output", {})

        station = data["station"]
        station["station_id"] = self.station_id_edit.text().strip()
        station["receiver_position"]["latitude_deg"] = self.latitude_spin.value()
        station["receiver_position"]["longitude_deg"] = self.longitude_spin.value()
        station["receiver_position"]["height_m"] = self.height_spin.value()
        station["antenna_height"] = self.antenna_height_spin.value()
        station["monument_height"] = self.monument_height_value
        station["environment_type"] = self.environment_combo.currentText().strip()
        station["reflector_surface_type"] = self.surface_combo.currentText().strip()

        input_data = data["input"]
        input_data["constellations"] = []
        input_data["signals"] = []
        enabled_systems = [sys_char for sys_char, checkbox in self.system_checks.items() if checkbox.isChecked()]
        input_data["exclude_constellations"] = [
            sys_char for sys_char, _label in self.SYSTEM_OPTIONS if sys_char not in enabled_systems
        ]
        input_data["exclude_signals"] = _split_csv(self.exclude_signals_edit.text())

        zones = self._zones_from_table()
        processing = data["processing"]
        processing["min_elevation_deg"] = min(zone["min_elevation_deg"] for zone in zones)
        processing["max_elevation_deg"] = max(zone["max_elevation_deg"] for zone in zones)
        processing["live_arc_window_minutes"] = int(self.live_arc_window_spin.value())
        processing["live_analysis_interval_seconds"] = int(self.live_interval_spin.value())
        processing["detrend_method"] = "polynomial_sin_elevation"
        processing["detrend_order"] = int(self.detrend_order_spin.value())
        processing["smoothing_method"] = self.smoothing_method_combo.currentText().strip() or "none"
        processing["smoothing_window"] = int(self.smoothing_window_spin.value())

        ir_data = data["ir"]
        ir_data["min_reflector_height"] = self.min_height_spin.value()
        ir_data["max_reflector_height"] = self.max_height_spin.value()
        ir_data["use_rising_arcs"] = True
        ir_data["use_setting_arcs"] = True

        processing.pop("min_samples_per_arc", None)

        geometry = data["geometry"]
        geometry["reflection_zones"] = zones
        geometry.pop("azimuth_mask", None)
        geometry.pop("reflector_azimuth_sector", None)
        geometry.pop("elevation_correction", None)

        qc = data["qc"]
        qc["min_arc_duration"] = self.min_arc_seconds_spin.value()
        qc["min_peak_to_noise_ratio"] = self.min_pnr_spin.value()
        qc["reject_cycle_slip_suspects"] = False

        self._apply_environment_policy(sync_yaml=False)
        products = data["products"]
        products["enable_reflector_height"] = True
        products["enable_sea_level"] = self.enable_sea_level_chk.isChecked()
        products["enable_snow_depth"] = self.enable_snow_depth_chk.isChecked()
        products["sea_level_reference"] = (
            self.sea_level_ref_spin.value() if self.enable_sea_level_chk.isChecked() else None
        )
        products["snow_depth_reference_height"] = (
            self.snow_ref_spin.value() if self.enable_snow_depth_chk.isChecked() else None
        )

        data["output"]["output_dir"] = self.output_dir_edit.text().strip()

        self.current_yaml_text = yaml.safe_dump(data, sort_keys=False, allow_unicode=False)
        self._set_yaml_editor_text(self.current_yaml_text)

    def _on_environment_changed(self, _text: str | None = None) -> None:
        if self._building_form:
            return
        self._apply_environment_policy(sync_yaml=True)

    def _apply_environment_policy(self, sync_yaml: bool) -> None:
        environment_mode = classify_environment(self.environment_combo.currentText())
        suggested_surface = {
            "water": "sea" if self.environment_combo.currentText().strip().lower() == "coastal" else "river",
            "snow": "snow",
            "height_only": "soil",
        }.get(environment_mode)

        previous_state = self._building_form
        self._building_form = True
        try:
            self.enable_height_chk.setChecked(True)
            if suggested_surface:
                current_surface = self.surface_combo.currentText().strip().lower()
                if not current_surface or current_surface in {"sea", "river", "snow", "soil"}:
                    _set_combo_value(self.surface_combo, suggested_surface)

            if environment_mode == "water":
                self.product_policy_label.setText("Water-facing environment: reflector height and sea-level style products are kept.")
                self.enable_sea_level_chk.setChecked(True)
                self.enable_snow_depth_chk.setChecked(False)
                self.enable_sea_level_chk.setEnabled(False)
                self.enable_snow_depth_chk.setEnabled(False)
                self.sea_level_ref_spin.setVisible(True)
                self.sea_level_ref_label.setVisible(True)
                self.snow_ref_spin.setVisible(False)
                self.snow_ref_label.setVisible(False)
            elif environment_mode == "snow":
                self.product_policy_label.setText("Snow environment: reflector height and snow-depth products are kept.")
                self.enable_sea_level_chk.setChecked(False)
                self.enable_snow_depth_chk.setChecked(True)
                self.enable_sea_level_chk.setEnabled(False)
                self.enable_snow_depth_chk.setEnabled(False)
                self.sea_level_ref_spin.setVisible(False)
                self.sea_level_ref_label.setVisible(False)
                self.snow_ref_spin.setVisible(True)
                self.snow_ref_label.setVisible(True)
            elif environment_mode == "height_only":
                self.product_policy_label.setText("Land environment: reflector height stays enabled, optional sea/snow products are hidden.")
                self.enable_sea_level_chk.setChecked(False)
                self.enable_snow_depth_chk.setChecked(False)
                self.enable_sea_level_chk.setEnabled(False)
                self.enable_snow_depth_chk.setEnabled(False)
                self.sea_level_ref_spin.setVisible(False)
                self.sea_level_ref_label.setVisible(False)
                self.snow_ref_spin.setVisible(False)
                self.snow_ref_label.setVisible(False)
            else:
                self.product_policy_label.setText("Custom or unknown environment: product switches remain manually editable.")
                self.enable_sea_level_chk.setEnabled(True)
                self.enable_snow_depth_chk.setEnabled(True)
                self.sea_level_ref_spin.setVisible(True)
                self.sea_level_ref_label.setVisible(True)
                self.snow_ref_spin.setVisible(True)
                self.snow_ref_label.setVisible(True)
        finally:
            self._building_form = previous_state

        if sync_yaml:
            self._sync_form_to_yaml()

    def _on_yaml_text_changed(self) -> None:
        if self._building_form:
            return
        text = self.yaml_editor.toPlainText()
        if not text.strip():
            return
        try:
            self.config = self._load_config_from_text(text)
            self.current_yaml_text = text
            self._load_config_to_form()
        except Exception:
            pass

    def import_yaml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import IR YAML", str(self.current_path.parent), "YAML Files (*.yaml *.yml)")
        if not path:
            return
        self.current_path = self._resolve_path(path)
        self.current_yaml_text = self.current_path.read_text(encoding="utf-8")
        self.config = self._load_config_from_text(self.current_yaml_text)
        self._load_config_to_form()

    def export_yaml(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export IR YAML",
            str(self.current_path),
            "YAML Files (*.yaml *.yml)",
        )
        if not path:
            return
        target = Path(path)
        self.current_yaml_text = self.yaml_editor.toPlainText()
        target.write_text(self.current_yaml_text, encoding="utf-8")
        self.current_path = target
        self.path_label.setText(str(self.current_path))

    def get_config(self):
        yaml_text = self.yaml_editor.toPlainText()
        config = self._load_config_from_text(yaml_text)
        self.current_yaml_text = yaml_text
        self.config = config
        return self.current_path, config, yaml_text

    def _accept_if_valid(self) -> None:
        try:
            self.config = self._load_config_from_text(self.yaml_editor.toPlainText())
            self.current_yaml_text = self.yaml_editor.toPlainText()
        except Exception as exc:
            QMessageBox.warning(self, "Reflectometry Config", f"Configuration is invalid:\n{exc}")
            return
        self.accept()

    def _read_initial_yaml(self, path: Path) -> str:
        if path.exists():
            return path.read_text(encoding="utf-8")
        return DEFAULT_CONFIG_YAML

    def _resolve_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.project_root / candidate

    def _set_yaml_editor_text(self, text: str) -> None:
        if self.yaml_editor.toPlainText() == text:
            return
        self.yaml_editor.blockSignals(True)
        try:
            self.yaml_editor.setPlainText(text)
        finally:
            self.yaml_editor.blockSignals(False)

    def _load_config_from_text(self, text: str):
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
                handle.write(text)
                temp_path = handle.name
            return load_config(temp_path)
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

    def _apply_dialog_styles(self) -> None:
        palette = self.palette()
        is_dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        if is_dark:
            pane_bg = "#1C212D"
            card_bg = "#161A23"
            soft_bg = "#242B3A"
            border = "#334155"
            text = "#E2E8F0"
            muted = "#94A3B8"
            accent = "#60A5FA"
        else:
            pane_bg = "#FFFFFF"
            card_bg = "#F8FAFC"
            soft_bg = "#EEF4FA"
            border = "#CBD5E1"
            text = "#0F172A"
            muted = "#64748B"
            accent = "#2563EB"

        self.setStyleSheet(
            f"""
            QDialog#reflectometryConfigDialog {{
                background-color: {card_bg};
            }}
            QDialog#reflectometryConfigDialog QLabel {{
                color: {text};
            }}
            QDialog#reflectometryConfigDialog QTabWidget#configTabs::pane {{
                border: none;
                background: transparent;
            }}
            QDialog#reflectometryConfigDialog QTabBar {{
                background: transparent;
            }}
            QDialog#reflectometryConfigDialog QTabBar::tab {{
                background-color: {soft_bg};
                color: {muted};
                border: none;
                border-radius: 8px;
                padding: 7px 14px;
                margin-right: 6px;
                margin-top: 0px;
                margin-bottom: 6px;
                min-width: 80px;
            }}
            QDialog#reflectometryConfigDialog QTabBar::tab:selected {{
                background-color: {pane_bg};
                color: {accent};
                font-weight: 600;
            }}
            QDialog#reflectometryConfigDialog QTabBar::tab:hover:!selected {{
                background-color: {card_bg};
                color: {text};
            }}
            QDialog#reflectometryConfigDialog QFrame#configCard {{
                background-color: {pane_bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QDialog#reflectometryConfigDialog QFrame#configInsetCard {{
                background-color: {soft_bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QDialog#reflectometryConfigDialog QLabel#cardTitle {{
                color: {text};
                font-size: 14px;
                font-weight: 600;
                padding: 0px;
            }}
            QDialog#reflectometryConfigDialog QLabel#cardDescription {{
                color: {muted};
                font-size: 12px;
                padding: 0px 0px 2px 0px;
            }}
            QDialog#reflectometryConfigDialog QScrollArea,
            QDialog#reflectometryConfigDialog QAbstractScrollArea {{
                border: none;
                background: transparent;
            }}
            QDialog#reflectometryConfigDialog QLineEdit,
            QDialog#reflectometryConfigDialog QComboBox,
            QDialog#reflectometryConfigDialog QDoubleSpinBox {{
                background-color: {pane_bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 5px 8px;
                min-height: 26px;
            }}
            QDialog#reflectometryConfigDialog QLineEdit:focus,
            QDialog#reflectometryConfigDialog QComboBox:focus,
            QDialog#reflectometryConfigDialog QDoubleSpinBox:focus,
            QDialog#reflectometryConfigDialog QPlainTextEdit:focus {{
                border: 1px solid {accent};
            }}
            QDialog#reflectometryConfigDialog QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QDialog#reflectometryConfigDialog QPlainTextEdit {{
                background-color: {pane_bg};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 10px;
                selection-background-color: {accent};
            }}
            QDialog#reflectometryConfigDialog QPushButton {{
                background-color: {pane_bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 5px 12px;
                min-height: 26px;
            }}
            QDialog#reflectometryConfigDialog QPushButton:hover {{
                border-color: {accent};
            }}
            QDialog#reflectometryConfigDialog QTableWidget {{
                background-color: {pane_bg};
                border: 1px solid {border};
                border-radius: 10px;
                gridline-color: {border};
                alternate-background-color: {soft_bg};
            }}
            QDialog#reflectometryConfigDialog QTableWidget::item {{
                padding: 6px 8px;
                border: none;
            }}
            QDialog#reflectometryConfigDialog QTableWidget::item:selected {{
                background-color: {accent};
                color: #FFFFFF;
            }}
            QDialog#reflectometryConfigDialog QHeaderView::section {{
                background-color: {soft_bg};
                color: {muted};
                border: none;
                border-bottom: 1px solid {border};
                padding: 8px 10px;
                font-weight: 600;
            }}
            """
        )


def _float_spin(minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setSingleStep(10 ** (-min(decimals, 2)))
    return spin


def _configure_form_layout(form: QFormLayout) -> None:
    form.setContentsMargins(8, 10, 8, 8)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(8)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)


def _connect_change(widget, callback) -> None:
    if isinstance(widget, QLineEdit):
        widget.textChanged.connect(callback)
    elif isinstance(widget, QComboBox):
        widget.currentTextChanged.connect(callback)
    elif isinstance(widget, QCheckBox):
        widget.stateChanged.connect(callback)
    elif isinstance(widget, QDoubleSpinBox):
        widget.valueChanged.connect(callback)


def _split_csv(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _enabled_systems_from_config(input_data: dict[str, object]) -> set[str]:
    all_systems = {"G", "R", "E", "C", "J", "S", "I"}
    include = {str(item) for item in input_data.get("constellations", []) or []}
    exclude = {str(item) for item in input_data.get("exclude_constellations", []) or []}
    enabled = include if include else set(all_systems)
    return enabled - exclude


def _table_text(item: QTableWidgetItem | None, default: str = "") -> str:
    if item is None:
        return default
    text = item.text().strip()
    return text or default


def _table_float(item: QTableWidgetItem | None, default: float) -> float:
    text = _table_text(item, "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _parse_angle_windows(text: str) -> list[list[float]]:
    windows: list[list[float]] = []
    for chunk in text.split(";"):
        item = chunk.strip()
        if not item:
            continue
        normalized = item.replace(",", "-").replace(":", "-")
        if "-" not in normalized:
            continue
        start_text, end_text = [part.strip() for part in normalized.split("-", maxsplit=1)]
        windows.append([float(start_text), float(end_text)])
    return windows


def _format_angle_windows(windows: list[list[float]]) -> str:
    return "; ".join(f"{float(start):g}-{float(end):g}" for start, end in windows)


def _set_combo_value(combo: QComboBox, value: str) -> None:
    if not value:
        combo.setCurrentText("")
        return
    index = combo.findText(value)
    if index >= 0:
        combo.setCurrentIndex(index)
    else:
        combo.setCurrentText(value)


def _wrap_layout(layout) -> QWidget:
    widget = QWidget()
    widget.setLayout(layout)
    return widget

