# Built-in PPP model data

RTGS uses these read-only files when the corresponding PPP configuration path is empty.
An explicitly configured file always takes precedence.

- `igs20.atx.gz`: IGS20 ANTEX calibration catalog from
  `https://files.igs.org/pub/station/general/igs20.atx.gz`.
- `OCEAN-GOT48.blq`: GOT4.8 ocean-loading coefficient catalog distributed with the
  HASPPP example data (`ZhangRunzhi20/HASPPP`, commit
  `951dc79333f00a47acac8b79410e3871317faf10`). The catalog contains station-specific
  records; RTGS applies a correction only when the current station ID matches a record.

ANTEX can cover satellite corrections without receiver metadata. Receiver corrections
still require a valid RTCM 1007/1008/1033 antenna descriptor or a configured antenna
name. A station absent from the BLQ catalog still needs coefficients generated for its
coordinates.
