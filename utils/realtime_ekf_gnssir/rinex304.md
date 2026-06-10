# RINEX

## The Receiver Independent Exchange Format

## Version 3.04

## International GNSS Service (IGS), RINEX Working

## Group and Radio Technical Commission for Maritime

## Services Special Committee 104 (RTCM-SC104)

## November 23, 2018

Acknowledgement: RINEX Version 3.02, 3.03 and 3.04 are based on RINEX Version 3.01, which was developed by: Werner Gurtner, Astronomical Institute of the University of Bern, Switzerland and Lou Estey, UNAVCO, Boulder, Colorado, USA.

RINEX Version 3.04 i

Table of Contents

0. REVISION HISTORY.............................................................................................................................. 1

1. THE PHILOSOPHY AND HISTORY OF RINEX .................................................................................. 9

2. GENERAL FORMAT DESCRIPTION ................................................................................................. 11

3. BASIC DEFINITIONS ........................................................................................................................... 12

3.1 Time .................................................................................................................................................. 12

3.2 Pseudo-Range ................................................................................................................................... 12

3.3 Phase ................................................................................................................................................. 12

Table 1: Observation Corrections for Receiver Clock Offset ............................................................. 13

3.4 Doppler ............................................................................................................................................. 13

3.5 Satellite numbers............................................................................................................................... 13

4. THE EXCHANGE OF RINEX FILES ................................................................................................... 14

Figure 2: Recommended filename parameters.................................................................................... 14

Table 2: Description of Filename Parameters ..................................................................................... 15

5. RINEX VERSION 3 FEATURES .......................................................................................................... 16

5.1 Observation codes ............................................................................................................................. 16

Table 3: Observation Code Components ............................................................................................ 16

Table 4 : RINEX Version 3.04 GPS Observation Codes .................................................................... 17

Table 5 : RINEX Version 3.04 GLONASS Observation Codes ......................................................... 18

Table 6 : RINEX Version 3.04 Galileo Observation Codes ............................................................... 19

Table 7 : RINEX Version 3.04 SBAS Observation Codes ................................................................. 19

Table 8 : RINEX Version 3.04 QZSS Observation Codes ................................................................. 20

Table 9 : RINEX Version 3.04 BDS Observation Codes ................................................................... 21

Table 10 : RINEX Version 3.04 IRNSS Observation Codes .............................................................. 22

5.2 Satellite system-dependent list of observables.................................................................................. 22

5.3 Marker type ....................................................................................................................................... 23

Table 11: Proposed Marker Type Keywords ...................................................................................... 23

5.4 Half-wavelength observations, half-cycle ambiguities ..................................................................... 24

5.5 Scale factor........................................................................................................................................ 24

5.6 Information about receivers on a vehicle .......................................................................................... 24

5.7 Signal strength .................................................................................................................................. 25

RINEX Version 3.04ii

Table 12: Standardized S/N Indicators ............................................................................................... 25

5.8 Date/time format in the PGM / RUN BY / DATE header record ..................................................... 25

5.9 Antenna phase center header record ................................................................................................. 26

5.10 Antenna orientation ......................................................................................................................... 26

5.11 Observation data records................................................................................................................. 26

Table 13: Example Observation Type Records .................................................................................. 26

Table 14: Example Observation Data Records ................................................................................... 26

5.12 Ionosphere delay as pseudo-observables ........................................................................................ 27

Table 15: Ionosphere Pseudo-Observable Coding .............................................................................. 27

Table 16: Ionosphere Pseudo-Observable Corrections to Observations ............................................. 27

5.13 Channel numbers as pseudo-observables ........................................................................................ 27

5.14 Corrections of differential code biases (DCBs) .............................................................................. 28

5.15 Corrections of antenna phase center variations (PCVs) .................................................................. 28

5.16 Navigation message files ................................................................................................................ 28

Table 17: Example of Navigation File Satellite System and Number Definition Record .................. 28

Table 18: Example of Navigation File Header IONOSPHERIC CORR Record ................................ 28

6. ADDITIONAL HINTS AND TIPS ........................................................................................................ 29

6.1 Versions ............................................................................................................................................ 29

6.2 Leading blanks in CHARACTER fields ........................................................................................... 29

6.3 Variable-length records ..................................................................................................................... 29

6.4 Blank fields ....................................................................................................................................... 29

6.5 Order of the header records, order of data records............................................................................ 29

6.6 Missing items, duration of the validity of values .............................................................................. 30

6.7 Unknown / Undefined observation types and header records ........................................................... 30

6.8 Event flag records ............................................................................................................................. 30

6.9 Receiver clock offset......................................................................................................................... 30

6.10 Two-digit years ............................................................................................................................... 30

6.11 Fit interval (GPS navigation message file) ..................................................................................... 31

6.12 Satellite health (GPS navigation message file) ............................................................................... 31

Table 19: Description of GPS Satellite Health Field .......................................................................... 31

6.13 Transmission time of message (GPS navigation message file)....................................................... 31

6.14 Antenna references, phase centers .................................................................................................. 31

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04iii

7. RINEX UNDER ANTISPOOFING (AS) ............................................................................................... 32

8. DEALING WITH DIFFERENT SATELLITE SYSTEMS .................................................................... 33

8.1 Time system identifier ...................................................................................................................... 33

Table 20: Relationship between GPS, QZSS, IRN, GST, GAL, BDS and RINEX Week Numbers .. 34

Table 21: Constellation Time Relationships ....................................................................................... 35

Table 22: GPS and BeiDou UTC Leap Second Relationship ............................................................. 35

8.2 Pseudorange definition...................................................................................................................... 36

Table 23: Constellation Pseudorange Corrections .............................................................................. 36

8.3 RINEX navigation message files ...................................................................................................... 37

8.3.1 RINEX navigation message files for GLONASS............................................................................ 37

Table 24: GLONASS Navigation File Data, Sign Convention........................................................... 37

8.3.2 RINEX navigation message files for Galileo ............................................................................. 37

8.3.3 RINEX navigation message files for GEO satellites ................................................................. 38

8.3.4 RINEX navigation message files for BDS ................................................................................. 39

8.3.5 RINEX navigation message files for IRNSS ............................................................................. 39

8.4 RINEX observation files for GEO satellites ..................................................................................... 40

9. MODIFICATIONS FOR VERSION 3.01, 3.02, 3.03 and 3.04 ............................................................. 40

9.1 Phase Cycle Shifts............................................................................................................................. 40

Table 25: RINEX Phase Alignment Correction Convention .............................................................. 42

Table 26: Example SYS / PHASE SHIFT Record............................................................................. 42

9.2 Galileo: BOC-Tracking of an MBOC-Modulated Signal ................................................................. 42

Table 27: Example of RINEX Coding of Galileo BOC Tracking of an MBOC Signal Record ......... 42

9.3 BDS Satellite System Code............................................................................................................... 42

9.4 New Observation Codes for GPS L1C and BDS .............................................................................. 43

9.5 Header Records for GLONASS Slot and Frequency Numbers ........................................................ 43

Table 28: Example of a GLONASS Slot- Frequency Records ........................................................... 43

9.6 GNSS Navigation Message File: Leap Seconds Record................................................................... 43

9.7 Clarifications in the Galileo Navigation Message File: .................................................................... 43

9.8 Quasi-Zenith Satellite System (QZSS) RINEX Version 3.02........................................................... 43

9.9 GLONASS Mandatory Code-Phase Alignment Header Record....................................................... 43

Table 29: Example of GLONASS Code Phase Bias Correction Record ............................................ 44

Table 30: Example of Unknown GLONASS Code Phase Bias Record ............................................. 44

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04iv

9.10 BDS system (Replaces Compass) ................................................................................................... 44

9.11 Indian Regional Navigation Satellite System (IRNSS) Version 3.03 ............................................. 44

9.12 Updates for Quasi-Zenith Satellite System (QZSS), BeiDou and GLONASS (CDMA) RINEX Version 3.04 ............................................................................................................................................ 44

Table 31: QZSS PRN to RINEX Satellite Identifier ........................................................................... 45

10 References .......................................................................................................................................... 47

APPENDIX: RINEX FORMAT DEFINITIONS AND EXAMPLES ......................................................... 1

A 1 RINEX File name description ............................................................................................................ 1

A 2 GNSS Observation Data File -Header Section Description ............................................................... 5

A 3 GNSS Observation Data File -Data Record Description ................................................................. 13

A 4 GNSS Observation Data File – Example #1 .................................................................................... 15

A 4 GNSS Observation Data File – Example #2 .................................................................................... 17

A 4 GNSS Observation Data File – Example #3 .................................................................................... 18

A 5 GNSS Navigation Message File – Header Section Description ...................................................... 19

A 6 GNSS Navigation Message File – GPS Data Record Description................................................... 23

A 7 GPS Navigation Message File – Example ....................................................................................... 24

A 8 GNSS Navigation Message File – GALILEO Data Record Description ......................................... 25

A 9 GALILEO Navigation Message File – Examples ............................................................................ 27

A 10 GNSS Navigation Message File – GLONASS Data Record Description...................................... 29

A 11 GNSS Navigation Message File – Example: Mixed GPS / GLONASS ........................................ 30

A 12 GNSS Navigation Message File – QZSS Data Record Description .............................................. 31

A 13 QZSS Navigation Message File – Example ................................................................................... 32

A 14 GNSS Navigation Message File – BDS Data Record Description ................................................ 33

A 15 BeiDou Navigation Message File – Example ................................................................................ 34

A 16 GNSS Navigation Message File – SBAS Data Record Description .............................................. 35

A 17 SBAS Navigation Message File -Example .................................................................................... 36

A 18 GNSS Navigation Message File – IRNSS Data Record Description............................................. 37

A 19 IRNSS Navigation Message File – Example ................................................................................. 39

A 20 Meteorological Data File -Header Section Description ................................................................. 40

A 21 Meteorological Data File -Data Record Description...................................................................... 42

A 22 Meteorological Data File – Example ............................................................................................. 42

A 23 Reference Code and Phase Alignment by Constellation and Frequency Band .............................. 43

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 1

0. REVISION HISTORY

Version 3.00 02 Feb 2006 A few typos and obsolete paragraphs removed.

08 Mar 2006 Epochs of met data of met files version 2.11 are in GPS time only (Table A20). 31 Mar 2006 DCB header record label corrected in Table A6: SYS / DCBS APPLIED. June 2006 Filenames for mixed GNSS nav mess files. 10 Aug 2006 Table A3: Error in format of EPOCH record: One 6X removed. Trailing 3X removed. 12 Sep 2006 GNSS navigation message files version 3.00 included (including Galileo). Table A4: Example of the kinematic event was wrong (kinematic event record). SYS / DCBS APPLIED header record simplified. Tables A6 and A8: Clarification for adjustment of “Transmission time of message“. 03 Oct 2006 Table A11: Mixed GPS/GLONASS navigation message file 26 Oct 2006 Table A4: Removed obsolete antispoofing flag Tables A6/8/10: Format error in SV / EPOCH / SV CLK: Space between svn and year was missing Half-cycle ambiguity flag (re-)introduced (5.4 and Table A4). Clarification of reported GLONASS time (8.1). New header record SYS / PCVS APPLIED New Table 10: Relations between GPS, GST, and GAL weeks Recommendation to avoid storing redundant navigation messages (8.3) 14 Nov 2006 Tables A6/10/12: Format error in BROADCAST ORBIT – n: 3X → 4X. Examples were OK. 21 Nov 2006 Marker type NON_PHYSICAL added 19-Dec-2006 Table A4: Example of SYS / DCBS APPLIED was wrong. 13-Mar-2007 Paragraph 3.3: Leftover from RINEX version 2 regarding wavelength factor for squaring- type receiver removed and clarified. 14-Jun-2007 Paragraph 5.11: Clarification regarding the observation record length 28-Nov-2007 Frequency numbers for GLONASS –7..+12 (BROADCAST ORBIT – 2) Version 3.01 22-Jun-2009 Phase cycle shifts

Galileo: BOC-tracking of an MBOC-modulated signal

RINEX Version 3.042

Compass satellite system: Identifier and observation codes Code for GPS L1C Header records for GLONASS slot and frequency numbers Order of data records Galileo nav. mess record BROADCAST ORBIT – 5: Bits 3-4 reserved for Galileo internal use Version 3.02 – IGS and RTCM-SC104 19-Nov-2011 Added Quasi Zenith Satellite System (QZSS) Constellation Updated text, tables and graphics Added Appendix Table 19 - phase alignment table 21-Jan-2012 Split the Constellation table into a table for each GNSS Added QZSS to the documentation Edited text to improve clarity Corrected sign in the phase alignment table, Removed QZSS P signals 9-May-2012 Edited text to improve clarity, Updated phase alignment table, Changed Met PGM / RUN BY / DATE to support 4 digit year as in all other records also changed format to support 4 digit year for met. Observation record, Changed SYS / PHASE SHIFTS to SHIFT 29-Nov-2012 Changed Table1 and 2 to Figure 1 and 2. Updated all Table numbers. Changed file naming convention, Section 4. Added Appendix Table A1 and increased all, updated all Appendix numbers Removed the option of supporting unknown tracking mode from Section 5.1. Harmonized L1C(new) signal identifiers for QZSS and GPS See : Table 2 and 6. Updated BeiDou System (BDS) (was Compass) information throughout the document added new BDS ephemeris definition to Appendix. (Based on input from the BDS Office) Corrected GLONASS SLOT/FRQ format in section 9.5, changed message status from optional to mandatory (See: Appendix Table A2). Added new mandatory GLONASS Code Phase Bias header record See section 9.9 11-Mar-2013 Updated Sections: 4.x, made .rnx the file name extension and updated Figure 2; 9.1 to clarify the use of the phase alignment header; A1 Edited to reflect file extension of *.rnx; A14 - BDS ephemeris changed AODC to IODC and AODE to IODE (as indicated by BDS Authority and new ICD); Appendix Table A19 (Changed GLONASS Reference Signals to C1-C2) and explicitly identified reference signal for all constellations and frequencies. 26-Mar-2013 Changed BeiDou to BDS for conform to ICD. In table 7 changed BDS signals from: C2x to C1x to more closely reflect existing bands in tables 2-6 and Appendix Tables A2 and A21.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.043

Updated Section 8.1: First paragraph updated to indicate current number of leap seconds; added a row to Table 12 to show the relationship between GPS week and BDT week. Added a table to show the approximate relationship of BDT to GPS time. Changed order of file type: from OG to GO etc in Appendix Table A1. Updated Appendix table A21 to show X signals and indicate that the X phase is to be aligned to the frequencies reference signal. Fixed a few small typos in A21 for GPS: L1C-D/P and D+P.

RINEX 3.02 Released 03-Dec-2013  Corrected Sections 3.1 to read: TIME OF FIRST OBS rather than start time record.  Added text to Section 5.4 and A3 to indicate that the Loss of Lock Bit is the least significant bit.  In section 9.5 GLONASS Slot and Frequency Numbers, changed optional to mandatory (as it was changed from optional to mandatory in version 3.02).  In Table A2 record: SYS / # / OBS TYPES changed Satellite system code (G/R/E/J/C/S/M to G/R/E/J/C/S).  In Section 5.7 added descriptive text to Table 12 (header- changed Signal to Carrier and in the body) .  In Table A3 record OBSERVATION changed 5: from average to good.  In note 4 after A8 …Galileo System Time added (GST) to make the following description more explicit.  Appendix A14 BeiDou Nav. removed the – sign in front of Cis 24-Jan-2014  Appendix A10 Section SV / EPOCH / SV CLK changed TauN to –TauN to agree with section 8.3.1 4-Apr-2014  Galileo Table A8 , BROADCAST ORBIT-5 - Bits 0-2 : changed from non-exclusive to exclusive (only one bit can be set). In ****) section added (GST)  Corrected Table A23 - BeiDou B1 phase correction column signal indicator to agree with BeiDou Table 9.  Corrected Table A2 - Band 1 = E1 (Was E2-L1-E1) to agree with Galileo Table 6.  In Table A5 - optional message TIME SYSTEM CORR added text to clarify the parameters T and W for BeiDou.  Section 8.3.1 Corrected typo in last line of first paragraph. 6-May-2014  Updated Section 10 Document References  Changed A6 from GPS/QZSS to GPS only as A12 contains a description of the QZSS ephemeris.  Corrected typo in Appendix 23 note 1: L2E changed to L2W 21-May-2014  Appendix A4 added two observation file header examples  Appendix A6 GPS Navigation, Broadcast Orbit-7 Fit Interval,

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.044

clarified in accordance with IS-GPS-200H section 20.3.3.4.3.1  Appendix A9 added Galileo navigation file example  Appendix A12 QZSS Navigation, Broadcast Orbit-5 field 4 allow define L2P flag to be set to one section 5.2.2.2.3(6)); Broadcast Orbit-7 Fit Interval clarified in accordance with section 5.2.2.2.4(4), IS-QZSS 1.5.  Appendix A13 added QZSS navigation file example  Appendix A15 added BeiDou navigation file example 26-May-2014  Removed “Added” from section 9.8, 9.9 and 9.10 titles  Added a note to section 9.9 (GLONASS COD/PHS/BIS) to allow unknown GLONASS code/phase, observation alignment in exceptional cases. Added a note to Appendix A2: GLONASS COD/PHS/BIS record definition. 9-June-2014  Edited Section 6.11 and Table A6:BO7 (GPS) to indicate that the GPS fit interval field should contain a period in hours. Edited Table A12:BO7 (QZSS) to make it clear that the fit interval is a flag and not a time period. Added support for unknown fit interval (specified as an empty field). 10-June-2014  Removed the reference to QZSS in Appendix 6 SC/EPOCH/SV CLK record as there is now a QZSS navigation file in Appendix 12.  Corrected A12 QZSS ICD reference from 5.1.2.3.2 to 5.1.2.1.3.2 12-June-2014  Added text to section 9.9 to indicate that when the GLONASS COD/PHS/BIS measurements are unknown then all fields in the record should be left blank (added an example). Updated the descriptive text in Table A2 GLONASS COD/PHS/BIS. 10-July-2014  Corrected Appendix numbers in body of the text  Added Note after BeiDou Table 9 to indicate that some RINEX 3.02 files may still use the 3.01 B1 coding convention 16-Jul-2014 - Section 9.1 Replaced: Phase observations must be shifted by the respective fraction of a cycle, either directly by the receiver or by a correction program or the RINEX conversion program, prior to RINEX file generation, to align them to each other with: All phase observations must be aligned to the designated constellation and frequency reference signal as specified in Appendix Table A23, either directly by the receiver or by a correction program or the RINEX conversion program, prior to RINEX file generation. Additionally, all data must be aligned with the appropriate reference signal indicated in Appendix Table A23 even when the receiver or reporting device is not tracking and/or providing data from that reference signal e.g. Galileo L5X phase data must be aligned to L5I. 29-Jul-2014 - Minor edits
- Updated last paragraph of section 8.4 re TIME SYSTEM CORR
- Corrected QZSS Appendix Table A12 PRN/EPOCH/SV CLK

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.045

record format specification
- Reformatted Appendix Table A12 and A14 31-Oct-2014 - BeiDou updates: changed B1 signal identifiers to C2x; observation and navigation Header “LEAP SECONDS messages changed to support both GPS and BDS leap seconds; updated the navigation header message “IONOSPHERIC CORR” to support different ionospheric correction parameters from each satellite. Updated BDS navigation message Table A14. Updated Sections 8.1 and 8.2.
- Added Description of the Indian Regional Navigation Satellite System (IRNSS) to the document, Updated RINEX release number to 3.03 Draft 1 19-Jan-2015 - Table 2 grammatical error corrections
- Updated broken http: link on page 17
- Updated Leap Second definition in section 8.1 and Appendix A2 and A5
- Update Galileo Appendix A8 navigation line 5 to indicate the exclusive and non-exclusive bits
- Added text to further clarify BeiDou Appendix A14 AODE and AODC definition
- Updated IRNSS Appendix 18 line 5, week number to indicate that the Week Number is aligned with the GPS week number
- Added IRNSS phase alignment information to Appendix 23

15-April-2015 - Editorial changes/corrections: in section 6.6 specified a new acronym Blank Not Known (BNK), 8.1 added text to indicate the relationship between BDT and GPS Time at start of BDT, corrected typo in Section 8.2 last paragraph changed GLO to UTC, clarified Section 9.2 Galileo Tracking, clarified Section 9.6 re BDS, removed Section 9.8 RINEX Meteorological section
- Re-formatted Appendix Table A2 and A5
- Clarified Observation (A2) and Navigation (A5) “LEAP SECONDS” record
- Clarified Navigation (A5) file “IONOSPHERIC CORR” record
- QZSS A12-BO-6, TGD blank if not know
- Corrected typo in A22,
- Clarified filename start time
- Minor punctuation and grammatical corrections throughout the document.
- Removed reference to unknown tracking mode in Appendix Table A2 message SYS / # / OBS TYPE.
- Updated all table numbers (some tables were not identified), improved table descriptions.
- Minor format changes 15-May-2015 - Added paragraph to section 8.3.2 to specify that RINEX parsers

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.046

should expect to encounter F/NAV and I/NAV messages in the same file…
- Removed “The attribute can be left blank if not known. See text!” text from the end of A2, SYS/#/OBS TYPES as it was decided in 3.02 not to allow unknown signals therefore this no longer applies
- Updated A8 (Galileo Nav. Message), Record 5 Field 2- Description to specify only I/NAV or F/NAV can be specified
- Corrected A9 (Galileo Nav. Example), Record 5 Field 2 from 519 to 517 to indicate I/NAV in accordance with the field specification
- Corrected A9, Record 6 Field 1 from 107(broadcast raw value) to 3.12m 25-May-2015 - Corrected Table of contents to show Section 10.0, References
- Section 2 second last paragraph added IRNSS to list of supported constellations
- Section 5.3 last paragraph concerning event flags added reference to Appendix A3
- Section 7, last paragraph, edited second sentence to make it more clear 1-June-2015 - Minor punctuation corrections
- Added C2X signal tracking example to Section 5.1 example list
- Added paragraph 3 to section 5.1, to indicate only know tracking modes are supported in RINEX 3.02 and 3.03
- Added note to Appendix A2, SYS/#/OBS TYPES to indicate only know tracking modes are allowed in RINEX 3.02 and 3.03
- Table 4 in L1 and L2 frequency bands, changed P to P (AS off) to improve clarity
- Added :”(e.g. units employing a Selective Availability Anti- Spoofing Module (SAASM))“ to last paragraph on page 18 to improve clarity. 24-June-2015 - Updated the last paragraph of Section 1 (RINEX 3.03)
- Clarified Section 4: Changed Obs. Freq. To Data Frequency and update Appendix Table A1 to match
- Added text to Section 8.3.2 (Galileo Navigation) to describe Issue of Data and related parameters
- Added reference to Galileo ICD in Appendix A8 BROADCAST ORBIT-6
- Added Galileo Examples to Appendix Table A9 29-June-2015 - Updated BeiDou RINEX 3.02 C1x-C2x Note below Table 9 for clarity
- Section 8.3.2 added Galileo ICD publication year to reference
- Corrected Beidou C1 to C2 encoding in Appendix A2 SYS/#/OBS TYPES and in Appendix A4 example 2 and 3
- Appendix A2 and A5 Clarified LEAP SECONDS Day number to be 0-6 for BeiDou and 1-7 for GPS and other constellations.
- Updated all Appendix table references to contain Axx, to

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.047

