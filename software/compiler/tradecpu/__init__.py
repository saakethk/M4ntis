"""TradeCPU toolchain: strategy compiler, assembler and golden-model simulator."""

from .asm import AsmError, Assembled, assemble, disassemble, format_asm, parse_asm
from .compiler import CompileError, CompileOptions, CompileResult, Diagnostic, compile_strategy
from .isa import Instr, Label, Op, load_program_message, tick_message
from .simulator import BalanceMsg, Decision, TradeCPU, run_rounds

__all__ = [
    "AsmError",
    "Assembled",
    "BalanceMsg",
    "CompileError",
    "CompileOptions",
    "CompileResult",
    "Decision",
    "Diagnostic",
    "Instr",
    "Label",
    "Op",
    "TradeCPU",
    "assemble",
    "compile_strategy",
    "disassemble",
    "format_asm",
    "load_program_message",
    "parse_asm",
    "run_rounds",
    "tick_message",
]
