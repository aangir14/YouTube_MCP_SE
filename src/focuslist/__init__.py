"""FocusList: YouTube Video Intelligence MCP Server.

A local Model Context Protocol (MCP) server for YouTube discovery,
account analytics, and constrained playlist curation.
"""

__version__ = "0.1.0"
__author__ = "Aangir Doshi, Harshil Srivastav, Ayush Patel"

from focuslist.clock import Clock, FakeClock, SystemClock
from focuslist.config import ProviderMode, Settings, get_settings
from focuslist.context import RequestContext
from focuslist.errors import ErrorCode, FocusListError
from focuslist.types import (
    AccountActivityRecord,
    ChannelRecord,
    ErrorEnvelope,
    MetaEnvelope,
    ProposalRecord,
    QuotaStatusRecord,
    RankedItemRecord,
    ResultEnvelope,
    VideoRecord,
)

__all__ = [
    "AccountActivityRecord",
    "ChannelRecord",
    "Clock",
    "ErrorCode",
    "ErrorEnvelope",
    "FakeClock",
    "FocusListError",
    "MetaEnvelope",
    "ProposalRecord",
    "ProviderMode",
    "QuotaStatusRecord",
    "RankedItemRecord",
    "RequestContext",
    "ResultEnvelope",
    "Settings",
    "SystemClock",
    "VideoRecord",
    "__author__",
    "__version__",
    "get_settings",
]