differentiate between body and Appendix tables. 14-July-2015 - Updated LEAP SECONDS record description in Appendix A2 and A5
- Converted Galileo SISA values in Appendix A9 from broadcast value into metres in accordance with RINEX specification and Galileo ICD Section 5.1.11 Table 76
- RINEX 3.03 Released 7-Sept.-2016 - GLONASS Table 5 G2 Section: added missing / to 7/16 to indicate frequency offset spacing
- Updated Tables 29 and 30 to remove errant # from end of message type tag to conform to Appendix A2 definition and examples
- Appendix A3 Observation definition clarified
- Appendix A10 GLONASS Navigation message, clarified the health indicator to be: 0 = healthy and 1 = unhealthy 03-Oct.-2016 - Appendix A3 Observation definition use of Signal Strength Indicator (SSI) further clarified
- Appendix A16 SBAS and QZSS SAIF Navigation message: clarified the health bit mask to be in accordance with Section 8.3.3. 06-Oct.-2016 - Appendix A1 Added Meteorological file name example 28-Oct.-2016 - Corrected http link to PRN Assignment Information on page 19 02-Dec-2016 - Minor punctuation, typographical and grammatical corrections
- Updated Leap second information in Table 22
- Section 8.3.3 and 8.3.4 Transmission Time of Message paragraphs, Changed PRN/EPOCH/SV CLK to SV/EPOCH/SV CLK, reorganized last sentence to improve clarity
- Changed PRN/EPOCH/SV CLK to SV/EPOCH/SV CLK in Table A12 24-Jan-2017 - Released RINEX 3.03 Update 1 25-Apr-2018 - Updated GLONASS, QZSS and BeiDou signal tables 5, 8 and 9 and related information in Appendix Table A23.
- Added Section 9.12 to describe the new signals and features.
- Changed RINEX 3.03 to 3.04 throughout the document.
- Added the new Constellation ICD information to the References section. 30-July-2018 - Corrected format typo in table 26
- Clarified A10 Health Field by specifying most significant bit of 3- bit Bn
- Changed A8 and A10 Label from OBS. RECORD to NAV RECORD
- Table 5 Changed the GLONASS CDMA signals for G1a to G4 and G2a to G6 to be consistent with labeling conventions used for other constellations
- Added new signals in BeiDou Table 9
- Added new Band to Constellation information to A2
- Corrected typo in Table A4 example #3 changed L2Q to L5Q

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.048

30-Aug.-2018 - Clarified QZSS Block I and II signals in Table 8
- Clarified BDS Generation 2 and 3 tracking signal in Table 9
- Updated Table A5 TIME SYSTEM CORR and related examples in appendix tables
- Added Text to specify that the body of RINEX 3.0x files names should be ASCII capital letters and numbers. File extension must be lower case. 11-Sept-2018 - Minor edits and document date update 01-Oct-2018 - Add clarification information to QZSS Table 8, L6 Channel information column.
- Updated Section 9.12 QZSS Block I and II signal coding description. 15-Oct-2018 - Updated format of BeiDou Table 9
- Appendix A2 - corrected 4 = G1a (GLO), reordered signal attribute codes to be in alphabetical order (page A8)
- Corrected A5 –W Reference week number by removing BDS from the group in parentheses so that it is clear that BDS week starts on 1-Jan-2006, as week zero. Also corrected BDUT example in A9
- Appendix A8 updated definition of SISA for -1.0 to read No Accuracy Precision Available/Unknown
- Updated A23 New GLONASS G1 and G2 Frequency Band identifiers to G1a and G2a 22-Oct-2018 - Minor format and editorial updates:
- Table #9 added text to specify new BDS-3 signals in Frequency Band/Frequency Column
- Section 5.12, Table #15, n: band/frequency changed from 1-8 to 1-9.
- Header of Table A6, A12, A14, A16 and A18: replaced OBS. with NAV.
- Updated release dates for QZSS documents in References section
- Corrected A23 QZSS linkage of notes 5 and 6 23-Nov-2018 - Changed IGS ftp://igscb.jpl.nasa.gov to ftp://igs.org and ftp://ftp.unibe.ch/aiub to ftp://ftp.aiub.unibe.ch in References section. Minor naming consistency edits. 23-Nov-2018 - RINEX 3.04 Released

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.049

1. THE PHILOSOPHY AND HISTORY OF RINEX The first proposal for the Receiver Independent Exchange Format RINEX was developed by the Astronomical Institute of the University of Bern for the easy exchange of the Global Positioning System (GPS) data to be collected during the first large European GPS campaign EUREF 89, which involved more than 60 GPS receivers of 4 different manufacturers. The governing aspect during the development was the following fact:

Most geodetic processing software for GPS data use a well-defined set of observables:

 the carrier-phase measurement at one or both carriers (actually being a measurement on the beat frequency between the received carrier of the satellite signal and a receiver-generated reference frequency)  the pseudorange (code) measurement, equivalent to the difference of the time of reception (expressed in the time frame of the receiver) and the time of transmission (expressed in the time frame of the satellite) of a distinct satellite signal  the observation time, being the reading of the receiver clock at the instant of validity of the carrier-phase and/or the code measurements

Usually the software assumes that the observation time is valid for both the phase and the code measurements, and for all satellites observed.

Consequently all these programs do not need most of the information that is usually stored by the receivers: they need phase, code, and time in the above mentioned definitions, and some station- related information like station name, antenna height, etc.

Until now, two major format versions have been developed and published:

th  The original RINEX Version 1 presented at and accepted by the 5International Geodetic Symposium on Satellite Positioning in Las Cruces, 1989. [Gurtner et al. 1989], [Evans 1989]  RINEX Version 2 presented at and accepted by the Second International Symposium of Precise Positioning with the Global Positioning System in Ottawa, 1990, mainly adding the possibility to include tracking data from different satellite systems (GLONASS, SBAS). [Gurtner and Mader 1990a, 1990b], [Gurtner 1994]

Several subversions of RINEX Version 2 have been defined:

 Version 2.10: Among other minor changes, allowing for sampling rates other than integer seconds and including raw signal strengths as new observables. [Gurtner 2002]

 Version 2.11: Includes the definition of a two-character observation code for L2C pseudoranges and some modifications in the GEO NAV MESS files [Gurtner and Estey 2005]

 Version 2.20: Unofficial version used for the exchange of tracking data from

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0410

spaceborne receivers within the IGS LEO pilot project [Gurtner and Estey 2002]

As spin-offs of this idea of a receiver-independent GPS exchange format, other RINEX-like exchange file formats have been defined, mainly used by the International GNSS Service IGS:

 Exchange format for satellite and receiver clock offsets determined by processing data of a GNSS tracking network [Ray and Gurtner 2010]  Exchange format for the complete broadcast data of space- based augmentation systems SBAS. [Suard et al. 2004]  IONEX: Exchange format for ionosphere models determined by processing data of a GNSS tracking network [Schaer et al. 1998]  ANTEX: Exchange format for phase center variations of geodetic GNSS antennae [Rothacher and Schmid 2010]

The upcoming European Navigation Satellite System Galileo and the enhanced GPS with new frequencies and observation types, especially the possibility to track frequencies on different channels, requires a more flexible and more detailed definition of the observation codes.

To improve the handling of the data files in case of “mixed” files, i.e. files containing tracking data of more than one satellite system, each one with different observation types, the record structure of the data record has been modified significantly and following several requests, the limitation to 80 characters length has been removed.

As the changes are quite significant, they lead to a new RINEX Version 3. The new version also includes the unofficial Version 2.20 definitions for space-borne receivers.

The major change leading to the release of version 3.01 was the requirement to generate consistent phase observations across different tracking modes or channels, i.e. to apply ¼-cycle shifts prior to RINEX file generation, if necessary, to facilitate the processing of such data.

RINEX 3.02 added support for the Japanese, Quasi Zenith Satellite System (QZSS), additional information concerning BeiDou (based on the released ICD) and a new message to enumerate GLONASS code phase biases.

RINEX 3.03 adds support for the Indian Regional Satellite System (IRNSS) and clarifies several implementation issues in RINEX 3.02. RINEX 3.03 also changes the BeiDou B1 signal convention back to the 3.01 convention where all B1 signals are identified as C2x (not C1 as in RINEX 3.02). Another issue with the implementation of 3.02 was the GPS navigation message fit interval field. Some implementations wrote the flag and others wrote a time interval. This release specifies that the fit interval should be a time period for GPS and a flag for QZSS. The Galileo Navigation section 8.3.2 was updated to clarify the Issue of Data (IOD). RINEX 3.03 was also modified to specify that only known observation tracking modes can be encoded in the standard.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0411

2. GENERAL FORMAT DESCRIPTION The RINEX version 3.XX format consists of three ASCII file types:

1. Observation data file
2. Navigation message file
3. Meteorological data file

Each file type consists of a header section and a data section. The header section contains global information for the entire file and is placed at the beginning of the file. The header section contains header labels in columns 61-80 for each line contained in the header section. These labels are mandatory and must appear exactly as given in these descriptions and examples.

The format has been optimized for minimum space requirements independent from the number of different observation types of a specific receiver or satellite system by indicating in the header the types of observations to be stored for this receiver and the satellite systems having been observed. In computer systems allowing variable record lengths, the observation records may be kept as short as possible. Trailing blanks can be removed from the records. There is no maximum record length limitation for the observation records.

Each Observation file and each Meteorological Data file basically contain the data from one site and one session. Starting with Version 2 RINEX also allows including observation data from more than one site subsequently occupied by a roving receiver in rapid static or kinematic applications. Although Version 2 and higher allow insertion of certain header records into the data section, it is not recommended to concatenate data from more than one receiver (or antenna) into the same file, even if the data do not overlap in time.

If data from more than one receiver have to be exchanged, it would not be economical to include the identical satellite navigation messages collected by the different receivers several times. Therefore, the navigation message file from one receiver may be exchanged or a composite navigation message file created, containing non-redundant information from several receivers in order to make the most complete file.

The format of the data records of the RINEX Version 1 navigation message file was identical to the former NGS exchange format. RINEX Version 3 navigation message files may contain navigation messages of more than one satellite system (GPS, GLONASS, Galileo, Quasi Zenith Satellite System (QZSS), BeiDou System (BDS), Indian Regional Navigation Satellite System (IRNSS) and SBAS).

The actual format descriptions as well as examples are given in the Appendix Tables at the end of the document.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0412

3. BASIC DEFINITIONS GNSS observables include three fundamental quantities that need to be defined: Time, Phase, and Range.

3.1 Time The time of the measurement is the receiver time of the received signals. It is identical for the phase and range measurements and is identical for all satellites observed at that epoch. For single- system data files, it is by default expressed in the time system of the respective satellite system. For mixed files, the actual time system used must be indicated in the TIME OF FIRST OBS header record.

3.2 Pseudo-Range The pseudo-range (PR) is the distance from the receiver antenna to the satellite antenna including receiver and satellite clock offsets (and other biases, such as atmospheric delays):

PR = distance + c * (receiver clock offset –satellite clock offset + other biases)

so that the pseudo-range reflects the actual behaviour of the receiver and satellite clocks. The pseudo-range is stored in units of meters.

See also clarifications for pseudoranges in mixed GPS/GLONASS/Galileo/QZSS/BDS files in chapter 8.2.

3.3 Phase The phase is the carrier-phase measured in whole cycles. The half-cycles measured by squaring- type receivers must be converted to whole cycles and flagged by the respective observation code (see Table 4 and Section 5.4, GPS only).

The phase changes in the same sense as the range (negative doppler). The phase observations between epochs must be connected by including the integer number of cycles.

The observables are not corrected for external effects such as: atmospheric refraction, satellite clock offsets, etc.

If necessary, phase observations are corrected for phase shifts needed to guarantee consistency between phases of the same frequency and satellite system based on different signal channels (See Section 9.1 and Appendix A23).

If the receiver or the converter software adjusts the measurements using the real-time-derived receiver clock offsets dT(r), the consistency of the 3 quantities phase / pseudo-range / epoch must be maintained, i.e. the receiver clock correction should be applied to all 3 observables:

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0413

Time (corr) = Time(r) - dT(r)

PR (corr) = PR (r) - dT(r)*c

phase (corr) = phase (r) - dT(r)*freq

Table 1: Observation Corrections for Receiver Clock Offset

3.4 Doppler The sign of the doppler shift as additional observable is defined as usual: Positive for approaching satellites.

3.5 Satellite numbers

Starting with RINEX Version 2 the former two-digit satellite numbers nn are preceded by a one- character system identifier s as shown in Figure 1.

Figure 1: Satellite numbers and Constellation Identifiers
* ) For detailed definition of QZSS, please refer the section 9.12 )

The same satellite system identifiers are also used in all header records when appropriate.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0414

4. THE EXCHANGE OF RINEX FILES

The original RINEX file naming convention was implemented in the MS-DOS era when file names were restricted to 8.3 characters. Modern operating systems typically support 255 character file names. The goal of the new file naming convention is to be more descriptive, flexible and extensible than the RINEX 2.11 file naming convention. Figure 2 below lists the elements of the RINEX 3.02 (and subsequent versions) file naming convention.

Figure 2: Recommended filename parameters.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0415

All elements of the main body of the file name must contain capital ASCII letters or numbers and all elements are fixed length and are separated by an underscore “_”.The file type and compression fields (extension) use a period “.” as a separator and must be ASCII characters and lower case. Fields must be padded with zeros to fill the field width. The file compression field is optional. See Appendix A1 for a detailed description of the RINEX 3.02 (and subsequent versions) file naming convention. Table 2 below lists sample file names for GNSS observation and navigation files.

File Name Comments ALGO00CAN_R_20121601000_01H_01S_MO.rnx Mixed RINEX GNSS observation file containing 1 hour of data, with an observation every second ALGO00CAN_R_20121601000_15M_01S_GO.rnx GPS RINEX observation file containing 15 minutes of data, with an observation every second ALGO00CAN_R_20121601000_01H_05Z_MO.rnx Mixed RINEX GNSS observation file containing 1 hour of data, with 5 observations per second ALGO00CAN_R_20121601000_01D_30S_GO.rnx GPS RINEX observation file containing 1 day of data, with an observation every 30 seconds ALGO00CAN_R_20121601000_01D_30S_MO.rnx Mixed RINEX GNSS observation file containing 1 day of data, with an observation every 30 seconds ALGO00CAN_R_20121600000_01D_GN.rnx RINEX GPS navigation file, containing one day’s data ALGO00CAN_R_20121600000_01D_RN.rnx RINEX GLONASS navigation file, containing one day’s data ALGO00CAN_R_20121600000_01D_MN.rnx RINEX mixed navigation file, containing one day’s data

Table 2: Description of Filename Parameters

In order to further reduce the size of observation files, Yuki Hatanaka developed a compression scheme that takes advantage of the structure of the RINEX observation data by forming higher- order differences in time between observations of the same type and satellite. This compressed file is also an ASCII file that is subsequently compressed again using standard compression programs. More information on the Hatanaka compression scheme can be found in: http://terras.gsi.go.jp/ja/crx2rnx.html  IGSMails 1525,1686,1726,1763,1785,4967,4969,4975

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0416

The file naming and compression recommendations are strictly speaking not part of the RINEX format definition. However, they significantly facilitate the exchange of RINEX data in large user communities like IGS.

5. RINEX VERSION 3 FEATURES This chapter contains features that have been introduced for RINEX Version 3.

5.1 Observation codes The new signal structures for GPS, Galileo and BDS make it possible to generate code and phase observations based on one or a combination of several channels: Two-channel signals are composed of I and Q components, three-channel signals of A, B, and C components. Moreover, a wideband tracking of a combined E5a + E5b Galileo frequency is possible. In order to keep the observation codes short but still allow for a detailed characterization of the actual signal generation, the length of the codes is increased from two (Version 1 and 2) to three by adding a signal generation attribute. The observation code tna consists of three parts: t :observation type C = pseudorange, L = carrier phase, D = doppler, S = signal strength n :band / frequency 1, 2,...,9

a : attribute tracking mode or channel, e.g., I, Q, etc

Table 3: Observation Code Components

Examples:

 L1C: C/A code-derived L1 carrier phase (GPS, GLONASS) Carrier phase on E2-L1- E1 derived from C channel (Galileo)  C2L: L2C pseudorange derived from the L channel (GPS)  C2X: L2C pseudorange derived from the mixed (M+L) codes (GPS)

Tables 4 to 10 describe each GNSS constellation and the frequencies and signal encoding methods used.

Unknown tracking modes are not supported in RINEX 3.02 and 3.03. Only the complete specification of all signals is allowed i.e. all three fields must be defined as specified in Tables 4- 10.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0417

Observation Codes GNSSFreq. Band Channel or CodePseudoCarrierSignal System/Frequency Doppler RangePhase Strength GPSC/A C1C L1C D1C S1C L1C (D) C1S L1S D1S S1S L1C (P) C1L L1L D1L S1L L1C (D+P) C1X L1X D1X S1X P (AS off) C1P L1P D1P S1P L1/1575.42 Z-tracking and similar C1W L1W D1W S1W (AS on) Y C1Y L1Y D1Y S1Y M C1M L1M D1M S1M codeless L1N D1N S1N C/A C2C L2C D2C S2C L1(C/A)+(P2-P1) C2D L2D D2D S2D (semi-codeless) L2C (M) C2S L2S D2S S2S L2C (L) C2L L2L D2L S2L L2C (M+L) C2X L2X D2X S2X L2/1227.60 P (AS off) C2P L2P D2P S2P Z-tracking and similar C2W L2W D2W S2W (AS on) Y C2Y L2Y D2Y S2Y M C2M L2M D2M S2M codeless L2N D2N S2N I C5I L5I D5I S5I L5/1176.45Q C5Q L5Q D5Q S5Q I+Q C5X L5X D5X S5X

Table 4 : RINEX Version 3.04 GPS Observation Codes

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0418

Observation Codes GNSSFreq. BandChannel or PseudoCarrierSignal System/FrequencyCodeDoppler RangePhase Strength GLONASS G1/C/A C1C L1C D1C S1C 1602+k*9/16 P C1P L1P D1P S1P k= -7….+12 L1OCd C4A L4A D4A S4A G1a/ L1OCp C4B L4B D4B S4B 1600.995 L1OCd+ L1OCp C4X L4X D4X S4X C/A C2C L2C D2C S2C G2/(GLONASS M) 1246+k*7/16P C2P L2P D2P S2P G2a/L2CSI C6A L6A D6A S6A 1248.06L2OCp C6B L6B D6B S6B L2CSI+ L2OCp C6X L6X D6X S6X I C3I L3I D3I S3I G3 / 1202.025Q C3Q L3Q D3Q S3Q I+Q C3X L3X D3X S3X

Table 5 : RINEX Version 3.04 GLONASS Observation Codes

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0419

Observation Codes GNSSFreq. Band Channel or CodePseudoCarrierSignal System/Frequency Doppler RangePhase Strength GalileoA PRS C1A L1A D1A S1A B I/NAV OS/CS/SoL C1B L1B D1B S1B E1 / 1575.42C no data C1C L1C D1C S1C B+C C1X L1X D1X S1X A+B+C C1Z L1Z D1Z S1Z I F/NAV OS C5I L5I D5I S5I E5a / 1176.45Q no data C5Q L5Q D5Q S5Q I+Q C5X L5X D5X S5X I I/NAV OS/CS/SoL C7I L7I D7I S7I E5b / 1207.140Q no data C7Q L7Q D7Q S7Q I+Q C7X L7X D7X S7X I C8I L8I D8I S8I E5(E5a+E5b) / Q C8Q L8Q D8Q S8Q 1191.795 I+Q C8X L8X D8X S8X A PRS C6A L6A D6A S6A B C/NAV CS C6B L6B D6B S6B E6 / 1278.75C no data C6C L6C D6C S6C B+C C6X L6X D6X S6X A+B+C C6Z L6Z D6Z S6Z

Table 6 : RINEX Version 3.04 Galileo Observation Codes For Galileo the band/frequency number n does not necessarily agree with the official frequency numbers: n = 7 for E5b, n = 8 for E5a+b.

Observation Codes GNSSFreq. Band/Channel or PseudoCarrierDoppler Signal SystemFrequencyCode RangePhaseStrength L1 / 1575.42 C/A C1C L1C D1C S1C I C5I L5I D5I S5I SBAS L5 / 1176.45Q C5Q L5Q D5Q S5Q I+Q C5X L5X D5X S5X

Table 7 : RINEX Version 3.04 SBAS Observation Codes

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0420

Observation Codes GNSSFreq. Band /Channel or PseudoCarrierSignal SystemFrequencyCodeDoppler RangePhase Strength QZSSC/A C1C L1C D1C S1C L1C (D) C1S L1S D1S S1S L1 / 1575.42L1C (P) C1L L1L D1L S1L L1C (D+P) C1X L1X D1X S1X L1S/L1-SAIF C1Z L1Z D1Z S1Z L2C (M) C2S L2S D2S S2S L2 / 1227.60L2C (L) C2L L2L D2L S2L L2C (M+L) C2X L2X D2X S2X I * C5I L5I D5I S5I L5 / 1176.45 Q * C5Q L5Q D5Q S5Q *(Block I Signals) I+Q * C5X L5X D5X S5X **(Block II L5S L5D ** C5D L5D D5D S5D Signals) L5P ** C5P L5P D5P S5P L5(D+P) ** C5Z L5Z D5Z S5Z L6 / 1278.75L6D*,**C6SL6SD6SS6S *(Block I LEXL6P * C6L L6L D6L S6L Signals)L6(D+P) * C6X L6X D6X S6X **(Block IIL6E ** C6E L6E D6E S6E Signals)L6(D+E)**C6ZL6ZD6ZS6Z

Table 8 : RINEX Version 3.04 QZSS Observation Codes Note: RINEX 1Z signal coding is used for both the initial Block I L1-SAIF signal and the updated L1S signal. L6D is the “code 1” of the L61(BlockI) and L62 (Block II) signals, L6P is the “code 2” (or pilot) signal of the L61(Block I) signal and L6E is the “code 2” of the L62(Block II) signal as specified in IS-QZSS-L6. See section 9.12 and Table 31 for QZSS PRN to RINEX identifier coding.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0421

Observation Codes GNSS Freq. Band / Frequency Channel or Code System PseudoCarrierSignal Doppler RangePhase Strength BDSI C2I L2I D2I S2I B1-2 / 1561.098Q C2Q L2Q D2Q S2Q I+Q C2X L2X D2X S2X Data C1D L1D D1D S1D Pilot C1P L1P D1P S1P B1 / 1575.42Data+PilotC1XL1XD1XS1X (BDS-3 Signals)B1AC1AL1AD1AS1A Codeless L1N D1N S1N Data C5D L5D D5D S5D B2a / 1176.45Pilot C5P L5P D5P S5P (BDS-3 Signals)Data+PilotC5XL5XD5XS5X B2b / 1207.140I C7I L7I D7I S7I (BDS-2 Signals)Q C7Q L7Q D7Q S7Q I+Q C7X L7X D7X S7X B2b / 1207.140Data C7D L7D D7D S7D (BDS-3 Signals)Pilot C7P L7P D7P S7P Data+Pilot C7Z L7Z D7Z S7Z B2(B2a+B2b)/1191.795Data C8D L8D D8D S8D (BDS-3 Signals)Pilot C8P L8P D8P S8P Data+Pilot C8X L8X D8X S8X B3/1268.52 I C6I L6I D6I S6I Q C6Q L6Q D6Q S6Q I+Q C6X L6X D6X S6X B3A C6A L6A D6A S6A

Table 9 : RINEX Version 3.04 BDS Observation Codes Note: When reading a RINEX 3.02 file, both C1x and C2x coding should be accepted and treated as C2x in RINEX 3.03.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0422

Observation Codes GNSS Freq. Band / Frequency Channel or Code System PseudoCarrierSignal Doppler RangePhase Strength IRNSSA SPS C5A L5A D5A S5A B RS (D) C5B L5B D5B S5B L5 / 1176.45 C RS (P) C5C L5C D5C S5C B+C C5X L5X D5X S5X A SPS C9A L9A D9A S9A B RS (D) C9B L9B D9B S9B S / 2492.028 C RS (P) C9C L9C D9C S9C B+C C9X L9X D9X S9X

