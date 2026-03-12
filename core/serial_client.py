"""
Serial Port Client Module

This module implements a serial port client for receiving GNSS raw data streams
via serial communication. It provides an interface similar to NtripClient but
reads from a local serial port instead of a remote NTRIP server.

Key Features:
- Serial port connection management (baud rate, data bits, stop bits, parity)
- Automatic port detection and connection
- Connection timeout and error handling
- Streaming data reception compatible with pyrtcm RTCMReader

The client is designed to work with GNSS receivers that output RTCM data via RS232.
"""

import serial
import time
import sys


class SerialClient:
    """
    Serial port client for receiving GNSS RTCM data.
    
    Implements serial port communication for receiving RTCM differential correction
    data from local GNSS receivers. Handles port configuration, connection management,
    and data streaming with proper error handling.
    
    Attributes:
        port (str): Serial port name (e.g., 'COM3', '/dev/ttyUSB0')
        baudrate (int): Baud rate for serial communication (e.g., 115200)
        databits (int): Number of data bits (5, 6, 7, or 8)
        stopbits (float): Number of stop bits (1, 1.5, or 2)
        parity (str): Parity setting ('None', 'Even', 'Odd', 'Mark', 'Space')
        flowctrl (str): Flow control ('None', 'RTS/CTS', 'XOn/XOff')
        timeout (float): Read timeout in seconds
        ser (serial.Serial): Active serial port connection
    """
    
    def __init__(self, port: str, baudrate: int = 115200, databits: int = 8, 
                 stopbits: float = 1, parity: str = 'None', flowctrl: str = 'None', 
                 timeout: float = 10.0):
        """
        Initialize serial client with port parameters.
        
        Args:
            port (str): Serial port name (e.g., 'COM3' on Windows, '/dev/ttyUSB0' on Linux)
            baudrate (int): Baud rate (default: 115200)
            databits (int): Data bits - 5, 6, 7, or 8 (default: 8)
            stopbits (float): Stop bits - 1, 1.5, or 2 (default: 1)
            parity (str): Parity - 'None', 'Even', 'Odd', 'Mark', 'Space' (default: 'None')
            flowctrl (str): Flow control - 'None', 'RTS/CTS', 'XOn/XOff' (default: 'None')
            timeout (float): Read timeout in seconds (default: 10.0)
        """
        self.port = port
        self.baudrate = baudrate
        self.databits = databits
        self.stopbits = stopbits
        self.parity = parity
        self.flowctrl = flowctrl
        self.timeout = timeout
        self.ser = None

    @classmethod
    def from_config(cls, stream_type: str = 'OBS'):
        """
        Create a SerialClient instance from global configuration settings.
        
        Args:
            stream_type: Either 'OBS' for observation stream or 'EPH' for ephemeris stream
            
        Returns:
            SerialClient instance initialized with configuration values
        """
        from .global_config import get_connection_settings
        
        settings = get_connection_settings(stream_type)
        if settings.source_type != "Serial Port":
            raise ValueError(f"Cannot create SerialClient from {stream_type} settings: source type is not Serial Port")
            
        return cls(
            settings.serial_port, 
            settings.baudrate,
            settings.databits if hasattr(settings, 'databits') else 8,
            settings.stopbits if hasattr(settings, 'stopbits') else 1,
            settings.parity if hasattr(settings, 'parity') else 'None',
            settings.flowctrl if hasattr(settings, 'flowctrl') else 'None',
            settings.timeout
        )

    def connect(self) -> serial.Serial:
        """
        Establish serial port connection.
        
        Opens the serial port with configured parameters and verifies connection.
        Raises exception if port cannot be opened or is invalid.
        
        Returns:
            serial.Serial: Connected serial port object ready for data reception
            
        Raises:
            serial.SerialException: When port cannot be opened or is invalid
        """
        try:
            # Map parity string to serial constants
            parity_map = {
                'None': serial.PARITY_NONE,
                'Even': serial.PARITY_EVEN,
                'Odd': serial.PARITY_ODD,
                'Mark': serial.PARITY_MARK,
                'Space': serial.PARITY_SPACE
            }
            parity = parity_map.get(self.parity, serial.PARITY_NONE)
            
            # Map databits to serial constants
            databits_map = {
                5: serial.FIVEBITS,
                6: serial.SIXBITS,
                7: serial.SEVENBITS,
                8: serial.EIGHTBITS
            }
            bytesize = databits_map.get(self.databits, serial.EIGHTBITS)
            
            # Map stopbits to serial constants
            stopbits_map = {
                1: serial.STOPBITS_ONE,
                1.5: serial.STOPBITS_ONE_POINT_FIVE,
                2: serial.STOPBITS_TWO
            }
            stopbits = stopbits_map.get(self.stopbits, serial.STOPBITS_ONE)
            
            # Determine flow control settings
            rtscts = False
            xonxoff = False
            if self.flowctrl == 'RTS/CTS':
                rtscts = True
            elif self.flowctrl == 'XOn/XOff':
                xonxoff = True
            
            # Open serial port with configured parameters
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=bytesize,
                stopbits=stopbits,
                parity=parity,
                timeout=self.timeout,
                rtscts=rtscts,
                xonxoff=xonxoff
            )
            
            # Verify connection
            if not self.ser.is_open:
                raise serial.SerialException(f"Failed to open port {self.port}")
            
            return self.ser
            
        except serial.SerialException as e:
            self.ser = None
            raise serial.SerialException(f"Serial connection error: {str(e)}")
        except Exception as e:
            self.ser = None
            raise Exception(f"Unexpected error opening serial port: {str(e)}")

    def close(self):
        """
        Close the serial port connection.
        
        Safely closes the open serial port. Safe to call even if port is already closed.
        """
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def read(self, size: int = 1) -> bytes:
        """
        Read data from serial port.
        
        Args:
            size (int): Number of bytes to read (default: 1)
            
        Returns:
            bytes: Data read from serial port (may be less than requested if timeout occurs)
            
        Raises:
            Exception: If serial port is not open
        """
        if not self.ser or not self.ser.is_open:
            raise Exception("Serial port is not open")
        
        return self.ser.read(size)

    def write(self, data: bytes) -> int:
        """
        Write data to serial port.
        
        Args:
            data (bytes): Data to write
            
        Returns:
            int: Number of bytes written
            
        Raises:
            Exception: If serial port is not open
        """
        if not self.ser or not self.ser.is_open:
            raise Exception("Serial port is not open")
        
        return self.ser.write(data)

    @staticmethod
    def list_available_ports():
        """
        List all available serial ports on the system.
        
        Returns:
            list: List of available serial port names
        """
        try:
            import serial.tools.list_ports
            ports = [port.device for port in serial.tools.list_ports.comports()]
            return ports
        except Exception:
            return []