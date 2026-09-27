`timescale 1ns/1ps

// EMITBALANCE (0x1A) and the EMIT_BALANCE message (type 0x04):
//   04 | b0 b1 b2 b3   -- Rs1 as int32, little-endian (b0 = bits 7:0)
// sharing the 8-deep outgoing queue with EMITDECISION, in issue order.
//
// Same setup as tb_stage6_uart: 50 MHz core, 115200 baud 8N1 on the real
// pins, programs loaded with LOAD_PROGRAM over UART_RXD, and an
// independent 8N1 decoder on UART_TXD.
//
// ======================= expected results ==========================
//
// Opcodes<<27: 02=10000000 03=18000000 0E=70000000 12=90000000
//              18=C0000000 19=C8000000 1A=D0000000 (others as tb_stage6)
//
// Test 1 -- positive and negative balance, mixed order
//   program S (18 words, LOAD_PROGRAM 01 48 00 ...):
//     0  49000000  LOAD_IMM R1 ...      1  00002710  ... 10000
//     2  4A000000  LOAD_IMM R2 ...      3  00000064  ... 100
//     4  1B280000  MUL  R3, R1, R2      -> 1000000
//     5  C0600000  SETBALANCE R3        -> BALANCE = 1000000
//     6  74000000  GETBALANCE R4        -> 1000000 = 0x000F4240
//     7  C8400840  EMITDECISION qty=R2, buf1, buy   (queued 1st)
//     8  D0800000  EMITBALANCE R4                   (queued 2nd)
//     9  4D000000  LOAD_IMM R5 ...      10 00003A98  ... 15000
//     11 1EA80000  MUL  R6, R5, R2      -> 1500000
//     12 90C00000  UPDATEBALANCE R6     -> 1000000 - 1500000 = -500000
//     13 77000000  GETBALANCE R7        -> -500000 = 0xFFF85EE0
//     14 D0E00000  EMITBALANCE R7                   (queued 3rd)
//     15 C8401000  EMITDECISION qty=R2, buf2, sell  (queued 4th)
//     16 50000000  JMP ...              17 00000010  ... 16 (park)
//   -> TX, 20 bytes, in exactly this order:
//        03 01 01 64 00   decision: buf1, buy, qty 100
//        04 40 42 0F 00   balance  +1000000
//        04 E0 5E F8 FF   balance   -500000 (two's complement)
//        03 02 00 64 00   decision: buf2, sell, qty 100
//   -> R4 = 1000000, R7 = -500000; 4 messages fit in the queue, so no
//      stalls, and every EMIT takes exactly 4 cycles fetch-to-fetch.
//
// Test 2 -- ordering under back-pressure
//   program T (15 words, LOAD_PROGRAM 01 3C 00 ...), for i = 1..6:
//     0  49000000  LOAD_IMM R1 ...      1  00000001  ... 1
//     2  4B000000  LOAD_IMM R3 ...      3  00000001  ... 1
//     4  4E000000  LOAD_IMM R6 ...      5  00000007  ... 7
//     6  C8200040  EMITDECISION qty=R1, buf0, buy   <- loop
//     7  12040000  SUB  R2, R0, R1      -> -i
//     8  D0400000  EMITBALANCE R2
//     9  092C0000  ADD    R1, R1, R3
//     10 35380000  CMP_LT R5, R1, R6
//     11 58A00000  JMP_IF R5 ...        12 00000006  ... 6
//     13 50000000  JMP ...              14 0000000D  ... 13 (park)
//   -> 12 messages, alternating, 60 bytes: for i = 1..6
//        03 00 01 ii 00  |  04 (256-i) FF FF FF      (-1 = FF FF FF FF ...)
//   -> the queue fills, so the EMITs stall (> 0 stall cycles), and nothing
//      is lost or reordered. End: R1 = 7.
// ===================================================================

module tb_stage6_emit_balance;

    localparam real BIT_NS  = 8680.0;
    localparam      OP_EMITDECISION = 5'h19;
    localparam      OP_EMITBALANCE  = 5'h1A;
    localparam      S_FETCH = 3'd0;

    reg  clk;
    reg  rst_n;
    reg  rxd;
    wire txd;

    integer errors;
    integer i;

    tradecpu_core #(
        .CLK_HZ              (50000000),
        .BAUD                (115200),
        .UART_TIMEOUT_CYCLES (100000)
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

    integer emit_stall_cycles;
    always @(posedge clk) begin
        if (dut.u_control_unit.msg_valid && !dut.u_control_unit.msg_ready)
            emit_stall_cycles = emit_stall_cycles + 1;
    end

    // fetch-to-fetch length of each EMIT (ir still holds it at the next FETCH)
    integer instr_len, emits, emits_not_4;
    wire [4:0] cur_op = dut.u_control_unit.ir[31:27];
    always @(posedge clk) begin
        if (dut.cpu_rst_n !== 1'b1) begin
            instr_len = 0;
        end else if (dut.u_control_unit.state == S_FETCH) begin
            if (instr_len != 0 && (cur_op == OP_EMITDECISION || cur_op == OP_EMITBALANCE)) begin
                emits = emits + 1;
                if (instr_len != 4)
                    emits_not_4 = emits_not_4 + 1;
            end
            instr_len = 1;
        end else begin
            instr_len = instr_len + 1;
        end
    end

    // independent 8N1 decoder on UART_TXD
    integer   tx_n, tx_frame_errs, kt;
    reg [7:0] tx_bytes [0:127];
    reg [7:0] tx_shift;
    always begin
        @(negedge txd);
        #(BIT_NS / 2.0);
        if (txd === 1'b0) begin
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

    task uart_send;
        input [7:0] b;
        integer k;
        begin
            rxd = 1'b0;
            #(BIT_NS);
            for (k = 0; k < 8; k = k + 1) begin
                rxd = b[k];
                #(BIT_NS);
            end
            rxd = 1'b1;
            #(BIT_NS);
        end
    endtask

    task uart_send_word;
        input [31:0] w;
        begin
            uart_send(w[7:0]);
            uart_send(w[15:8]);
            uart_send(w[23:16]);
            uart_send(w[31:24]);
        end
    endtask

    task wait_tx;
        input integer n;
        integer guard;
        begin
            guard = 0;
            while (tx_n < n && guard < 1000000) begin
                @(negedge clk);
                guard = guard + 1;
            end
            if (tx_n < n) begin
                $display("FAIL: timed out waiting for %0d TX bytes (have %0d)", n, tx_n);
                errors = errors + 1;
            end
        end
    endtask

    reg [7:0] exp_tx [0:127];
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

    task exp_balance;
        input [31:0] value;
        begin
            exp_tx[exp_n]     = 8'h04;
            exp_tx[exp_n + 1] = value[7:0];
            exp_tx[exp_n + 2] = value[15:8];
            exp_tx[exp_n + 3] = value[23:16];
            exp_tx[exp_n + 4] = value[31:24];
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

    // ---------------- test sequence ----------------

    initial begin
        errors            = 0;
        clk               = 0;
        rxd               = 1'b1;
        rst_n             = 0;
        tx_n              = 0;
        exp_n             = 0;
        tx_frame_errs     = 0;
        emit_stall_cycles = 0;
        instr_len         = 0;
        emits             = 0;
        emits_not_4       = 0;

        // like the FPGA's power-up BRAM: all zero = NOPs
        for (i = 0; i < 512; i = i + 1)
            dut.u_control_unit.prog_mem[i] = 32'd0;

        @(negedge clk);
        @(negedge clk);
        rst_n = 1;
        repeat (20) @(negedge clk);

        // ---------------- Test 1 ----------------
        uart_send(8'h01); uart_send(8'h48); uart_send(8'h00);
        uart_send_word(32'h49000000); uart_send_word(32'h00002710);
        uart_send_word(32'h4A000000); uart_send_word(32'h00000064);
        uart_send_word(32'h1B280000);
        uart_send_word(32'hC0600000);
        uart_send_word(32'h74000000);
        uart_send_word(32'hC8400840);
        uart_send_word(32'hD0800000);
        uart_send_word(32'h4D000000); uart_send_word(32'h00003A98);
        uart_send_word(32'h1EA80000);
        uart_send_word(32'h90C00000);
        uart_send_word(32'h77000000);
        uart_send_word(32'hD0E00000);
        uart_send_word(32'hC8401000);
        uart_send_word(32'h50000000); uart_send_word(32'h00000010);

        exp_decision(8'd1, 8'd1, 16'd100);
        exp_balance(32'd1000000);
        exp_balance(-32'sd500000);
        exp_decision(8'd2, 8'd0, 16'd100);
        wait_tx(20);
        repeat (100) @(negedge clk);

        check_tx_bytes("T1: 4 messages, bytes 0-19 mismatches", 0, 20);
        check_true("T1: order = decision, +bal, -bal, decision",
                   tx_bytes[0] === 8'h03 && tx_bytes[5] === 8'h04 &&
                   tx_bytes[10] === 8'h04 && tx_bytes[15] === 8'h03);
        check_true("T1: -500000 sent as E0 5E F8 FF",
                   tx_bytes[11] === 8'hE0 && tx_bytes[12] === 8'h5E &&
                   tx_bytes[13] === 8'hF8 && tx_bytes[14] === 8'hFF);
        check32("T1: R4 = GETBALANCE after seed", dut.u_register_file.registers[4], 32'sd1000000);
        check32("T1: R7 = GETBALANCE after buy",  dut.u_register_file.registers[7], -32'sd500000);
        check32("T1: BALANCE register",           dut.u_balance_reg.balance, -32'sd500000);
        check32("T1: EMITs executed",             emits, 4);
        check32("T1: EMITs not 4 cycles",         emits_not_4, 0);
        check32("T1: queue-full stall cycles",    emit_stall_cycles, 0);
        check32("T1: no extra TX bytes",          tx_n, 20);

        // ---------------- Test 2 ----------------
        uart_send(8'h01); uart_send(8'h3C); uart_send(8'h00);
        uart_send_word(32'h49000000); uart_send_word(32'h00000001);
        uart_send_word(32'h4B000000); uart_send_word(32'h00000001);
        uart_send_word(32'h4E000000); uart_send_word(32'h00000007);
        uart_send_word(32'hC8200040);
        uart_send_word(32'h12040000);
        uart_send_word(32'hD0400000);
        uart_send_word(32'h092C0000);
        uart_send_word(32'h35380000);
        uart_send_word(32'h58A00000); uart_send_word(32'h00000006);
        uart_send_word(32'h50000000); uart_send_word(32'h0000000D);

        for (i = 1; i <= 6; i = i + 1) begin
            exp_decision(8'd0, 8'd1, i);
            exp_balance(-i);
        end
        wait_tx(80);
        repeat (100) @(negedge clk);

        check_tx_bytes("T2: 12 alternating msgs, bytes 20-79 mismatches", 20, 80);
        check_true("T2: first balance -1 = 04 FF FF FF FF",
                   tx_bytes[25] === 8'h04 && tx_bytes[26] === 8'hFF &&
                   tx_bytes[27] === 8'hFF && tx_bytes[28] === 8'hFF &&
                   tx_bytes[29] === 8'hFF);
        check_true("T2: queue filled, EMITs stalled", emit_stall_cycles > 0);
        $display("      (stall cycles: %0d)", emit_stall_cycles);
        check32("T2: R1 = 7 (loop finished)", dut.u_register_file.registers[1], 7);
        check32("T2: no extra TX bytes",      tx_n, 80);
        check32("TX framing errors",          tx_frame_errs, 0);
        check_true("no protocol error",       dut.dbg_proto_error === 1'b0);

        if (errors == 0)
            $display("tb_stage6_emit_balance: ALL TESTS PASSED -- EMITBALANCE / EMIT_BALANCE correct");
        else
            $display("tb_stage6_emit_balance: %0d TEST(S) FAILED", errors);

        $finish;
    end

endmodule
