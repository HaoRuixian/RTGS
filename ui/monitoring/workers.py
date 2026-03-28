"""
GNSS RT Monitor - Real-time data acquisition and processing threads.

This module implements the multi-threaded architecture for GNSS real-time monitoring:
  - IOThread: Receives raw RTCM messages from NTRIP server
  - DataProcessingThread: Parses RTCM messages and extracts satellite observations
  - LoggingThread: Records raw RTCM or formatted observations to files
  - StreamSignals: Qt signals for inter-thread communication

Architecture follows a producer-consumer pattern with ring buffers for efficient,
non-blocking data exchange between threads. Each thread is independent and can be
monitored/controlled separately.
"""

import threading
import time
import os
import sys
import csv
from queue import Queue
from typing import List
from PySide6.QtCore import QObject, Signal
from core.pyrtcm_compat import patch_pyrtcm_glonass_g3

patch_pyrtcm_glonass_g3()
from pyrtcm import RTCMReader
from datetime import datetime, timedelta, timezone

from core.global_config import get_global_config
from core.ntrip_client import NtripClient
from core.serial_client import SerialClient
from core.ring_buffer import RingBuffer
from core.rinex3_writer import RINEX3Writer
from core.rinex_loader import FileEphemerisProvider, RinexObservationReader, read_rinex_observation_header
from core.mixed_gnss_reader import MixedGNSSReader


class StreamSignals(QObject):
    """
    Qt signal container for inter-thread communication in the monitoring pipeline.
    
    Attributes:
        log_signal (Signal[str]): Emitted when log messages are generated (status updates, errors).
        epoch_signal (Signal[object]): Emitted when a complete epoch of observations is available (carries EpochObservation).
        status_signal (Signal[str, bool]): Emitted when stream connection status changes (thread_name, connected).
    """
    log_signal = Signal(str)
    epoch_signal = Signal(object)
    status_signal = Signal(str, bool)