Table 10 : RINEX Version 3.04 IRNSS Observation Codes

GPS-SBAS and –pseudorandom noise (PRN) code assignments see: https://media.defense.gov/2016/Jul/26/2001583103/-1/-1/1/PRN%20CODE%20ASSIGNMENT%20PROCESS.PDF

Antispoofing (AS) of GPS: True codeless GPS receivers (squaring-type receivers) use the attribute N. Semi-codeless receivers tracking the first frequency using C/A code and the second frequency using some codeless options use attribute D. Z-tracking under AS or similar techniques to recover pseudorange and phase on the “P-code” band use attribute W. Y-code tracking receivers (e.g. units employing a Selective Availability Anti-Spoofing Module (SAASM)) use attribute Y.

Appendix Table A23 enumerates the fractional phase corrections required to align each signal to the frequencies reference signal.

As all observations affected by “AS on” now get their own attribute (codeless, semi-codeless, Z- tracking and similar), the Antispoofing flag introduced into the observation data records of RINEX Version 2 has become obsolete.

5.2 Satellite system-dependent list of observables The order of the observations stored per epoch and satellite in the observation records is given by a list of observation codes in a header record. As the types of the observations actually generated by a receiver may heavily depend on the satellite system, RINEX Version 3 requests system-dependent observation code lists (header record type SYS / # / OBS TYPES).

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0423

5.3 Marker type

In order to indicate the nature of the marker, a MARKER TYPE header record has been defined. Proposed keywords are given in Table 11.

Marker Type Description Geodetic Earth-fixed high-precision monument Non Geodetic Earth-fixed low-precision monument Non_Physical Generated from network processing Space borne Orbiting space vehicle Air borne Aircraft, balloon, etc. Water Craft Mobile water craft Ground Craft Mobile terrestrial vehicle Fixed Buoy “Fixed” on water surface Floating Buoy Floating on water surface Floating Ice Floating ice sheet, etc Glacier “Fixed” on a glacier Ballistic Rockets, shells, etc Animal Animal carrying a receiver Human Human being

Table 11: Proposed Marker Type Keywords

The record is required except for GEODETIC and NON_GEODETIC marker types.

Attributes other than GEODETIC and NON_GEODETIC will tell the user program that the data were collected by a moving receiver. The inclusion of a “start moving antenna” record (event flag
2) into the data body of the RINEX file is therefore not necessary. However, event flags 2 and 3 (See Appendix A3) are still necessary to flag alternating kinematic and static phases of a receiver visiting multiple earth-fixed monuments. Users may define other project-dependent keywords.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0424

5.4 Half-wavelength observations, half-cycle ambiguities Half-wavelength observations (collected by codeless squaring techniques) get their own observation codes. A special wavelength factor header line and bit 1 of the LLI flag in the observation records are no longer necessary. If a receiver changed between squaring and full cycle tracking within the time period of a RINEX file, observation codes for both types of observations have to be inserted into the respective SYS / # / OBS TYPES header record. Half-wavelength phase observations are stored in full cycles. Ambiguity resolution, however, has to account for half wavelengths!

Full-cycle observations collected by receivers with possible half cycle ambiguity (e.g., during acquisition or after loss of lock) are to be flagged with Loss of Lock Indicator bit 1 set (see Appendix Table A3). Note: The loss of lock bit is the least significant bit.

5.5 Scale factor The optional SYS / SCALE FACTOR record allows the storage of phase data with 0.0001 of a cycle resolution, if the data was multiplied by a scale factor of 10 before being stored into the RINEX file. This feature is used to increase resolution by 10, 100, etc only. It is a modification of the Version 2.20 OBS SCALE FACTOR record.

5.6 Information about receivers on a vehicle For the processing of data collected by receivers on a vehicle, the following additional information can be provided by special header records:

 Antenna position (position of the antenna reference point) in a body-fixed coordinate system: ANTENNA: DELTA X/Y/Z  Boresight of antenna: The unit vector of the direction of the antenna axis towards the GNSS satellites. It corresponds to the vertical axis on earth-bound antenna: ANTENNA: B.SIGHT XYZ  Antenna orientation: Zero-direction of the antenna. Used for the application of “azimuth”- dependent phase center variation models (see 6.14 below): ANTENNA: ZERODIR XYZ  Current center of mass of the vehicle (for space borne receivers): CENTER OF MASS: XYZ  Average phase center position: ANTENNA: PHASECENTER (see below)

All three quantities have to be given in the same body-fixed coordinate system. The attitude of the vehicle has to be provided by separate attitude files in the same body-fixed coordinate system.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0425

5.7 Signal strength The generation of the RINEX signal strength indicators sn_rnx in the data records (1 = very weak,…,9 = very strong) are standardized in case the raw signal strengthsn_raw is given in dbHz:

sn_rnx = MIN(MAX(INT(sn_raw/6),1),9)

Carrier to Noise ratio(dbHz) Carrier to Noise ratio(RINEX) < 12 1 (minimum possible signal strength) 12-17 2 18-23 3 24-29 4 30-35 5 (threshold for good tracking) 36-41 6 42-47 7 48-53 8 ≥ 54 9 (maximum possible signal strength)

Table 12: Standardized S/N Indicators

The raw carrier to noise ratio can be optionally (preferred) stored as Sna observations in the data records and should be given in dbHz if possible. The new SIGNAL STRENGTH UNIT header record can be used to indicate the units of these observations.

5.8 Date/time format in the PGM / RUN BY / DATE header record

The format of the generation time of the RINEX files stored in the second header record PGM / RUN BY / DATE is now defined to be:

yyyymmdd hhmmss zone

zone: 3 – 4 character code for the time zone

It is recommended to use UTC as the time zone. Set zone to LCL if local time was used with unknown local time system code.

S/N is the raw S/N at the output of the correlators, without attempting to recover any correlation losses

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0426

5.9 Antenna phase center header record An optional header record for antenna phase center positions ANTENNA: PHASECENTER is defined to allow for higher precision positioning without need of additional external antenna information. It can be useful in well-defined networks or applications. It contains the position of an average phase center relative to the antenna reference point (ARP) for a specific frequency and satellite system. On vehicles, the phase center position can be reported in the body-fixed coordinate system (ANTENNA: DELTA X/Y/Z). See 6.14 below. See section 5.15 regarding the use of phase center variation corrections.

5.10 Antenna orientation Header records have been defined to report the orientation of the antenna zero-direction as well as the direction of its vertical axis (bore-sight) if mounted tilted on a fixed station. The header records can also be used for antennas on vehicles. See 6.14 below.

5.11 Observation data records Aside from the new observation code definitions, the most conspicuous modification of the RINEX format concerns the observation records. As the types of the observations and their order within a data record depend on the satellite system, the new format should make it easier for programs as well as human beings to read the data records. Each observation record begins with the satellite number snn, the epoch record starts with special character >. It is now also much easier to synchronize the reading program with the next epoch record in case of a corrupted data file or when streaming observation data in a RINEX-like format. The record length limitation to 80 characters of RINEX Versions 1 and 2 has been removed.

For the following list of observation types for the four satellite systems G,R,E,S :

G 5 C1P L1P L2X C2X S2X SYS / # / OBS TYPES R 2 C1C L1C SYS / # / OBS TYPES E 2 L1B L5I SYS / # / OBS TYPES S 2 C1C L1C SYS / # / OBS TYPES

Table 13: Example Observation Type Records

The epoch and observation records are as follows:

> 2006 03 24 13 10 54.0000000 0 7 -0.123456789210 G06 23619095.450 -53875.632 8 -41981.375 5 23619112.008 24.158 G09 20886075.667 -28688.027 9 -22354.535 6 20886082.101 38.543 G12 20611072.689 18247.789 9 14219.770 8 20611078.410 32.326 R21 21345678.576 12345.567 5 R22 22123456.789 23456.789 5 E11 65432.123 5 48861.586 7 S20 38137559.506 335849.135 9

Table 14: Example Observation Data Records

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0427

The receiver clock correction in the epoch record has been placed such that it could be preceded by an identifier to make it system-dependent in a later format revision, if necessary. The clock correction is optional and is given in units of seconds.

5.12 Ionosphere delay as pseudo-observables RINEX files could also be used to make available additional information linked to the actual observations. One such element is the ionosphere delay, having been determined or derived from an ionosphere model. We add the ionosphere phase delay expressed in full cycles of the respective satellite system-dependent wavelength as pseudo-observable to the list of the RINEX observables.

t: observation type I = Ionosphere phase delay

n: band/frequency 1, 2, ...,9

a: attribute blank

Table 15: Ionosphere Pseudo-Observable Coding The ionosphere pseudo-observable has to be included into the list of observables of the respective satellite system. Only one ionosphere observable per satellite is allowed.

The user adds the ionosphere delay to the raw phase observation of the same wavelength and converts it to other wavelengths and to pseudorange corrections in meters:

corr_phase(fi) = raw_phase(fi) + d_ion(fi)

corr_prange(fi) = raw_prange(fi) - d_ion(fi)  c/fi

st d_ion(fk) = d_ion(fi)  (fi/fk)**2 (accounting for 1order effects only)

Table 16: Ionosphere Pseudo-Observable Corrections to Observations d_ion(fi): Given ionospheric phase correction for frequency fi

5.13 Channel numbers as pseudo-observables For special applications, it might be necessary to know the receiver channel numbers having been assigned by the receiver to the individual satellites. We may include this information as another pseudo-observable:

- t : observation type: X = Receiver channel number
- n : band / frequency : 1
- a : attribute: blank

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0428

The lowest channel number allowed is 1 (re-number channels beforehand, if necessary). In the case of a receiver using multiple channels for one satellite, the channels could be packed with two digits each right-justified into the same data field, order corresponding to the order of the observables concerned. Format F14.3 according to (<5-nc>(2X),<nc>I2.2,’.000’), nc being the number of channels.

Restriction: Not more than 5 channels and channel numbers <100.

Examples:  0910.000 for channels 9 and 10  010203.000 for channels 1, 2, and 3 -----F14.3----

5.14 Corrections of differential code biases (DCBs) For special high-precision applications, it might be useful to generate RINEX files with corrections of the differential code biases (DCBs) already applied. There are programs available to correct the observations in RINEX files for differential code biases (e.g., cc2noncc, J. Ray 2005). This can be reported by special header records SYS / DCBS APPLIED pointing to the file containing the applied corrections.

5.15 Corrections of antenna phase center variations (PCVs) For more precise applications, an elevation-dependent or elevation and azimuth-dependent Phase Center Variation (PCV) model for the antenna (referring to the agreed-upon ARP) should be used. For special applications, it might be useful to generate RINEX files with these variations already applied. This can be reported by special header records SYS / PCVS APPLIED pointing to the file containing the PCV correction models.

5.16 Navigation message files The header portion has been unified (with respect to the format definitions) for all satellite systems. The first record of each data block now contains the code for the satellite system and the satellite number.

G06 1999 09 02 17 51 44 -.839701388031D-03 -.165982783074D-10 .000000000000D+00

Table 17: Example of Navigation File Satellite System and Number Definition Record Header records with system-dependent contents also contain the system identifier. They are repeated for each system, if applicable.

GPSA .1676D-07 .2235D-07 .1192D-06 .1192D-06 IONOSPHERIC CORR GPSB .1208D+06 .1310D+06 -.1310D+06 -.1966D+06 IONOSPHERIC CORR GAL .1234D+05 .2345D+04 -.3456D+03 IONOSPHERIC CORR

Table 18: Example of Navigation File Header IONOSPHERIC CORR Record

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0429

6. ADDITIONAL HINTS AND TIPS

6.1 Versions

Programs developed to read RINEX files have to verify the version number. Files of newer versions may look different even if they do not use any of the newer features.

6.2 Leading blanks in CHARACTER fields We propose that routines to read files automatically should delete leading blanks in any CHARACTER input field. Routines creating RINEX files should also left-justify all variables in the CHARACTER fields.

6.3 Variable-length records ASCII files usually have variable record lengths, so we recommend to first read each observation record into a blank string long enough to accommodate the largest possible observation record and decode the data afterwards. In variable length records, empty data fields at the end of a record may be missing, especially in the case of the optional receiver clock offset.

6.4 Blank fields In view of future modifications, we recommend to carefully skip any fields currently defined to be blank (format fields nX), because they may be assigned to new contents in future versions.

6.5 Order of the header records, order of data records As the header record descriptors in columns 61-80 are mandatory, the programs reading a RINEX Version 3 header must decode the header records with formats according to the record descriptor, provided the records have been first read into an internal buffer.

We therefore propose to allow free ordering of the header records, with the following exceptions:  The RINEX VERSION / TYPE record must be the first record in a file  The SYS / # / OBS TYPES record(s) should precede any SYS / DCBS APPLIED and SYS / SCALE FACTOR records  The # OF SATELLITES record (if present) should be immediately followed by the corresponding number of PRN / # OF OBS records. These records may be handy for documentary purposes. However, since they may only be created after having read the whole raw data file, we define them to be optional  The END OF HEADER of course is the last record in the header

Record is defined by the satellite system with the largest number of possible observables plus any “pseudo-observables” such as ionosphere etc. The length limitation to 80 characters of RINEX Versions 1 and 2 has been removed.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0430

Data records: Multiple epoch observation data records with identical time tags are not allowed (exception: Event records). Epochs have to appear ordered in time.

6.6 Missing items, duration of the validity of values Items that are not known at the file creation time can be set to zero or blank (Blank if Not Known
- BNK) or the respective record may be completely omitted. Consequently, items of missing header records will be set to zero or blank by the program reading RINEX files. Trailing blanks may be truncated from the record.

Each value remains valid until changed by an additional header record.

6.7 Unknown / Undefined observation types and header records It is a good practice for a program reading RINEX files to make sure that it properly deals with unknown observation types, header records or event flags by skipping them and/or reporting them to the user. The program should also check the RINEX version number in the header record and take proper action if it cannot deal with it.

6.8 Event flag records The “number of satellites” also corresponds to the number of records of the same epoch following the EPOCH record. Therefore, it may be used to skip the appropriate number of data records if certain event flags are not to be evaluated in detail.

6.9 Receiver clock offset A receiver-derived clock offset can optionally be reported in the RINEX observation files. In order to remove uncertainties about whether the data (epoch, pseudorange, phase) have been corrected or not by the reported clock offset, RINEX Versions 2.10 onward requests a clarifying header record: RCV CLOCK OFFS APPL. It would then be possible to reconstruct the original observations, if necessary.

6.10 Two-digit years RINEX version 2 stores the years of data records with two digits only. The header of observation files contains a TIME OF FIRST OBS record with the full four-digit year; the GPS nav. messages contain the GPS week numbers. From these two data items, the unambiguous year can easily be reconstructed.

A hundred-year ambiguity occurs in the met data and GLONASS and GEO nav. messages: instead of introducing a new TIME OF FIRST OBS header line, it is safe to stipulate that any two- digit years in RINEX Version 1 and Version 2.xx files are understood to represent:

80-99: 1980-1999 00-79: 2000-2079

Full 4-digit year fields are defined in RINEX version 3 files.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0431

6.11 Fit interval (GPS navigation message file) Bit 17 in word 10 of subframe 2 is a “fit interval” flag which indicates the curve-fit interval used by the GPS Control Segment in determining the ephemeris parameters, as follows (see IS-GPS- 200H, 20.3.3.4.3.1):

0 = 4 hours 1 = greater than 4 hours.

Together with the IODC values and Table 20-XII (of the ICD) the actual fit interval can be determined. The second value in the last record of each message shall contain the fit interval in hours determined using IODC, fit flag, and Table 20-XII, according to the Interface Document IS- GPS-200H. Note: The QZSS fit interval is not defined the same way as it is in GPS, see Appendix Table A12.

6.12 Satellite health (GPS navigation message file) The health of the signal components (bits 18 to 22 of word three in subframe one) are included from version 2.10 on using the health value reported in the second field of the sixth navigation message record.

A program reading RINEX files could easily decide if bit 17 only or all bits (17-22) have been written:

RINEX Value: 0 Health OK RINEX Value: 1 Health not OK (bits 18-22 not stored) RINEX Value: >32 Health not OK (bits 18-22 stored) Table 19: Description of GPS Satellite Health Field

6.13 Transmission time of message (GPS navigation message file) The transmission time of a message can be shortly before midnight Saturday/Sunday, with the ToE and ToC of the message already in the next week.

As the reported week in the RINEX nav message (BROADCAST ORBIT -5 record) goes with ToE (this is different from the GPS week in the original satellite message!), the transmission time of message should be reduced by 604800 (i.e., will become negative) to also refer to the same week.

6.14 Antenna references, phase centers We distinguish between

 The marker, i.e. the geodetic reference monument, on which an antenna is mounted directly with forced centering or on a tripod

 The antenna reference point (ARP), i.e., a well-defined point on the antenna, e.g., the center of the bottom surface of the preamplifier. The antenna height is measured from the marker to the ARP and reported in the ANTENNA: DELTA H/E/N header record. Small horizontal eccentricities of the ARP with respect to the marker can be reported in the same

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0432

record. On vehicles, the position of the ARP is reported in the body-fixed coordinate system in an ANTENNA: DELTA X/Y/Z header record.

 The average phase center: A frequency-dependent and minimum elevation-angle- dependent position of the average phase center above the antenna reference point. Its position is important to know in mixed-antenna networks. It can be given in an absolute sense or relative to a reference antenna using the optional header record: ANTENNA: PHASECENTER. For fixed stations the components are in north/east/up direction, on vehicles the position is reported in the body-fixed system X,Y,Z. For more precise applica- tions, an elevation-dependent or elevation and azimuth-dependent phase center variation (PCV) model for the antenna (referring to the agreed-upon ARP) should be used. For special applications it might be useful to generate RINEX files with these corrections already applied. This can be reported by special header records SYS / PCVS APPLIED pointing to the file containing the PCV correction models.

 The orientation of the antenna: The “zero direction” is usually oriented towards north on fixed stations. Deviations from the north direction can be reported with the azimuth of the zero-direction in an ANTENNA: ZERODIR AZI header record. On vehicles, the zero- direction is reported as a unit vector in the body-fixed coordinate system in an ANTENNA: ZERODIR XYZ header record. The zero direction of a tilted antenna on a fixed station can be reported as unit vector in the left-handed north/east/up local coordinate system in an ANTENNA: ZERODIR XYZ header record.

 The boresight direction of an antenna on a vehicle: The “vertical” symmetry axis of the antenna pointing towards the GNSS satellites. It can be reported as unit vector in the body- fixed coordinate system in the ANTENNA: B.SIGHT XYZ record. A tilted antenna on a fixed station could be reported as unit vector in the left-handed north/east/up local coordinate system in the same type of header record.

In order to interpret the various positions correctly, it is important that the MARKER TYPE record be included in the RINEX header.

7. RINEX UNDER ANTISPOOFING (AS) Some receivers generate code (pseudorange) delay differences between the first and second frequency using cross-correlation techniques when AS is on and may recover the phase observations on L2 in full cycles. Using the C/A code delay on L1 and the observed difference, it is possible to generate a code delay observation for the second frequency. Other receivers recover P code observations by breaking down the Y code into P and W code.

Most of these observations may suffer from an increased noise level. To enable post-processing programs to take special actions, AS-infected observations have been flagged in RINEX Version 2 using bit number 2 of the Loss of Lock Indicators (i.e. their current values are increased by 4). In RINEX Version 3, there are special attributes for the observation type to more precisely characterize the observable (codeless, semi-codeless, Z-tracking or similar techniques when AS on, L2C, P-code when AS off, Y-code tracking), making the AS flag obsolete.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0433

8. DEALING WITH DIFFERENT SATELLITE SYSTEMS

8.1 Time system identifier

GPS time runs, apart from small differences (<< 1 microsecond), parallel to UTC. But it is a continuous time scale, i.e. it does not insert any leap seconds. GPS time is usually expressed in GPS weeks and GPS seconds past 00:00:00 (midnight) Saturday/Sunday. GPS time started with week zero at 00:00:00 UTC (midnight) on January 6, 1980.

The GPS week is transmitted by the satellites as a 10 bit number. It has a roll-over after week 1023. The first roll-over happened on August 22, 1999, 00:00:00 GPS time.

In order to avoid ambiguities, the GPS week reported in the RINEX navigation message files is a continuous number without roll-over, i.e. …1023, 1024, 1025, …

We use GPS as time system identifier for the reported GPS time.

QZSS runs on QZSS time, which conforms to UTC Japan Standard Time Group (JSTG) time and the offset with respect to GPS time is controlled. The following properties apply to the QZSS time definition: the length of one second is defined with respect to International Atomic Time (TAI); QZSS time is aligned with GPS time (offset from TAI by integer seconds); the QZSS week number is defined with respect to the GPS week.

We use QZS as a time system identifier for the reported QZSS time

GLONASS is basically running on UTC (or, more precisely, GLONASS system time linked to UTC(SU)), i.e. the time tags are given in UTC and not GPS time. It is not a continuous time, i.e. it introduces the same leap seconds as UTC. The reported GLONASS time has the same hours as UTC and not UTC+3 h as the original GLONASS System Time!

We use GLO as time system identifier for the reported GLONASS time.

Galileo runs on Galileo System Time (GST), which is, apart from small differences (tens of nanoseconds), nearly identical to GPS time:

 The Galileo week starts at midnight Saturday/Sunday at the same second as the GPS week  The GST week as transmitted by the satellites is a 12 bit value with a roll-over after week
4095. The GST week started at zero at the first roll-over of the broadcast GPS week after 1023, i.e. at Sun, 22-Aug-1999 00:00:00 GPS time In order to remove possible misunderstandings and ambiguities, the Galileo week reported in the RINEX navigation message files is a continuous number without roll-over, i.e., …4095,4096,4097,… and it is aligned to the GPS week.

We use GAL as time system identifier for this reported Galileo time.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0434

The BDS Time (BDT) System is a continuous timekeeping system, with its length of second being st an SI second. BDT zero time started at 00:00:00 UTC on January 1, 2006 (GPS week 1356) therefore BDT is 14 seconds behind GPS time. BDT is synchronized with UTC within 100 nanoseconds (modulo 1 second).

 The BDT week starts at midnight Saturday/Sunday  The BDT week is transmitted by the satellites as a 13 bit number. It has a roll-over after week 8191. In order to avoid ambiguities, the BDT week reported in the RINEX navigation message files is a continuous number without roll-over, i.e. …8191, 8192, 8193, …

We use BDT as time system identifier for the reported BDS time.

IRNSS runs on Indian Regional Navigation Satellite System Time (IRNSST). The IRNSST ndst start epoch is 00:00:00 on Sunday August 22, 1999, which corresponds to August 21, 1999, 23:59:47 UTC (same time as the first GPS week roll over). Seconds of week are counted from 00:00:00 IRNSST hours Saturday/Sunday midnight which also corresponds to the start of the GPS week. Week numbers are consecutive from the start time and will roll over after week 1023 (at the same time as GPS and QZSS roll over).

We use IRN as the time system identifier for the reported IRNSS time.

ConstellationGPSGPSGPSGPSGPSGPS /Archival TimeEphemerisEphemerisEphemerisEphemerisEphemerisEphemeris RepresentationWeekWeekWeekWeekWeekWeek Period #1Period #2Period #3Period #4Period #5Period #6

GPS Broadcast 0 – 1023 0 – 1023 0 – 1023 0 – 1023 0 – 1023 0 – 1023 QZSS Broadcast 0 – 1023 0 – 1023 0 – 1023 0 – 1023 0 – 1023 IRNSS0 – 1023 0 – 1023 0 – 1023 0 – 1023 0 – 1023 Broadcast GST Broadcast 0 – 1023 1024 – 2047 2048 – 3071 3072 – 4095 0 – 1023 BDS Broadcast0(RINEX692 – 1715 1716 – 2739 2740 – 3763 3764 – 4787 and RINEXWeek 1356) – 691 GPS/QZS/IRN/0 – 1023 1024 – 2047 2048 – 3071 3072 – 4095 4096 – 5119 5120 -6143 GAL RINEX

Table 20: Relationship between GPS, QZSS, IRN, GST, GAL, BDS and RINEX Week Numbers

The header records TIME OF FIRST OBS and (if present) TIME OF LAST OBS in pure GPS, GLONASS, Galileo, QZSS or BDS observation files can (in mixed GPS/GLONASS/Galileo/QZSS/BDS/IRNSS observation files must) contain the time system identifier defining the system that all time tags in the file are referring to:

- GPS to identify GPS time
- GLO to identify the GLONASS UTC time system
- GAL to identify Galileo time

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0435

- QZS to identify QZSS time
- BDT to identify BDS time
- IRN to identify IRNSS time

Pure GPS observation files default to GPS, pure GLONASS files default to GLO, pure Galileo files default to GAL and similarly pure BDS observation files default to BDT (same for QZSS and IRNSS).

Apart from the small errors in the realizations of the different time systems, the relations between the systems are:

GLO = UTC = GPS - ΔtLS GPS = GAL = UTC + ΔtLS GPS = QZS = UTC + ΔtLS GPS = IRN = UTC + ΔtLS BDT = UTC + ΔtLSBDS

Table 21: Constellation Time Relationships Where: Delta time between GPS and UTC due to leap seconds, as transmitted by the GPS satellites in the almanac ΔtLS = (1999-01-01 - 2006-01-01: ΔtLS = 13, 2006-01-01 - 2009-01-01: ΔtLS = 14, 2009-01-01 - 2012-07-01: ΔtLS = 15, 2012-07-01 - 2015-07-01: ΔtLS = 16, 2015-07-01 - 2017-01-01: ΔtLS = 17 and 2017-01-01 - ????-??-??: ΔtLS = 18 ).

Delta time between BDT and UTC due to leap seconds, as transmitted by the BDS satellites in the almanac ΔtLSBDS = (2006-01-01 - 2009-01-01: ΔtLSBDS = 0, 2009-01-01 - 2012-07-01: ΔtLSBDS = 1, 2012-07-01 - 2015-07-01: ΔtLSBDS = 2, 2015-07-01 - 2017-00-01: ΔtLSBDS = 3 and 2017-01-01 - ????-??-??: ΔtLS = 4). See BDS-SIS-ICD- 2.0 Section 5.2.4.17 Table 22: GPS and BeiDou UTC Leap Second Relationship In order to have the current number of leap seconds available, we recommend including ΔtLS by adding a LEAP SECOND line into the RINEX file header.

If there are known non-integer biases between “GPS receiver clock”, “GLONASS receiver clock”, “BDS receiver clock” or “Galileo receiver clock” in the same receiver, they should be applied in the process of RINEX conversion. In this case, the respective code and phase observations have to be corrected also (c * bias if expressed in meters).

Unknown biases will have to be solved for during the post processing.

The small differences (modulo 1 second) between: BDS system time, Galileo system time,

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0436

GLONASS system time, UTC(SU), UTC(USNO) and GPS system time have to be dealt with during the post-processing and not before the RINEX conversion. It may also be necessary to solve for remaining differences during the post-processing.

8.2 Pseudorange definition The pseudorange (code) measurement is defined to be equivalent to the difference of the time of reception (expressed in the time frame of the receiver) and the time of transmission (expressed in the time frame of the satellite) of a distinct satellite signal.

In a mixed-mode GPS/GLONASS/Galileo/QZSS/BDS receiver referring all pseudorange observations to one receiver clock only,

 the raw GLONASS pseudoranges will show the current number of leap seconds between GPS/GAL/BDT time and GLONASS time if the receiver clock is running in the GPS, GAL or BDT time frame  the raw GPS, Galileo and BDS pseudoranges will show the negative number of leap seconds between GPS/GAL/BDT time and GLONASS time if the receiver clock is running in the GLONASS time frame In order to avoid misunderstandings and to keep the code observations within the format fields, the pseudo-ranges must be corrected in this case as follows:

PR_mod(GPS) = PR(GPS) + C* ΔtLS if generated with a receiver clock running in the GLONASS time frame PR_mod(GAL) = PR(GAL) + C* ΔtLS if generated with a receiver clock running in the GLONASS time frame

PR_mod(BDT) = PR(BDT) + C* ΔtLSBDS if generated with a receiver clock running in the GLONASS time frame

PR_mod(GLO) = PR(GLO) - C* ΔtLS if generated with a receiver clock running in the GPS or GAL time frame

PR_mod(GLO) = PR(GLO) - C*ΔtLSBDS if generated with a receiver clock running in the BDT time frame

PR_mod(GPS) = PR(GPS) + C*(ΔtLS-if generated with a receiver clock ΔtLSBDS)running in the BDT time frame

Table 23: Constellation Pseudorange Corrections

to remove the contributions of the leap seconds from the pseudoranges.

ΔtLS is the actual number of leap seconds between GPS/GAL and GLO time, as broadcast in the GPS almanac and distributed in Circular T of BIPM.

ΔtLSBDS is the actual number of leap seconds between BDT and UTC time, as broadcast in the BDT almanac.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0437

8.3 RINEX navigation message files The header section of the RINEX Version 3.XX navigation message files have been slightly changed compared to the previous Version 2. The format of the header section is identical for all satellite systems: GPS, GLONASS, Galileo, SBAS, QZSS and IRNSS. One exception is that BDS “IONOSPHERIC CORR” message has a few extra fields (See: Appendix Table A5).

The data portion of the navigation message files contains records with floating point numbers. The format is identical for all satellite systems; the number of records per message and the contents, however, are satellite system-dependent. The format of the version 3 data records has been changed slightly; the satellite codes now also contain the satellite system identifier.

It is possible to generate mixed navigation message files, i.e. files containing navigation messages of more than one satellite system. Header records with system-dependent contents have to be repeated for each satellite system, if applicable. Using the satellite system identifier of the satellite code, the reading program can determine the number of data records to be read for each message block.

The time tags of the navigation messages (e.g., time of ephemeris, time of clock) are given in the respective satellite time systems!

It is recommended to avoid storing redundant navigation messages (e.g., the same message broadcast at different times) in the RINEX file.

8.3.1 RINEX navigation message files for GLONASS The header section and the first data record (epoch, satellite clock information) are equal to the GPS navigation file. The following three records contain the satellite position, velocity and acceleration, the clock and frequency biases, as well as auxiliary information such as health, satellite frequency (channel) and age of the information.

The corrections of the satellite time to UTC are as follows:

GPS: Tutc = Tsv –af0 –af1 *(Tsv-Toc) -... –A0 -... –ΔtLS GLONASS: Tutc = Tsv + TauN –GammaN*(Tsv-Tb) + TauC

In order to use the same sign conventions for the GLONASS cor- rections as in the GPS navigation files, the broadcast GLONASS values are stored as: -TauN, +GammaN, -TauC.

Table 24: GLONASS Navigation File Data, Sign Convention

The time tags in the GLONASS navigation files are given in UTC (i.e. not Moscow time or GPS time).

8.3.2 RINEX navigation message files for Galileo The Galileo Open Service allows access to two navigation message types: F/NAV (Freely Accessible Navigation) and I/NAV (Integrity Navigation). The content of the two messages differs in various items, however, in general it is very similar to the content of the GPS navigation message,

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0438

e.g. the orbit parameterization is the same.

There are items in the navigation message that depend on the origin of the message (F/NAV or I/NAV): The SV clock parameters actually define the satellite clock for the dual-frequency ionosphere-free linear combination. F/NAV reports the clock parameters valid for the E5a-E1 combination, the I/NAV reports the parameters for the E5b-E1 combination. The second parameter in the Broadcast Orbit 5 record (bits 8 and 9) indicates the frequency pair the stored clock corrections are valid for.

Some parameters contain the information stored bitwise. The interpretation is as follows:

 Convert the floating point number read from the RINEX file into the nearest integer  Extract the values of the requested bits from the integer

Example:

0.170000000000D+02 -> 17 = 2+2-> Bits 4 and 0 are set, all others are zero

RINEX file encoders should encode one RINEX Galileo navigation message for each I/NAV and F/NAV signal decoded. Therefore if both: I/Nav and F/Nav messages are decoded, then the relevant bit fields must be set in the RINEX message and both should be written in separate messages. The Galileo ICD (2010) Section 5.1.9.2 indicates that some of the contents of the broadcast navigation message may change, yet the issue of data (IOD) may not change. To ensure that all relevant information is available message encoders should monitor the contents of the file and write new navigation messages when the contents have changed.

RINEX file parsers should expect to encounter F/NAV and I/NAV messages with the same IOD in the same file. Additionally, parsers should also expect to encounter more than one F/NAV or I/NAV ephemeris message with the same IOD, as the navigation message Data Validity Status (DVS) and other parameters may change independently of the IOD, yet some other data may be the same, however, the transmission time will be updated (See Note in Galileo ICD (2010) Section 5.1.9.2 Issue of Data).

As mentioned above, the GAL week in the RINEX navigation message files is a continuous number; it has been aligned to the GPS week by the program creating the RINEX file.

8.3.3 RINEX navigation message files for GEO satellites As the GEO broadcast orbit format differs from the GPS message, a special GEO navigation message file format has been defined, which is nearly identical with the GLONASS navigation message file format.

The header section contains information about the generating program, comments, and the difference between the GEO system time and UTC.

The first data record contains the epoch and satellite clock information; the following records

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0439

contain the satellite position, velocity and acceleration and auxiliary information (health, URA and IODN).

The time tags in the GEO navigation files are given in the GPS time frame, i.e. not UTC.

The corrections of the satellite time to UTC are as follows:

GEO: Tutc = Tsv –aGf0 –aGf1 *(Tsv-Toe) –W0 –ΔtLS

W0 being the correction to transform the GEO system time to UTC. See Toe, aGf0, aGf1 in the Appendix Table A16 format definition table.

The Transmission Time of Message (SV / EPOCH / SV CLK header record) is expressed in GPS seconds of the week. It marks the beginning of the message transmission. It has to refer to the same GPS week as the Epoch of Ephemerides. If necessary, the Transmission Time of Message may have to be adjusted by - or + 604800 seconds (which would make it lower than zero or larger than 604800, respectively and then further corrected to correspond to the Epoch of Ephemeris) so that it is referenced to the GPS week of the Epoch of Ephemeris. This is a redefinition of the Version 2.10 Message frame time.

Health shall be defined as follows:

 bits 0 to 3 equal to health in Message Type 17 (MT17)  bit 4 is set to 1 if MT17 health is unavailable  bit 5 is set to 1 if the URA index is equal to 15

8.3.4 RINEX navigation message files for BDS

The BDS Open Service broadcast navigation message is similar in content to the GPS navigation message.

The header section and the first data record (epoch, satellite clock information) are equal to the GPS navigation file. The following six records are similar to GPS.

The BDT week number is a continuous number. The broadcast 13-bit BDS System Time week has a roll-over after 8191. It starts at zero on: 1-Jan-2006, hence BDT week = BDT week_BRD
+ (n*8192) (Where n: number of BDT roll-overs). See Appendix Table A14 for details.

8.3.5 RINEX navigation message files for IRNSS

The IRNSS Open Service broadcast navigation message is similar in content to the GPS navigation message.

The header section and the first data record (epoch, satellite clock information) are equal to the GPS navigation file. See Appendix Tables A18 and A19 for a description and example of each field.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0440

8.4 RINEX observation files for GEO satellites A separate satellite system identifier has been defined for the Satellite-Based Augmentation System (SBAS) payloads. S, is to be used in the RINEX VERSION / TYPE header line and in the satellite identifier snn, nn being the GEO PRN number minus 100.

e.g.: PRN = 120 ⇒snn = S20

In mixed dual frequency GPS satellite / single frequency GEO payload observation files, the fields for the second frequency observations of SBAS satellites remain blank, are set to zero values or (if last in the record) can be truncated.

The time system identifier of GEO satellites generating GPS signals defaults to GPS time. In the SBAS message definitions, bit 3 of the health word is currently marked as reserved. In case of bit 4 set to 1, it is recommended to set bits 0,1,2,3 to 1, as well.

User Range Accuracy (URA):

The same convention for converting the URA index to meters is used as with GPS. Set URA = 32767 meters if URA index = 15.

Issue Of Data Navigation (IODN)

The IODN is defined as the 8 first bits after the message type 9, called IODN in RTCA DO229, Annex A and Annex B and called spare in Annex C. The D-UTC A0, A1, T, W, S, U record in Version 2.11 has been renamed the TIME SYSTEM CORR record in RINEX 3.x.

9. MODIFICATIONS FOR VERSION 3.01, 3.02, 3.03 and 3.04

9.1 Phase Cycle Shifts

Carrier phases tracked on different signal channels or modulation bands of the same frequency may differ in phase by 1/4 (e.g., GPS: P/Y-code-derived L2 phase vs. L2C-based phase) or, in some exceptional cases, by other fractional parts of a cycle. Appendix Table A23 specifies the reference signal and the phase shifts that are specified by the Interface Control Documentation (ICD) for each constellation. All phase observations must be aligned in RINEX 3.01 and later files and the new SYS / PHASE SHIFT header is mandatory. See Appendix Table A2 for the messages definition. If the phase alignment is not known, then the observation data should not be published in a

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0441

RINEX 3.0x file. In order to facilitate data processing, phase observations stored in RINEX files must be consistent across all satellites of a satellite system and across each frequency band. Within a RINEX 3.0x file:  All phase observations must be aligned to the designated constellation and frequency reference signal as specified in Appendix Table A23, either directly by the receiver or by a correction program or the RINEX conversion program, prior to RINEX file generation. Additionally, all data must be aligned with the appropriate reference signal indicated in Appendix Table A23 even when the receiver or reporting device is not tracking and/or providing data from that reference signal e.g. Galileo L5X phase data must be aligned to L5I.  Phase corrections must be reported in a new mandatory SYS / PHASE SHIFT header record to allow the reconstruction of the original values, if needed. The uncorrected reference signal group of observations are left blank in the SYS / PHASE SHIFT records. Appendix Table A23 specifies the reference signal that should be used by each constellation and frequency band. Additionally, Appendix Table A23 indicates the relationship between the phase observations for each frequency’s signals. Concerning the mandatory SYS / PHASE SHIFT header records:  If the SYS / PHASE SHIFT record values are set to zero in the RINEX file, then either the raw data provided by the receiver or the data format (RTCM-Multiple Signal Messages format for example) have already been aligned and the RINEX conversion program did not apply any phase corrections since they had already been applied. In this case, Appendix Table A23 can be used to determine the fractional cycles that had been added to each signal’s phase observation to align the phase observations to the reference signal.  If the file does not contain any observation pairs affected by phase shifts (i.e. only reference signals reported), then the observation code field is defined and the rest of the SYS / PHASE SHIFT header record field of the respective satellite system(s) are left blank.  If the reported phase correction of an observation type does not affect all satellites of the same system, then the header record allows for the affected satellites to be indicated.  If the applied phase corrections or the phase alignment is unknown, then the observation code field and the rest of the SYS / PHASE SHIFT header record field of the respective satellite system(s) are left blank. This use case is intended for exceptional situations where the data is intended for special projects and analysis.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0442

Sign of the correction Δφ:

φRINEX = φ original + Δφ

φ original : Uncorrected or corrected, i.e. as issued by the GNSS receiver or in a standardized data stream such as RTCM-MSM Δφ : Phase correction to align the phase to other phases of the same frequency but different channel / modulation band

Table 25: RINEX Phase Alignment Correction Convention

Example (Definition see Appendix Table A2): ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| G L2S -0.25000 03 G15 G16 G17 SYS / PHASE SHIFT Table 26: Example SYS / PHASE SHIFT Record

9.2 Galileo: BOC-Tracking of an MBOC-Modulated Signal Galileo E1 will be modulated by the so-called MBOC modulation. Obviously it is possible for a receiver to track the signal also in a BOC mode, though leading to different noise characteristics. In order to keep this non-standard tracking mode of a MBOC signal apart, bit 2 of the loss-of- lock indicator LLI (the antispoofing flag not used for Galileo) in the observation data records is used.

Non-standard BOC tracking of an MBOC-modulated signal: Increase the LLI by 4.

Note: This flag is intended for experimental applications and is optional. In future releases of RINEX, this non-standard tracking mode flag may be removed.

Example: Satellite E11, BOC tracking on L1C, LLI = 4: ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| G 5 C1C L1W L2W C1W S2W SYS / # / OBS TYPES R 2 C1C L1C SYS / # / OBS TYPES E 2 L1C L5I SYS / # / OBS TYPES S 2 C1C L1C SYS / # / OBS TYPES 18.000 INTERVAL END OF HEADER > 2006 03 24 13 10 36.0000000 0 5 -0.123456789012 G06 23629347.915 .300 8 -.353 4 23629347.158 24.158 G09 20891534.648 -.120 9 -.358 6 20891545.292 38.123 G12 20607600.189 -.430 9 .394 5 20607600.848 35.234 E11 .32448 .178 7 S20 38137559.506 335849.135 9

Table 27: Example of RINEX Coding of Galileo BOC Tracking of an MBOC Signal Record

9.3 BDS Satellite System Code The satellite system code for BeiDou navigation satellite System (BDS) has been defined as “C”, see Figure 1.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0443

9.4 New Observation Codes for GPS L1C and BDS New observation codes for GPS L1C and BDS observables have been defined: See Tables 4 and 9.

9.5 Header Records for GLONASS Slot and Frequency Numbers In order to make available a cross-reference list between the GLONASS slot numbers used in the RINEX files to designate the GLONASS satellites and the allotted frequency numbers, a mandatory observation file header record is assigned. This allows processing of GLONASS files without having to get this information from GLONASS navigation message files or other sources.

Example (Definition See Appendix Table A2): ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| 18 R01 1 R02 2 R03 3 R04 4 R05 5 R06 -6 R07 -5 R08 -4 GLONASS SLOT / FRQ # R09 -3 R10 -2 R11 -1 R12 0 R13 1 R14 2 R15 3 R16 4 GLONASS SLOT / FRQ # R17 5 R18 -5 GLONASS SLOT / FRQ # Table 28: Example of a GLONASS Slot- Frequency Records

9.6 GNSS Navigation Message File: Leap Seconds Record The optional LEAP SECONDS record was modified to also include ΔtLS (or ΔtLSBDS for BDS), WNLSF (adjusted to continuous week number) and DN.

9.7 Clarifications in the Galileo Navigation Message File: Some clarifications in the Galileo BROADCAST ORBIT – 5 and BROADCAST ORBIT – 6 records were added (see Table A8).

9.8 Quasi-Zenith Satellite System (QZSS) RINEX Version 3.02 The version number is adjusted to 3.02. Version 3.02 added QZSS: specifications, parameters and definitions to the document. Each QZSS satellite broadcasts signals using two PRN codes. The GPS compatible signals are broadcast using PRN codes in the range of 193-197. In a RINEX observation file the PRN code is: broadcast prn - 192, yielding: J01, J02 etc In a RINEX SBAS file the PRN code is: broadcast prn - 100, yielding: S83, S84 etc.

See Appendix Table A23 to convert each signal’s aligned phase observations back to raw satellite phase.

9.9 GLONASS Mandatory Code-Phase Alignment Header Record Recent analysis has revealed that some GNSS receivers produce biased GLONASS observations. The code-phase bias results in the code and phase observations not being measured at the same time. To remedy this problem, a mandatory GLONASS Code-Phase header bias record is required. Although this header message is mandatory, it can contain zeros if the GLONASS data issued by the receiver is aligned. See the GLONASS CODE/PHASE BIAS (GLONASS COD/PHS/BIS) definition in Appendix Table A2. The GLONASS code-phase alignment message contains: L1C, L1P, L2C and L2P corrections. Phase data from GNSS receivers that issue biased data must be corrected by the amount specified in the GLONASS COD/PHS/BIS record before it is written in RINEX format.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0444

To align the non-aligned L1C phase to the pseudo range observation, the following correction is required: AlignedL1Cphase = ObservedL1Cphase + (GLONASSC1C_CodePhaseBias_M / Lambda) where:  AlignedL1C phase in cycles (written to RINEX file)  ObservedL1C phase in cycles  GLONASSC1C_CodePhaseBias_M is in metres  Lamba is the wavelength for the particular GLONASS frequency

GLONASS L1P, L2C and L2P are handled in the same manner.

Example (See Appendix Table A2 for details):

----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| C1C -10.000 C1P -10.123 C2C -10.432 C2P -10.634 GLONASS COD/PHS/BIS

Table 29: Example of GLONASS Code Phase Bias Correction Record

Note: If the GLONASS code phase alignment is unknown, then all fields within GLONASS COD/PHS/BIS header record are left blank (see example below). This use case is intended for exceptional situations where the data is intended for special projects and analysis.

----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| GLONASS COD/PHS/BIS

Table 30: Example of Unknown GLONASS Code Phase Bias Record

9.10 BDS system (Replaces Compass) Added BDS: naming convention, time system definition, header section description, and parameters throughout the document. Updated: Sections: 8.1, 8.2, 8.3.5, 9.11 and Appendix Table A2, added ephemeris Table A14 and updated Table A23.

9.11 Indian Regional Navigation Satellite System (IRNSS) Version 3.03

The RINEX version number was changed to 3.03. Version 3.03 adds IRNSS, specifications, parameters and definitions to this document.

9.12 Updates for Quasi-Zenith Satellite System (QZSS), BeiDou and GLONASS (CDMA) RINEX Version 3.04

Added new signal codes to: Table #5, for GLONASS, Table #8 for QZSS and Table #9 for BeiDou

The phase alignment of L1C has changed in QZSS Block II satellites to maintain compatibility

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0445

with GPS Block III. See Appendix Table A23 and related notes to convert each signal’s aligned phase observations back to raw satellite phase.

RINEXStandard PNTSub-meter LevelCentimeter LevelPositioning Signal IDSignals andAugmentationAugmentation forTechnology CentimeterExperiments (L6E)Verification (L1-SAIF/L1S) LevelService (L5S) (PRN-202) Augmentation (PRN-182) (PRN Code) (LEX/L6D)

(PRN-192)

J01 193 183

J02 194 184 204 196

J03 195 185 205 200

J04 196 186 206

J05 197 187 207

J06 198 188 208

J07 199 189 209 197

J08 200 190 210

J09 201 191 211

Table 31: QZSS PRN to RINEX Satellite Identifier

In RINEX 3.04 all QZSS signals are identified the using the standard PRN numbering conventions i.e. Jxx and the Sxx identifier has been dropped. All QZSS signals are identified in RINEX 3.04 as J01-J09 as shown in Table 31.

QZSS Block I satellites have replaced the L1-SAIF signal with the L1S signal. For QZSS Block I observations prior to the introduction of the L1S signal, the observation codes "1Z" refer to tracking of the "L1-SAIF" signal. Similarly, the "6S", "6L", "6X" observation codes refer to tracking of the LEX data channel, LEX pilot channel, and combined LEX pilot+data tracking prior to the introduction of the L61 signal on QZSS Block I.

QZSS Block II satellites broadcast the L1S signal. The L1S signal broadcasts the Sub-Meter- Level Augmentation Service (SLAS) correction data using PRN 183-191. In a RINEX observation file the signal ID of L1S is: broadcast prn-182, yielding J01, J02….J09. QZSS Block II satellites also broadcast the L5S signal. The L5S signals broadcasts the Positioning Technology Verification Service (PTVS) correction data using PRN, 196, 200, 197. PTVS

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0446

broadcasts the experimental Dual Frequency Multi-Constellation (DFMC) signal. In a RINEX observation file the signal ID of L5S is PRN 196, 200, 197and is assigned to J02, J03 and J07 respectively.

The second data channel L6E was introduced on the L6 signal of QZSS Block II. In a RINEX observation file the RINEX signal ID of L6E is: broadcast prn-202, yielding J02, J03…J09.

Updated Tables 5, 8 and 9 and A23 signals codes and information to support new GLONASS CDMA, QZSS and BeiDou 3 signals.

Updated Appendix table A5 TIME SYSTEM CORR message description.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0447

10 References

Evans, A. (1989): “Summary of the Workshop on GPS Exchange Formats.” Proceedings of the Fifth International Geodetic Symposium on Satellite Systems, pp. 917ff, Las Cruces.

Gurtner, W., G. Mader, D. Arthur (1989): “A Common Exchange Format for GPS Data.” CSTG GPS Bulletin Vol.2 No.3, May/June 1989, National Geodetic Survey, Rockville.

Gurtner, W., G. Mader (1990a): “The RINEX Format: Current Status, Future Developments.” Proceedings of the Second International Symposium of Precise Positioning with the Global Positioning system, pp. 977ff, Ottawa.

Gurtner, W., G. Mader (1990b): “Receiver Independent Exchange Format Version 2.” CSTG GPS Bulletin Vol.3 No.3, Sept/Oct 1990, National Geodetic Survey, Rockville.

Gurtner, W. (1994): “RINEX: The Receiver-Independent Exchange Format.” GPS World, Volume 5, Number 7, July 1994.

Gurtner, W. (2002): “RINEX: The Receiver Independent Exchange Format Version 2.10”. ftp://igs.org/pub/data/format/rinex210.txt

Gurtner, W., L. Estey (2002),: “RINEX Version 2.20 Modifications to Accommodate Low Earth Orbiter Data”. ftp://ftp.aiub.unibe.ch/rinex/rnx_leo.txt

Gurtner, W., L. Estey (2005): “RINEX: The Receiver Independent Exchange Format Version 2.11”. ftp://igs.org/pub/data/format/rinex211.txt

Gurtner, W., L. Estey (2007): “RINEX: The Receiver Independent Exchange Format Version 3.00”. ftp://igs.org/pub/data/format/rinex300.pdf

Hatanaka, Y (2008): “ A Compression Format and Tools for GNSS Observation Data”. Bulletin of the Geographical Survey Institute, Vol. 55, pp 21-30, Tsukuba, March 2008. http://www.gsi.go.jp/ENGLISH/Bulletin55.html

Ray, J., W. Gurtner (2010): “RINEX Extensions to Handle Clock Information”. ftp://igs.org/pub/data/format/rinex_clock302.txt.

Ray, J. (2005): “Final update for P1-C1 bias values & cc2noncc”. IGSMail 5260

Rothacher, M., R. Schmid (2010): “ANTEX: The Antenna Exchange Format Version 1.4”. ftp://igs.org/pub/station/general/antex14.txt.

Schaer, S., W. Gurtner, J. Feltens (1998): “IONEX: The Ionosphere Map Exchange Format Version 1“. ftp://igs.org/pub/data/format/ionex1.pdf

Suard, N., W. Gurtner, L. Estey (2004): “Proposal for a new RINEX-type Exchange File for GEO SBAS Broadcast Data”. ftp://igs.org/pub/data/format/geo_sbas.txt

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0448

Document: RTCA DO 229, Appendix A

Document: Global Positioning Systems Directorate, Systems Engineering and Integration Interface Specification IS-GPS-200H, Navstar GPS Space Segment/Navigation User Interfaces, Sept. 24, 2013

Document: GLObal NAvigation Satellite System (GLONASS), Interface Control Document, (Edition 5.1), 2008.

Document: Global Navigation Satellite System GLONASS, Interface Control Document, General Description of Code Division Multiple Access Signal System, Edition 1.0, 2016.

Document: Global Navigation Satellite System GLONASS, Interface Control Document, Code Division Multiple Access, Open Service Navigation Signal in L1 frequency band, Edition 1.0, 2016.

Document: Global Navigation Satellite System GLONASS, Interface Control Document, Code Division Multiple Access, Open Service Navigation Signal in L2 frequency band, Edition 1.0, 2016.

Document: Global Navigation Satellite System GLONASS, Interface Control Document, Code Division Multiple Access, Open Service Navigation Signal in L3 frequency band, Edition 1.0, 2016.

Document: European GNSS (Galileo) Open Service, Signal In Space, Interface Control Document, Issue 1.3, December, 2016. : (https://www.gsc-europa.eu/system/files/galileo_documents/Galileo-OS-SIS- ICD.pdf)

Document: Quasi-Zenith Satellite System, Interface Specification, Satellite Positioning, Navigation and Timing Service (IS-QZSS-PNT-002), Cabinet Office, January 29, 2018

Document: Quasi-Zenith Satellite System, Interface Specification, Sub-meter Level Augmentation Service (IS-QZSS-L1S-002), Cabinet Office, April 13, 2018

Document: Quasi-Zenith Satellite System, Interface Specification, Centimeter Level Augmentation Service (IS-QZSS-L6-001) Draft, Cabinet Office, August 31, 2018

Document: Quasi-Zenith Satellite System, Interface Specification, Positioning Technology Verification Service (IS-QZSS-TV), Draft Edition, Cabinet Office, July 12, 2016

Document: Quasi-Zenith Satellite System, Interface Specification, Positioning Technology Verification Service (IS-QZSS-TV-001), Cabinet Office, April 13, 2018

Document: BeiDou Navigation Satellite, System, Signal In Space, Interface Control Document, Open Service Signal, (Version2.0), China Satellite Navigation Office December 2013

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.0449

Document: BeiDou Navigation Satellite, System, Signal In Space, Interface Control Document, Open Service Signal B1C, (Version 1.0), China Satellite Navigation Office, December 2017

Document: BeiDou Navigation Satellite, System, Signal in Space, Interface Control Document, Open Service Signal B2a, (Version 1.0), China Satellite Navigation Office, December 2017

Document: BeiDou Navigation Satellite, System, Signal in Space, Interface Control Document, Open Service Signal B2I, (Version 1.0), China Satellite Navigation Office. February 2017

Document: RTCM Standard 10403.2, Differential GNSS (Global Navigation Satellite Systems) Services – Version 3, November 7, 2013.

Document: Indian Regional Navigation Satellite System Signal in Space ICD for Standard Positioning Service, Version 1.0, June 2014 (Indian Space Research Organization, Bangalore, 2014)

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A1

APPENDIX: RINEX FORMAT DEFINITIONS AND EXAMPLES

A 1 RINEX File name description

Table A1 RINEX File name description Field Field Description Example Required Comment/Example <SITE/XXXXMRCCCALGO00CAN Yes File name supports a maximum STATION-Where:of 10 monuments at the same MONUMENT/XXXX - existingstation and a maximum of 10 RECEIVER/IGS station namereceivers per monument. COUNTRY/M – monument or marker number (0-9)Country codes follow : ISO R – receiver number3166-1 alpha-3 (0-9) CCC – ISO Country code (Total 9 characters) <DATA SOURCE> Data SourceR Yes This field is used to indicate how R – From Receiverthe data was collected either data using vendor orfrom the receiver at the station or other softwarefrom a data stream S – From data Stream (RTCM or other) U – Unknown (1 character) <START TIME> YYYYDDDHHMM2012150Yes For GPS files use : GPS Year, YYYY – Gregorian1200day of year, hour of day, minute year 4 digits,of day (see text below for DDD – day of Year,details) HHMM – hours andStart time should be the nominal minutes of daystart time of the first observation. GLONASS, Galileo, BeiDou etc (11 characters)use respective time system. <FILE PERIOD> DDU15M Yes File Period DD – file period15M–15 Minutes U – units of file01H–1 Hour period.01D–1 Day File period is used to01Y–1 Year specify intended00U-Unspecified collection period of the file. (3 characters)

RINEX3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A2

Table A1 RINEX File name description Field Field Description Example Required Comment/Example <DATA FREQ> DDU05Z MandatoryXXC – 100 Hertz for RINEXXXZ – HertZ, DD – data frequencyObs. Data.XXS – Seconds, U – units of data rateNOTXXM – Minutes, (3 characters)requiredXXH – Hours, forXXD – Days NavigationXXU – Unspecified Files. <DATA TYPE > DDMO Yes Two characters represent the DD – Data typedata type: GO - GPS Obs., (2 characters)RO - GLONASS Obs., EO - Galileo Obs. JO - QZSS Obs. CO - BDS Obs. IO – IRNSS Obs. SO - SBAS Obs. MO Mixed Obs. GN - Nav. GPS, RN- GLONASS Nav., EN- Galileo Nav., JN- QZSS Nav., CN- BDS Nav. IN – IRNSS Nav. SN- SBAS Nav. MN- Nav. All GNSS Constellations) MM-Meteorological Observation Etc <FORMAT> FFFrnx Yes Three character indicating the FFF – File formatdata format : RINEX - rnx, (3 characters)Hatanaka Compressed RINEX – crx, ETC

<COMPRESSION> (2-3 Characters) gz No gz Sub Total 34 or 35 Fields Separators (7 characters –Obs._ underscore between all fields File)and “.” Between data type and (6 characters –Eph.file format and the compression File)method

Total 41-42(Obs. File)Mandatory IGS RINEX obs. 37-38 (Eph. File)Characters

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A3

Filename Details and Examples:

<STATION/PROJECT NAME>: IGS users should follow XXXXMRCCC (9 char) site and station naming convention described above.

GNSS industry users could use the 9 characters to indicate the project name and/or number.

<DATA SOURCE>: With real-time data streaming RINEX files for the same station can be created at many locations. If the RINEX file is derived from data collected at the receiver (official file) then the source is specified as R. On the other hand if the RINEX file is derived from a real-time data stream then the data source is marked as S to indicate Streamed data source. If the data source is unknown the source is marked as U.

<START TIME>: The start time is the file start time which should coincide with the first observation in the file. GPS file start time is specified in GPS Time. Mixed observation file start times are defined in the same time system as the file observation time system specified in the header. Files containing only: GLONASS, Galileo, QZSS, BDS or SBAS observations are all based on their respective time system.

<FILE PERIOD>: Is used to specify the data collection period of the file.

GNSS observation file name - file period examples:

ALGO00CAN_R_20121601000_15M_01S_GO.rnx.gz //15 min, GPS Obs. 1 sec. ALGO00CAN_R_20121601000_01H_05Z_MO.rnx.gz //1 hour, Obs Mixed and 5Hz ALGO00CAN_R_20121601000_01D_30S_GO.rnx.gz //1 day, Obs GPS and 30 sec ALGO00CAN_R_20121601000_01D_30S_MO.rnx.gz //1 day, Obs. Mixed, 30 sec

GNSS navigation file name - file period examples:

ALGO00CAN_R_20121600000_15M_GN.rnx.gz // 15 minute GPS only ALGO00CAN_R_20121600000_01H_GN.rnx.gz // 1 hour GPS only ALGO00CAN_R_20121600000_01D_MN.rnx.gz // 1 day mixed

<DATA FREQ>: Used to distinguish between observation files that cover the same period but contain data at a different sampling rate. GNSS data file - observation frequency examples:

ALGO00CAN_R_20121601000_01D_01C_GO.rnx.gz //100 Hz data rate

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A4

ALGO00CAN_R_20121601000_01D_05Z_RO.rnx.gz //5 Hz data rate ALGO00CAN_R_20121601000_01D_01S_EO.rnx.gz //1 second data rate ALGO00CAN_R_20121601000_01D_05M_JO.rnx.gz //5 minute data rate ALGO00CAN_R_20121601000_01D_01H_CO.rnx.gz //1 hour data rate ALGO00CAN_R_20121601000_01D_01D_SO.rnx.gz //1 day data rate ALGO00CAN_R_20121601000_01D_00U_MO.rnx.gz //Unspecified

Note : Data frequency field not required for RINEX Navigation files.

< DATA TYPE/ FORMAT/>: The data type describes the content of the file. The first character indicates constellation and the second indicates whether the files contains observations or navigation data. The next three characters indicate the data file format. GNSS observation filename - format/data type examples:

ALGO00CAN_R_20121601000_15M_01S_GO.rnx.gz //RINEX obs. GPS ALGO00CAN_R_20121601000_15M_01S_RO.rnx.gz //RINEX obs. GLONASS ALGO00CAN_R_20121601000_15M_01S_EO.rnx.gz //RINEX obs. Galileo ALGO00CAN_R_20121601000_15M_01S_JO.rnx.gz //RINEX obs. QZSS ALGO00CAN_R_20121601000_15M_01S_CO.rnx.gz //RINEX obs. BDS ALGO00CAN_R_20121601000_15M_01S_SO.rnx.gz //RINEX obs. SBAS ALGO00CAN_R_20121601000_15M_01S_MO.rnx.gz //RINEX obs. mixed

GNSS navigation filename examples:

ALGO00CAN_R_20121600000_01H_GN.rnx.gz //RINEX nav. GPS ALGO00CAN_R_20121600000_01H_RN.rnx.gz //RINEX nav. GLONASS ALGO00CAN_R_20121600000_01H_EN.rnx.gz //RINEX nav. Galileo ALGO00CAN_R_20121600000_01H_JN.rnx.gz //RINEX nav. QZSS ALGO00CAN_R_20121600000_01H_CN.rnx.gz //RINEX nav. BDS ALGO00CAN_R_20121600000_01H_SN.rnx.gz //RINEX nav. SBAS ALGO00CAN_R_20121600000_01H_MN.rnx.gz //RINEX nav. mixed

Meteorological filename example:

ALGO00CAN_R_20121600000_01D_30M_MM.rnx.gz //RINEX Met.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A5

<COMPRESSION>:

Valid compression methods include: gzip - “.gz”, bzip2 - “.bz2” and “.zip”.

Note: The main body of the file name should contain only ASCII capital letters and numbers. The file extension .rnx.gz should be lowercase.

A 2 GNSS Observation Data File -Header Section Description TABLE A2 GNSS OBSERVATION DATA FILE - HEADER SECTION DESCRIPTION HEADER LABELDESCRIPTION FORMA (Columns 61-80)T RINEX VERSION / TYPE Formatversion :3.04F9.2,11X,  File type: O for Observation DataA1,19X,  Satellite System:A1,19X G: GPS R: GLONASS E: Galileo J: QZSS C: BDS I: IRNSS S: SBAS payload M: Mixed PGM / RUN BY / DATE Nameof program creating current fileA20,  Name of agency creating current fileA20,  Date and time of file creationA20 Format: yyyymmdd hhmmss zone zone: 3-4 char. code for time zone. 'UTC ' recommended! 'LCL ' if local time with unknown local time system code
* COMMENT Commentline(s)A60 MARKER NAME Nameof antenna markerA60
* MARKER NUMBER Numberof antenna markerA20 MARKER TYPE Typeof the marker:A20,40X GEODETIC : Earth-fixed, high- precision monument NON_GEODETIC : Earth-fixed, low- precision monument NON_PHYSICAL : Generated from network processing SPACEBORNE : Orbiting space vehicle GROUND_CRAFT : Mobile terrestrial vehicle WATER_CRAFT : Mobile water craft AIRBORNE: Aircraft, balloon, etc. FIXED_BUOY : "Fixed" on water surface

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A6

TABLE A2 GNSS OBSERVATION DATA FILE - HEADER SECTION DESCRIPTION FLOATING_BUOY: Floating on water surface FLOATING_ICE : Floating ice sheet, etc. GLACIER : "Fixed" on a glacier BALLISTIC : Rockets, shells, etc ANIMAL : Animal carrying a receiver HUMAN : Human being Record required except for GEODETIC and NON_GEODETIC marker types. Users may define other project-dependent keywords. OBSERVER / AGENCY Nameof observer / agencyA20,A40 REC # / TYPE / VERS Receivernumber, type, and version(Version:3A20 e.g. Internal Software Version) ANT # / TYPE Antennanumber and type2A20 APPROX POSITION XYZ Geocentricapproximate marker position (Units:3F14.4 Meters, System: ITRS recommended) Optional for moving platforms ANTENNA: DELTA H/E/N Antennaheight: Height of the antenna referenceF14.4, point (ARP) above the marker  Horizontal eccentricity of ARP relative to the2F14.4 marker (east/north) All units in meters
* ANTENNA: DELTA X/Y/Z -Positionof antenna reference point for antenna3F14.4 on vehicle (m): XYZ vector in body-fixed coordinate system *ANTENNA:PHASECENTER Averagephase centerposition with respectto antenna reference point (m)  Satellite system (G/R/E/J/C/I/S)A1,  Observation code1X,A3,  North/East/Up (fixed station) orF9.4, 2F14.4  X/Y/Z in body-fixed system (vehicle)
* ANTENNA: B.SIGHT XYZ Directionof the “vertical” antenna axis towards3F14.4 the GNSS satellites. Antenna on vehicle: Unit vector in body-fixed coordinate system. Tilted antenna on fixed station: Unit vector in N/E/Up left-handed system.
* ANTENNA: ZERODIR AZI Azimuthof the zero-direction of a fixed antennaF14.4 (degrees, from north)
* ANTENNA: ZERODIR XYZ Zero-directionof antenna3F14.4 Antenna on vehicle: Unit vector in body-fixed coordinate system Tilted antenna on fixed station: Unit vector in N/E/Up left-handed system

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A7

TABLE A2 GNSS OBSERVATION DATA FILE - HEADER SECTION DESCRIPTION
* CENTER OF MASS: XYZ Currentcenter of mass (X,Y,Z, meters) of3F14.4 vehicle in body-fixed coordinate system. Same system as used for attitude.

SYS / # / OBS TYPES Satellitesystem code(G/R/E/J/C/I/S)A1,  Number of different observation types for the2X,I3, specified satellite system Observation descriptors: Type, Band, Attribute13(1X,A3  Use continuation line(s) for more than 13) observation descriptors. In mixed files: Repeat for each satellite system. These records should precede any SYS / SCALE FACTOR records (see below).6X, The following observation descriptors are defined in13(1X,A3 RINEX Version 3.XX:) Type: C = Code / Pseudorange L = Phase D = Doppler S = Raw signal strength(carrier to noise ratio) I = Ionosphere phase delay X = Receiver channel numbers Band: 1 = L1 (GPS, QZSS, SBAS,BDS) G1 (GLO) E1 (GAL) B1 (BDS) 2 = L2 (GPS, QZSS) G2 (GLO) B1-2 (BDS) 4 = G1a (GLO) 5 = L5 (GPS, QZSS, SBAS, IRNSS) E5a (GAL) B2/B2a (BDS) 6 = E6 (GAL) L6 (QZSS) B3 (BDS) G2a (GLO) 7 = E5b (GAL) B2/B2b (BDS) 8 = E5a+b (GAL) B2a+b (BDS)

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A8

TABLE A2 GNSS OBSERVATION DATA FILE - HEADER SECTION DESCRIPTION 9 = S (IRNSS) 0 for type X (all)

Attribute: A = A channel (GAL, IRNSS, GLO) B = B channel (GAL, IRNSS, GLO) C = C channel (GAL, IRNSS) C code-based (SBAS,GPS,GLO,QZSS) D = Semi-codeless (GPS) Data Channel (BDS) I = I channel (GPS,GAL, QZSS, BDS) L = L channel (L2C GPS, QZSS) P channel (GPS, QZSS) M = M code-based (GPS) N = Codeless (GPS) P = P code-based (GPS,GLO) Pilot Channel (BDS) Q = Q channel (GPS,GAL,QZSS,BDS) S = D channel (GPS, QZSS) M channel (L2C GPS, QZSS) W = Based on Z-tracking (GPS)(see text) X = B+C channels (GAL, IRNSS) I+Q channels (GPS,GAL, QZSS,BDS) M+L channels (GPS, QZSS) D+P channels (GPS, QZSS, BDS) Y = Y code-based (GPS) Z = A+B+C channels (GAL) D+P channels (BDS)

All characters in uppercase only! Units : Phase : full cycles Pseudorange : meters Doppler : Hz SNR etc. : receiver-dependent Ionosphere : full cycles Channel # : See text

Sign definition: See text.

The sequence of the observations in the observation records has to correspond to the sequence of the types in this record of the respective satellite system.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A9

TABLE A2 GNSS OBSERVATION DATA FILE - HEADER SECTION DESCRIPTION

Note: In RINEX 3.02, 3.03 and 3.04 all fields (Type, Band and Attribute) must be defined. Only known tracking modes are allowed.
* SIGNAL STRENGTH UNIT Unitof thecarrier to noise ratioobservablesSnnA20,40X (if present) DBHZ : S/N given in dbHz
* INTERVAL Observationinterval in secondsF10.3 TIME OF FIRST OBS Timeof first observation record (4-digit-year,5I6,F13.7, month, day, hour, min, sec)  Time system:5X,A3 GPS (=GPS time system) GLO (=UTC time system) GAL (=Galileo time system) QZS (= QZSS time system) BDT (= BDS time system) IRN (= IRNSS time system) Compulsory in mixed GNSS files Defaults: GPS for pure GPS files GLO for pure GLONASS files GAL for pure Galileo files QZS for pure QZSS files BDT for pure BDS files IRN for pure IRNSS files
* TIME OF LAST OBS Timeof last observation record (4-digit-year,5I6,F13.7, month, day, hour, min, sec)  Time system: Same value as in TIME OF5X,A3 FIRST OBS record
* RCV CLOCK OFFS APPL Epoch,code, and phase are corrected byI6 applying the real-time-derived receiver clock offset: 1=yes, 0=no; default: 0=no Record required if clock offsets are reported in the EPOCH/SAT records

* SYS / DCBS APPLIED Satellitesystem(G/R/E/J/C/I/S)A1,  Program name used to apply differential code1X,A17, bias corrections  Source of corrections (URL)1X,A40 Repeat for each satellite system. No corrections applied: Blank fields or record not present.
* SYS / PCVS APPLIED Satellite system(G/R/E/J/C/I/S)A1,  Program name used to apply phase center1X,A17,

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A10

TABLE A2 GNSS OBSERVATION DATA FILE - HEADER SECTION DESCRIPTION variation corrections  Source of corrections (URL)1X,A40 Repeat for each satellite system. No corrections applied: Blank fields or record not present.
* SYS / SCALE FACTOR Satellitesystem(G/R/E/J/C/I/S)A1,  Factor to divide stored observations with before1X,I4, use (1,10,100,1000)  Number of observation types involved. 0 or2X,I2, blank: All observation types  List of observation types12(1X,A3 )  Use continuation line(s) for more than 12 observation types.10X, 12(1X,A3 Repeat record if different factors are applied to) different observation types. A value of 1 is assumed if record is missing. SYS / PHASE SHIFT Phaseshift correction used to generate phases consistent with respect to cycle shifts  Satellite system (G/R/E/J/C/I/S)A1,1X,  Carrier phase observation code:A3,1X, Type Band Attribute  Correction applied (cycles)F8.5  Number of satellites involved 0 or blank: All2X,I2.2, satellites of system  List of satellites 10(1X,A3  Use continuation line(s) for more than 10 ) satellites. 18X, Repeat the record for all affected codes. 10(1X,A3 See chapter 9.1 for more details! )

GLONASS SLOT / FRQ # GLONASSslot and frequency numbers  Number of satellites in listI3,1X, List of :  Satellite numbers (system code, slot)8(A1,I2.2,  Frequency numbers (-7...+6)1X,I2,1X)  Use continuation lines for more than 8 Satellites4X,8(A1, I2.2,1X,I2 ,1X) GLONASS COD/PHS/BIS GLONASS Phase bias correction used to align4(X1,A3,

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A11

TABLE A2 GNSS OBSERVATION DATA FILE - HEADER SECTION DESCRIPTION code and phase observations.X1,F8.3)  GLONASS signal identifier : C1C and Code Phase bias correction (metres)  GLONASS signal identifier : C1P and Code Phase bias correction (metres)  GLONASS signal identifier : C2C and Code Phase bias correction (metres)  GLONASS signal identifier : C2P and Code Phase bias correction (metres) Note: If the GLONASS code phase bias values are unknown then all fields in the record are left blank (see example in Section 9.9) and only the record header is defined.
* LEAP SECONDS CurrentNumber of leap secondsI6,  Future or past leap seconds ΔtLSF(BNK) , i.e.I6, future leap second if the week and day numberI6, are in the future.  Respective week number WN_LSF (continuous number) (BNK). For GPS, GAL, QZS and IRN, weeks since 6-Jan-1980. When BDS only file leap seconds specified, weeks since 1-Jan-2006.I6  Respective day number DN (0-6) BeiDou and (1-7) for GPS and others constellations, (BNK). The day number is the GPS or BeiDou day before the leap second (See Note 1 below). In the case of the Tuesday, June 30/2015 (GPS Week 1851, DN 3) the UTC leap second actually occurred 16 seconds into the next GPS day.A3  Time system identifier: only GPS and BDS are valid identifiers. Blank defaults to GPS see Notes section below. Notes:
1. GPS, GAL, QZS and IRN time systems are aligned and are equivalent with respect to leap seconds (Leap seconds since 6-Jan-1980).See the GPS almanac, and DN reference IS-GPS-200H 20.3.3.5.2.4.
2. For BDS only observation files, the Number of leap seconds since 1-Jan-2006 as transmitted by the BDS almanac ΔtLS(see BDS-SIS-ICD-2.0 5.2.4.17)
* # OF SATELLITES Numberof satellites, for which observations areI6 stored in the file
* PRN / # OF OBS Satellitenumbers, number of observations for3X,

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A12

