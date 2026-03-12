# RINEX Recording Customization Guide

## Overview

The GNSS Toolbox now provides full customization options for RINEX 3.04 file format when recording observations. This guide explains how to configure these options.

## Recording Settings Dialog

### Accessing the Dialog

In the Monitoring Module, click the **"Logging Settings"** button to open the Data Logging Configuration dialog.

### Format Selection

Choose one of three output formats:
- **CSV**: Comma-separated text format with selected fields
- **Binary RTCM**: Raw binary RTCM messages
- **RINEX**: Standard RINEX 3.04 observation format (recommended for professional use)

### RINEX-Specific Options

When you select the **RINEX** format, additional configuration fields appear:

#### 1. **Station Code** (4 characters)
- Example: `SCOA`, `RTGS`, `TEST`
- Used as the first part of the RINEX filename
- Padded with zeros if shorter than 4 characters
- Default: `RTGS`

#### 2. **Receiver Number** (2 characters)
- Example: `00`, `01`, `02`
- Used as station variant identifier
- Typically `00` for single receiver
- Padded with zeros if needed
- Default: `00`

#### 3. **Country Code** (3 characters)
- Example: `CHN` (China), `FRA` (France), `USA`
- Used as the country/agency code in the RINEX filename
- Padded with spaces if shorter than 3 characters
- Default: `CHN`

#### 4. **Period** (Processing period)
- Example: `01D` (1 day), `01H` (1 hour), `06H` (6 hours)
- Indicates the time span covered by the file
- Format: `NNX` where N=digit, X=D/H/M/S
- Default: `01D`

#### 5. **Interval** (Sampling interval)
- Example: `30S` (30 seconds), `1S` (1 second), `1M` (1 minute)
- Indicates the observation rate in the file
- Format: `NNX` where N=digit, X=S/M/H/D
- Default: `30S`

#### 6. **Data Type** (2 characters)
- Example: `MO` (Observation), `EN` (Navigation ephemeris)
- Standard code indicating the type of data
- Default: `MO`

## RINEX Filename Format

The filename is automatically generated following the standard RINEX 3 convention:

```
{STATION}{RECEIVER}{COUNTRY}_R_{YYYYDDD}{HHMM}_{PERIOD}_{INTERVAL}_{DATATYPE}.rnx
```

### Example:
```
SCOA00FRA_R_20230010000_01D_30S_MO.rnx
```

Breaking it down:
- `SCOA` - Station code (4 chars)
- `00` - Receiver number (2 chars)
- `FRA` - Country code (3 chars)
- `_R_` - Fixed identifier for RINEX
- `2023` - Year
- `001` - Day of year (January 1st)
- `0000` - Time (00:00 UTC)
- `_01D` - Period (1 day)
- `_30S` - Interval (30 seconds)
- `_MO` - Data type (Observations)
- `.rnx` - File extension

## CSV Format Options

When selecting CSV format, a **"Select fields to include in CSV"** list appears. Choose which fields to save:

- **UTC Time**: Date and time stamp
- **PRN**: Satellite identifier (e.g., G01, R15)
- **Sys**: System name (GPS, GLO, GAL, BDS, etc.)
- **El(°)**: Elevation angle in degrees
- **Az(°)**: Azimuth angle in degrees
- **Freq**: Signal frequency code (e.g., 1C, 5X)
- **SNR (dBHz)**: Signal-to-noise ratio
- **Pseudorange (m)**: Code measurement in meters
- **Phase (cyc)**: Carrier phase in cycles
- **Doppler (Hz)**: Doppler shift in Hz

## Recording Control

### Starting Recording
1. Configure output directory
2. Select format (CSV, Binary RTCM, or RINEX)
3. Set RINEX options if using RINEX format:
   - Station Code (4 chars)
   - Receiver Number (2 chars, usually 00)
   - Country Code (3 chars)
   - Period, Interval, Data Type
4. Click **"START RECORDING"** (green button)

