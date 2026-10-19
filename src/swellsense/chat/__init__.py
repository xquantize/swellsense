"""Chat tools for live conditions.

The model picks a tool. The window, the score and the ranking are computed
here and handed back as compact JSON for the model to phrase.
"""

from swellsense.chat.tools import TOOLS, dispatch, resolve_when

__all__ = ["TOOLS", "dispatch", "resolve_when"]
