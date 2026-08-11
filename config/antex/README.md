# SC02 ANTEX subset

`igs20_sc02.atx.gz` is a compact subset of the IGS `igs20.atx` calibration
file published on 2026-07-02. It contains the latest record for every GNSS
satellite PRN in that file plus the `TRM59800.80 SCIT` receiver antenna used
by SC02.

Source: `https://files.igs.org/pub/station/general/igs20.atx.gz`

The subset follows the same last-record selection used by
`AntexCalibration`; it avoids shipping the full 60 MB receiver antenna
catalog while retaining the complete satellite PCO/PCV model needed by the
configured APC SSR stream.