class IOThread(threading.Thread):
    """
    Data acquisition thread for GNSS RTCM streams.

    Responsibilities:
    - Support both NTRIP server and Serial port data sources
    - Maintain connection and receive RTCM streams
    - Decode RTCM frames using pyrtcm
    - Push raw messages into processing and logging ring buffers

    Notes:
    - Pure producer: no parsing or state management
    - Automatic reconnection on failure
    """    
    def __init__(self, name: str, settings: dict, ring_buffer: RingBuffer, signals: StreamSignals, logging_buffer: RingBuffer = None):
        """
        Args:
            name: Stream identifier (e.g. 'OBS', 'EPH')
            settings: Connection parameters (includes 'source' field indicating NTRIP or Serial)
            ring_buffer: Output buffer for processing thread
            signals: Qt signal emitter
            logging_buffer: Optional buffer for raw logging
        """
        super().__init__()
        self.name = name
        self.settings = settings
        self.ring_buffer = ring_buffer
        self.logging_buffer = logging_buffer
        self.signals = signals
        self.daemon = True
        self.running = True
        self.client = None
        self.msg_count = 0
        self.last_log_time = time.time()
        self.source_type = settings.get('source', 'NTRIP Server')  # 'NTRIP Server' or 'Serial Port'
    
    def _safe_emit(self, signal_type: str, *args):
        """安全发送信号，处理信号源已删除的情况"""
        try:
            if not self.signals:
                return
            if signal_type == 'log':
                self.signals.log_signal.emit(args[0] if args else '')
            elif signal_type == 'status':
                self.signals.status_signal.emit(self.name, args[0] if args else False)
            elif signal_type == 'epoch':
                self.signals.epoch_signal.emit(args[0] if args else None)
        except RuntimeError:
            # Signal source has been deleted, silently ignore
            pass
    
    def run(self):
        """
        Main thread execution loop.
        
        Procedure:
          1. Determine data source type (NTRIP or Serial)
          2. Set thread priority to HIGHEST on Windows for low-latency I/O.
          3. Initialize appropriate client (NtripClient or SerialClient)
          4. Enter retry loop: connect → decode RTCM → write to buffers → log statistics.
          5. On connection failure, wait 3s and reconnect.
          6. Exit on stop signal.
        
        Emits:
          - log_signal: Connection status, errors, periodic rate statistics.
          - status_signal: (thread_name, connected_bool) on connection state change.
        """
        # Attempt to raise thread priority on Windows for time-sensitive I/O
        # Higher priority ensures consistent network reception without data loss
        if sys.platform == 'win32':
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                thread_handle = kernel32.OpenThread(0x1F03FF, False, kernel32.GetCurrentThreadId())
                if thread_handle:
                    kernel32.SetThreadPriority(thread_handle, 2)  # THREAD_PRIORITY_HIGHEST
                    kernel32.CloseHandle(thread_handle)
            except:
                pass
        
        # Step 1: Initialize appropriate client based on source type
        if self.source_type == "Serial Port":
            self._run_serial()
        else:
            self._run_ntrip()

    def _run_ntrip(self):
        """NTRIP server data reception loop"""
        # Step 1: Initialize NTRIP client with configuration parameters
        # Raises exception if configuration is invalid (prevents thread from running)
        try:
            self.client = NtripClient(
                self.settings['host'], int(self.settings['port']),
                self.settings['mountpoint'], self.settings['user'], self.settings['password']
            )
        except Exception as e:
            self.signals.log_signal.emit(f"[{self.name}] NTRIP Config Error: {e}")
            return

        # Step 2: Main reception loop with automatic reconnection and error handling
        # Loop continues until stop() is called; connection failures trigger automatic retry
        while self.running:
            try:
                # Step 2a: Log connection attempt
                host_port = f"{self.settings['host']}:{self.settings['port']}"
                mount = self.settings['mountpoint']
                self.signals.log_signal.emit(f"[{self.name}] Connecting to NTRIP {host_port}/{mount}...")
                
                # Step 2b: Attempt to connect to NTRIP server
                sock = self.client.connect()
                if not sock:
                    self.signals.log_signal.emit(f"[{self.name}] NTRIP connection failed. Retry in 3s...")
                    self.signals.status_signal.emit(self.name, False)
                    # Adaptive wait: check stop flag every 100ms during 3-second retry delay
                    # Allows responsive shutdown even during reconnection wait
                    for _ in range(30): 
                        if not self.running: return
                        time.sleep(0.1)
                    continue
                
                # Step 2c: Connected successfully - log and initialize RTCM reader
                self.signals.log_signal.emit(f"[{self.name}] Connected to NTRIP {host_port}/{mount}")
                self.signals.status_signal.emit(self.name, True)
                reader = RTCMReader(sock)
                self.msg_count = 0
                self.last_log_time = time.time()

                # Step 2d: Main reception loop - read RTCM messages and distribute to buffers
                # The IOThread is a pure producer: no message parsing, filtering, or state management
                # All messages go directly to ring_buffer for DataProcessingThread to parse
                for raw, msg in reader:
                    # Check for shutdown signal during message reception
                    if not self.running: break
                    # Skip malformed messages (msg = None if parsing failed at socket level)
                    if msg is None: continue
                    
                    self.msg_count += 1
                    
                    # Periodic statistics logging (every 10 seconds)
                    # Helps monitor connection quality and data throughput
                    now = time.time()
                    if now - self.last_log_time >= 10.0:
                        rate = self.msg_count / (now - self.last_log_time)
                        self.signals.log_signal.emit(
                            f"[{self.name}] NTRIP Receiving: {self.msg_count} msgs, {rate:.1f} msg/s"
                        )
                        self.msg_count = 0
                        self.last_log_time = now
                    
                    # Non-blocking write to processing buffer
                    # This buffer feeds DataProcessingThread for RTCM parsing
                    # Non-blocking: drops oldest message if buffer full (prevents reception stall)
                    self.ring_buffer.put((raw, msg), block=False)
                    
                    # Simultaneous non-blocking write to independent logging buffer
                    # Logging buffer stores raw RTCM data for file recording
                    # Separate from processing buffer to prevent data loss if file I/O lags
                    # Used by LoggingThread for binary RTCM and CSV recording
                    if self.logging_buffer is not None:
                        self.logging_buffer.put((raw, msg), block=False)

            except Exception as e:
                # Connection error: log and signal connection loss
                self.signals.log_signal.emit(f"[{self.name}] NTRIP Error: {str(e)}")
                self.signals.status_signal.emit(self.name, False)
            finally:
                # Step 3: Clean disconnection and retry delay
                # Finally block ensures proper cleanup even after exceptions
                if self.client: 
                    self.client.close()
                try:
                    self.signals.log_signal.emit(f"[{self.name}] NTRIP Connection closed")
                    self.signals.status_signal.emit(self.name, False)
                except RuntimeError:
                    # Signal source has been deleted during shutdown
                    pass
                # Wait 2 seconds before retry to avoid rapid reconnection attempts
                time.sleep(2)

    def _run_serial(self):
        """Serial port data reception loop"""
        # Step 1: Initialize Serial client with configuration parameters
        try:
            port = self.settings['port']  # e.g., 'COM3' or '/dev/ttyUSB0'
            baudrate = int(self.settings.get('baudrate', 115200))
            self.client = SerialClient(port, baudrate=baudrate, timeout=10.0)
        except Exception as e:
            self.signals.log_signal.emit(f"[{self.name}] Serial Config Error: {e}")
            return

        # Step 2: Main reception loop with automatic reconnection and error handling
        while self.running:
            try:
                # Step 2a: Log connection attempt
                port = self.settings['port']
                baudrate = self.settings.get('baudrate', 115200)
                self.signals.log_signal.emit(f"[{self.name}] Connecting to Serial {port}@{baudrate}...")
                
                # Step 2b: Attempt to connect to serial port
                sock = self.client.connect()
                if not sock:
                    self.signals.log_signal.emit(f"[{self.name}] Serial connection failed. Retry in 3s...")
                    self.signals.status_signal.emit(self.name, False)
                    # Adaptive wait: check stop flag every 100ms during 3-second retry delay
                    for _ in range(30): 
                        if not self.running: return
                        time.sleep(0.1)
                    continue
                
                # Step 2c: Connected successfully - log and initialize RTCM reader
                self.signals.log_signal.emit(f"[{self.name}] Connected to Serial {port}@{baudrate}")
                self.signals.status_signal.emit(self.name, True)
                reader = MixedGNSSReader(sock)
                self.msg_count = 0
                self.last_log_time = time.time()

                # Step 2d: Main reception loop - read RTCM messages and distribute to buffers
                for raw, msg in reader:
                    # Check for shutdown signal during message reception
                    if not self.running: break
                    # Keep unknown RTCM frames out of the processing path, but still
                    # allow them to be logged as raw bytes if binary logging is active.
                    if msg is None:
                        if self.logging_buffer is not None and raw and raw[:1] == b'\xd3':
                            self.logging_buffer.put((raw, msg), block=False)
                        continue
                    
                    self.msg_count += 1
                    
                    # Periodic statistics logging (every 10 seconds)
                    now = time.time()
                    if now - self.last_log_time >= 10.0:
                        rate = self.msg_count / (now - self.last_log_time)
                        self.signals.log_signal.emit(
                            f"[{self.name}] Serial Receiving: {self.msg_count} msgs, {rate:.1f} msg/s"
                        )
                        self.msg_count = 0
                        self.last_log_time = now
                    
                    # Non-blocking write to processing buffer
                    self.ring_buffer.put((raw, msg), block=False)
                    
                    # Simultaneous non-blocking write to independent logging buffer
                    if self.logging_buffer is not None and getattr(msg, "protocol", "RTCM") != "UBX":
                        self.logging_buffer.put((raw, msg), block=False)

            except Exception as e:
                # Connection error: log and signal connection loss
                self.signals.log_signal.emit(f"[{self.name}] Serial Error: {str(e)}")
                self.signals.status_signal.emit(self.name, False)
            finally:
                # Step 3: Clean disconnection and retry delay
                if self.client: 
                    self.client.close()
                try:
                    self.signals.log_signal.emit(f"[{self.name}] Serial Connection closed")
                    self.signals.status_signal.emit(self.name, False)
                except RuntimeError:
                    # Signal source has been deleted during shutdown
                    pass
                # Wait 2 seconds before retry to avoid rapid reconnection attempts
                time.sleep(2)

    def stop(self):
        """
        Signal the thread to stop.
        
        The thread will exit at the next iteration of its main loop
        or when waiting for reconnection (within 3 seconds max).
        """
        self.running = False


