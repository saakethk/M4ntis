"""
TradeCPU bring-up test #2: buy / sell / hold + EMITBALANCE

Strategy (watches buffer 0 only):
  price went UP since last round   -> BUY 10 shares  (DECISION_EVENT action=1)
  price went DOWN since last round -> SELL 10 shares (DECISION_EVENT action=0)
  price unchanged                  -> do nothing     (no DECISION_EVENT)
  every round ends with EMITBALANCE, so you always see the cash balance.

Starting cash is $10,000.00 (1,000,000 cents). The first round of ticks is a
warm-up (there is no "previous price" yet), so it trades nothing.

The script computes the expected messages with an independent Python model
and compares them against what the board actually sends back.
"""
import serial
import time

COM_PORT = "COM4"   # your port
BAUD = 115200

# ---------------------------------------------------------------- encoder
OP = {
    "MUL": 0x03, "SUB": 0x02, "CMP_GT": 0x05, "CMP_LT": 0x06,
    "LOAD_IMM": 0x09, "JMP": 0x0A, "JMP_IF": 0x0B,
    "GETBALANCE": 0x0E, "GETSTOCKPRICE": 0x0F, "GETSTOCKPRICEBEFORE": 0x10,
    "UPDATEBALANCE": 0x12, "UPDATEALLSTOCKBUFFERS": 0x13,
    "SETBALANCE": 0x18, "EMITDECISION": 0x19, "EMITBALANCE": 0x1A,
}
TWO_WORD = {"LOAD_IMM", "JMP", "JMP_IF"}


def word(op, rd=0, rs1=0, rs2=0, var=0, buf=0, imm5=0):
    # Spec section 3: opcode[31:27] Rd[26:24] Rs1[23:21] Rs2[20:18]
    #                 var_id[17:14] buf_id[13:11] imm5[10:6]
    return ((OP[op] << 27) | (rd << 24) | (rs1 << 21) | (rs2 << 18)
            | (var << 14) | (buf << 11) | (imm5 << 6))


def assemble(src):
    """src: list of (label_or_None, mnemonic, kwargs). Two passes for labels."""
    labels, addr = {}, 0
    for label, op, _ in src:
        if label:
            labels[label] = addr
        addr += 2 if op in TWO_WORD else 1
    words, listing = [], []
    for label, op, orig in src:
        kw = dict(orig)
        second = None
        if op == "LOAD_IMM":
            second = kw.pop("imm") & 0xFFFF
        elif op in ("JMP", "JMP_IF"):
            second = labels[kw.pop("to")]
        if op == "JMP_IF":
            # The spec names JMP_IF's condition "Rs" without saying whether it
            # lives in the Rd or Rs1 field. JMP_IF never writes a register, so
            # putting the same register in BOTH fields works either way.
            kw["rd"] = kw["rs1"]
        listing.append((len(words), label, op, orig))
        words.append(word(op, **kw))
        if second is not None:
            words.append(second)
    return words, listing


R0, R1, R2, R3, R4, R5, R6 = range(7)
BUF = 0

program_src = [
    # --- setup: starting cash = 10000 * 100 = 1,000,000 cents ($10,000.00)
    #     (LOAD_IMM is 16-bit signed, so 1,000,000 has to be built with MUL)
    (None,   "LOAD_IMM",   dict(rd=R1, imm=10000)),
    (None,   "LOAD_IMM",   dict(rd=R2, imm=100)),
    (None,   "MUL",        dict(rd=R1, rs1=R1, rs2=R2)),
    (None,   "SETBALANCE", dict(rs1=R1)),
    (None,   "LOAD_IMM",   dict(rd=R0, imm=0)),     # R0 = 0 (for negation)
    (None,   "LOAD_IMM",   dict(rd=R6, imm=10)),    # R6 = shares per trade
    (None,   "GETBALANCE", dict(rd=R5)),
    (None,   "EMITBALANCE", dict(rs1=R5)),          # report starting cash
    (None,   "UPDATEALLSTOCKBUFFERS", {}),          # warm-up round, no trade
    # --- main loop, once per round of 5 ticks
    ("LOOP", "UPDATEALLSTOCKBUFFERS", {}),
    (None,   "GETSTOCKPRICE",       dict(rd=R1, buf=BUF)),          # now
    (None,   "GETSTOCKPRICEBEFORE", dict(rd=R2, buf=BUF, imm5=1)),  # last round
    (None,   "CMP_GT",  dict(rd=R3, rs1=R1, rs2=R2)),
    (None,   "JMP_IF",  dict(rs1=R3, to="BUY")),
    (None,   "CMP_LT",  dict(rd=R3, rs1=R1, rs2=R2)),
    (None,   "JMP_IF",  dict(rs1=R3, to="SELL")),
    (None,   "JMP",     dict(to="REPORT")),                         # flat: hold
    ("BUY",  "MUL",     dict(rd=R4, rs1=R1, rs2=R6)),   # cost = price * qty
    (None,   "UPDATEBALANCE", dict(rs1=R4, buf=BUF)),   # positive = buy, cash down
    (None,   "EMITDECISION",  dict(rs1=R6, buf=BUF, imm5=1)),
    (None,   "JMP",     dict(to="REPORT")),
    ("SELL", "MUL",     dict(rd=R4, rs1=R1, rs2=R6)),
    (None,   "SUB",     dict(rd=R4, rs1=R0, rs2=R4)),   # make it negative
    (None,   "UPDATEBALANCE", dict(rs1=R4, buf=BUF)),   # negative = sell, cash up
    (None,   "EMITDECISION",  dict(rs1=R6, buf=BUF, imm5=0)),
    ("REPORT", "GETBALANCE",  dict(rd=R5)),
    (None,   "EMITBALANCE",   dict(rs1=R5)),
    (None,   "JMP",     dict(to="LOOP")),
]