TABLE A2 GNSS OBSERVATION DATA FILE - HEADER SECTION DESCRIPTION each observation type indicated in the SYS / # /A1,I2.2, OBS TYPES record.9I6  If more than 9 observation types:6X,9I6 Use continuation line(s) In order to avoid format overflows, 99999 indicates >= 99999 observations in the RINEX file.

This record is (these records are) repeated for each satellite present in the data file. END OF HEADER Lastrecord in the header section.60X Records marked with * are optional

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A13

A 3 GNSS Observation Data File -Data Record Description TABLE A3 GNSS OBSERVATION DATA FILE – DATA RECORD DESCRIPTION DESCRIPTION FORMAT EPOCH record  Record identifier : >A1, Epoch  year (4 digits):1X,I4,  month, day, hour, min (two digits)4(1X,I2.2),  secF11.7,  Epoch flag,2X,I1, 0: OK 1: power failure between previous and current epoch >1: Special event  Number of satellites observed in current epoch I3,  (reserved)6X,  Receiver clock offset (seconds, optional)F15.12 Epoch flag = 0 or 1: OBSERVATION records follow  Satellite numberA1,I2.2,  m fields of observation data (in the same sequence as given in them(F14.3, respective SYS / # / OBS TYPES record), each containing the specifiedI1, observations for example: pseudorange, phase, LLI, Doppler and SNR. This record is repeated for each satellite having been observed in the currentI1) epoch. The record length is given by the number of observation types for this satellite. Observations: For definition, see text. Missing observations are written as 0.0 or blanks. Phase values overflowing the fixed format F14.3 have to be clipped into the valid interval (e.g add or subtract 10**9), set bit 0 of LLI indicator. Loss of lock indicator (LLI). 0 or blank: OK or not known

Bit 0 set: Lost lock between previous and current observation: Cycle slip possible. For phase observations only. Note: Bit 0 is the least significant bit.

Bit 1 set: Half-cycle ambiguity/slip possible. Software not capable of handling half cycles should skip this observation. Valid for the current epoch only.

Bit 2 set: Galileo BOC-tracking of an MBOC-modulated signal (may suffer from increased noise).

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A14

TABLE A3 GNSS OBSERVATION DATA FILE – DATA RECORD DESCRIPTION Signal Strength Indicator (SSI) projected into interval 1-9: 1: minimum possible signal strength 5: average/good S/N ratio 9: maximum possible signal strength 0 or blank: not known, don't care Standardization for S/N values given in dbHz: See text. Notes:
1. Loss of Lock Indicator (LLI) should only be associated with the phase observation.
2. Signal Strength Indicator (SSI) should be deprecated and replaced by a defined SNR field for each signal. However if this is not possible/practical then SSI should be specified for each phase signal type for example. GPS: L1C, L1W, L2W, L2X and L5X.
3. If only the pseudorange measurements are observed then the SSI should be associated with the code measurements. Epoch flag 2-5: EVENT: Special records may follow  Epoch flag[2X,I1]  2: start moving antenna  3: new site occupation (end of kinematic data) (at least MARKER NAME record follows)  4: header information follows  5: external event (epoch is significant, same time frame as observation time tags)  "Number of satellites" contains number of special records to follow. 0 if no[I3] special records follow. Maximum number of records: 999

For events without significant epoch the epoch fields in the EPOCH RECORD can be left blank Epoch flag = 6: EVENT: Cycle slip records follow  Epoch flag[2X,I1]  6: cycle slip records follow to optionally report detected and repaired cycle slips (same format as OBSERVATIONS records;  slip instead of observation;  LLI and signal strength blank or zero)

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A15

A 4 GNSS Observation Data File – Example #1 +------------------------------------------------------------------------------+ | TABLE A4 | | GNSS OBSERVATION DATA FILE - EXAMPLE #1 | +------------------------------------------------------------------------------+

----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

3.04 OBSERVATION DATA M RINEX VERSION / TYPE G = GPS R = GLONASS E = GALILEO S = GEO M = MIXED COMMENT XXRINEXO V9.9 AIUB 20060324 144333 UTC PGM / RUN BY / DATE EXAMPLE OF A MIXED RINEX FILE VERSION 3.04 COMMENT The file contains L1 pseudorange and phase data of the COMMENT geostationary AOR-E satellite (PRN 120 = S20) COMMENT A 9080 MARKER NAME 9080.1.34 MARKER NUMBER BILL SMITH ABC INSTITUTE OBSERVER / AGENCY X1234A123 GEODETIC 1.3.1 REC # / TYPE / VERS G1234 ROVER ANT # / TYPE
4375274. 587466. 4589095. APPROX POSITION XYZ .9030 .0000 .0000 ANTENNA: DELTA H/E/N 0 RCV CLOCK OFFS APPL G 5 C1C L1W L2W C1W S2W SYS / # / OBS TYPES R 2 C1C L1C SYS / # / OBS TYPES E 2 L1B L5I SYS / # / OBS TYPES S 2 C1C L1C SYS / # / OBS TYPES 18.000 INTERVAL G APPL_DCB xyz.uvw.abc//pub/dcb_gps.dat SYS / DCBS APPLIED DBHZ SIGNAL STRENGTH UNIT 2006 03 24 13 10 36.0000000 GPS TIME OF FIRST OBS 18 R01 1 R02 2 R03 3 R04 4 R05 5 R06 -6 R07 -5 R08 -4 GLONASS SLOT / FRQ # R09 -3 R10 -2 R11 -1 R12 0 R13 1 R14 2 R15 3 R16 4 GLONASS SLOT / FRQ # R17 5 R18 -5 GLONASS SLOT / FRQ # G L1C SYS / PHASE SHIFT G L1W 0.00000 SYS / PHASE SHIFT G L2W SYS / PHASE SHIFT R L1C SYS / PHASE SHIFT E L1B SYS / PHASE SHIFT E L5I SYS / PHASE SHIFT S L1C SYS / PHASE SHIFT C1C -10.000 C1P -10.123 C2C -10.432 C2P -10.634 GLONASS COD/PHS/BIS END OF HEADER > 2006 03 24 13 10 36.0000000 0 5 -0.123456789012 G06 23629347.915 .300 8 -.353 4 23629347.158 24.158 G09 20891534.648 -.120 9 -.358 6 20891545.292 38.123 G12 20607600.189 -.430 9 .394 5 20607600.848 35.234 E11 .324 8 .178 7 S20 38137559.506 335849.135 9 > 2006 03 24 13 10 54.0000000 0 7 -0.123456789210 G06 23619095.450 -53875.632 8 -41981.375 4 23619095.008 25.234 G09 20886075.667 -28688.027 9 -22354.535 7 20886076.101 42.231 G12 20611072.689 18247.789 9 14219.770 6 20611072.410 36.765 R21 21345678.576 12345.567 5 R22 22123456.789 23456.789 5 E11 65432.123 5 48861.586 7 S20 38137559.506 335849.135 9 > 2006 03 24 13 11 12.0000000 2 2 *** FROM NOW ON KINEMATIC DATA! *** COMMENT TWO COMMENT LINES FOLLOW DIRECTLY THE EVENT RECORD COMMENT

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A16

> 2006 3 24 13 11 12.0000000 0 4 -0.123456789876 G06 21110991.756 16119.980 7 12560.510 4 21110991.441 25.543 G09 23588424.398 -215050.557 6 -167571.734 6 23588424.570 41.824 G12 20869878.790 -113803.187 8 -88677.926 6 20869878.938 36.961 G16 20621643.727 73797.462 7 57505.177 2 20621644.276 15.368 > 3 4 A 9081 MARKER NAME 9081.1.34 MARKER NUMBER .9050 .0000 .0000 ANTENNA: DELTA H/E/N --> THIS IS THE START OF A NEW SITE <-- COMMENT > 2006 03 24 13 12 6.0000000 0 4 -0.123456987654 G06 21112589.384 24515.877 6 19102.763 4 21112589.187 25.478 G09 23578228.338 -268624.234 7 -209317.284 6 23578228.398 41.725 G12 20625218.088 92581.207 7 72141.846 5 20625218.795 35.143 G16 20864539.693 -141858.836 8 -110539.435 2 20864539.943 16.345 > 2006 03 24 13 13 1.2345678 5 0 > 4 2 AN EVENT FLAG 5 WITH A SIGNIFICANT EPOCH COMMENT AND AN EVENT FLAG 4 TO ESCAPE FOR THE TWO COMMENT LINES COMMENT > 2006 03 24 13 14 12.0000000 0 4 -0.123456012345 G06 21124965.133 0.30213 -0.62614 21124965.275 27.528 G09 23507272.372 -212616.150 7 -165674.789 7 23507272.421 42.124 G12 20828010.354 -333820.093 6 -260119.395 6 20828010.129 37.002 G16 20650944.902 227775.130 7 177487.651 3 20650944.363 18.040 > 4 1 *** LOST LOCK ON G 06 COMMENT . . . > 4 1 END OF FILE COMMENT ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A17

A 4 GNSS Observation Data File – Example #2 +------------------------------------------------------------------------------+ | TABLE A4 | | GNSS OBSERVATION DATA FILE - EXAMPLE #2 | +------------------------------------------------------------------------------+ ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| 3.04 OBSERVATION DATA M RINEX VERSION / TYPE sbf2rin-9.3.3 20140511 000610 LCL PGM / RUN BY / DATE faa1 MARKER NAME 92201M012 MARKER NUMBER Unknown Unknown OBSERVER / AGENCY 3001320 SEPT POLARX4 2.5.1p1 REC # / TYPE / VERS 725235 LEIAR25.R4 NONE ANT # / TYPE -5246415.0000 -3077260.0000 -1913842.0000 APPROX POSITION XYZ 0.1262 0.0000 0.0000 ANTENNA: DELTA H/E/N G 18 C1C L1C D1C S1C C1W S1W C2W L2W D2W S2W C2L L2L D2L SYS / # / OBS TYPES S2L C5Q L5Q D5Q S5Q SYS / # / OBS TYPES E 16 C1C L1C D1C S1C C5Q L5Q D5Q S5Q C7Q L7Q D7Q S7Q C8Q SYS / # / OBS TYPES L8Q D8Q S8Q SYS / # / OBS TYPES S 4 C1C L1C D1C S1C SYS / # / OBS TYPES R 12 C1C L1C D1C S1C C2P L2P D2P S2P C2C L2C D2C S2C SYS / # / OBS TYPES C 8 C2I L2I D2I S2I C7I L7I D7I S7I SYS / # / OBS TYPES J 12 C1C L1C D1C S1C C2L L2L D2L S2L C5Q L5Q D5Q S5Q SYS / # / OBS TYPES G L1C SYS / PHASE SHIFT G L2W SYS / PHASE SHIFT G L2L 0.00000 SYS / PHASE SHIFT G L5Q 0.00000 SYS / PHASE SHIFT E L1C 0.00000 SYS / PHASE SHIFT E L5Q 0.00000 SYS / PHASE SHIFT E L7Q 0.00000 SYS / PHASE SHIFT E L8Q 0.00000 SYS / PHASE SHIFT S L1C SYS / PHASE SHIFT R L1C SYS / PHASE SHIFT R L2P 0.00000 SYS / PHASE SHIFT R L2C SYS / PHASE SHIFT C L2I SYS / PHASE SHIFT C L7I SYS / PHASE SHIFT J L1C SYS / PHASE SHIFT J L2L 0.00000 SYS / PHASE SHIFT J L5Q 0.00000 SYS / PHASE SHIFT 30.000 INTERVAL 2014 5 10 0 0 0.0000000 GPS TIME OF FIRST OBS 2014 5 10 23 59 30.0000000 GPS TIME OF LAST OBS 72 # OF SATELLITES C1C 0.000 C2C 0.000 C2P 0.000 GLONASS COD/PHS/BIS DBHZ SIGNAL STRENGTH UNIT 24 R01 1 R02 -4 R03 5 R04 6 R05 1 R06 -4 R07 5 R08 6 GLONASS SLOT / FRQ # R09 -2 R10 -7 R11 0 R12 -1 R13 -2 R14 -7 R15 0 R16 -1 GLONASS SLOT / FRQ # R17 4 R18 -3 R19 3 R20 2 R21 4 R22 -3 R23 3 R24 2 GLONASS SLOT / FRQ # END OF HEADER > 2014 05 10 00 00 0.0000000 0 28 END OF FILE COMMENT ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A18

A 4 GNSS Observation Data File – Example #3 +------------------------------------------------------------------------------+ | TABLE A4 | | GNSS OBSERVATION DATA FILE - EXAMPLE #3 | +------------------------------------------------------------------------------+ ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| 3.04 OBSERVATION DATA M: MIXED RINEX VERSION / TYPE GR25 V3.08 20140513 072944 UTC PGM / RUN BY / DATE SNR is mapped to RINEX snr flag value [1-9] COMMENT LX: < 12dBHz -> 1; 12-17dBHz -> 2; 18-23dBHz -> 3 COMMENT 24-29dBHz -> 4; 30-35dBHz -> 5; 36-41dBHz -> 6 COMMENT 42-47dBHz -> 7; 48-53dBHz -> 8; >= 54dBHz -> 9 COMMENT Tokio MARKER NAME TOKI MARKER NUMBER SU Japan - Leica Geosystems OBSERVER / AGENCY 1870023 LEICA GR25 3.08/6.401 REC # / TYPE / VERS LEIAS10 NONE ANT # / TYPE -3956196.8609 3349495.1794 3703988.8347 APPROX POSITION XYZ 0.0000 0.0000 0.0000 ANTENNA: DELTA H/E/N G 16 C1C L1C D1C S1C C2S L2S D2S S2S C2W L2W D2W S2W C5Q SYS / # / OBS TYPES L5Q D5Q S5Q SYS / # / OBS TYPES R 12 C1C L1C D1C S1C C2P L2P D2P S2P C2C L2C D2C S2C SYS / # / OBS TYPES E 16 C1C L1C D1C S1C C5Q L5Q D5Q S5Q C7Q L7Q D7Q S7Q C8Q SYS / # / OBS TYPES L8Q D8Q S8Q SYS / # / OBS TYPES C 8 C2I L2I D2I S2I C7I L7I D7I S7I SYS / # / OBS TYPES J 12 C1C L1C D1C S1C C2S L2S D2S S2S C5Q L5Q D5Q S5Q SYS / # / OBS TYPES S 4 C1C L1C D1C S1C SYS / # / OBS TYPES DBHZ SIGNAL STRENGTH UNIT 1.000 INTERVAL 2014 05 13 07 30 0.0000000 GPS TIME OF FIRST OBS 2014 05 13 07 34 59.0000000 GPS TIME OF LAST OBS 0 RCV CLOCK OFFS APPL G L1C SYS / PHASE SHIFT G L2S -0.25000 SYS / PHASE SHIFT G L2W SYS / PHASE SHIFT G L5Q -0.25000 SYS / PHASE SHIFT R L1C SYS / PHASE SHIFT R L2P 0.25000 SYS / PHASE SHIFT R L2C SYS / PHASE SHIFT E L1C +0.50000 SYS / PHASE SHIFT E L5Q -0.25000 SYS / PHASE SHIFT E L7Q -0.25000 SYS / PHASE SHIFT E L8Q -0.25000 SYS / PHASE SHIFT C L2I SYS / PHASE SHIFT C L7I SYS / PHASE SHIFT J L1C SYS / PHASE SHIFT J L2S SYS / PHASE SHIFT J L5Q -0.25000 SYS / PHASE SHIFT S L1C SYS / PHASE SHIFT 24 R01 1 R02 -4 R03 5 R04 6 R05 1 R06 -4 R07 5 R08 6 GLONASS SLOT / FRQ # R09 -2 R10 -7 R11 0 R12 -1 R13 -2 R14 -7 R15 0 R16 -1 GLONASS SLOT / FRQ # R17 4 R18 -3 R19 3 R20 2 R21 4 R22 -3 R23 3 R24 2 GLONASS SLOT / FRQ # C1C 0.000 C1P 0.000 C2C 0.000 C2P 0.000 GLONASS COD/PHS/BIS 16 1694 7 LEAP SECONDS END OF HEADER > 2014 05 13 07 30 0.0000000 0 25 END OF FILE COMMENT ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A19

A 5 GNSS Navigation Message File – Header Section Description TABLE A5 GNSS NAVIGATION MESSAGE FILE - HEADER SECTION DESCRIPTION HEADER LABELDESCRIPTION FORMAT (Columns 61-80) RINEX VERSION / TYPE Formatversion :3.04F9.2,11X,  File type ('N' for navigation data)A1,19X,  Satellite System:A1,19X G: GPS R: GLONASS E: Galileo J: QZSS C: BDS I: IRNSS S: SBAS Payload M: Mixed PGM / RUN BY / DATE Nameof program creating current fileA20,  Name of agency creating current fileA20,  Date and time of file creationA20 Format: yyyymmdd hhmmss zone zone: 3-4 char. code for time zone. 'UTC ' recommended! 'LCL ' if local time with unknown local time system code
* COMMENT Commentline(s)A60
* IONOSPHERIC CORR Ionosphericcorrection parameters  Correction type:A4,1X, GAL= Galileo ai0 - ai2 GPSA= GPS alpha0 - alpha3 GPSB= GPS beta0 - beta3 QZSA = QZS alpha0 - alpha3 QZSB = QZS beta0 - beta3 BDSA = BDS alpha0 - alpha3 BDSB = BDS beta0 - beta3 IRNA = IRNSS alpha0 - alpha3 IRNB = IRNSS beta0 - beta3  Parameters:4D12.4 GAL: ai0, ai1, ai2, Blank GPS: alpha0-alpha3 or beta0-beta3 QZS: alpha0-alpha3 or beta0-beta3 BDS: alpha0-alpha3 or beta0-beta3 IRN: alpha0-alpha3 or beta0-beta3  Time mark, Transmission Time (seconds of 1X,A1 week) converted to hours of day and then to A- X. See BDS example below:

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A20

TABLE A5 GNSS NAVIGATION MESSAGE FILE - HEADER SECTION DESCRIPTION HEADER LABELDESCRIPTION FORMAT (Columns 61-80) A=BDT 00h-01h; B=BDT 01h-02h; ... X= BDT 23h-24h.

This field is mandatory for BDS and optional for the other constellations, (BNK).

 SV ID, identify which satellite provided the1X,I2 ionospheric parameters. This field is mandatory for BDS and optional for the other constellations (BNK).

Note 1: Multiple IONOSPHERIC CORR message can be written in the header.

Note 2: It is recommended that BDS ionospheric broadcast model parameters from BDS GEO satellites, be given the most priority. Then the parameters from BDS IGSO satellites should be given secondary priority and then tertiary priority is given to BDS MEO satellite ionospheric correction parameters.
* TIME SYSTEM CORR Difference between GNSS system time and UTC or other time systems  Type:A4,1X, GPUT = GPS - UTC (a0, a1) GLUT = GLO - UTC (a0= -TauC, a1=zero) GAUT = GAL - UTC ( a0, a1) BDUT =BDS - UTC (a0=A0UTC, a1=A1UTC ) QZUT = QZS - UTC (a0, a1) IRUT = IRN - UTC (a0=A0UTC, a1=A1UTC ) SBUT = SBAS - UTC (a0, a1)

GLGP = GLO - GPS (a0=TauGPS, a1=zero) GAGP = GAL – GPS (See **Note Below) (a0 = A0G, a1 = A1G for GAL INAV/FNAV; a0 = –A0GGTO, a1 = –A1 GGTO for GPS CNAV) QZGP = QZS - GPS (a0, a1) IRGP =IRN - GPS (a0=A0, a1=A1 )

 a0,a1 coefficients of linear polynomialD17.10,

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A21

TABLE A5 GNSS NAVIGATION MESSAGE FILE - HEADER SECTION DESCRIPTION HEADER LABELDESCRIPTION FORMAT (Columns 61-80) Δt = a0 + a1·(t-tref) for fractional partD16.9, (excluding leap seconds) of time system difference (a0 sec, a1 sec/sec)  T Reference time for polynomial (Seconds into GPS/GAL/BDS/QZS/IRN/SBAS week)1XI6,  W Reference week number (GPS/GAL/QZS/IRN/SBAS week, continuous1XI4, number from 6-Jan-1980), T and W zero for GLONASS. BDS week, continuous from: 1- Jan-2006  S Source System and number Snn of GNSS satellite1X,A5,1X broadcasting the time system difference or SBAS satellite broadcasting the MT12. Use EGNOS, WAAS, or MSAS for SBAS time differences from MT17.  U UTC Identifier (0 if unknown) I2,1X 1=UTC(NIST), 2=UTC(USNO), 3=UTC(SU), 4=UTC(BIPM), 5=UTC(Europe Lab), 6=UTC(CRL), 7=UTC(NTSC) (BDS), >7 = not assigned yet S and U for SBAS only. **Note: RINEX 3.04 and 3:03 provides the same sign and value for the Galileo minus GPS time offset but the GPGA label is replaced by GAGP in RINEX 3.04.

* LEAP SECONDS CurrentNumber of leapsecondsI6,  Future or past leap seconds ΔtLSF (BNK), i.e.I6, future leap second if the week and day number are in the future.  Respective week number WN_LSFI6, (continuous number) (BNK). For GPS, GAL, QZS and IRN, weeks since 6-Jan-1980. When BDS only file leap seconds specified, weeks since 1-Jan-2006.  Respective day number DN (0-6) BeiDou andI6 (1-7) for GPS and others constellations, (BNK). The day number is the GPS or BeiDou day before the leap second (See Note 1 below). In the case of the Tuesday, June 30/2015 (GPS Week 1851, DN 3) the UTC leap second actually occurred 16 seconds into the next GPS

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A22

TABLE A5 GNSS NAVIGATION MESSAGE FILE - HEADER SECTION DESCRIPTION HEADER LABELDESCRIPTION FORMAT (Columns 61-80) day.  Time system identifier: only GPS and BDS areA3 valid identifiers. Blank defaults to GPS, see Notes section below. Notes:
1. GPS, GAL, QZS and IRN time systems are aligned and are equivalent with respect to leap seconds (Leap seconds since 6-Jan-1980).See the GPS almanac and DN reference IS-GPS- 200H 20.3.3.5.2.4.
2. For BDS only navigation files, the Number of leap seconds since 1-Jan-2006 as transmitted by the BDS almanac ΔtLS(see BDS-SIS-ICD-2.0 5.2.4.17) END OF HEADER Records marked with * are optional, BNK- Blank if Not Know/Defined

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A23

A 6 GNSS Navigation Message File – GPS Data Record Description TABLE A6 GNSS NAVIGATION MESSAGE FILE – GPS DATA RECORD DESCRIPTION NAV. RECORD DESCRIPTION FORMAT SV / EPOCH / SV CLK - Satellite system (G), sat number (PRN)A1,I2.2,
- Epoch: Toc - Time of Clock (GPS) year (41X,I4, digits)
- month, day, hour, minute, second5(1X,I2.2),
- SV clock bias (seconds)3D19.12
- SV clock drift (sec/sec)
- SV clock drift rate (sec/sec2)*) BROADCAST ORBIT - 1 - IODE Issue of Data, Ephemeris4X,4D19.12
- Crs (meters)
- Delta n (radians/sec)***)
- M0 (radians) BROADCAST ORBIT - 2 - Cuc (radians)4X,4D19.12
- e Eccentricity
- Cus (radians)
- sqrt(A) (sqrt(m)) BROADCAST ORBIT - 3 - Toe Time of Ephemeris (sec of GPS week)4X,4D19.12
- Cic (radians)
- OMEGA0 (radians)
- Cis (radians) BROADCAST ORBIT - 4 - i0 (radians)4X,4D19.12
- Crc (meters)
- omega (radians)
- OMEGA DOT (radians/sec) BROADCAST ORBIT - 5 - IDOT (radians/sec)4X,4D19.12
- Codes on L2 channel
- GPS Week # (to go with TOE) Continuous number, not mod(1024)!
- L2 P data flag BROADCAST ORBIT - 6 - SV accuracy (meters) See GPS ICD 200H4X,4D19.12 Section 20.3.3.3.1.3 use specified equations to define nominal values, N = 0- (1+N/2) 6: use 2(round to one decimal place (N-2) i.e. 2.8, 5.7 and 11.3) , N= 7-15:use 2 , 8192 specifies use at own risk
- SV health (bits 17-22 w 3 sf 1)
- TGD (seconds)
- IODC Issue of Data, Clock BROADCAST ORBIT - 7 - Transmission time of message **)4X,4D19.12 (sec of GPS week, derived e.g.from Z- count in Hand Over Word (HOW))
- Fit Interval in hours see section 6.11. (BNK).

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A24

