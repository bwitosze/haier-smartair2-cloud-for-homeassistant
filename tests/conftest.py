"""Load codec.py without the package __init__.py, which needs Home Assistant."""

import enum
import importlib
import sys
import types
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent.parent / "custom_components" / "haier_smartair2"


class _Platform(enum.StrEnum):
    CLIMATE = "climate"
    SENSOR = "sensor"


# const.py:16 imports Platform from homeassistant.const.
ha = types.ModuleType("homeassistant")
ha_const = types.ModuleType("homeassistant.const")
ha_const.Platform = _Platform
ha.const = ha_const
sys.modules.setdefault("homeassistant", ha)
sys.modules.setdefault("homeassistant.const", ha_const)

# A synthetic package: its __path__ resolves "from .const import" and its __init__ never runs.
package = types.ModuleType("haier_codec_pkg")
package.__path__ = [str(PACKAGE_DIR)]
sys.modules["haier_codec_pkg"] = package

codec = importlib.import_module("haier_codec_pkg.codec")
