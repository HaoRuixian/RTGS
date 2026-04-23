# rtcm2rinex Executables

This folder contains the packaged standalone builds of the RTCM to RINEX tool.

## Files

- `windows/rtcm2rinex.exe`
- `linux/rtcm2rinex`

## Usage

Windows:

```powershell
.\windows\rtcm2rinex.exe -h
.\windows\rtcm2rinex.exe input.rtcm3 -o output -i 15 -p 01D
```

Linux:

```bash
chmod +x ./linux/rtcm2rinex
./linux/rtcm2rinex -h
./linux/rtcm2rinex input.rtcm3 -o output -i 15 -p 01D
```

## Notes

- Both builds are single-file executables produced with PyInstaller.
- They do not require the project Python environment to run.
- The Linux build is self-contained, but it still requires a compatible glibc-based Linux system.
