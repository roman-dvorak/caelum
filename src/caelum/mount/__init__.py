"""Where a telescope on the network is pointed, read without ever touching capture.

`MountSource` implementations (`alpaca`, `indi`) talk to a mount driver on
another computer; `MountPoller` runs one in its own thread and keeps the latest
`MountState`, so a slow or unreachable server can never delay a frame.
"""

from .poller import MountPoller
from .state import MountState, MountStatus

__all__ = ["MountPoller", "MountState", "MountStatus"]