class RinexReplayThread(threading.Thread):
    """Replay RINEX observation files as pseudo real-time epochs."""

    def __init__(
        self,
        name: str,
        settings: dict,
        signals: StreamSignals,
        handler=None,
        eph_settings: dict | None = None,
        target_systems: list[str] | None = None,
    ):
        super().__init__()
        self.name = name
        self.settings = settings
        self.signals = signals
        self.handler = handler
        self.eph_settings = eph_settings or {}
        self.target_systems = target_systems
        self.daemon = True
        self.running = True
        self.stop_event = threading.Event()
        self._ephemeris_ready = False

    def _emit_log(self, message: str) -> None:
        try:
            self.signals.log_signal.emit(message)
        except RuntimeError:
            pass

    def _emit_status(self, name: str, value: bool) -> None:
        try:
            self.signals.status_signal.emit(name, value)
        except RuntimeError:
            pass

    def _emit_epoch(self, epoch) -> None:
        try:
            self.signals.epoch_signal.emit(epoch)
        except RuntimeError:
            pass

    def _resolve_receiver_position(self, metadata):
        config = get_global_config()
        approx = getattr(config, "approx_rec_pos", None)
        if approx and len(approx) >= 3 and any(abs(float(item)) > 1e-6 for item in approx[:3]):
            return [float(approx[0]), float(approx[1]), float(approx[2])]

        if metadata.has_nonzero_approx_position:
            coords = list(metadata.approx_position_ecef)
            try:
                config.update_general_settings({"approx_rec_pos": coords})
            except Exception:
                pass
            self._emit_log(f"[{self.name}] Receiver position loaded from RINEX header")
            return coords

        raise ValueError(
            "RINEX header APPROX POSITION XYZ is zero. Please set receiver ECEF coordinates manually in the config."
        )

    def _load_ephemeris_provider(self):
        file_path = str(self.eph_settings.get("file_path", "")).strip()
        if not file_path:
            return None

        file_type = str(self.eph_settings.get("file_type", "Auto Detect"))
        provider = FileEphemerisProvider.from_file(
            file_path,
            file_type=file_type,
            broadcast_ephemeris=getattr(self.handler, "broadcast_eph", None),
        )
        self._ephemeris_ready = True
        self._emit_status("EPH_DATA", True)
        self._emit_log(
            f"[{self.name}] Loaded {'precise SP3' if provider.kind == 'precise' else 'broadcast RINEX'} ephemeris: {file_path}"
        )
        return provider

    @staticmethod
    def _normalize_replay_speed(value) -> float:
        try:
            replay_speed = float(value or 1.0)
        except (TypeError, ValueError):
            replay_speed = 1.0
        return replay_speed if replay_speed > 0.0 else 1.0

    @staticmethod
    def _epoch_source_delta_seconds(previous_epoch_time, current_epoch_time, interval_hint: float) -> float:
        safe_interval = max(1e-3, float(interval_hint or 1.0))
        if previous_epoch_time is None:
            return 0.0
        if current_epoch_time is None:
            return safe_interval

        delta_seconds = (current_epoch_time - previous_epoch_time).total_seconds()
        if delta_seconds <= 0.0:
            return safe_interval
        return float(delta_seconds)

    @staticmethod
    def _target_replay_deadline(
        replay_start_monotonic: float,
        accumulated_source_seconds: float,
        replay_speed: float,
    ) -> float:
        safe_speed = replay_speed if replay_speed > 0.0 else 1.0
        return replay_start_monotonic + (max(0.0, accumulated_source_seconds) / safe_speed)

    def run(self):
        obs_path = str(self.settings.get("file_path", "")).strip()
        if not obs_path:
            self._emit_log(f"[{self.name}] RINEX Config Error: observation file is not set")
            return

        try:
            metadata = read_rinex_observation_header(obs_path)
            receiver_position = self._resolve_receiver_position(metadata)
            ephemeris_provider = self._load_ephemeris_provider()

            replay_speed = self._normalize_replay_speed(self.settings.get("replay_speed", 1.0))

            reader = RinexObservationReader(obs_path)
            self._emit_log(
                f"[{self.name}] Replaying RINEX file at {replay_speed:.1f}x"
                + (f" (header interval {metadata.interval_seconds:g}s)" if metadata.interval_seconds else "")
            )
            self._emit_status(self.name, True)

            previous_epoch_time = None
            interval_hint = max(1e-3, float(metadata.interval_seconds or 1.0))
            epoch_count = 0
            replay_start_monotonic = time.perf_counter()
            accumulated_source_seconds = 0.0

            for epoch in reader.iter_epochs(
                ephemeris_provider=ephemeris_provider,
                receiver_position_ecef=receiver_position,
                target_systems=self.target_systems,
            ):
                if not self.running:
                    break

                accumulated_source_seconds += self._epoch_source_delta_seconds(
                    previous_epoch_time,
                    epoch.utc_datetime,
                    interval_hint,
                )
                target_deadline = self._target_replay_deadline(
                    replay_start_monotonic,
                    accumulated_source_seconds,
                    replay_speed,
                )
                wait_seconds = target_deadline - time.perf_counter()
                if wait_seconds > 0.0 and self.stop_event.wait(wait_seconds):
                        break

                previous_epoch_time = epoch.utc_datetime
                epoch_count += 1
                self._emit_epoch(epoch)

                if epoch_count == 1:
                    self._emit_log(f"[{self.name}] First replay epoch emitted: {len(epoch.satellites)} satellites")
                elif epoch_count % 100 == 0:
                    self._emit_log(f"[{self.name}] Replay progress: {epoch_count} epochs")

            if self.running:
                self._emit_log(f"[{self.name}] RINEX replay completed")

        except Exception as exc:
            self._emit_log(f"[{self.name}] RINEX Replay Error: {exc}")
            import traceback
            self._emit_log(f"[{self.name}] Traceback: {traceback.format_exc()}")
        finally:
            self._emit_status(self.name, False)
            if self._ephemeris_ready:
                self._emit_status("EPH_DATA", False)

    def stop(self):
        self.running = False
        self.stop_event.set()


