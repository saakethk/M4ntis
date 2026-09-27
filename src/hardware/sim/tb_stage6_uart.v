`timescale 1ns/1ps

// Stage 6: UART link, spec section 6. Everything goes through the real
// serial pins at the real timing -- 50 MHz core clock (clk50 from the
// board MMCM), 115200 baud, 434 clocks (8680 ns) per bit, 8N1. The
// testbench bit-bangs UART_RXD and has its own independent 8N1 decoder on
// UART_TXD (samples mid-bit).
//
// Simulation only proves the byte/bit logic is right against an ideal
// clock. It says nothing about the real USB-UART bridge, pin direction,
// or board clock -- that is what hardware bring-up is for.
//
// ======================= expected results ==========================
//
// Instruction words (hand-assembled, spec section 3 layout):
//   opcode<<27: 01=08000000 06=30000000 09=48000000 0A=50000000
//               0B=58000000 0F=78000000 13=98000000 19=C8000000
//   Rd<<24, Rs1<<21, Rs2<<18, buf_id<<11, imm5<<6
//
// Program P (8 words, 32 bytes -> LOAD_PROGRAM 01 20 00 ...):
//   0  98000000  UPDATEALLSTOCKBUFFERS
//   1  79001000  GETSTOCKPRICE R1, buf2
//   2  C8201040  EMITDECISION  qty=R1, buf2, buy (imm5=1)
//   3  4A000000  LOAD_IMM R2 ...
//   4  00000007  ... 7
//   5  C8402000  EMITDECISION  qty=R2, buf4, sell (imm5=0)
//   6  50000000  JMP ...
//   7  00000000  ... 0
//   -> 35 bytes on the wire: 01 20 00 | 00 00 00 98 | 00 10 00 79 |
//      40 10 20 C8 | 00 00 00 4A | 07 00 00 00 | 00 20 40 C8 |
//      00 00 00 50 | 00 00 00 00
//
// T0  CLKS_PER_BIT = round(50e6 / 115200) = 434; nothing loaded yet
// T1  LOAD_PROGRAM P. Part-way (after 11 bytes): CPU held in reset
//     (cpu_rst_n = 0, pc = 0), prog_mem[0] = 98000000 already written,
//     prog_mem[5] still the sentinel. After: prog_mem[0..7] = P,
//     prog_mem[8], [9], [511] untouched, prog_loaded = 1, not holding,
//     no protocol error; the CPU then blocks on UPDATEALLSTOCKBUFFERS.
// T2  TICK round 1 at exact baud:
//       02 00 64 00  buf0 =    100
//       02 01 38 FF  buf1 =   -200 (0xFF38)
//       02 02 34 12  buf2 =   4660 (0x1234)
//       02 03 FF 7F  buf3 =  32767
//       02 04 00 80  buf4 = -32768
//     -> exactly 5 one-cycle tick_valid pulses into stock_buffers with
//        those (buf_id, price) pairs; still blocked after 4, one advance
//        after the 5th; BUF[b][1] = the prices, R1 = 4660.
//     -> DECISION_EVENTs, 10 bytes:
//          03 02 01 34 12   buf2, buy,  qty 4660
//          03 04 00 07 00   buf4, sell, qty 7
//     -> TX start bit (first byte 0x03, bit 0 = 1) is 8680 ns wide.
// T3  TICK round 2 with the host's clock off by +/-3% (bit = 8940.4 /
//     8419.6 ns): prices 1,2,3,4,5 -> 5 more pulses, 2 advances total,
//     TX: 03 02 01 03 00 | 03 04 00 07 00
// T4  Reload with program Q (13 words, LOAD_PROGRAM 01 34 00 ...):
//   0  49000000  LOAD_IMM R1 ...     1  00000001  ... 1
//   2  4B000000  LOAD_IMM R3 ...     3  00000001  ... 1
//   4  4E000000  LOAD_IMM R6 ...     5  0000000D  ... 13
//   6  C8200840  EMITDECISION qty=R1, buf1, buy   <- loop
//   7  092C0000  ADD    R1, R1, R3
//   8  35380000  CMP_LT R5, R1, R6
//   9  58A00000  JMP_IF R5 ...      10 00000006  ... 6
//   11 50000000  JMP ...            12 0000000B  ... 11 (park)
//     -> the reload resets the CPU: R2 (7 from P) = 0, heads = 0
//     -> 12 DECISION_EVENTs, qty 1..12, in order, none lost:
//          03 01 01 qq 00 for qq = 01..0C  (60 bytes)
//        The CPU emits far faster than 115200 baud drains, so the 8-deep
//        queue fills and EMITDECISION stalls (> 0 stall cycles).
//        End: R1 = 13, R5 = 0.
// T5  Error handling / resync:
//     a) stray type byte 55              -> ignored, proto_error = 1
//     b) byte 02 with a LOW stop bit     -> dropped (framing error), so
//        the following 02 00 0A 00 is a clean TICK: buf0 = 10
//     c) 02 07 11 11 (buf_id 7)          -> dropped, no pulse
//     d) 02 08 22 22 (buf_id 8)          -> dropped (not aliased to 0)
//     e) 02 01, then silence > timeout   -> decoder back to idle; then
//        02 03 39 30 is a clean TICK: buf3 = 12345
//        => exactly 2 pulses in all of T5
//     f) 01 08 00 AA BB, then silence    -> load abandoned: CPU stays
//        held, prog_loaded = 0, prog_mem[0] unchanged (no full word)
//        then a full LOAD_PROGRAM R (4 words, 01 10 00 ...):
//          0 4F000000 LOAD_IMM R7 ... 1 00000123 ... 0x123
//          2 50000000 JMP ...         3 00000002 ... 2
//        -> released, prog_loaded = 1, R7 = 291
//     No TX framing errors or false start bits seen at any point.
// ===================================================================

module tb_stage6_uart;

    localparam real BIT_NS   = 8680.0;
    localparam      TIMEOUT  = 100000;       // 2 ms at 50 MHz, shortened for sim
    localparam      SENTINEL = 32'hF8000000; // reserved opcode 0x1F: no effect

    localparam S_WAIT_TICKS = 3'd5;

    reg clk;
    reg rst_n;
    reg rxd;
    wire txd;

    integer errors;
    integer i;

    tradecpu_core #(
        .CLK_HZ              (50000000),
        .BAUD                (115200),
        .UART_TIMEOUT_CYCLES (TIMEOUT)
    ) dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .tick_valid  (1'b0),
        .tick_buf_id (3'd0),
        .tick_price  (16'd0),
        .UART_RXD    (rxd),
        .UART_TXD    (txd)
    );

    always #10 clk = ~clk;   // 50 MHz

    // ---------------- monitors ----------------

    // ticks as seen at the Stage 3 stock_buffers staging interface
    integer    tk_n;
    reg [2:0]  tk_id    [0:63];
    reg [15:0] tk_price [0:63];
    always @(posedge clk) begin
        if (dut.u_stock_buffers.tick_valid === 1'b1) begin
            tk_id[tk_n]    = dut.u_stock_buffers.tick_buf_id;
            tk_price[tk_n] = dut.u_stock_buffers.tick_price;
            tk_n = tk_n + 1;
        end
    end

    integer emit_stall_cycles;
    always @(posedge clk) begin
        if (dut.u_control_unit.msg_valid && !dut.u_control_unit.msg_ready)
            emit_stall_cycles = emit_stall_cycles + 1;
    end

    // independent 8N1 decoder on the FPGA's TX pin
    integer   tx_n, tx_frame_errs, tx_false_starts, kt;
    reg [7:0] tx_bytes [0:255];
    reg [7:0] tx_shift;
    always begin
        @(negedge txd);
        #(BIT_NS / 2.0);
        if (txd !== 1'b0) begin
            tx_false_starts = tx_false_starts + 1;
        end else begin
            for (kt = 0; kt < 8; kt = kt + 1) begin
                #(BIT_NS);
                tx_shift[kt] = txd;
            end
            #(BIT_NS);
            if (txd !== 1'b1)
                tx_frame_errs = tx_frame_errs + 1;
            tx_bytes[tx_n] = tx_shift;
            tx_n = tx_n + 1;
        end
    end

    realtime t_fall, start_bit_ns;
    initial begin
        start_bit_ns = 0.0;
        @(posedge rst_n);
        @(negedge txd);
        t_fall = $realtime;
        @(posedge txd);
        start_bit_ns = $realtime - t_fall;
    end

    // ---------------- helpers ----------------

    task check32;
        input [8*48-1:0]    label;
        input signed [31:0] actual;
        input signed [31:0] expected;
        begin
            if (actual !== expected) begin
                $display("FAIL: %0s -- got %0d, expected %0d", label, actual, expected);
                errors = errors + 1;
            end else begin
                $display("PASS: %0s -- %0d", label, actual);
            end
        end
    endtask

    task check_hex;
        input [8*48-1:0] label;
        input [31:0]     actual;
        input [31:0]     expected;
        begin
            if (actual !== expected) begin
                $display("FAIL: %0s -- got %08h, expected %08h", label, actual, expected);
                errors = errors + 1;
            end else begin
                $display("PASS: %0s -- %08h", label, actual);
            end
        end
    endtask

    task check_true;
        input [8*48-1:0] label;
        input            cond;
        begin
            if (cond !== 1'b1) begin
                $display("FAIL: %0s", label);
                errors = errors + 1;
            end else begin
                $display("PASS: %0s", label);
            end
        end
    endtask

    // host -> FPGA serial
    task uart_send;
        input [7:0] b;
        input real  bit_ns;
        integer k;
        begin
            rxd = 1'b0;
            #(bit_ns);
            for (k = 0; k < 8; k = k + 1) begin
                rxd = b[k];
                #(bit_ns);
            end
            rxd = 1'b1;
            #(bit_ns);
        end
    endtask

    task uart_send_bad_stop;
        input [7:0] b;
        integer k;
        begin
            rxd = 1'b0;
            #(BIT_NS);
            for (k = 0; k < 8; k = k + 1) begin
                rxd = b[k];
                #(BIT_NS);
            end
            rxd = 1'b0;          // stop bit held low
            #(BIT_NS);
            rxd = 1'b1;
            #(BIT_NS);
        end
    endtask

    // message under construction, sent a slice at a time
    reg [7:0] msg [0:127];
    integer   msg_len;

    task msg_byte;
        input [7:0] b;
        begin
            msg[msg_len] = b;
            msg_len = msg_len + 1;
        end
    endtask

    task msg_word;
        input [31:0] w;
        begin
            msg_byte(w[7:0]);
            msg_byte(w[15:8]);
            msg_byte(w[23:16]);
            msg_byte(w[31:24]);
        end
    endtask

    task send_msg_range;
        input integer from, to_excl;
        integer k;
        begin
            for (k = from; k < to_excl; k = k + 1)
                uart_send(msg[k], BIT_NS);
        end
    endtask

    task send_tick;
        input [7:0]  id;
        input [15:0] price;
        input real   bit_ns;
        begin
            uart_send(8'h02, bit_ns);
            uart_send(id, bit_ns);
            uart_send(price[7:0], bit_ns);
            uart_send(price[15:8], bit_ns);
        end
    endtask

    task wait_tx;
        input integer n;
        integer guard;
        begin
            guard = 0;
            while (tx_n < n && guard < 2000000) begin
                @(negedge clk);
                guard = guard + 1;
            end
            if (tx_n < n) begin
                $display("FAIL: timed out waiting for %0d TX bytes (have %0d)", n, tx_n);
                errors = errors + 1;
            end
        end
    endtask

    // expected TX byte stream
    reg [7:0] exp_tx [0:255];
    integer   exp_n;

    task exp_decision;
        input [7:0]  buf_id, action;
        input [15:0] qty;
        begin
            exp_tx[exp_n]     = 8'h03;
            exp_tx[exp_n + 1] = buf_id;
            exp_tx[exp_n + 2] = action;
            exp_tx[exp_n + 3] = qty[7:0];
            exp_tx[exp_n + 4] = qty[15:8];
            exp_n = exp_n + 5;
        end
    endtask

    task check_tx_bytes;
        input [8*48-1:0] label;
        input integer    from, to_excl;
        integer k, bad;
        begin
            bad = 0;
            for (k = from; k < to_excl; k = k + 1) begin
                if (tx_bytes[k] !== exp_tx[k]) begin
                    $display("      TX byte %0d: got %02h, expected %02h", k, tx_bytes[k], exp_tx[k]);
                    bad = bad + 1;
                end
            end
            check32(label, bad, 0);
        end
    endtask

    task check_tick;
        input [8*48-1:0]    label;
        input integer       idx;
        input [2:0]         id;
        input signed [15:0] price;
        begin
            check_true(label, (tk_id[idx] === id) && (tk_price[idx] === price));
            if (!((tk_id[idx] === id) && (tk_price[idx] === price)))
                $display("      pulse %0d: got buf %0d price %0d", idx, tk_id[idx], $signed(tk_price[idx]));
        end
    endtask

    // ---------------- test sequence ----------------

    initial begin
        errors            = 0;
        clk               = 0;
        rxd               = 1'b1;
        rst_n             = 0;
        tk_n              = 0;
        tx_n              = 0;
        exp_n             = 0;
        tx_frame_errs     = 0;
        tx_false_starts   = 0;
        emit_stall_cycles = 0;

        for (i = 0; i < 512; i = i + 1)
            dut.u_control_unit.prog_mem[i] = SENTINEL | i;

        @(negedge clk);
        @(negedge clk);
        rst_n = 1;
        repeat (100) @(negedge clk);

        // ---------------- T0 ----------------
        check32("T0: CLKS_PER_BIT (50 MHz / 115200)", dut.CLKS_PER_BIT, 434);
        check_true("T0: nothing loaded yet", dut.dbg_prog_loaded === 1'b0);

        // ---------------- T1: LOAD_PROGRAM ----------------
        msg_len = 0;
        msg_byte(8'h01); msg_byte(8'h20); msg_byte(8'h00);
        msg_word(32'h98000000);
        msg_word(32'h79001000);
        msg_word(32'hC8201040);
        msg_word(32'h4A000000);
        msg_word(32'h00000007);
        msg_word(32'hC8402000);
        msg_word(32'h50000000);
        msg_word(32'h00000000);
        check32("T1: LOAD_PROGRAM message length", msg_len, 35);

        send_msg_range(0, 11);
        repeat (20) @(negedge clk);
        check_true("T1: mid-load CPU held in reset", dut.cpu_rst_n === 1'b0 && dut.dbg_loading === 1'b1);
        check32("T1: mid-load pc held at 0", dut.u_control_unit.pc, 0);
        check_hex("T1: mid-load word 0 already written", dut.u_control_unit.prog_mem[0], 32'h98000000);
        check_hex("T1: mid-load word 5 not yet written", dut.u_control_unit.prog_mem[5], SENTINEL | 5);

        send_msg_range(11, 35);
        repeat (20) @(negedge clk);
        check_hex("T1: prog_mem[0]", dut.u_control_unit.prog_mem[0], 32'h98000000);
        check_hex("T1: prog_mem[1]", dut.u_control_unit.prog_mem[1], 32'h79001000);
        check_hex("T1: prog_mem[2]", dut.u_control_unit.prog_mem[2], 32'hC8201040);
        check_hex("T1: prog_mem[3]", dut.u_control_unit.prog_mem[3], 32'h4A000000);
        check_hex("T1: prog_mem[4]", dut.u_control_unit.prog_mem[4], 32'h00000007);
        check_hex("T1: prog_mem[5]", dut.u_control_unit.prog_mem[5], 32'hC8402000);
        check_hex("T1: prog_mem[6]", dut.u_control_unit.prog_mem[6], 32'h50000000);
        check_hex("T1: prog_mem[7]", dut.u_control_unit.prog_mem[7], 32'h00000000);
        check_hex("T1: prog_mem[8] untouched",   dut.u_control_unit.prog_mem[8],   SENTINEL | 8);
        check_hex("T1: prog_mem[9] untouched",   dut.u_control_unit.prog_mem[9],   SENTINEL | 9);
        check_hex("T1: prog_mem[511] untouched", dut.u_control_unit.prog_mem[511], SENTINEL | 511);
        check_true("T1: prog_loaded, CPU released, no error",
                   dut.dbg_prog_loaded === 1'b1 && dut.dbg_loading === 1'b0 &&
                   dut.cpu_rst_n === 1'b1 && dut.dbg_proto_error === 1'b0);
        repeat (100) @(negedge clk);
        check_true("T1: CPU runs P, blocks on UPDATEALLSTOCKBUFFERS",
                   dut.u_control_unit.state == S_WAIT_TICKS && dut.u_control_unit.pc == 0);

        // ---------------- T2: TICK round 1 ----------------
        send_tick(8'd0, 16'd100,   BIT_NS);
        send_tick(8'd1, -16'sd200, BIT_NS);
        send_tick(8'd2, 16'h1234,  BIT_NS);
        send_tick(8'd3, 16'd32767, BIT_NS);
        repeat (20) @(negedge clk);
        check_true("T2: 4 of 5 staged, CPU still blocked",
                   dut.u_stock_buffers.tick_pending == 5'b01111 &&
                   dut.u_control_unit.state == S_WAIT_TICKS && dut.dbg_advance_count == 0);
        send_tick(8'd4, 16'h8000, BIT_NS);
        repeat (20) @(negedge clk);

        check32("T2: tick_valid pulses (1 cycle each)", tk_n, 5);
        check_tick("T2: pulse 0 = buf0,    100", 0, 3'd0, 16'sd100);
        check_tick("T2: pulse 1 = buf1,   -200", 1, 3'd1, -16'sd200);
        check_tick("T2: pulse 2 = buf2,   4660", 2, 3'd2, 16'sd4660);
        check_tick("T2: pulse 3 = buf3,  32767", 3, 3'd3, 16'sd32767);
        check_tick("T2: pulse 4 = buf4, -32768", 4, 3'd4, -16'sd32768);
        check32("T2: buffers advanced once", dut.dbg_advance_count, 1);
        check32("T2: BUF[1][1] = -200", $signed(dut.u_stock_buffers.g_buf[1].mem[1]), -32'sd200);
        check32("T2: BUF[4][1] = -32768", $signed(dut.u_stock_buffers.g_buf[4].mem[1]), -32'sd32768);
        check32("T2: R1 = GETSTOCKPRICE buf2", dut.u_register_file.registers[1], 32'sd4660);

        exp_decision(8'd2, 8'd1, 16'd4660);
        exp_decision(8'd4, 8'd0, 16'd7);
        wait_tx(10);
        check_tx_bytes("T2: DECISION_EVENT bytes 0-9 mismatches", 0, 10);
        check_true("T2: TX start bit = 8680 ns (115200 baud)",
                   start_bit_ns > 8679.0 && start_bit_ns < 8681.0);
        $display("      (TX start bit measured %0.1f ns)", start_bit_ns);

        // ---------------- T3: TICK round 2, host clock +/-3% ----------------
        send_tick(8'd0, 16'd1, BIT_NS * 1.03);
        send_tick(8'd1, 16'd2, BIT_NS * 0.97);
        send_tick(8'd2, 16'd3, BIT_NS * 1.03);
        send_tick(8'd3, 16'd4, BIT_NS * 0.97);
        send_tick(8'd4, 16'd5, BIT_NS * 1.03);
        repeat (20) @(negedge clk);
        check32("T3: tick pulses total", tk_n, 10);
        check_tick("T3: pulse 5 = buf0, 1 (+3%)", 5, 3'd0, 16'sd1);
        check_tick("T3: pulse 6 = buf1, 2 (-3%)", 6, 3'd1, 16'sd2);
        check_tick("T3: pulse 7 = buf2, 3 (+3%)", 7, 3'd2, 16'sd3);
        check_tick("T3: pulse 8 = buf3, 4 (-3%)", 8, 3'd3, 16'sd4);
        check_tick("T3: pulse 9 = buf4, 5 (+3%)", 9, 3'd4, 16'sd5);
        check32("T3: buffers advanced twice", dut.dbg_advance_count, 2);
        exp_decision(8'd2, 8'd1, 16'd3);
        exp_decision(8'd4, 8'd0, 16'd7);
        wait_tx(20);
        check_tx_bytes("T3: DECISION_EVENT bytes 10-19 mismatches", 10, 20);

        // ---------------- T4: reload + queue back-pressure ----------------
        msg_len = 0;
        msg_byte(8'h01); msg_byte(8'h34); msg_byte(8'h00);
        msg_word(32'h49000000); msg_word(32'h00000001);
        msg_word(32'h4B000000); msg_word(32'h00000001);
        msg_word(32'h4E000000); msg_word(32'h0000000D);
        msg_word(32'hC8200840);
        msg_word(32'h092C0000);
        msg_word(32'h35380000);
        msg_word(32'h58A00000); msg_word(32'h00000006);
        msg_word(32'h50000000); msg_word(32'h0000000B);
        check32("T4: LOAD_PROGRAM message length", msg_len, 55);
        send_msg_range(0, 55);
        repeat (5) @(negedge clk);
        check32("T4: reload reset R2 (was 7)", dut.u_register_file.registers[2], 0);
        check32("T4: reload reset buffer heads", dut.u_stock_buffers.g_buf[0].head, 0);

        for (i = 1; i <= 12; i = i + 1)
            exp_decision(8'd1, 8'd1, i);
        wait_tx(80);
        repeat (100) @(negedge clk);
        check_tx_bytes("T4: 12 DECISION_EVENTs, bytes 20-79 mismatches", 20, 80);
        check32("T4: no extra TX bytes", tx_n, 80);
        check_true("T4: EMITDECISION stalled on full queue", emit_stall_cycles > 0);
        $display("      (EMITDECISION stall cycles: %0d)", emit_stall_cycles);
        check32("T4: R1 = 13 (loop finished)", dut.u_register_file.registers[1], 13);
        check32("T4: R5 = 0 (loop exit)",      dut.u_register_file.registers[5], 0);
        check32("T4: parked at JMP 11",         dut.u_control_unit.pc, 11);
        check_true("T4: still no protocol error", dut.dbg_proto_error === 1'b0);

        // ---------------- T5: errors and resync ----------------
        uart_send(8'h55, BIT_NS);
        repeat (20) @(negedge clk);
        check_true("T5a: stray 0x55 -> error flag, decoder idle",
                   dut.dbg_proto_error === 1'b1 && dut.u_uart_protocol.rstate == 0);

        uart_send_bad_stop(8'h02);
        repeat (20) @(negedge clk);
        check_true("T5b: bad-stop byte dropped, decoder idle", dut.u_uart_protocol.rstate == 0);
        send_tick(8'd0, 16'd10, BIT_NS);
        repeat (20) @(negedge clk);
        check32("T5b: next TICK decoded cleanly", tk_n, 11);
        check_tick("T5b: pulse 10 = buf0, 10", 10, 3'd0, 16'sd10);

        send_tick(8'd7, 16'h1111, BIT_NS);
        send_tick(8'd8, 16'h2222, BIT_NS);
        repeat (20) @(negedge clk);
        check32("T5c/d: buf_id 7 and 8 dropped (no pulse)", tk_n, 11);
        check_true("T5c/d: decoder idle", dut.u_uart_protocol.rstate == 0);

        uart_send(8'h02, BIT_NS);
        uart_send(8'h01, BIT_NS);
        repeat (TIMEOUT + 5000) @(negedge clk);
        check_true("T5e: truncated TICK timed out, decoder idle", dut.u_uart_protocol.rstate == 0);
        send_tick(8'd3, 16'd12345, BIT_NS);
        repeat (20) @(negedge clk);
        check32("T5e: TICK after timeout decoded", tk_n, 12);
        check_tick("T5e: pulse 11 = buf3, 12345", 11, 3'd3, 16'sd12345);

        uart_send(8'h01, BIT_NS);
        uart_send(8'h08, BIT_NS);
        uart_send(8'h00, BIT_NS);
        uart_send(8'hAA, BIT_NS);
        uart_send(8'hBB, BIT_NS);
        repeat (TIMEOUT + 5000) @(negedge clk);
        check_true("T5f: abandoned load keeps CPU held",
                   dut.dbg_loading === 1'b1 && dut.cpu_rst_n === 1'b0 &&
                   dut.dbg_prog_loaded === 1'b0 && dut.u_uart_protocol.rstate == 0);
        check_hex("T5f: prog_mem[0] unchanged (no full word)", dut.u_control_unit.prog_mem[0], 32'h49000000);

        msg_len = 0;
        msg_byte(8'h01); msg_byte(8'h10); msg_byte(8'h00);
        msg_word(32'h4F000000); msg_word(32'h00000123);
        msg_word(32'h50000000); msg_word(32'h00000002);
        send_msg_range(0, 19);
        repeat (100) @(negedge clk);
        check_true("T5f: full reload releases CPU",
                   dut.dbg_loading === 1'b0 && dut.dbg_prog_loaded === 1'b1);
        check32("T5f: R7 = 0x123 from new program", dut.u_register_file.registers[7], 291);

        check32("T5: tick pulses in all of T5", tk_n - 10, 2);
        check32("TX framing errors seen by host decoder", tx_frame_errs, 0);
        check32("TX false start bits",                    tx_false_starts, 0);
        check32("TX bytes total",                         tx_n, 80);

        if (errors == 0)
            $display("tb_stage6_uart: ALL TESTS PASSED -- Stage 6 simulation criteria met");
        else
            $display("tb_stage6_uart: %0d TEST(S) FAILED", errors);

        $finish;
    end

endmodule
