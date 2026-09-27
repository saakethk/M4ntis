"""The FPGA link: framing a run against the board model, and failing when the board is silent."""

from __future__ import annotations

import pytest
from tradecpu.hwtest import FakeBoard

from mantis.services import compiler, fpga
from tests.conftest import CROSSOVER


class SilentPort:
    def write(self, data: bytes) -> int:
        return len(data)

    def read(self, n: int) -> bytes:
        return b""

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        pass


class ListedPort:
    def __init__(self, device: str) -> None:
        self.device = device


def crossover_words() -> list[int]:
    return [int(word, 16) for word in compiler.compile_document(CROSSOVER)["manifest"]["words"]]


def test_run_program_reads_balance_and_decisions_per_tick():
    prices = [15000 + 100 * (i % 20 if i % 40 < 20 else 20 - i % 20) for i in range(60)]
    run = fpga.run_program(FakeBoard(), crossover_words(), [[p, 0, 0, 0, 0] for p in prices])
    assert run.starting_balance == 1_000_000
    assert len(run.ticks) == 60
    decisions = [d for tick in run.ticks for d in tick.decisions]
    assert {d.action for d in decisions} == {"buy", "sell"} and all(d.buf == 0 for d in decisions)


def test_silent_board_is_unavailable():
    with pytest.raises(fpga.FpgaUnavailable, match="stopped responding"):
        fpga.run_program(SilentPort(), crossover_words(), [[15000, 0, 0, 0, 0]])


def test_status_uses_default_port_and_list_ports(monkeypatch):
    monkeypatch.setenv("FPGA_SERIAL_PORT", "")
    monkeypatch.setattr(
        "serial.tools.list_ports.comports",
        lambda: [],
    )
    assert fpga.status() == {
        "connected": False,
        "port": "COM4",
        "busy": False,
        "detail": "No FPGA found on COM4. Plug in the board, or set FPGA_SERIAL_PORT to its port.",
    }

    monkeypatch.setenv("FPGA_SERIAL_PORT", "COM4")
    monkeypatch.setattr(
        "serial.tools.list_ports.comports",
        lambda: [ListedPort("com4")],
    )
    connected = fpga.status()
    assert connected["connected"] is True and connected["port"] == "COM4"

    monkeypatch.setenv("FPGA_SERIAL_PORT", "/dev/no-such-board")
    monkeypatch.setattr(
        "serial.tools.list_ports.comports",
        lambda: [],
    )
    assert fpga.status() == {
        "connected": False,
        "port": "/dev/no-such-board",
        "busy": False,
        "detail": "No FPGA found on /dev/no-such-board. Plug in the board, or set FPGA_SERIAL_PORT to its port.",
    }

    monkeypatch.setenv("FPGA_SERIAL_PORT", "")
    with pytest.raises(fpga.FpgaUnavailable, match="could not open"):
        fpga.open_port()
