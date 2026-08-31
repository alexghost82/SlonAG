"""Connectivity module - LAN discovery, TLS transport, session management, migration, remote adapter.

This package provides the full connectivity stack for Slon:
- Discovery of same-LAN devices via Bonjour/mDNS
- Authenticated TLS/WSS transport for LAN connections
- Remote transport adapter for out-of-LAN connectivity
- Session state machine with auto-reconnect and health monitoring
- Transparent LAN/remote migration
"""

from mark.connectivity import types
from mark.connectivity.discovery import LANDeviceScanner, LANDevice
from mark.connectivity.transport import LANTransport, LANTransportError
from mark.connectivity.session import ConnectivitySession, ConnectivitySessionError
from mark.connectivity.migration import LANRemoteMigration
from mark.connectivity.monitor import ConnectivityMonitor
from mark.connectivity.remote import RemoteAdapter, RemoteAdapterError

__all__ = [
    "LANDeviceScanner",
    "LANDevice",
    "LANTransport",
    "LANTransportError",
    "ConnectivitySession",
    "ConnectivitySessionError",
    "LANRemoteMigration",
    "ConnectivityMonitor",
    "RemoteAdapter",
    "RemoteAdapterError",
    "types",
]
