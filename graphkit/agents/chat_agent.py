"""Compatibility import; implementation lives in graphkit.chat.agent."""
import sys
from ..chat import agent as _implementation
sys.modules[__name__] = _implementation
