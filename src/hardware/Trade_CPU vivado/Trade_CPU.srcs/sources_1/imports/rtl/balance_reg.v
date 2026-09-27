`timescale 1ns/1ps

// BALANCE: one dedicated 32-bit signed register (spec sections 1/5). Not
// register-file-addressed -- only GETBALANCE reads it, and only
// UPDATEBALANCE / SETBALANCE change it. No multiply in here; the
// host/compiler already did quantity x price.
//
// BALANCE is cash on hand.
//   SETBALANCE    (set_en):    BALANCE = value, overwriting it -- how a
//                              program seeds its starting cash
//   UPDATEBALANCE (update_en): the amount keeps the spec's "positive =
//                              buy, negative = sell" convention, so it is
//                              SUBTRACTED:
//     buy  (+amount) -> BALANCE decreases (cash spent)
//     sell (-amount) -> BALANCE increases (cash received)
// The two come from different opcodes so they never fire together; set
// wins if they somehow did. Starts at 0 on reset. Overflow wraps (plain
// 32-bit subtract).

module balance_reg (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        update_en,
    input  wire [31:0] amount,

    input  wire        set_en,
    input  wire [31:0] set_value,

    output reg  [31:0] balance
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            balance <= 32'd0;
        else if (set_en)
            balance <= set_value;
        else if (update_en)
            balance <= balance - amount;
    end

endmodule