TABLE A6 GNSS NAVIGATION MESSAGE FILE – GPS DATA RECORD DESCRIPTION NAV. RECORD DESCRIPTION FORMAT
- Spare
- Spare *) In order to account for the various compilers, E,e,D, and d are allowed letters between the fraction and exponent of all floating point numbers in the navigation message files. Zero-padded two-digit exponents are required, however.

**) Adjust the Transmission time of message by + or -604800 to refer to the reported week in BROADCAST ORBIT 5, if necessary. Set value to 0.9999E9 if not known.

A 7 GPS Navigation Message File – Example +------------------------------------------------------------------------------+ | TABLE A7 | | GPS NAVIGATION MESSAGE FILE - EXAMPLE | +------------------------------------------------------------------------------+ ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

3.04 N: GNSS NAV DATA G: GPS RINEX VERSION / TYPE XXRINEXN V3 AIUB 19990903 152236 UTC PGM / RUN BY / DATE EXAMPLE OF VERSION 3.04 FORMAT COMMENT GPSA .1676D-07 .2235D-07 .1192D-06 .1192D-06 IONOSPHERIC CORR GPSB .1208D+06 .1310D+06 -.1310D+06 -.1966D+06 IONOSPHERIC CORR GPUT .1331791282D-06 .107469589D-12 552960 1025 G12 2 TIME SYSTEM CORR 13 LEAP SECONDS END OF HEADER G06 1999 09 02 17 51 44 -.839701388031D-03 -.165982783074D-10 .000000000000D+00 .910000000000D+02 .934062500000D+02 .116040547840D-08 .162092304801D+00 .484101474285D-05 .626740418375D-02 .652112066746D-05 .515365489006D+04 .409904000000D+06 -.242143869400D-07 .329237003460D+00 -.596046447754D-07 .111541663136D+01 .326593750000D+03 .206958726335D+01 -.638312302555D-08 .307155651409D-09 .000000000000D+00 .102500000000D+04 .000000000000D+00 .000000000000D+00 .000000000000D+00 .000000000000D+00 .910000000000D+02 .406800000000D+06 .400000000000E+01 G13 1999 09 02 19 00 00 .490025617182D-03 .204636307899D-11 .000000000000D+00 .133000000000D+03 -.963125000000D+02 .146970407622D-08 .292961152146D+01 -.498816370964D-05 .200239347760D-02 .928156077862D-05 .515328476143D+04 .414000000000D+06 -.279396772385D-07 .243031939942D+01 -.558793544769D-07 .110192796930D+01 .271187500000D+03 -.232757915425D+01 -.619632953057D-08 -.785747015231D-11 .000000000000D+00 .102500000000D+04 .000000000000D+00 .000000000000D+00 .000000000000D+00 .000000000000D+00 .389000000000D+03 .410400000000D+06 .400000000000E+01