### Stopping Recording
1. Click **"STOP RECORDING"** (red button)
2. Files are automatically closed and finalized

### Status Indicators
- **🟢 Green bar**: Recording is active
- **⚪ Gray bar**: Recording is stopped
- **Status text**: Shows file count, duration, format, and other details

## File Rotation

The **"Split: N min"** setting controls automatic file rotation:
- Files are automatically closed and new files opened after the specified duration
- Default: 60 minutes
- Minimum: 1 minute
- Maximum: 1440 minutes (24 hours)

## Sampling & Intervals

### Binary RTCM Format
- Records all raw RTCM messages in real-time
- No sampling needed
- "Sampling interval" setting is ignored

### CSV/RINEX Formats
- **"Interval: N sec"** parameter controls observation sampling rate
- Values between 1-3600 seconds
- Default: 1 second
- Example: Setting to 30 seconds records observations every 30 seconds

## Output Directory Structure

```
logs/
├── SCOA00FRA_R_20230010000_01D_30S_MO.rnx
├── SCOA00FRA_R_20230011800_01D_30S_MO.rnx  (after rotation)
├── observations_20230101_000000.csv
└── rtcm_binary_20230101_000000.rtcm
```

## RINEX Header Information

The RINEX file header includes:
- Station marker name and number
- Receiver and antenna type information
- Approximate position (if available)
- Time of first observation
- System/Signal configuration
- SNR mapping documentation
- Observation types per system

## Common RINEX Configurations

### High-Resolution Real-Time Monitoring
```
Station Code: RTGS
Receiver No.: 00
Country Code: CHN  
Period:       01D
Interval:     1S (every 1 second)
Data Type:    MO
```

### Standard Daily File (IGS Compatible)
```
Station Code: SCOA (example)
Receiver No.: 00
Country Code: FRA (example)
Period:       01D
Interval:     30S
Data Type:    MO
```

### Hourly Split Files
Combined with **Split: 60 min** setting:
```
Station Code: <station>
Receiver No.: 00
Country Code: <country>
Period:       01H
Interval:     30S
Data Type:    MO
```

### Multi-Receiver Setup
```
Station Code: SITE (same for all receivers)
Receiver No.: 01 (first receiver)
             02 (second receiver)
             etc.
Country Code: CHN
```

## Troubleshooting

### Recording Not Starting
- ✅ Check that output directory is set and writable
- ✅ Ensure sufficient disk space
- ✅ Verify GNSS receiver is connected and streams are active

### No Data in RINEX File
- ✅ Wait for satellites to be acquired (check skyplot)
- ✅ Verify sampling interval is not too large
- ✅ Check that GNSS signals are being received

### Incorrect Filename Format
- ✅ Ensure Station Code is exactly 4 characters (padded with 0s if needed)
- ✅ Ensure Receiver Number is exactly 2 characters (default: 00)
- ✅ Ensure Country Code is exactly 3 characters
- ✅ Use standard abbreviations: CHN, FRA, USA, etc.

### Large File Sizes
- **Solution 1**: Increase sampling interval (e.g., 30S instead of 1S)
- **Solution 2**: Reduce file rotation time (create smaller splits)
- **Solution 3**: Use CSV format with fewer fields
- Note: Binary RTCM files are typically largest

## Reference: Standard RINEX 3.04 Files

File from example: `SCOA00FRA_R_20230010000_01D_30S_MO.rnx`
- SCOA: IGN-RGP station code
- 00: Receiver variant
- FRA: France
- 30S: 30-second sampling
- Includes GPS, GLONASS, Galileo, BeiDou, QZSS, SBAS observations

## Related Documentation

- [RINEX 3.04 Standard](https://files.igs.org/pub/data/format/rinex304.pdf)
- [IGS Data and Product Standards](https://www.igs.org/formats-and-standards/)
- [SPP Algorithm Documentation](./SPP_Algorithm.md)
- [RTCM Compliance Report](./RTCM_COMPLIANCE_REPORT.md)
