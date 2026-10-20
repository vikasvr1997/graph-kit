"""Compatibility import; implementation lives in graphkit.chat.guardrails."""
import sys
from ..chat import guardrails as _implementation
sys.modules[__name__] = _implementation