class DataProcessingThread(threading.Thread):
    """
    RTCM parsing and epoch assembly thread.

    Consumes raw RTCM messages from the ring buffer, updates ephemeris state,
    and emits complete observation epochs to the UI layer.

    This thread is CPU-bound and independent of I/O and logging.
    """
    
    def __init__(self, name: str, ring_buffer: RingBuffer, handler, signals: StreamSignals):
        """
        Initialize the DataProcessingThread.
        
        Args:
            name: Thread identifier string.
            ring_buffer: RingBuffer containing (raw_bytes, RTCMMessage) tuples.
            handler: RTCMHandler instance for message parsing and ephemeris management.
            signals: StreamSignals object for Qt signal emission.
        """
        super().__init__()
        self.name = name
        self.ring_buffer = ring_buffer
        self.handler = handler
        self.signals = signals
        self.daemon = True
        self.running = True
        self.epoch_count = 0
        self.msg_count = 0
        self.msg_types = {}  # Track message types
        self.eph_count = 0
        self.eph_status_reported = False
        self.last_log_time = time.time()
        self.first_epoch = True
        # Pending partial epoch merging: gps_time -> {'epoch': EpochObservation, 'last_update': time.time()}
        self.pending_epochs = {}
        # Merge timeout in seconds: wait this long for additional system messages for same epoch
        self.EPOCH_MERGE_TIMEOUT = 0.15
        
    def run(self):
        """
        Main processing loop: consume RTCM messages, parse, and emit epochs.
        
        Procedure:
        1. Wait for (raw, msg) from ring_buffer (blocking with 100ms timeout)
        2. Extract message type ID (1019/1020/1042/1045/1046/63 are ephemeris)
        3. Pass msg to handler.process_message() for parsing and buffering
        4. If epoch_data returned (complete observation set), emit epoch_signal
        5. Every 30 seconds, log statistics: epoch rate, message types, ephemeris count
        """
        self.signals.log_signal.emit(f"[{self.name}] Processing thread started")
        while self.running:
            try:
                # Step 1: Blocking get from ring_buffer with timeout
                # Blocks up to 100ms if no data available, allows responsive shutdown
                data = self.ring_buffer.get(block=True, timeout=0.1)
                
                # Check if buffer is closed or empty
                if data is None:
                    if self.ring_buffer.closed:
                        self.signals.log_signal.emit(f"[{self.name}] Buffer closed, stopping")
                        break
                    continue
                
                # Step 2: Unpack RTCM message tuple and track it
                raw, msg = data
                self.msg_count += 1
                
                # Extract message type ID for statistics tracking
                if msg is None:
                    continue

                msg_id = getattr(msg, 'identity', 'UNKNOWN')
                self.msg_types[msg_id] = self.msg_types.get(msg_id, 0) + 1
                
                # Track ephemeris vs observation messages
                # Message types: 1019=GPS EPH, 1020=GLONASS EPH, 1042=BDS EPH, 1045=Galileo EPH, 1046=Galileo EPH
                if msg_id in ["1019", "1020", "1041", "1042", "1044", "1045", "1046", "63", "SBAS_RAW_9"]:
                    self.eph_count += 1
                    if not self.eph_status_reported:
                        self.signals.status_signal.emit("EPH_DATA", True)
                        self.eph_status_reported = True
                
                # Step 3: Process RTCM message through handler
                # Handler manages ephemeris caching and emits EpochObservation when all satellites for epoch are received
                epoch_data = self.handler.process_message(msg)

                # Step 4: If handler returned an EpochObservation, merge by gps_time
                if epoch_data:
                    key = float(getattr(epoch_data, 'gps_time', 0.0))
                    nowt = time.time()
                    if key in self.pending_epochs:
                        # Merge satellites and signals into pending epoch
                        pending = self.pending_epochs[key]
                        existing = pending['epoch']
                        # Merge satellite dictionaries (overwrite/extend)
                        for sat_k, sat_v in epoch_data.satellites.items():
                            existing.satellites[sat_k] = sat_v
                        pending['last_update'] = nowt
                    else:
                        # New pending epoch
                        self.pending_epochs[key] = {'epoch': epoch_data, 'last_update': nowt}

                # Emit pending epochs that have not been updated recently (merge timeout)
                to_emit = []
                tnow = time.time()
                for k, info in list(self.pending_epochs.items()):
                    if tnow - info['last_update'] >= self.EPOCH_MERGE_TIMEOUT:
                        to_emit.append(k)

                for k in to_emit:
                    info = self.pending_epochs.pop(k, None)
                    if info is None: continue
                    epoch_out = info['epoch']
                    self.epoch_count += 1
                    if self.first_epoch:
                        n_sats = len(epoch_out.satellites)
                        n_sigs = sum(len(sat.signals) for sat in epoch_out.satellites.values())
                        self.signals.log_signal.emit(
                            f"[{self.name}] First epoch received (merged): {n_sats} satellites, {n_sigs} signals"
                        )
                        self.first_epoch = False
                    # Emit merged epoch
                    self.signals.epoch_signal.emit(epoch_out)
                
                # Step 5: Periodic statistics output every 30 seconds
                now = time.time()
                if now - self.last_log_time >= 30.0:
                    # Compute rates: epochs per second, messages per second
                    epoch_rate = self.epoch_count / (now - self.last_log_time)
                    msg_rate = self.msg_count / (now - self.last_log_time)
                    # Get top 5 message types by frequency
                    top_msgs = sorted(self.msg_types.items(), key=lambda x: x[1], reverse=True)[:5]
                    msg_summary = ', '.join([f"#{k}({v})" for k, v in top_msgs])
                    self.signals.log_signal.emit(
                        f"[{self.name}] Stats: {self.msg_count} msgs ({msg_rate:.1f}/s), "
                        f"{self.epoch_count} epochs ({epoch_rate:.2f}/s), "
                        f"{self.eph_count} eph, Top: {msg_summary}"
                    )
                    # Reset counters for next statistics window
                    self.msg_count = 0
                    self.epoch_count = 0
                    self.eph_count = 0
                    self.msg_types.clear()
                    self.last_log_time = now
                    
            except Exception as e:
                # Log exception with full traceback for debugging
                self.signals.log_signal.emit(f"[{self.name}] Processing Error: {str(e)}")
                import traceback
                self.signals.log_signal.emit(f"[{self.name}] Traceback: {traceback.format_exc()}")
                time.sleep(0.01)  # Brief sleep to prevent error spam 
    
    def stop(self):
        self.running = False


