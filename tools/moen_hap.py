"""Shared HAP plumbing for the u_by_moen experiment tools.

Loads the pairing JSON (from MOEN_HAP_PAIRING_B64 in the home-assistant
repo .env, or --pairing-file) and builds an aiohomekit IpPairing — the
same machinery the integration's local.py uses. Read/write of existing
characteristics ONLY; never any pair-setup operation (bad pair attempts
wedge the shower's HAP server).

Usage from scripts:
    pairing = await load_pairing(args)
    ...
    await pairing.close()
"""
import base64
import json
import os
import sys
from pathlib import Path

from aiohomekit.controller import Controller
from aiohomekit.controller.ip.pairing import IpPairing

# Mirror custom_components/u_by_moen/local.py iids (aid=1)
MAIN_ACTIVE_IID = 9
HEATER_CURRENT_TEMP_IID = 13
HEATER_TARGET_STATE_IID = 15
HEATER_TARGET_TEMP_IID = 16
OUTLET_ACTIVE_IIDS = {1: 18, 2: 23, 3: 28, 4: 33}
READ_IIDS = [MAIN_ACTIVE_IID, HEATER_CURRENT_TEMP_IID, HEATER_TARGET_STATE_IID, HEATER_TARGET_TEMP_IID] + list(
    OUTLET_ACTIVE_IIDS.values()
)

DEFAULT_ENV = Path(__file__).resolve().parent.parent.parent / "home-assistant" / ".env"


def load_env(env_path=None):
    """Parse KEY=VALUE lines from the home-assistant .env (no dotenv dependency)."""
    path = Path(env_path or os.environ.get("MOEN_ENV_FILE") or DEFAULT_ENV)
    if not path.is_file():
        sys.exit(f"env file not found: {path}")
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def pairing_from_env(env) -> IpPairing:
    """Decode MOEN_HAP_PAIRING_B64 into an IpPairing (no file writes)."""
    raw = env.get("MOEN_HAP_PAIRING_B64")
    if not raw:
        sys.exit("MOEN_HAP_PAIRING_B64 missing from env file")
    data = json.loads(base64.b64decode(raw))
    return IpPairing(Controller(), data)


def c_to_f(celsius: float) -> float:
    return round(celsius * 9 / 5 + 32)


def f_to_c(fahrenheit: float) -> float:
    return round((fahrenheit - 32) * 5 / 9, 5)


def fmt_state(result: dict) -> str:
    """Format a get_characteristics result the way local.py reads it."""
    def val(iid):
        return result.get((1, iid), {}).get("value")

    def flag(iid):
        v = val(iid)
        return "?" if v is None else str(int(bool(v)))

    cur = val(HEATER_CURRENT_TEMP_IID)
    tgt = val(HEATER_TARGET_TEMP_IID)
    parts = [
        f"main={flag(MAIN_ACTIVE_IID)}",
        "outlets=[" + ",".join(str(p) + ":" + flag(i) for p, i in OUTLET_ACTIVE_IIDS.items()) + "]",
        f"cur={cur}C" if cur is not None else "cur=?",
        f"tgt={tgt}C" if tgt is not None else "tgt=?",
    ]
    if cur is not None:
        parts.append(f"cur={c_to_f(float(cur))}F")
    if tgt is not None:
        parts.append(f"tgt={c_to_f(float(tgt))}F")
    state15 = val(HEATER_TARGET_STATE_IID)
    if state15 is None:
        # distinguish "not reported" from error entries in the raw result
        entry = result.get((1, HEATER_TARGET_STATE_IID), {})
        parts.append(f"iid15={entry.get('status', 'missing')}")
    else:
        parts.append(f"iid15={state15}")
    return " ".join(parts)


READ_PAIRS = [(1, iid) for iid in READ_IIDS]