# RTCM to RINEX Tool Usage

## Tool entry

This project provides the RTCM to RINEX converter here:

- `utils/rtcm_to_rinex.py`

Convenience launchers are also available:

- `rtcm_to_rinex.bat`
- `venv/Scripts/rtcm_to_rinex.bat`

If the virtual environment is activated, you can run:

```powershell
rtcm_to_rinex -h
```

If the virtual environment is not activated, run:

```powershell
.\rtcm_to_rinex.bat -h
```

## Basic usage

```powershell
rtcm_to_rinex <input.rtcm3/dat> [-o OUT] [-i SEC] [-d YYYY-MM-DD] [-s SITE] [-n NAME] [-r RX]
```

`-o` supports two modes:

- Output directory: the tool creates a standard RINEX 3 long filename automatically.
- Output file: the tool writes exactly to the given `.rnx` path.

## Common examples

Convert one file and let the tool generate the RINEX filename:

```powershell
rtcm_to_rinex GNSS_Data\F9P\raw_20260324.rtcm3 -o GNSS_Data\F9P\RINEX
```

Convert one file and write to a fixed filename:

```powershell
rtcm_to_rinex 20251025.dat -o output\20251025.rnx
```

Specify station and receiver information:

```powershell
rtcm_to_rinex GNSS_Data\UM982\raw_20260324.rtcm3 -o output -s UM98 --num 00 --country CHN -n UM982 -r UM982
```

Write a decimated 15-second RINEX file:

```powershell
rtcm_to_rinex GNSS_Data\F9P\raw_20260324.rtcm3 -o output -i 15 -p 01D
```

Convert an offline file with an explicit reference date:

```powershell
rtcm_to_rinex 20251025.dat -o output\20251025.rnx -d 2025-10-25
```

Set an approximate receiver position in ECEF:

```powershell
rtcm_to_rinex sample.rtcm3 -o output --xyz -2267744.6605 5009154.1703 3221290.2301
```

## Important options

- `input`: input RTCM file, such as `.rtcm3`, `.dat`, `.log`
- `-o, --output`: output directory or output `.rnx` file
- `-i, --interval`: output sampling interval in seconds, such as `1`, `15`, `30`
- `-p, --period`: long filename period code, such as `01H`, `01D`
- `-d, --date`: reference date for historical offline files
- `-s, --site`: 4-character station code in the RINEX long filename
- `--num`: 2-character receiver number in the RINEX long filename
- `--country`: 3-character country code in the RINEX long filename
- `-n, --name`: marker name in the header
- `-r, --rx`: receiver type in the header
- `-a, --ant`: antenna type in the header
- `--xyz X Y Z`: approximate receiver ECEF position

## Output behavior

- The tool scans the RTCM file first, then writes the RINEX file.
- Observation types are inferred from the RTCM data.
- Multiple MSM messages at the same epoch are merged before writing.
- For historical offline files, the tool can infer the reference date from the filename, or you can force it with `--reference-date`.

## Recommended workflow

1. Activate the project virtual environment.
2. Run `rtcm_to_rinex -h` to view the built-in help.
3. Convert one sample file first.
4. After checking the header and epoch range, batch-convert the remaining files.