class LoggingThread(threading.Thread):
    """
    Asynchronous logging thread for GNSS monitoring data.

    Supported formats:
    - binary: raw RTCM stream
    - csv: sampled satellite observations
    - rinex: RINEX 3.04 observation files
    
    Features:
    - File rotation based on time intervals
    - File count tracking
    - Duration tracking
    - Real-time status reporting
    """
    
    def __init__(self, settings: dict, ring_buffers: dict, merged_satellites: dict, signals: StreamSignals, logging_buffer: RingBuffer = None, get_latest_epoch=None):
        """
        Initialize logging thread.
        
        Args:
            settings: Logging configuration dict with keys:
                - directory: str (output path)
                - split_minutes: int (file rotation interval)
                - sample_interval: int (sampling interval in seconds)
                - format: str ('csv', 'binary', 'rinex')
                - fields: list (CSV fields to save)
            ring_buffers: dict mapping stream names ('OBS', 'EPH') to RingBuffer objects
            merged_satellites: dict reference to monitoring_module's merged_satellites
            signals: StreamSignals instance for emitting log messages
            logging_buffer: RingBuffer专用的logging缓冲区（Binary格式时使用）
            get_latest_epoch: Optional callable that returns the latest EpochObservation
        """
        super().__init__()
        self.settings = settings
        self.ring_buffers = ring_buffers
        self.merged_satellites = merged_satellites
        self.signals = signals
        self.logging_buffer = logging_buffer
        self.get_latest_epoch = get_latest_epoch
        self.daemon = True
        self.running = True
        self.stop_event = threading.Event()
        
        # File tracking attributes
        self.file_count = 0
        self.start_time = time.time()
        self.current_filename = ""
        self.last_rinex_epoch_time = None
        
    def get_file_count(self):
        """Get the number of files created so far."""
        return self.file_count
    
    def get_duration(self):
        """Get the recording duration in seconds."""
        return time.time() - self.start_time
    
    def get_current_filename(self):
        """Get the current filename being written to."""
        return self.current_filename

    @staticmethod
    def _normalize_utc_datetime(epoch_time: datetime) -> datetime:
        """Convert aware datetimes to naive UTC for internal epoch alignment."""
        if epoch_time.tzinfo is None:
            return epoch_time
        return epoch_time.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _round_time_to_interval(epoch_time: datetime, sample_interval: int) -> datetime:
        """Round a UTC datetime to the nearest sampling boundary."""
        epoch_time = LoggingThread._normalize_utc_datetime(epoch_time)
        interval = max(1, int(sample_interval))
        anchor = datetime(1980, 1, 6)
        total_seconds = (epoch_time - anchor).total_seconds()
        rounded_seconds = round(total_seconds / interval) * interval
        rounded_time = anchor + timedelta(seconds=rounded_seconds)
        return rounded_time.replace(microsecond=0)

    def _align_epoch_time(self, epoch_time: datetime, sample_interval: int) -> datetime | None:
        """Return an aligned epoch time if the epoch is on a sample boundary."""
        epoch_time = self._normalize_utc_datetime(epoch_time)
        aligned_time = self._round_time_to_interval(epoch_time, sample_interval)
        if abs((epoch_time - aligned_time).total_seconds()) > 1e-3:
            return None
        return aligned_time

    def _get_latest_epoch_data(self):
        """Fetch the latest epoch snapshot if the callback is available."""
        if not self.get_latest_epoch:
            return None
        try:
            return self.get_latest_epoch()
        except Exception:
            return None

    def _get_initial_rinex_file_time(self, sample_interval: int) -> datetime:
        """Choose a stable UTC start time for the RINEX long filename."""
        if self.last_rinex_epoch_time is not None:
            last_epoch_time = self._normalize_utc_datetime(self.last_rinex_epoch_time)
            return last_epoch_time + timedelta(seconds=max(1, int(sample_interval)))

        epoch_data = self._get_latest_epoch_data()
        epoch_time = getattr(epoch_data, 'utc_datetime', None) if epoch_data else None
        if epoch_time:
            aligned_time = self._align_epoch_time(epoch_time, sample_interval)
            if aligned_time:
                return aligned_time

        return self._round_time_to_interval(datetime.now(timezone.utc), sample_interval)

    def _update_rinex_writer_position(self, rinex_writer: RINEX3Writer) -> None:
        """Push the latest station ECEF coordinates into the RINEX header state."""
        approx_pos = getattr(get_global_config(), 'approx_rec_pos', None)
        try:
            if approx_pos and any(abs(float(v)) > 0.0 for v in approx_pos[:3]):
                rinex_writer.set_approx_position(approx_pos)
        except (TypeError, ValueError):
            return
    
    def run(self):
        """
        Main logging worker loop: manage file operations and data writing.
        
        Procedure:
        1. Configure logging parameters: file path, format, rotation settings
        2. Open initial log file with timestamp-based naming
        3. Main loop: monitor for file rotation and write data periodically
        4. For binary format: write raw RTCM messages immediately
        5. For CSV/RINEX format: sample and write satellite data at specified interval
        6. Close file gracefully on shutdown
        """
        settings = self.settings
        split_secs = int(settings.get('split_minutes', 60)) * 60  # File rotation period in seconds
        sample_interval = int(settings.get('sample_interval', 1))  # CSV sampling period in seconds
        fields = settings.get('fields', [])                        # Selected fields for CSV output
        format_type = settings.get('format', 'csv')                # Output format: 'csv', 'binary', 'rinex'
        out_path = settings.get('directory', '')                   # Output directory path
        
        # Validate output directory
        if not out_path or not os.path.isdir(out_path):
            self.signals.log_signal.emit(f"[Logging] Error: Invalid output directory: {out_path}")
            return
        
        current_file = None
        writer = None
        rinex_writer = None
        file_start = 0
        last_sample_time = time.time()  # Track time for CSV sampling interval
        
        def open_new_file():
            """Open a new log file with timestamp and write appropriate header."""
            nonlocal current_file, writer, rinex_writer, file_start
            
            try:
                # Step 1: Generate timestamp-based filename
                ts = time.gmtime(time.time())
                name_time = time.strftime("%Y%m%d_%H%M%S", ts)
                
                # Extract mount point name from configuration
                config = get_global_config()
                mount = getattr(config.obs_settings, 'mountpoint', None) or 'UNKNOWN'
                safe_mount = ''.join(c for c in str(mount) if c.isalnum() or c in ('_', '-')) or 'UNKNOWN'
                
                # Step 2: Determine file extension based on format type
                if format_type == 'csv':
                    ext = 'csv'
                elif format_type == 'binary':
                    ext = 'rtcm'
                elif format_type == 'rinex':
                    ext = 'rnx'
                else:
                    ext = 'csv'  # fallback to csv
                
                # Step 3: Construct full file path and open for writing
                fname = f"{safe_mount}_{name_time}.{ext}"
                path = os.path.join(out_path, fname)
                
                # Increment file counter
                self.file_count += 1
                
                # Open file based on format (binary vs text mode)
                if format_type == 'binary':
                    # Binary mode for raw RTCM data with large buffer
                    current_file = open(path, 'wb', buffering=65536)  # 64KB buffer
                    writer = None
                    rinex_writer = None
                elif format_type == 'rinex':
                    # RINEX3 format: use standard long filenames derived from the
                    # actual logging cadence instead of the UI free-text fields.
                    split_period = RINEX3Writer.format_period_code(
                        split_secs,
                        settings.get('rinex_options', {}).get('period', '01D'),
                    )
                    sample_code = RINEX3Writer.format_interval_code(sample_interval)
                    file_time = self._get_initial_rinex_file_time(sample_interval)
                    rinex_opts = {
                        'station_code': settings.get('rinex_options', {}).get('station_code', 'RTGS'),
                        'receiver_number': settings.get('rinex_options', {}).get('receiver_number', '00'),
                        'country_code': settings.get('rinex_options', {}).get('country_code', 'CHN'),
                        'period': split_period,
                        'interval': sample_code,
                        'datatype': settings.get('rinex_options', {}).get('datatype', 'MO'),
                        'file_time': file_time,
                    }

                    marker_name = rinex_opts['station_code'] or safe_mount
                    rinex_writer = RINEX3Writer(
                        out_path,
                        marker_name=marker_name,
                        marker_number="0",
                        **rinex_opts,
                    )
                    if not rinex_writer.open():
                        raise Exception(f"Failed to open RINEX file: {rinex_writer.filename}")

                    self._update_rinex_writer_position(rinex_writer)
                    latest_epoch = self._get_latest_epoch_data()
                    latest_satellites = getattr(latest_epoch, 'satellites', None) if latest_epoch else None
                    obs_source = self.merged_satellites if self.merged_satellites else latest_satellites
                    sys_obs_types = self._detect_obs_types(obs_source)
                    if not rinex_writer.write_header(
                        sys_obs_types=sys_obs_types,
                        receiver_type="Generic",
                        antenna_type="UNKNOWN",
                    ):
                        raise Exception("Failed to write RINEX header")

                    fname = os.path.basename(rinex_writer.filename)
                    self.current_filename = fname
                    current_file = None
                    writer = None
                else:
                    # Text mode for CSV format
                    current_file = open(path, 'a', newline='', encoding='utf-8', buffering=65536)
                    writer = csv.writer(current_file)
                    rinex_writer = None
                    self.current_filename = fname
                    # CSV header row: field names
                    if writer:
                        writer.writerow(fields)

                if format_type == 'binary':
                    self.current_filename = fname
                
                file_start = time.time()
                self.signals.log_signal.emit(
                    f"[Logging] Opened: {self.current_filename} (format: {format_type}, File #{self.file_count})"
                )
                return current_file, writer, rinex_writer
                
            except Exception as e:
                self.signals.log_signal.emit(f"[Logging] Error opening file: {e}")
                return None, None, None
        
        # Step 1: Open first log file. RINEX waits for the first real epoch so the
        # long filename and header can use the actual observation start time.
        if format_type == 'rinex':
            current_file, writer, rinex_writer = None, None, None
            file_start = time.time()
        else:
            current_file, writer, rinex_writer = open_new_file()
            if current_file is None:
                return
        
        # Add initial status signal with start time
        self.signals.log_signal.emit(f"[Logging] Started recording at {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(self.start_time))}")
        
        # Step 2: Main logging loop
        while self.running and not self.stop_event.is_set():
            try:
                if format_type == 'rinex' and rinex_writer is None:
                    latest_epoch = self._get_latest_epoch_data()
                    latest_satellites = getattr(latest_epoch, 'satellites', None) if latest_epoch else None
                    latest_epoch_time = getattr(latest_epoch, 'utc_datetime', None) if latest_epoch else None
                    aligned_latest_time = (
                        self._align_epoch_time(latest_epoch_time, sample_interval)
                        if latest_epoch_time else None
                    )
                    if (
                        not latest_satellites
                        or aligned_latest_time is None
                        or aligned_latest_time == self.last_rinex_epoch_time
                    ):
                        time.sleep(0.1)
                        continue

                    current_file, writer, rinex_writer = open_new_file()
                    if rinex_writer is None:
                        break
                    file_start = time.time()

                # Step 2a: Check if file rotation is needed (split_minutes elapsed)
                if time.time() - file_start >= split_secs:
                    try:
                        if format_type == 'rinex' and rinex_writer:
                            rinex_writer.close()
                        elif current_file:
                            current_file.close()
                    except:
                        pass
                    if format_type == 'rinex':
                        current_file, writer, rinex_writer = None, None, None
                        file_start = time.time()
                    else:
                        # Open new file with new timestamp
                        current_file, writer, rinex_writer = open_new_file()
                        if current_file is None:
                            break
                        last_sample_time = time.time()
                
                # Step 2b: Write data based on format type
                current_time = time.time()
                if format_type == 'binary':
                    # Binary format: write raw RTCM messages in real-time without sampling
                    # Directly reads from logging_buffer and writes to file
                    self._save_binary_rtcm(current_file)
                    # Brief sleep to prevent CPU spinning while waiting for data
                    time.sleep(0.01)
                else:
                    if format_type == 'rinex':
                        # RINEX output is driven by the epoch timestamp itself rather than
                        # wall-clock polling so the header/body remain aligned to true epochs.
                        self._save_rinex_obs(rinex_writer, sample_interval)
                        time.sleep(0.1)
                    elif current_time - last_sample_time >= sample_interval:
                        # CSV format: sample and write satellite data at specified interval
                        self._save_csv_obs(current_file, writer, fields)
                        last_sample_time = current_time
                        # Longer sleep for text formats since sampling is lower frequency
                        time.sleep(0.1)
                    else:
                        time.sleep(0.1)
                    
            except Exception as e:
                # Log any errors but keep thread running
                self.signals.log_signal.emit(f"[Logging] Error in logging loop: {e}")
                import traceback
                self.signals.log_signal.emit(f"[Logging] Traceback: {traceback.format_exc()}")
                time.sleep(1)
        
        # Step 3: Cleanup on shutdown
        if format_type == 'rinex' and rinex_writer:
            rinex_writer.close()
        elif current_file:
            current_file.close()
        
        duration = time.time() - self.start_time
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_str = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
        
        self.signals.log_signal.emit(f"[Logging] Logging thread stopped. Total files: {self.file_count}, Duration: {duration_str}")
    
    def _save_binary_rtcm(self, file_handle):
        """
        Save raw RTCM binary data directly from ring buffers.
        
        Uses dedicated logging_buffer if available to avoid data loss.
        Falls back to shared OBS buffer if logging_buffer not available.
        """
        try:
            # 优先使用独立的logging buffer（不与DataProcessingThread竞争）
            buffer = self.logging_buffer or self.ring_buffers.get('OBS')
            
            if buffer is None:
                return
            
            # 持续读取，直到缓冲区空
            count = 0
            bytes_written = 0
            
            while True:
                try:
                    data = buffer.get(block=False)
                    if data is None:
                        break
                    
                    raw, msg = data
                    if raw is not None:
                        # Write raw binary RTCM data immediately
                        file_handle.write(raw)
                        bytes_written += len(raw)
                        count += 1
                except:
                    break
            
            # Flush after writing batch (更频繁的flush确保数据不丢失)
            if count > 0:
                file_handle.flush()
                    
        except Exception as e:
            self.signals.log_signal.emit(f"[Logging] Error saving binary RTCM: {e}")
    
    def _detect_obs_types(self, satellites=None) -> dict:
        """
        Auto-detect observation types from a satellite-state mapping.
        
        Scans the provided satellite mapping and extracts signal codes to build
        the ``sys_obs_types`` dictionary.
        Falls back to standard defaults if no signals are found.
        
        Returns:
            Dict mapping system (e.g., 'G', 'R') to list of observation codes
            e.g., {'G': ['C1C', 'L1C', 'D1C', 'S1C']}
        """
        sys_obs_types: dict = {}
        obs_codes_per_sys: dict = {}
        
        source_satellites = satellites if satellites is not None else self.merged_satellites

        # Scan all satellites to collect raw signal IDs
        try:
            for sat_id, sat_state in source_satellites.items():
                if not sat_id or len(sat_id) < 2:
                    continue

                sys = sat_id[0]
                if sys not in obs_codes_per_sys:
                    obs_codes_per_sys[sys] = set()

                signals = getattr(sat_state, 'signals', {})
                if isinstance(signals, dict):
                    for sig_id in signals.keys():
                        obs_codes_per_sys[sys].add(sig_id)
        except Exception as e:
            self.signals.log_signal.emit(f"[Logging] Warning: Error scanning satellites for obs types: {e}")

        # Convert raw signal IDs into RINEX observation codes
        for sys, sig_ids in obs_codes_per_sys.items():
            obs_list: List[str] = []
            for sig in sorted(sig_ids):
                # append code, phase, doppler, snr for each signal
                obs_list.append(f"C{sig}")
                obs_list.append(f"L{sig}")
                obs_list.append(f"D{sig}")
                obs_list.append(f"S{sig}")
            if obs_list:  # Only add if we found signals for this system
                sys_obs_types[sys] = obs_list

        # Provide standard defaults if nothing was detected
        if not sys_obs_types:
            # Default observation types for common systems
            sys_obs_types = {
                'G': ['C1C', 'L1C', 'D1C', 'S1C'],  # GPS L1
                'R': ['C4A', 'L4A', 'D4A', 'S4A'],  # GLONASS
                'E': ['C1C', 'L1C', 'D1C', 'S1C'],  # Galileo E1
                'C': ['C2D', 'L2D', 'D2D', 'S2D'],  # BeiDou B1I
                'J': ['C1C', 'L1C', 'D1C', 'S1C'],  # QZSS L1
                'S': ['C1C', 'L1C', 'D1C', 'S1C'],  # SBAS L1
                'I': ['C5A', 'L5A', 'D5A', 'S5A'],  # IRNSS L5
            }
        
        return sys_obs_types
    
    def _save_rinex_obs(self, rinex_writer, sample_interval):
        """
        Save observation data in RINEX 3 format.
        
        Args:
            rinex_writer: RINEX3Writer instance
        """
        try:
            epoch_data = self._get_latest_epoch_data()
            if not epoch_data:
                return

            snapshot = dict(getattr(epoch_data, 'satellites', {}) or {})
            if not snapshot:
                return

            epoch_time = getattr(epoch_data, 'utc_datetime', None)
            if not epoch_time:
                return

            aligned_epoch_time = self._align_epoch_time(epoch_time, sample_interval)
            if aligned_epoch_time is None:
                return

            if self.last_rinex_epoch_time == aligned_epoch_time:
                return

            self._update_rinex_writer_position(rinex_writer)

            if not rinex_writer.header_written:
                self.signals.log_signal.emit(f"[Logging] Warning: RINEX header not written before first observation")
                return

            success = rinex_writer.write_observation(aligned_epoch_time, snapshot)
            if not success:
                self.signals.log_signal.emit(f"[Logging] Warning: Failed to write RINEX observation epoch")
                return

            self.last_rinex_epoch_time = aligned_epoch_time
             
        except Exception as e:
            self.signals.log_signal.emit(f"[Logging] Error saving RINEX observation: {e}")
            import traceback
            self.signals.log_signal.emit(f"[Logging] Traceback: {traceback.format_exc()}")
    
    def _save_csv_obs(self, file_handle, writer, fields):
        """
        Save observation data in CSV format.
        
        Args:
            file_handle: Open file handle
            writer: CSV writer object
            fields: List of field names to save
        """
        try:
            # Get snapshot of current satellite data
            snapshot = dict(self.merged_satellites)
            
            # Get latest epoch data for UTC time
            epoch_data = None
            utc_datetime = None
            if self.get_latest_epoch:
                epoch_data = self.get_latest_epoch()
                if epoch_data:
                    utc_datetime = getattr(epoch_data, 'utc_datetime', None)
            
            # Format UTC time string: YYYY-MM-DD HH:MM:SS
            utc_time_str = utc_datetime.strftime('%Y-%m-%d %H:%M:%S') if utc_datetime else ''
            
            rows = []
            sys_map = {'G': 'GPS', 'R': 'GLO', 'E': 'GAL', 'C': 'BDS', 'J': 'QZS', 'S': 'SBS'}
            
            for key, sat in sorted(snapshot.items()):
                sys_char = key[0]
                el = getattr(sat, 'el', getattr(sat, 'elevation', 0)) or 0
                az = getattr(sat, 'az', getattr(sat, 'azimuth', 0)) or 0
                
                # Process all signals for this satellite
                sorted_codes = sorted(sat.signals.keys())
                if not sorted_codes:
                    continue
                
                for code in sorted_codes:
                    sig = sat.signals.get(code)
                    if not sig:
                        continue
                    
                    snr = getattr(sig, 'snr', 0) or 0
                    pr = getattr(sig, 'pseudorange', None)
                    ph = getattr(sig, 'phase', None)
                    doppler = getattr(sig, 'doppler', 0) or 0
                    
                    # Build value map for flexible field selection
                    # Include UTC time fields
                    valmap = {
                        'UTC Time': utc_time_str,
                        'PRN': key,
                        'Sys': sys_map.get(sys_char, sys_char),
                        'El(°)': f"{el:.1f}",
                        'Az(°)': f"{az:.1f}",
                        'Freq': code,
                        'SNR (dBHz)': f"{snr:.1f}",
                        'Pseudorange (m)': f"{(pr if pr is not None else '')}",
                        'Phase (cyc)': f"{(ph if ph is not None else '')}",
                        'Doppler (Hz)': f"{doppler:.3f}"
                    }
                    
                    row = [valmap.get(f, '') for f in fields]
                    rows.append(row)
            
            # Write rows in CSV format
            for row in rows:
                writer.writerow(row)
            
            if rows:
                file_handle.flush()
                
        except Exception as e:
            self.signals.log_signal.emit(f"[Logging] Error saving CSV observation: {e}")
    
    def stop(self):
        """Stop the logging thread gracefully."""
        self.running = False
        self.stop_event.set()
