"""Small console pipeline for printing a fully parsed epoch to stdout."""

from core.data_models import EpochObservation
from core.display_info import (
    group_satellites_by_system,
    print_epoch_footer,
    print_epoch_header,
    print_satellite_block,
)


def process_epoch(epoch_data: EpochObservation) -> None:
    """Print a complete console summary for one parsed epoch."""
    print_epoch_header(epoch_data)

    sats_by_sys, sys_map = group_satellites_by_system(epoch_data)

    total_valid = 0
    for sys_char, sat_list in sats_by_sys.items():
        total_valid += print_satellite_block(sys_char, sat_list, sys_map)

    print_epoch_footer(epoch_data, total_valid)
