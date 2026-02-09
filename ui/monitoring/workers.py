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
from PySide6.QtCore import QObject, Signal
from pyrtcm import RTCMReader

from core.global_config import get_global_config
from core.ntrip_client import NtripClient
from core.serial_client import SerialClient
from core.ring_buffer import RingBuffer


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
                    self.signals.log_signal.emit(f"[{self.name}] NTRIP Connection closed")
                self.signals.status_signal.emit(self.name, False)
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
                reader = RTCMReader(sock)
                self.msg_count = 0
                self.last_log_time = time.time()

                # Step 2d: Main reception loop - read RTCM messages and distribute to buffers
                for raw, msg in reader:
                    # Check for shutdown signal during message reception
                    if not self.running: break
                    # Skip malformed messages (msg = None if parsing failed at socket level)
                    if msg is None: continue
                    
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
                    if self.logging_buffer is not None:
                        self.logging_buffer.put((raw, msg), block=False)

            except Exception as e:
                # Connection error: log and signal connection loss
                self.signals.log_signal.emit(f"[{self.name}] Serial Error: {str(e)}")
                self.signals.status_signal.emit(self.name, False)
            finally:
                # Step 3: Clean disconnection and retry delay
                if self.client: 
                    self.client.close()
                    self.signals.log_signal.emit(f"[{self.name}] Serial Connection closed")
                self.signals.status_signal.emit(self.name, False)
                # Wait 2 seconds before retry to avoid rapid reconnection attempts
                time.sleep(2)

    def stop(self):
        """
        Signal the thread to stop.
        
        The thread will exit at the next iteration of its main loop
        or when waiting for reconnection (within 3 seconds max).
        """
        self.running = False


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
        self.last_log_time = time.time()
        self.first_epoch = True
        
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
                msg_id = getattr(msg, 'identity', 'UNKNOWN')
                self.msg_types[msg_id] = self.msg_types.get(msg_id, 0) + 1
                
                # Track ephemeris vs observation messages
                # Message types: 1019=GPS EPH, 1020=GLONASS EPH, 1042=BDS EPH, 1045=Galileo EPH, 1046=Galileo EPH
                if msg_id in ["1019", "1020", "1042", "1045", "1046", "63"]:
                    self.eph_count += 1
                
                # Step 3: Process RTCM message through handler
                # Handler manages ephemeris caching and emits EpochObservation when all satellites for epoch are received
                epoch_data = self.handler.process_message(msg)
                
                # Step 4: If epoch complete (all satellites for time instant), emit epoch signal to UI
                if epoch_data:
                    self.epoch_count += 1
                    if self.first_epoch:
                        # Log summary of first received epoch
                        n_sats = len(epoch_data.satellites)
                        n_sigs = sum(len(sat.signals) for sat in epoch_data.satellites.values())
                        self.signals.log_signal.emit(
                            f"[{self.name}] First epoch received: {n_sats} satellites, {n_sigs} signals"
                        )
                        self.first_epoch = False
                    self.signals.epoch_signal.emit(epoch_data)
                
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
    - rinex: simplified RINEX-like text output
    
    Features:
    - File rotation based on time intervals
    - File count tracking
    - Duration tracking
    - Real-time status reporting
    """
    
    def __init__(self, settings: dict, ring_buffers: dict, merged_satellites: dict, signals: StreamSignals, logging_buffer: RingBuffer = None):
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
        """
        super().__init__()
        self.settings = settings
        self.ring_buffers = ring_buffers
        self.merged_satellites = merged_satellites
        self.signals = signals
        self.logging_buffer = logging_buffer
        self.daemon = True
        self.running = True
        self.stop_event = threading.Event()
        
        # File tracking attributes
        self.file_count = 0
        self.start_time = time.time()
        self.current_filename = ""
        
    def get_file_count(self):
        """Get the number of files created so far."""
        return self.file_count
    
    def get_duration(self):
        """Get the recording duration in seconds."""
        return time.time() - self.start_time
    
    def get_current_filename(self):
        """Get the current filename being written to."""
        return self.current_filename
    
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
        file_start = 0
        last_sample_time = time.time()  # Track time for CSV sampling interval
        
        def open_new_file():
            """Open a new log file with timestamp and write appropriate header."""
            nonlocal current_file, writer, file_start
            
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
                
                # Store current filename for status reporting
                self.current_filename = fname
                
                # Increment file counter
                self.file_count += 1
                
                # Open file based on format (binary vs text mode)
                if format_type == 'binary':
                    # Binary mode for raw RTCM data with large buffer
                    current_file = open(path, 'wb', buffering=65536)  # 64KB buffer
                    writer = None
                else:
                    # Text mode for CSV/RINEX formats
                    current_file = open(path, 'a', newline='', encoding='utf-8', buffering=65536)
                    writer = csv.writer(current_file)
                
                # Step 4: Write format-specific headers
                if format_type == 'csv':
                    # CSV header row: field names
                    if writer:
                        writer.writerow(fields)
                elif format_type == 'rinex':
                    # RINEX-like simplified header with metadata
                    current_file.write("# RINEX3 (not support now)\n")
                    current_file.write(f"# Mountpoint: {mount}\n")
                    current_file.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    current_file.write("# Fields: " + ",".join(fields) + "\n")
                elif format_type == 'binary':
                    # Binary RTCM files have no header (raw data only)
                    pass
                
                file_start = time.time()
                self.signals.log_signal.emit(f"[Logging] Opened: {fname} (format: {format_type}, File #{self.file_count})")
                return current_file, writer
                
            except Exception as e:
                self.signals.log_signal.emit(f"[Logging] Error opening file: {e}")
                return None, None
        
        # Step 1: Open first log file
        current_file, writer = open_new_file()
        if current_file is None:
            return
        
        # Add initial status signal with start time
        self.signals.log_signal.emit(f"[Logging] Started recording at {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(self.start_time))}")
        
        # Step 2: Main logging loop
        while self.running and not self.stop_event.is_set():
            try:
                # Step 2a: Check if file rotation is needed (split_minutes elapsed)
                if time.time() - file_start >= split_secs:
                    try:
                        current_file.close()
                    except:
                        pass
                    # Open new file with new timestamp
                    current_file, writer = open_new_file()
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
                    # CSV/RINEX format: sample and write satellite data at specified interval
                    # Only writes if sample_interval seconds have elapsed since last write
                    if current_time - last_sample_time >= sample_interval:
                        self._save_text_format(current_file, writer, fields, format_type)
                        last_sample_time = current_time
                    # Longer sleep for text formats since sampling is lower frequency
                    time.sleep(0.1)
                    
            except Exception as e:
                # Log any errors but keep thread running
                self.signals.log_signal.emit(f"[Logging] Error in logging loop: {e}")
                import traceback
                self.signals.log_signal.emit(f"[Logging] Traceback: {traceback.format_exc()}")
                time.sleep(1)
        
        # Step 3: Cleanup on shutdown
        if current_file:
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
    
    def _save_text_format(self, file_handle, writer, fields, format_type):
        """
        Save processed satellite data in text format (CSV or RINEX-like).
        
        Args:
            file_handle: Open file handle
            writer: CSV writer object (None for RINEX)
            fields: List of field names to save
            format_type: 'csv' or 'rinex'
        """
        try:
            # Get snapshot of current satellite data
            snapshot = dict(self.merged_satellites)
            
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
                    valmap = {
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
            
            # Write rows based on format
            if format_type == 'rinex':
                # Space-separated format for RINEX-like output
                for row in rows:
                    file_handle.write(' '.join(str(x) for x in row) + '\n')
            else:
                # CSV format
                for row in rows:
                    writer.writerow(row)
            
            if rows:
                file_handle.flush()
                
        except Exception as e:
            self.signals.log_signal.emit(f"[Logging] Error saving text format: {e}")
    
    def stop(self):
        """Stop the logging thread gracefully."""
        self.running = False
        self.stop_event.set()