----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A25

A 8 GNSS Navigation Message File – GALILEO Data Record Description TABLE A8 GNSS NAVIGATION MESSAGE FILE - GALILEO DATA RECORD DESCRIPTION NAV. RECORD DESCRIPTION FORMAT SV / EPOCH / SV CLK - Satellite system (E), satellite numberA1,I2.2,
- Epoch: Toc - Time of Clock GALyear (41X,I4, digits)
- month, day, hour, minute, second5(1X,I2.2),
- SV clock bias (seconds) af03D19.12
- SV clock drift (sec/sec) af1
- SV clock drift rate (sec/sec2) af2 (see*) Br.Orbit-5, data source, bits 8+9) BROADCAST ORBIT - 1 - IODnav Issue of Data of the nav batch4X,4D19.12
- Crs (meters)
- Delta n (radians/sec)***)
- M0 (radians) BROADCAST ORBIT - 2 - Cuc (radians)4X,4D19.12
- e Eccentricity
- Cus (radians)
- sqrt(a) (sqrt(m)) BROADCAST ORBIT - 3 - Toe Time of Ephemeris (sec of GAL week)4X,4D19.12
- Cic (radians)
- OMEGA0 (radians)
- Cis (radians) BROADCAST ORBIT - 4 - i0 (radians)4X,4D19.12
- Crc (meters)
- omega (radians)
- OMEGA DOT (radians/sec) BROADCAST ORBIT - 5 - IDOT (radians/sec)4X,4D19.12
- Data sources (FLOAT --> INTEGER) Bit 0 set: I/NAV E1-B Bit 1 set: F/NAV E5a-I Bit 2 set: I/NAV E5b-I Bits 0 and 2 : Both can be set if the navigation messages were merged, however, bits 0-2 cannot all be set, as the I/NAV and F/NAV messages contain different information Bit 3 reserved for Galileo internal use Bit 4 reserved for Galileo internal use Bit 8 set: af0-af2, Toc, SISA are for E5a,E1 Bit 9 set: af0-af2, Toc, SISA are for E5b,E1 Bits 8-9 : exclusive (only one bit can be set)
- GAL Week # (to go with Toe)****)
- Spare

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A26

