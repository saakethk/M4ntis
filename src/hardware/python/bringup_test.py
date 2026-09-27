import serial
import time

print("begin test program: UPDATEALLSTOCKBUFFERS, GETSTOCKPRICE, EMITDECISION")

COM_PORT = "COM4"       # CHANGE THIS to your actual port
BAUD = 115200            # confirmed fixed value, do not change

ser = serial.Serial(COM_PORT, baudrate=BAUD, timeout=2)
time.sleep(0.5)  # let the port settle

# ---- Program: UPDATEALLSTOCKBUFFERS, GETSTOCKPRICE, EMITDECISION ----
# This is the exact test program suggested by the hardware team for
# bring-up: it repeats 3 steps, so every round of 5 TICKs sends one
# price straight back as a decision, proving the whole chain works.
#
# Word 0: UPDATEALLSTOCKBUFFERS (0x13 << 27)
# Word 1: GETSTOCKPRICE R1, buf_id=3   (0x0F opcode, Rd=1, buf_id=3)
# Word 2: EMITDECISION Rs1=R1, buf_id=3, action=1 (buy)
# Word 3: JMP back to word 0 (loop forever)
# Word 4: (jump target address word for the JMP above = 0)
#
# NOTE: these exact hex values should be double-checked against
# docs/tradecpu_full_specification.md Section 3's bit layout before
# trusting them blindly -- construct/verify independently if anything
# about the result looks wrong. This is a starting point, not gospel.
instructions = [
    0x98000000,  # UPDATEALLSTOCKBUFFERS
    0x79001800,  # GETSTOCKPRICE R1, buf3
    0xC8201840,  # EMITDECISION qty=R1, buf3, buy
    0x50000000,  # JMP (address in next word)
    0x00000000,  # jump target: address 0
]

program_bytes = b''.join(w.to_bytes(4, byteorder='little') for w in instructions)

# ---- Send LOAD_PROGRAM ----
msg = bytes([0x01]) + len(program_bytes).to_bytes(2, 'little') + program_bytes
ser.write(msg)
print(f"Sent LOAD_PROGRAM ({len(program_bytes)} bytes)")
time.sleep(0.2)

# ---- Send 5 TICKs, one per buffer, distinct known prices ----
for buf_id in range(5):
    price = 1000 + buf_id  # buf3 will be 1003
    tick = bytes([0x02, buf_id]) + price.to_bytes(2, 'little', signed=True)
    ser.write(tick)
    print(f"Sent TICK buf{buf_id} = {price}")
    time.sleep(0.05)

# ---- Read back the DECISION_EVENT ----
print("Waiting for DECISION_EVENT...")
response = ser.read(5)  # DECISION_EVENT is always exactly 5 bytes

if len(response) == 5:
    msg_type, buf_id, action, qty_lo, qty_hi = response
    quantity = int.from_bytes(bytes([qty_lo, qty_hi]), 'little', signed=True)
    print(f"Received: type=0x{msg_type:02X} buf_id={buf_id} "
          f"action={'buy' if action else 'sell'} quantity={quantity}")
    if msg_type == 0x03 and buf_id == 3 and quantity == 1003:
        print(">>> SUCCESS: echoed price matches what was sent (1003)")
    else:
        print(">>> Got a response, but values don't match expected -- "
              "investigate (see guide section 4, Step 5)")
else:
    print(f">>> FAILED: expected 5 bytes back, got {len(response)}. "
          f"No response, or malformed. See guide section 4, Step 5.")

ser.close()