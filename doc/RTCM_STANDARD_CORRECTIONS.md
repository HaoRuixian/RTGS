# RTCM 10403.3 Standard Compliance Analysis and Corrections

## Issue Summary
The current implementation references message types that do not exist in RTCM 10403.3 standard. After careful review of the official specification document (October 7, 2016), the following discrepancies were identified.

---

## Key Findings

### 1. **SSR Messages (State Space Representation)**
According to RTCM 10403.3 Section 3.2 (Message Type Summary):

#### GPS SSR Messages (1057-1062):
- **Message 1057**: SSR GPS Orbit Correction
  - Header uses: DF002, DF385, DF391, DF388, DF375, DF413, DF414, DF415, DF387
  - Satellite data uses: DF068, DF071, DF365-DF370
  
- **Message 1058**: SSR GPS Clock Correction
  - Header uses: DF002, DF385, DF391, DF388, DF413, DF414, DF415, DF387
  - Satellite data uses: DF068, DF376-DF378

- **Message 1059**: SSR GPS Code Bias
  - Uses: DF002, DF385, DF391, DF388, DF413, DF414, DF415, DF387, DF068, DF379-DF380, DF383
  
- **Message 1060**: SSR GPS Combined Orbit and Clock
  - Combines fields from 1057 and 1058

- **Message 1061**: SSR GPS URA (User Range Accuracy)
  - Uses: DF002, DF385, DF391, DF388, DF413, DF414, DF415, DF387, DF068, DF389

- **Message 1062**: SSR GPS High Rate Clock Correction
  - Uses: DF002, DF385, DF391, DF388, DF413, DF414, DF415, DF387, DF068, DF390

#### GLONASS SSR Messages (1063-1068):
- **Message 1063**: SSR GLONASS Orbit Correction
- **Message 1064**: SSR GLONASS Clock Correction
- **Message 1065**: SSR GLONASS Code Bias
- **Message 1066**: SSR GLONASS Combined Orbit and Clock
- **Message 1067**: SSR GLONASS URA
- **Message 1068**: SSR GLONASS High Rate Clock Correction

Similar structure to GPS messages but using GLONASS-specific data fields.

---

### 2. **Network RTK Correction Messages (NOT SSR)**
These differ from SSR messages. Used for differential corrections between reference stations:

#### GPS Network RTK Corrections (1015-1017):
- **Message 1015**: GPS Ionospheric Correction Differences
  - Uses: DF002, DF059, DF072, DF065, DF066, DF060, DF061, DF067, DF068, DF074, DF075, DF069

- **Message 1016**: GPS Geometric Correction Differences
  - Uses: DF002, DF059, DF072, DF065, DF066, DF060, DF061, DF067, DF068, DF074, DF075, DF070, DF071

- **Message 1017**: GPS Combined Geometric and Ionospheric Correction Differences
  - Combines fields from 1015 and 1016

#### GLONASS Network RTK Corrections (1037-1039):
- **Message 1037**: GLONASS Ionospheric Correction Differences
- **Message 1038**: GLONASS Geometric Correction Differences
- **Message 1039**: GLONASS Combined Geometric and Ionospheric Correction Differences

---

### 3. **GLONASS Bias Message**
- **Message 1230**: GLONASS L1 and L2 Code-Phase Biases
  - **NOT** an ionospheric correction
  - **NOT** SSR format
  - Uses GLONASS-specific Code-Phase Bias data structure
  - Field size: 32 + 16*N bytes (where N = number of Code-Phase Biases, max 4)

---

### 4. **Non-Existent Messages in Implementation**
The following message IDs in the current code DO NOT EXIST in RTCM 10403.3:
- **1225, 1226, 1227**: Coded as "Tropospheric Corrections" - **NOT FOUND**
- **1240, 1241, 1242, 1244, 1245**: Coded as "SSR Corrections" - **INCORRECT** (should be 1057-1068)
- **1264-1268**: Coded as "Grid Ionospheric" - **NOT FOUND**
- **1269-1271**: Coded as "Grid Tropospheric/Time Bias" - **NOT FOUND**

These message IDs are completely non-standard and should be removed from the implementation.