TABLE A8 GNSS NAVIGATION MESSAGE FILE - GALILEO DATA RECORD DESCRIPTION NAV. RECORD DESCRIPTION FORMAT BROADCAST ORBIT - 6 - SISA Signal in space accuracy (meters) No4X,4D19.12 Accuracy Prediction Available(NAPA) / unknown: -1.0
- SV health (FLOAT converted to INTEGER)*****) See Galileo ICD Section 5.1.9.3 Bit 0: E1B DVS Bits 1-2: E1B HS Bit 3: E5a DVS Bits 4-5: E5a HS Bit 6: E5b DVS Bits 7-8: E5b HS
- BGD E5a/E1 (seconds)
- BGD E5b/E1 (seconds) BROADCAST ORBIT - 7 - Transmission time of message **)4X,4D19.12 (sec of GAL week, derived from WN and TOW of page type 1)
- spare
- spare
- spare *) In order to account for the various compilers, E,e,D, and d are allowed letters between the fraction and exponent of all floating point numbers in the navigation message files. Zero-padded two-digit exponents are required, however.

**) Adjust the Transmission time of message by + or -604800 to refer to the reported week in BROADCAST ORBIT 5, if necessary. Set value to 0.9999E9 if not known.

***) Angles and their derivatives transmitted in units of semi-circles and semi-circles/sec have to be converted to radians by the RINEX generator.

****) The GAL week number is a continuous number, aligned to (and hence identical to) the continuous GPS week number used in the RINEX navigation message files. The broadcast 12-bit Galileo System Time (GST) week has a roll-over after 4095. It started at zero at the first GPS roll-over (continuous GPS week 1024). Hence GAL week = GST week + 1024 + n*4096 (n: number of GST roll-overs).

*****) If bit 0 or bit 2 of Data sources (BROADCAST ORBIT – 5) is set, E1B DVS & HS, E5b DVS & HS and both BGDs are valid. -If bit 1 of Data sources is set, E5a DVS & HS and BGD E5a/E1 are valid. -Non valid parameters are set to 0 and to be ignored

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A27

A 9 GALILEO Navigation Message File – Examples +------------------------------------------------------------------------------+ | TABLE A9 | | GALILEO NAVIGATION MESSAGE FILE - EXAMPLES | +------------------------------------------------------------------------------+

----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| 3.04 N: GNSS NAV DATA E: GALILEO NAV DATA RINEX VERSION / TYPE NetR9 5.01 Receiver Operator 20150619 000000 UTC PGM / RUN BY / DATE GAL .1248D+03 .5039D+00 .2377D-01 .0000D+00 IONOSPHERIC CORR GAUT .3725290298D-08 .532907052D-14 345600 1849 E10 5 TIME SYSTEM CORR 16 17 1851 3 LEAP SECONDS END OF HEADER E12 2015 06 19 02 10 00 -.138392508961D-02 -.131464616970D-09 .000000000000D+00 .930000000000D+02 -.165531250000D+03 .285797618904D-08 .138275888459D+01 -.782497227192D-05 .346679124050D-03 .114385038614D-04 .544062509727D+04 .439800000000D+06 .298023223877D-07 -.296185101312D+01 -.111758708954D-07 .965683294025D+00 .993750000000D+02 -.629360976005D+00 -.541593988135D-08 -.571452374714D-11 .516000000000D+03 .184900000000D+04 .312000000000D+01 .000000000000D+00 -.651925802231D-08 -.605359673500D-08 .440734000000D+06 E12 2015 06 19 02 10 00 -.138392508961D-02 -.131464616970D-09 .000000000000D+00 .930000000000D+02 -.165531250000D+03 .285797618904D-08 .138275888459D+01 -.782497227192D-05 .346679124050D-03 .114385038614D-04 .544062509727D+04 .439800000000D+06 .298023223877D-07 -.296185101312D+01 -.111758708954D-07 .965683294025D+00 .993750000000D+02 -.629360976005D+00 -.541593988135D-08 -.571452374714D-11 .513000000000D+03 .184900000000D+04 .312000000000D+01 .000000000000D+00 -.651925802231D-08 -.605359673500D-08 .440725000000D+06 E12 2015 06 19 02 10 00 -.138392532244D-02 -.131450406116D-09 .000000000000D+00 .930000000000D+02 -.165531250000D+03 .285797618904D-08 .138275888459D+01 -.782497227192D-05 .346679124050D-03 .114385038614D-04 .544062509727D+04 .439800000000D+06 .298023223877D-07 -.296185101312D+01 -.111758708954D-07 .965683294025D+00 .993750000000D+02 -.629360976005D+00 -.541593988135D-08 -.571452374714D-11 .258000000000D+03 .184900000000D+04 .312000000000D+01 .000000000000D+00 -.651925802231D-08 .000000000000D+00 .440730000000D+06 3.04 NAVIGATION DATA M (Mixed) RINEX VERSION / TYPE BCEmerge congo 20150620 012902 GMT PGM / RUN BY / DATE Merged GPS/GLO/GAL/BDS/QZS/SBAS navigation file COMMENT based on CONGO and MGEX tracking data COMMENT DLR: O. Montenbruck; TUM: P. Steigenberger COMMENT BDUT 5.5879354477e-09-2.042810365e-14 14 492 B10 7 TIME SYSTEM CORR GAUT 3.7252902985e-09 5.329070518e-15 345600 1849 E10 5 TIME SYSTEM CORR GLGP -3.7252902985e-09 0.000000000e+00 345600 1849 R10 0 TIME SYSTEM CORR GLUT 1.0710209608e-08 0.000000000e+00 345600 1849 R10 0 TIME SYSTEM CORR GAGP -2.0081643015e-09-9.769962617e-15 432000 1849 E12 0 TIME SYSTEM CORR GPUT 4.5110937208e-09 7.105427358e-15 372608 1849 G10 2 TIME SYSTEM CORR QZUT 1.9557774067e-08 1.598721155e-14 61440 1850 J01 0 TIME SYSTEM CORR 18 LEAP SECONDS END OF HEADER E12 2015 06 19 02 10 00-1.383925089613e-03-1.314646169703e-10 0.000000000000e+00 9.300000000000e+01-1.655312500000e+02 2.857976189037e-09 1.382758884589e+00 -7.824972271919e-06 3.466791240498e-04 1.143850386143e-05 5.440625097275e+03 4.398000000000e+05 2.980232238770e-08-2.961851013120e+00-1.117587089539e-08 9.656832940254e-01 9.937500000000e+01-6.293609760051e-01-5.415939881349e-09 -5.714523747137e-12 5.130000000000e+02 1.849000000000e+03 3.120000000000e+00 0.000000000000e+00-6.519258022308e-09-6.053596735001e-09 4.404850000000e+05

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A28

E12 2015 06 19 02 10 00-1.383925322443e-03-1.314504061156e-10 0.000000000000e+00 9.300000000000e+01-1.655312500000e+02 2.857976189037e-09 1.382758884589e+00 -7.824972271919e-06 3.466791240498e-04 1.143850386143e-05 5.440625097275e+03 4.398000000000e+05 2.980232238770e-08-2.961851013120e+00-1.117587089539e-08 9.656832940254e-01 9.937500000000e+01-6.293609760051e-01-5.415939881349e-09 -5.714523747137e-12 2.580000000000e+02 1.849000000000e+03 3.120000000000e+00 0.000000000000e+00-6.519258022308e-09 0.000000000000e+00 4.405300000000e+05 ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A29

A 10 GNSS Navigation Message File – GLONASS Data Record Description TABLE A10 GNSS NAVIGATION MESSAGE FILE – GLONASS DATA RECORD DESCRIPTION NAV. RECORD DESCRIPTION FORMAT SV / EPOCH / SV CLK - Satellite system (R), satellite numberA1,I2.2, (slot number in sat. constellation)
- Epoch: Toc - Time of Clock (UTC)1X,I4, year (4 digits)
- month, day, hour, minute, second5(1X,I2.2),
- SV clock bias (sec) (-TauN)3D19.12
- SV relative frequency bias (+GammaN)
- Message frame time (tk+nd*86400) in seconds of the UTC week*) BROADCAST ORBIT - 1 - Satellite position X (km)4X,4D19.12
- velocity X dot (km/sec)
- X acceleration (km/sec2)
- health (0=healthy, 1=unhealthy) (MSB of 3-bit Bn) BROADCAST ORBIT - 2 - Satellite position Y (km)4X,4D19.12
- velocity Y dot (km/sec)
- Y acceleration (km/sec2)
- frequency number(-7...+13) (-7...+6 ICD 5.1) BROADCAST ORBIT - 3 - Satellite position Z (km)4X,4D19.12
- velocity Z dot (km/sec)
- Z acceleration (km/sec2)
- Age of oper. information (days) (E)

*) In order to account for the various compilers, E,e,D, and d are allowed letters between the fraction and exponent of all floating point numbers in the navigation message files. Zero-padded two- digit exponents are required, however.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A30

A 11 GNSS Navigation Message File – Example: Mixed GPS / GLONASS

+------------------------------------------------------------------------------+ | TABLE A11 | | GNSS NAVIGATION MESSAGE FILE – EXAMPLE MIXED GPS/GLONASS | +------------------------------------------------------------------------------+

----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

3.04 N: GNSS NAV DATA M: MIXED RINEX VERSION / TYPE XXRINEXN V3 AIUB 20061002 000123 UTC PGM / RUN BY / DATE EXAMPLE OF VERSION 3.04 FORMAT COMMENT GPSA 0.1025E-07 0.7451E-08 -0.5960E-07 -0.5960E-07 IONOSPHERIC CORR GPSB 0.8806E+05 0.0000E+00 -0.1966E+06 -0.6554E+05 IONOSPHERIC CORR GPUT 0.2793967723E-08 0.000000000E+00 147456 1395 G10 2 TIME SYSTEM CORR GLUT 0.7823109626E-06 0.000000000E+00 0 1395 R10 0 TIME SYSTEM CORR 14 LEAP SECONDS END OF HEADER G01 2006 10 01 00 00 00 0.798045657575E-04 0.227373675443E-11 0.000000000000E+00 0.560000000000E+02-0.787500000000E+01 0.375658504827E-08 0.265129935612E+01 -0.411644577980E-06 0.640150101390E-02 0.381097197533E-05 0.515371852875E+04 0.000000000000E+00 0.782310962677E-07 0.188667086536E+00-0.391155481338E-07 0.989010441512E+00 0.320093750000E+03-0.178449589759E+01-0.775925177541E-08 0.828605943335E-10 0.000000000000E+00 0.139500000000E+04 0.000000000000E+00 0.200000000000E+01 0.000000000000E+00-0.325962901115E-08 0.560000000000E+02 -0.600000000000E+02 0.400000000000E+01 G02 2006 10 01 00 00 00 0.402340665460E-04 0.386535248253E-11 0.000000000000E+00 0.135000000000E+03 0.467500000000E+02 0.478269921862E-08-0.238713891022E+01 0.250712037086E-05 0.876975362189E-02 0.819191336632E-05 0.515372778320E+04 0.000000000000E+00-0.260770320892E-07-0.195156738598E+01 0.128522515297E-06 0.948630520258E+00 0.214312500000E+03 0.215165003775E+01-0.794140221985E-08 -0.437875382124E-09 0.000000000000E+00 0.139500000000E+04 0.000000000000E+00 0.200000000000E+01 0.000000000000E+00-0.172294676304E-07 0.391000000000E+03 -0.600000000000E+02 0.400000000000E+01 R01 2006 10 01 00 15 00-0.137668102980E-04-0.454747350886E-11 0.900000000000E+02 0.157594921875E+05-0.145566368103E+01 0.000000000000E+00 0.000000000000E+00 -0.813711474609E+04 0.205006790161E+01 0.931322574615E-09 0.700000000000E+01 0.183413398438E+05 0.215388488770E+01-0.186264514923E-08 0.100000000000E+01 R02 2006 10 01 00 15 0-0.506537035108E-04 0.181898940355E-11 0.300000000000E+02 0.155536342773E+05-0.419384956360E+00 0.000000000000E+00 0.000000000000E+00 -0.199011298828E+05 0.324192047119E+00-0.931322574615E-09 0.100000000000E+01 0.355333544922E+04 0.352666091919E+01-0.186264514923E-08 0.100000000000E+01 ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A31

A 12 GNSS Navigation Message File – QZSS Data Record Description TABLE A12 QZSS NAVIGATION MESSAGE FILE – QZSS DATA RECORD DESCRIPTION NAV. RECORDDESCRIPTION FORMAT (Columns 61-80) SV / EPOCH / SV CLK - Satellite system (J), Satellite PRN-192A1,I2,
- Epoch: Toc - Time of Clock year (41X,I4, digits)
- month, day, hour, minutes, seconds5(1X,I2),
- SV clock bias (seconds)3D19.12
- SV clock drift (sec/sec)
- SV clock drift rate (sec/sec2)*) BROADCAST ORBIT - 1 - IODE Issue of Data, Ephemeris4X,4D19.12
- Crs (meters)
- Delta n (radians/sec)
- M0 (radians) BROADCAST ORBIT - 2 - Cuc (radians)4X,4D19.12
- e Eccentricity
- Cus (radians)
- sqrt(A) (sqrt(m)) BROADCAST ORBIT - 3 - Toe Time of Ephemeris (sec of GPS4X,4D19.12 week)
- Cic (radians)
- OMEGA (radians)
- CIS (radians) BROADCAST ORBIT - 4 - i0 (radians)4X,4D19.12
- Crc (meters)
- omega (radians)
- OMEGA DOT (radians/sec) BROADCAST ORBIT – 5 - IDOT (radians/sec)4X,4D19.12
- Codes on L2 channel (fixed to 2, see IS-QZSS-PNT 4.1.2.7)
- GPS Week # (to go with TOE) Continuous number, not mod(1024)!
- L2P data flag set to 1 since QZSS does not track L2P BROADCAST ORBIT – 6 - SV accuracy (meters) (IS -QZSS-PNT,4X,4D19.12 Section 5.4.3.1) which refers to: IS GPS 200H Section 20.3.3.3.1.3 use specified equations to define nominal values, N = (1+N/2) 0-6: use 2(round to one decimal place i.e. 2.8, 5.7 and 11.3) , N= 7- (N-2) 15:use 2 , 8192 specifies use at own risk
- SV health (bits 17-22 w 3 sf 1) (see IS- QZSS-PNT 5.4.1)

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A32

TABLE A12 QZSS NAVIGATION MESSAGE FILE – QZSS DATA RECORD DESCRIPTION NAV. RECORDDESCRIPTION FORMAT (Columns 61-80)
- TGD (seconds) The QZSS ICD specifies a do not use bit pattern "10000000" this condition is represented by a blank field.
- IODC Issue of Data, Clock

BROADCAST ORBIT – 7 - Transmission time of message **) (sec4X,4D19.12 of GPS week, derived e.g. from Z-count in Hand Over Word (HOW)
- Fit interval flag (0 / 1) (see IS-QZSS- PNT, 4.1.2.4(3) 0 – two hours), 1 – more than 2 hours. Blank if not known.
- Spare
- Spare Records marked with * are optional

**) Adjust the Transmission time of message by -604800 to refer to the reported week, if necessary.

*) In order to account for the various compilers, letters E,e,D, and d are allowed between the fraction and exponent of all floating point numbers in the navigation message files. Zero-padded two-digit exponents are required, however.

A 13 QZSS Navigation Message File – Example +------------------------------------------------------------------------------+ | TABLE A13 | | QZSS NAVIGATION MESSAGE FILE - EXAMPLE | +------------------------------------------------------------------------------+ ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| 3.04 N: GNSS NAV DATA J: QZSS RINEX VERSION / TYPE GR25 V3.08 20140513 072944 UTC PGM / RUN BY / DATE 16 1694 7 LEAP SECONDS END OF HEADER J01 2014 05 13 08 15 12 3.323303535581D-04-1.818989403546D-11 0.000000000000D+00 6.900000000000D+01-4.927812500000D+02 2.222949737636D-09 7.641996743610D-01 -1.654587686062D-05 7.542252133135D-02 1.197867095470D-05 6.492895933151D+03 2.025120000000D+05-8.381903171539D-07-9.211997910060D-01-2.041459083557D-06 7.082252892260D-01-1.558437500000D+02-1.575843337115D+00-2.349740733276D-09 -6.793140104410D-10 2.000000000000D+00 1.792000000000D+03 1.000000000000D+00 2.000000000000D+00 1.000000000000D+00-4.656612873077D-09 6.900000000000D+01 1.989000000000D+05 0.000000000000D+00 ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A33

