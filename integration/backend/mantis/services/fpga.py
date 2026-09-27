"""Run compiled programs on the TradeCPU FPGA over its UART link.

The wire protocol is the board's (see ``software/compiler/tradecpu/hwtest.py`` and
``hardware/python/balance_test.py``): send LOAD_PROGRAM, read the starting balance,
then for every tick send one price per stock slot and read DECISION messages until
the board acknowledges the tick with a BALANCE message.

There is no software fallback. When the board is not configured, cannot be opened,
or stops answering, callers get :class:`FpgaUnavailable` and nothing is recorded.
Only one run can use the board at a time; a second one gets :class:`FpgaBusy`.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from mantis.config import COMPILER_ROOT, env
from mantis.errors import Conflict, ServiceUnavailable

if str(COMPILER_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPILER_ROOT))

from tradecpu.hwtest import read_until_balance  # noqa: E402
from tradecpu.isa import NUM_BUFFERS, load_program_message, tick_message  # noqa: E402
from tradecpu.simulator import BalanceMsg, Decision  # noqa: E402

DEFAULT_BAUD = 115200  # fixed by the board's UART
READ_TIMEOUT_S = 2.0
SETTLE_S = 0.5

_board_lock = threading.Lock()


class FpgaUnavailable(ServiceUnavailable):
    pass


class FpgaBusy(Conflict):
    def __init__(self) -> None:
        super().__init__("The FPGA is busy running another backtest. Try again when it finishes.")


class Port(Protocol):
    def write(self, data: bytes) -> int | None: ...
    def read(self, n: int) -> bytes: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class Tick:
    """What the board sent back for one tick: its trade decisions and its balance afterwards."""

    decisions: list[Decision]
    balance: int


@dataclass(frozen=True)
class BoardRun:
    starting_balance: int
    ticks: list[Tick]


def serial_port_path() -> str:
    return env("FPGA_SERIAL_PORT")


def status() -> dict[str, Any]:
    """Whether a board appears to be attached, without opening (and disturbing) it."""
    path = serial_port_path()
    if not path:
        return {"connected": False, "port": None, "busy": False, "detail": _NOT_CONFIGURED}
    if not os.path.exists(path):
        return {
            "connected": False,
            "port": path,
            "busy": False,
            "detail": f"No FPGA found at {path}. Plug in the board or fix FPGA_SERIAL_PORT.",
        }
    busy = _board_lock.locked()
    return {"connected": True, "port": path, "busy": busy, "detail": "Busy running a backtest" if busy else f"Connected at {path}"}


@contextmanager
def board() -> Iterator[Port]:
    """Exclusive access to the board's serial port, closed afterwards."""
    if not _board_lock.acquire(blocking=False):
        raise FpgaBusy()
    try:
        port = open_port()
        try:
            yield port
        finally:
            port.close()
    finally:
        _board_lock.release()


def open_port() -> Port:
    path = serial_port_path()
    if not path:
        raise FpgaUnavailable(_NOT_CONFIGURED)
    try:
        import serial  # pyserial
    except ImportError as exc:
        raise FpgaUnavailable("Backtests need pyserial to talk to the FPGA: pip install pyserial") from exc
    baud = int(env("FPGA_BAUD", str(DEFAULT_BAUD)))
    try:
        port = serial.Serial(path, baudrate=baud, timeout=READ_TIMEOUT_S)
    except (serial.SerialException, OSError, ValueError) as exc:
        raise FpgaUnavailable(f"The FPGA is not connected: could not open {path} ({exc}).") from exc
    time.sleep(SETTLE_S)
    port.reset_input_buffer()
    return port


def run_program(port: Port, words: list[int], rounds: list[list[int]]) -> BoardRun:
    """Load ``words`` and feed each round of prices (one per stock slot). Raises FpgaUnavailable on silence."""
    port.write(load_program_message(words))
    start = _balance_of(read_until_balance(port), "after the program was loaded")
    ticks: list[Tick] = []
    for index, prices in enumerate(rounds):
        if len(prices) != NUM_BUFFERS:
            raise ValueError(f"each round needs {NUM_BUFFERS} prices")
        for buf, price in enumerate(prices):
            port.write(tick_message(buf, price))
        messages = read_until_balance(port)
        ticks.append(
            Tick(
                decisions=[m for m in messages if isinstance(m, Decision)],
                balance=_balance_of(messages, f"at tick {index + 1} of {len(rounds)}"),
            )
        )
    return BoardRun(start, ticks)


def _balance_of(messages: list, when: str) -> int:
    last = messages[-1] if messages else None
    if not isinstance(last, BalanceMsg):
        raise FpgaUnavailable(
            f"The FPGA at {serial_port_path()} stopped responding {when}. Check that it is powered on and programmed with TradeCPU."
        )
    return last.value


_NOT_CONFIGURED = (
    "Backtests run on the TradeCPU FPGA, and no board is configured. Connect it over USB and set "
    "FPGA_SERIAL_PORT in the repo-root .env (e.g. /dev/tty.usbserial-XXXX)."
)