---

## Data Field Corrections

### Correct DF Field Mappings for SSR Usage:

| DF # | Name | Type | Bits | Purpose |
|------|------|------|------|---------|
| DF385 | GPS Epoch Time 1s | uint20 | 20 | Seconds since GPS week start |
| DF387 | No. of Satellites | uint6 | 6 | Number of satellites in message |
| DF388 | Multiple Message Indicator | bit(1) | 1 | More messages follow flag |
| DF391 | SSR Update Interval | bit(4) | 4 | Update rate code (see Table 3.4-2) |
| DF413 | IOD SSR | uint4 | 4 | Issue of Data SSR |
| DF414 | SSR Provider ID | uint16 | 16 | Provider identification |
| DF415 | SSR Solution ID | uint4 | 4 | Solution variant ID |
| DF365 | Delta Radial | int22 | 22 | Orbit correction radial (0.1mm) |
| DF366 | Delta Along-Track | int20 | 20 | Orbit correction along-track (0.4mm) |
| DF367 | Delta Cross-Track | int20 | 20 | Orbit correction cross-track (0.4mm) |
| DF376 | Delta Clock C0 | int22 | 22 | Clock correction constant term (0.1mm) |
| DF377 | Delta Clock C1 | int21 | 21 | Clock correction first derivative (0.001mm/s) |
| DF378 | Delta Clock C2 | int27 | 27 | Clock correction second derivative (0.00002mm/s²) |

---

## Message Structure Examples

### Message 1057 (SSR GPS Orbit Correction)
```
Header (68 bits):
- Message Number (DF002): 12 bits
- GPS Epoch Time 1s (DF385): 20 bits
- SSR Update Interval (DF391): 4 bits
- Multiple Message Indicator (DF388): 1 bit
- Satellite Reference Datum (DF375): 1 bit
- IOD SSR (DF413): 4 bits
- SSR Provider ID (DF414): 16 bits
- SSR Solution ID (DF415): 4 bits
- No. of Satellites (DF387): 6 bits

Satellite-specific data per satellite (135 bits each):
- GPS Satellite ID (DF068): 6 bits
- GPS IODE (DF071): 8 bits
- Delta Radial (DF365): 22 bits
- Delta Along-Track (DF366): 20 bits
- Delta Cross-Track (DF367): 20 bits
- Dot Delta Radial (DF368): 21 bits
- Dot Delta Along-Track (DF369): 19 bits
- Dot Delta Cross-Track (DF370): 19 bits
```

### Message 1015 (GPS Ionospheric Correction Differences)
```
Header (76 bits):
- Message Number (DF002): 12 bits
- Network ID (DF059): 8 bits
- Subnetwork ID (DF072): 4 bits
- GPS Epoch Time TOW (DF065): 23 bits
- Multiple Message Indicator (DF066): 1 bit
- Master Reference Station ID (DF060): 12 bits
- Auxiliary Reference Station ID (DF061): 12 bits
- # of GPS Sats (DF067): 4 bits

Data block per satellite (28 bits each):
- GPS Satellite ID (DF068): 6 bits
- Ambiguity Status Flag (DF074): 2 bits
- Non Sync Count (DF075): 3 bits
- Ionospheric Correction Difference (DF069): 17 bits
```

---

## Recommendation

The implementation should:

1. **Remove all non-standard message IDs** (1225-1227, 1240-1245, 1264-1271)

2. **Implement standard SSR messages** (1057-1062, 1063-1068) with correct structure and DF field references

3. **Implement Network RTK Correction messages** (1015-1017, 1037-1039) if needed for DGNSS

4. **Correctly parse Message 1230** as GLONASS Code-Phase Biases, not ionospheric correction

5. **Add proper error handling** for unrecognized message types

6. **Reference RTCM 10403.3 tables** for exact field definitions and bit allocations

---

## References

- RTCM Standard 10403.3, October 7, 2016
- Section 3.2: Message Type Summary (page 27-45)
- Section 3.4: Data Fields (page 49-108)
- Section 3.5.12: State Space Messages (page 169-192)
- Section 3.5.7: GPS Network RTK Correction Messages (page 124-132)