A 14 GNSS Navigation Message File – BDS Data Record Description Table A14 GNSS NAVIGATION MESSAGE FILE – BDS DATA RECORD DESCRIPTION NAV. RECORD DESCRIPTION FORMAT

- Satellite system (C), sat number (PRN)A1,I2.2,
- Epoch: Toc - Time of Clock (BDT) year1X,I4 (4 digits) SV /EPOCH / SV CLK
- month, day, hour, minute, second5,1X,I2.2,
- SV clock bias (seconds)3D19.12
- SV clock drift (sec/sec)
- SV clock drift rate (sec/sec)*)
- AODE Age of Data, Ephemeris (as4X,4D19.12 specified in BeiDou ICD Table Section BROADCAST ORBIT –5.2.4.11 Table 5-8) and field range is: 0- 131.
- Crs (meters)
- Delta n (radians/sec) **)
- M0 (radians)
- Cuc (radians)4X,4D19.12 BROADCAST ORBIT –
- e Eccentricity
- Cus (radians)
- sqrt(A) (sqrt(m))
- Toe Time of Ephemeris (sec of BDT4X,4D19.12 BROADCAST ORBIT –week) 3-Cic(radians)
- OMEGA0 (radians)
- Cis (radians)
- i0 (radians)4X,4D19.12 BROADCAST ORBIT –
- Crc (meters)
- omega (radians)
- OMEGA DOT (radians/sec)
- IDOT (radians/sec)4X,4D19.12 BROADCAST ORBIT –
- Spare
- BDT Week #***)
- Spare
- SV accuracy (meters See: BDS4X,4D19.12 ICD Section 5.2.4.: to define nominal (1+N/2) values, N = 0-6: use 2(round to one BROADCAST ORBIT –decimal place i.e. 2.8, 5.7 and 11.3) , N= (N-2) 67-15:use 2, 8192 specifies use at own risk)
- SatH1
- TGD1 B1/B3 (seconds)
- TGD2 B2/B3 (seconds)

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A34

- Transmission time of message ****)4X,4D19.12 (sec of BDT week,) BROADCAST ORBIT –- AODC Age of Data Clock (as specified 7in BeiDou ICD Table Section 5.2.4.9 Table 5-6) and field range is: 0-31.
- Spare
- Spare *) In order to account for the various compilers, E,e,D, and d are allowed letters between the fraction and exponent of all floating point numbers in the navigation message files. Zero- padded two-digit exponents are required, however.

**) Angles and their derivatives transmitted in units of semi-circles and semi-circles/sec have to be converted to radians by the RINEX generator.

***) The BDT week number is a continuous number. The broadcast 13-bit BDS System Time week has a roll-over after 8191. It started at zero at 1-Jan-2006, Hence BDT week = BDT week_BRD + (n*8192) where (n: number of BDT roll-overs).

****) Adjust the Transmission time of message by + or -604800 to refer to the reported week in BROADCAST ORBIT -5, if necessary. Set value to 0.9999E9 if not known.

A 15 BeiDou Navigation Message File – Example +------------------------------------------------------------------------------+ | TABLE A15 | | BeiDou NAVIGATION MESSAGE FILE - EXAMPLE | +------------------------------------------------------------------------------+ ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| 3.04 NAVIGATION DATA M (Mixed) RINEX VERSION / TYPE BCEmerge montenbruck 20140517 072316 GMT PGM / RUN BY / DATE DLR: O. Montenbruck; TUM: P. Steigenberger COMMENT BDUT -9.3132257462e-10 9.769962617e-15 14 435 TIME SYSTEM CORR END OF HEADER C01 2014 05 10 00 00 00 2.969256602228e-04 2.196998138970e-11 0.000000000000e+00 1.000000000000e+00 4.365468750000e+02 1.318269196918e-09-3.118148933476e+00 1.447647809982e-05 2.822051756084e-04 8.092261850834e-06 6.493480609894e+03 5.184000000000e+05-2.654269337654e-08 3.076630958509e+00-3.864988684654e-08 1.103024081152e-01-2.506406250000e+02 2.587808789012e+00-3.039412318009e-10 2.389385241772e-10 0.000000000000e+00 4.350000000000e+02 0.000000000000e+00 2.000000000000e+00 0.000000000000e+00 1.420000000000e-08-1.040000000000e-08 5.184000000000e+05 0.000000000000e+00 ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A35

A 16 GNSS Navigation Message File – SBAS Data Record Description TABLE A16 GNSS NAVIGATION MESSAGE FILE – SBAS DATA RECORD DESCRIPTION NAV. RECORD DESCRIPTION FORMAT SV / EPOCH / SV CLK - Satellite system (S), satellite number (slotA1,I2.2, number in sat. constellation)
- Epoch: Toc - Time of Clock (GPS) year (41X,I4, digits)
- month, day, hour, minute, second5(1X,I2.2),
- SV clock bias (sec) (aGf0)3D19.12,
- SV relative frequency bias (aGf1)
- Transmission time of message (start of the*) message) in GPS seconds of the week BROADCAST ORBIT - 1 - Satellite position X (km)4X,4D19.12
- velocity X dot (km/sec)
- X acceleration (km/sec2)
- Health: SBAS: See Section 8.3.3 bit mask for: health, health availability and User Range Accuracy. BROADCAST ORBIT - 2 - Satellite position Y (km)4X,4D19.12
- velocity Y dot (km/sec)
- Y acceleration (km/sec2)
- Accuracy code (URA, meters) BROADCAST ORBIT - 3 - Satellite position Z (km)4X,4D19.12
- velocity Z dot (km/sec)
- Z acceleration (km/sec2)
- IODN (Issue of Data Navigation, DO229, 8 first bits after Message Type if MT9)

*) In order to account for the various compilers, E,e,D, and d are allowed letters between the fraction and exponent of all floating point numbers in the navigation message files. Zero-padded two-digit exponents are required, however.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A36

A 17 SBAS Navigation Message File -Example +------------------------------------------------------------------------------+ | TABLE A17 | | SBAS NAVIGATION MESSAGE FILE - EXAMPLE | +------------------------------------------------------------------------------+ ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

3.04 N: GNSS NAV DATA S: SBAS RINEX VERSION / TYPE SBAS2RINEX 3.0 CNES 20031018 140100 PGM / RUN BY / DATE EXAMPLE OF VERSION 3.04 FORMAT COMMENT SBUT -.1331791282D-06 -.107469589D-12 552960 1025 EGNOS 5 TIME SYSTEM CORR 13 LEAP SECONDS This file contains navigation message data from a SBAS COMMENT (geostationary) satellite, here AOR-W (PRN 122 = # S22) COMMENT END OF HEADER S22 2003 10 18 0 1 4-1.005828380585D-07 6.366462912410D-12 5.184420000000D+05 2.482832392000D+04-3.593750000000D-04-1.375000000000D-07 0.000000000000D+00 -3.408920872000D+04-1.480625000000D-03-5.000000000000D-08 4.000000000000D+00 -1.650560000000D+01 8.360000000000D-04 6.250000000000D-08 2.300000000000D+01 S22 2003 10 18 0 5 20-9.872019290924D-08 5.456968210638D-12 5.186940000000D+05 2.482822744000D+04-3.962500000000D-04-1.375000000000D-07 0.000000000000D+00 -3.408958936000D+04-1.492500000000D-03-5.000000000000D-08 4.000000000000D+00 -1.628960000000D+01 8.520000000000D-04 6.250000000000D-08 2.400000000000D+01 S22 2003 10 18 0 9 36-9.732320904732D-08 4.547473508865D-12 5.189510000000D+05 2.482812152000D+04-4.325000000000D-04-1.375000000000D-07 0.000000000000D+00 -3.408997304000D+04-1.505000000000D-03-5.000000000000D-08 4.000000000000D+00 -1.606960000000D+01 8.800000000000D-04 6.250000000000D-08 2.500000000000D+01 S22 2003 10 18 0 13 52-9.592622518539D-08 4.547473508865D-12 5.192110000000D+05 2.482800632000D+04-4.681250000000D-04-1.375000000000D-07 0.000000000000D+00 -3.409035992000D+04-1.518125000000D-03-3.750000000000D-08 4.000000000000D+00 -1.584240000000D+01 8.960000000000D-04 6.250000000000D-08 2.600000000000D+01

----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A37

A 18 GNSS Navigation Message File – IRNSS Data Record Description TABLE A18 GNSS NAVIGATION MESSAGE FILE – IRNSS DATA RECORD DESCRIPTION NAV. RECORD DESCRIPTION FORMAT SV / EPOCH / SV CLK - Satellite system (I), sat number (PRN)A1,I2.2,
- Epoch: Toc - Time of Clock (IRNSS) year1X,I4, (4 digits)
- month, day, hour, minute, second5(1X,I2.2),
- SV clock bias (seconds)3D19.12
- SV clock drift (sec/sec)
- SV clock drift rate (sec/sec2)*) BROADCAST ORBIT - 1 - IODEC Issue of Data, Ephemeris and4X,4D19.12 Clock
- Crs (meters)***)
- Delta n (radians/sec)
- M0 (radians) BROADCAST ORBIT - 2 - Cuc (radians)4X,4D19.12
- e Eccentricity
- Cus (radians)
- sqrt(A) (sqrt(m)) BROADCAST ORBIT - 3 - Toe Time of Ephemeris (sec of IRNSS4X,4D19.12 week)
- Cic (radians)
- OMEGA0 (radians)
- Cis (radians) BROADCAST ORBIT - 4 - i0 (radians)4X,4D19.12
- Crc (meters)
- omega (radians)
- OMEGA DOT (radians/sec) BROADCAST ORBIT - 5 - IDOT (radians/sec)4X,4D19.12
- Blank
- IRN Week # (to go with TOE) Continuous number, not mod (1024), counted from 1980 (same as GPS).
- Blank BROADCAST ORBIT - 6 - User Range Accuracy(m), See IRNSS4X,4D19.12 ICD Section 6.2.1.4 , use specified equations to define nominal values, N = 0- (1+N/2) 6: use 2(round to one decimal place (N-2) i.e. 2.8, 5.7 and 11.3) , N= 7-15:use 2 , 8192 specifies use at own risk
- Health (Sub frame 1,bits 155(most significant) and 156(least significant)), where 0 = L5 and S healthy, 1 = L5 healthy and S unhealthy, 2= L5 unhealthy and S healthy, 3= both L5 and S unhealthy

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A38

TABLE A18 GNSS NAVIGATION MESSAGE FILE – IRNSS DATA RECORD DESCRIPTION NAV. RECORD DESCRIPTION FORMAT
- TGD (seconds)
- Blank BROADCAST ORBIT - 7 - Transmission time of message **)4X,4D19.12 (sec of IRNSS week)
- Blank
- Blank
- Blank *) In order to account for the various compilers, E,e,D, and d are allowed letters between the fraction and exponent of all floating point numbers in the navigation message files. Zero-padded two-digit exponents are required, however.

**) Adjust the Transmission time of message by + or -604800 to refer to the reported week in BROADCAST ORBIT 5, if necessary. Set value to 0.9999E9 if not known.

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A39

A 19 IRNSS Navigation Message File – Example +------------------------------------------------------------------------------+ | TABLE A19 | | IRNSS NAVIGATION MESSAGE FILE - EXAMPLE | +------------------------------------------------------------------------------+

----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

3.04 NAVIGATION DATA I (IRNSS) RINEX VERSION / TYPE DecodIRNSS montenbruck 20141004 164512 GMT PGM / RUN BY / DATE Source: IRNSS-1A Navbits COMMENT END OF HEADER I01 2014 04 01 00 00 00-9.473115205765e-04 1.250555214938e-12 0.000000000000e+00 0.000000000000e+00-5.820625000000e+02 4.720196615135e-09-1.396094758025e+00 -1.898035407066e-05 2.257102518342e-03-1.068413257599e-05 6.493487739563e+03 1.728000000000e+05 6.705522537231e-08-8.912102146884e-01-5.215406417847e-08 4.758105460020e-01 4.009375000000e+02-2.999907424014e+00-4.414469594664e-09 -4.839487298357e-10 1.786000000000e+03 1.130000000000e+01 0.000000000000e+00-4.190951585770e-09 1.728000000000e+05 I01 2014 04 01 02 00 00-9.473022073507e-04 1.250555214938e-12 0.000000000000e+00 1.000000000000e+00-5.101875000000e+02 4.945920303147e-09-8.741766987741e-01 -1.684948801994e-05 2.254169434309e-03-1.182407140732e-05 6.493469217300e+03 1.800000000000e+05 2.346932888031e-07-8.912408598963e-01-1.117587089539e-08 4.758065024964e-01 4.403750000000e+02-2.996779607145e+00-4.508759236491e-09 -5.464513333200e-10 1.786000000000e+03 1.130000000000e+01 0.000000000000e+00-4.190951585770e-09 1.800000000000e+05 I01 2014 04 01 04 00 00-9.472924284637e-04 1.250555214938e-12 0.000000000000e+00 2.000000000000e+00-5.100000000000e+02 5.217360181136e-09-3.491339518362e-01 -1.697987318039e-05 2.254509832710e-03-1.212581992149e-05 6.493469842911e+03 1.872000000000e+05 1.378357410431e-07-8.912725364615e-01 2.942979335785e-07 4.758010370344e-01 4.460625000000e+02-2.996772972812e+00-4.790199531038e-09 -6.039537285256e-10 1.786000000000e+03 1.130000000000e+01 0.000000000000e+00-4.190951585770e-09 1.872000000000e+05 ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A40

A 20 Meteorological Data File -Header Section Description TABLE A20 METEOROLOGICAL DATA FILE - HEADER SECTION DESCRIPTION HEADER LABELDESCRIPTION FORMAT (Columns 61-80) RINEX VERSION /- Format version : 3.04F9.2,11X, TYPE- File type: M for Meteorological DataA1,39X PGM / RUN BY / DATE - Name of program creating current fileA20,
- Name of agency creating current fileA20,
- Date of file creation (See section 5.8)A20
* COMMENT - Comment line(s) A60 MARKER NAME - Station Name (preferably identical toA60 MARKER NAME in the associated Observation File)
* MARKER NUMBER - Station Number (preferably identical toA20 MARKER NUMBER in the associated Observation File) # / TYPES OF OBSERV - Number of different observation types storedI6, in the file
- Observation types9(4X,A2) The following meteorological observation types are defined in RINEX Version 3: PR : Pressure (mbar) TD : Dry temperature (deg Celsius) HR : Relative humidity (percent) ZW : Wet zenith path delay (mm), (for WVR data) ZD : Dry component of zen.path delay (mm) ZT : Total zenith path delay (mm) WD : Wind azimuth (deg) from where the wind blows WS : Wind speed (m/s) RI : "Rain increment" (1/10 mm): Rain accumulation since last measurement HI : Hail indicator non-zero: Hail detected since last measurement The sequence of the types in this record must correspond to the sequence of the measurements in the data records.
- If more than 9 observation types are being(6X,9(4X,A used, use continuation lines with format2))

SENSORDescription of the met sensor MOD/TYPE/ACC- Model (manufacturer) A20,

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A41

TABLE A20 METEOROLOGICAL DATA FILE - HEADER SECTION DESCRIPTION HEADER LABELDESCRIPTION FORMAT (Columns 61-80)
- TypeA20,6X,
- Accuracy (same units as obs values)F7.1,4X,
- Observation typeA2,1X Record is repeated for each observation type found in # / TYPES OF OBSERV record SENSOR POS XYZ/H - Approximate position of the met sensor - Geocentric coordinates X,Y,Z (ITRF or3F14.4, WGS84)1F14.4,
- Ellipsoidal height H1X,A2,1X
- Observation type Set X, Y, Z to (BNK). Make sure H refers to ITRF or WGS-84! Record required for barometer, recommended for other sensors. END OF HEADER Last record in the header section. 60X Records marked with * are optional

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A42

A 21 Meteorological Data File -Data Record Description TABLE A21 METEOROLOGICAL DATA FILE - DATA RECORD DESCRIPTION OBS. RECORD DESCRIPTION FORMAT EPOCH / MET - Epoch in GPS time (not local time!) year (41X,I4.4, digits, padded with 0 if necessary)
- month, day, hour, min, sec5(1X,I2),
- Met data in the same sequence as given in themF7.1 header
- More than 8 met data types: Use continuation4X,10F7.1 lines

A 22 Meteorological Data File – Example

+------------------------------------------------------------------------------+ | TABLE A22 | | METEOROLOGICAL DATA FILE - EXAMPLE | +------------------------------------------------------------------------------+ ----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8| 3.04 METEOROLOGICAL DATA RINEX VERSION / TYPE XXRINEXM V9.9 AIUB 19960401 144333 UTC PGM / RUN BY / DATE EXAMPLE OF A MET DATA FILE COMMENT A 9080 MARKER NAME 3 PR TD HR # / TYPES OF OBSERV PAROSCIENTIFIC 740-16B 0.2 PR SENSOR MOD/TYPE/ACC HAENNI 0.1 TD SENSOR MOD/TYPE/ACC ROTRONIC I-240W 5.0 HR SENSOR MOD/TYPE/ACC 0.0000 0.0000 0.0000 1234.5678 PR SENSOR POS XYZ/H END OF HEADER 1996 4 1 0 0 15 987.1 10.6 89.5 1996 4 1 0 0 30 987.2 10.9 90.0 1996 4 1 0 0 45 987.1 11.6 89.0

----|---1|0---|---2|0---|---3|0---|---4|0---|---5|0---|---6|0---|---7|0---|---8|

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A43

A 23 Reference Code and Phase Alignment by Constellation and Frequency Band TABLE A23 Reference Code and Phase Alignment by Frequency Band System FrequencyFrequencySignal RINEXPhase Correction Band[MHz]Observationapplied to each Codeobserved phase to obtain aligned phase.

(φRINEX = φ original(as issued by the SV) + Δφ) GPS L1 1575.42 C/A L1C None (Reference Signal) L1C-D L1S +¼ cycle L1C-P L1L +¼ cycle L1C-(D+P) L1X +¼ cycle P L1P +¼ cycle Z-tracking L1W +¼ cycle Codeless L1N +¼ cycle L21227.60 C/A L2C For Block II/IIA/IIR – None; See Note 1 For Block IIR-M/IIF/III -¼ cycle

See Note 2 Semi-L2D None codeless L2C(M) L2S -¼ cycle L2C(L) L2L -¼ cycle L2C(M+L) L2X -¼ cycle P L2P None (Reference Signal) Z-tracking L2W None Codeless L2N None L5 1176.45 I L5I None (Reference Signal) Q L5Q -¼ cycle I+Q L5X Must be aligned to L5I GLONASSG11602+k*9/16 C/AL1CNone (Reference Signal) GLONASS P L1P +¼ cycle G1a 1600.995 L1OCd L4A None (Reference Signal) L1OCp L4B None L1OCd+L4X None L1OCd G2 1246+k*7/16 C/A L2C None (Reference Signal) P L2P +¼ cycle

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A44

TABLE A23 Reference Code and Phase Alignment by Frequency Band System FrequencyFrequencySignal RINEXPhase Correction Band[MHz]Observationapplied to each Codeobserved phase to obtain aligned phase.

(φRINEX = φ original(as issued by the SV) + Δφ) G2a 1248.06 L2CSI L6A None (Reference Signal) L2OCp L6B None L2CSI+L6X None L2OCp G3 1202.025 I L3I None (Reference Signal) Q L3Q +¼ cycle I+Q L3X Must be aligned to L3I Galileo E1 1575.42 B I/NAVL1B None (Reference Signal) OS/CS/SoL C no data L1C +½ cycle B+C L1X Must be aligned to L1B E5A 1176.45 I L5I None(Reference Signal) Q L5Q -¼ cycle I+Q L5X Must be aligned to L5I E5B 1207.140 I L7I None (Reference Signal) Q L7Q -¼ cycle I+Q L7X Must be aligned to L7I E5(A+B) 1191.795 I L8I None (Reference Signal) Q L8Q -¼ cycle I+Q L8X Must be aligned to L8I E6 1278.75 B L6B None (Reference Signal) C L6C -½ cycle B+C L6X Must be aligned to L6B QZSS L1 1575.42 C/A L1C None (Reference Signal) L1C (D) L1S +¼ cycle (See Note 5 Below) L1C (P) L1L +¼ cycle L1C-(D+P) L1X +¼ cycle L1S L1Z N/A L2 1227.60 L2C (M) L2S None (Reference Signal) L2C (L) L2L None L2CL2X None (M+L) L5 1176.45 I L5I None (Reference Signal) Q L5Q -¼ cycle

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A45

TABLE A23 Reference Code and Phase Alignment by Frequency Band System FrequencyFrequencySignal RINEXPhase Correction Band[MHz]Observationapplied to each Codeobserved phase to obtain aligned phase.

(φRINEX = φ original(as issued by the SV) + Δφ) QZSS I+Q L5X Must be aligned to L5I L5S 1176.45 I L5D None Reference Signal Q L5P -¼ cycle I+Q L5Z None must be aligned to L5D 1278.75 L6D L6S None (Reference Signal) L6 (See NoteL6P L6L None 6 Below)L6(D+P) L6X None L6E L6E None L6(D+E) L6Z None BDS B1-2 1561.098 I L2I None (Reference Signal) (See Note 4 Below) Q L2Q -¼ cycle I+Q L2X Must be aligned to L2I Data (D) L1D None Reference Signal B1 1575.42Pilot(P) L1P +¼ cycle(preliminary) D+P L1X Must be aligned to L1D Data (D) L5D None Reference Signal B2a 1176.45Pilot(P) L5P +¼ cycle(preliminary) D+P L5X Must be aligned to L5D B2b1207.140 I L7I None (Reference (BDS-2)Signal) Q L7Q -¼ cycle I+Q L7X Must be aligned to L7I B2b1207.140 Data (D) L7D None Reference Signal (BDS-3)Pilot(P) L7P +¼ cycle(preliminary) D+P L7Z Must be aligned to L7D B2a+B2b 1191.795 Data (D) L8D None Reference Signal Pilot(P) L8P +¼ cycle(preliminary) D+P L8X Must be aligned to L8D B3 1268.52 I L6I None (Reference Signal) Q L6Q -¼ cycle I+Q L6X Must be aligned to L6I B3A L6A Must be aligned to L6I IRNSS L5 1176.45 A SPS L5A None (Reference Signal)

RINEX 3.04.IGS.RTCM.doc 2018-11-23

RINEX Version 3.04 Appendix A46

TABLE A23 Reference Code and Phase Alignment by Frequency Band System FrequencyFrequencySignal RINEXPhase Correction Band[MHz]Observationapplied to each Codeobserved phase to obtain aligned phase.

(φRINEX = φ original(as issued by the SV) + Δφ) B RS(D) L5B Restricted(See Note 3) C RS(P) L5C None B+C L5X Must be aligned to L5A S 2492.028 A SPS L9A None (Reference Signal) IRNSSB RS(D)L9BRestricted(See Note3) C RS(P) L9C None B+C L9X Must be aligned to L9A

NOTES:

1) The GPS L2 phase shift values ignore FlexPower when the phases of the L2W and L2C can be changed on the satellite.

2) The phase of the L2 C/A signal is dependent on the GPS satellite generation.

3) There is no public information available concerning the restricted service signals.

4) Note: Both C1x and C2x (RINEX 3.01 definition) have been used to identify the B1 frequency signals in RINEX 3.02 files. If C2x coding is read in a RINEX 3.02 file treat it as equivalent to C1x.

5) There has been a phase alignment change between the QZSS Block I and Block II satellites. The table above shows the Block II alignment. Block I corrections: L1S none, L1L +¼.

6) L6D,L6P, L6E are identical to L61/L62(code1),L61(code2),L62(code2) in IS-QZSS-L6 respectively.

RINEX 3.04.IGS.RTCM.doc 2018-11-23