instructions, listing = assemble(program_src)

# ------------------------------------------------------------ test data
# buf0 price per round (cents). Round 0 is the warm-up.
BUF0_PRICES = [1000, 1010, 1005, 1005, 1020, 990]
#               warm   up    down  flat   up   down
OTHER_PRICE = 500   # buffers 1-4 just need *a* tick each round
QTY = 10
START_CASH = 1_000_000


def expected_messages():
    """Independent model of the strategy, NOT derived from the encoder."""
    rounds, cash = [], START_CASH
    for prev, now in zip(BUF0_PRICES, BUF0_PRICES[1:]):
        msgs = []
        if now > prev:
            cash -= now * QTY
            msgs.append(("DECISION", BUF, "buy", QTY))
        elif now < prev:
            cash += now * QTY
            msgs.append(("DECISION", BUF, "sell", QTY))
        msgs.append(("BALANCE", cash))
        rounds.append(msgs)
    return rounds


# ------------------------------------------------------------ serial I/O
def read_message(ser):
    """Read one board->host message, parsed by its type byte."""
    head = ser.read(1)
    if not head:
        return None
    body = ser.read(4)
    if len(body) != 4:
        return ("TRUNCATED", head[0], body)
    if head[0] == 0x03:
        # DECISION_EVENT body: buf_id, action, quantity (int16 little-endian)
        return ("DECISION", body[0], "buy" if body[1] else "sell",
                int.from_bytes(body[2:4], "little", signed=True))
    if head[0] == 0x04:
        return ("BALANCE", int.from_bytes(body, "little", signed=True))
    return ("UNKNOWN", head[0], body)


def fmt(m):
    if m is None:
        return "(nothing -- timed out)"
    if m[0] == "DECISION":
        return f"DECISION buf{m[1]} {m[2].upper():4s} qty={m[3]}"
    if m[0] == "BALANCE":
        return f"BALANCE  {m[1]:>9} cents  (${m[1] / 100:,.2f})"
    return repr(m)


def send_round(ser, buf0_price):
    for b in range(5):
        price = buf0_price if b == BUF else OTHER_PRICE
        ser.write(bytes([0x02, b]) + price.to_bytes(2, "little", signed=True))
        time.sleep(0.01)


def main():
    print("Program listing:")
    for addr, label, op, kw in listing:
        print(f"  {addr:3d}  {(label or ''):7s} {op:22s} {kw}")
    print("\ninstructions = [")
    for i, w in enumerate(instructions):
        print(f"    0x{w:08X},  # word {i}")
    print("]\n")

    ser = serial.Serial(COM_PORT, baudrate=BAUD, timeout=2)
    time.sleep(0.5)
    ser.reset_input_buffer()

    body = b"".join(w.to_bytes(4, "little") for w in instructions)
    ser.write(bytes([0x01]) + len(body).to_bytes(2, "little") + body)
    print(f"Sent LOAD_PROGRAM ({len(instructions)} words)")

    failures = 0

    # Starting balance is emitted right after the program loads.
    got = read_message(ser)
    ok = got == ("BALANCE", START_CASH)
    failures += not ok
    print(f"\n[start]  expected BALANCE {START_CASH}  got {fmt(got)}  "
          f"{'PASS' if ok else 'FAIL'}")

    # Warm-up round: no messages expected.
    send_round(ser, BUF0_PRICES[0])
    print(f"[warm-up] sent buf0={BUF0_PRICES[0]} (no output expected)")

    for i, exp in enumerate(expected_messages(), start=1):
        prev, now = BUF0_PRICES[i - 1], BUF0_PRICES[i]
        send_round(ser, now)
        print(f"\n[round {i}] buf0 {prev} -> {now}")
        for e in exp:
            got = read_message(ser)
            ok = got == e
            failures += not ok
            print(f"   expected {fmt(e):40s} got {fmt(got):40s} "
                  f"{'PASS' if ok else 'FAIL'}")
            if got is None:
                break

    extra = ser.read(ser.in_waiting or 0)
    if extra:
        failures += 1
        print(f"\nFAIL: board sent unexpected extra bytes: {extra.hex(' ')}")

    ser.close()
    print("\n" + ("ALL CHECKS PASSED" if failures == 0
                  else f"{failures} CHECK(S) FAILED -- see above"))


if __name__ == "__main__":
    main()
