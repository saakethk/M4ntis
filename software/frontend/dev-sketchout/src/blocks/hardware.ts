/**
 * Hardware limits of the FPGA target. These are placeholders until the hardware team
 * confirms the final register file / stock buffer counts.
 */
export const NUM_STOCK_BUFFERS = 8;
export const NUM_VAR_SLOTS = 8;

/** Max history window the backtester can serve (5 years of trading days). */
export const MAX_LOOKBACK_DAYS = 252 * 5;
