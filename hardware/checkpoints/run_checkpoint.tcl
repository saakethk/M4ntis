# Synthesis/implementation checkpoint for the real design (tradecpu_top),
# Vivado NON-PROJECT mode: reads rtl/*.v straight from the repo, runs
# synth -> opt -> place -> route in memory, writes reports, and never
# opens or modifies the Vivado project. No bitstream. See README.md.
#
# usage (from anywhere; run it from a scratch dir so .Xil/ lands there):
#   vivado -mode batch -nojournal -log <dir>/vivado.log \
#          -source <repo>/checkpoints/run_checkpoint.tcl [-tclargs <report_dir>]
# report_dir defaults to checkpoints/reports/.

set ckpt_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $ckpt_dir]
if {$argc > 0} {
    # vivado.bat on Windows splits a quoted argument at spaces (this repo
    # lives under ".../Trade CPU/"), so glue the pieces back together
    set report_dir [file normalize [join $argv " "]]
} else {
    set report_dir "$ckpt_dir/reports"
}
file mkdir $report_dir

set part xc7s50csga324-2
set top  tradecpu_top

# read_verilog/read_xdc take a LIST of files, so a path with a space in it
# (".../Trade CPU/...") must be wrapped or it's read as two files
foreach f [lsort [glob "$repo_dir/rtl/*.v"]] {
    read_verilog [list $f]
}
read_xdc [list "$ckpt_dir/tradecpu_top_checkpoint.xdc"]

# ---------------- synthesis ----------------
synth_design -top $top -part $part
report_utilization              -file "$report_dir/synth_utilization.rpt"
report_utilization -hierarchical -file "$report_dir/synth_utilization_hier.rpt"
set synth_cells [llength [get_cells -hierarchical -filter {IS_PRIMITIVE}]]

# ---------------- implementation ----------------
opt_design
place_design
route_design

report_timing_summary -max_paths 10 -report_unconstrained \
                      -file "$report_dir/impl_timing_summary.rpt"
report_timing -delay_type max -max_paths 10 -sort_by slack \
              -file "$report_dir/impl_worst_setup_paths.rpt"
report_timing -delay_type min -max_paths 5 -sort_by slack \
              -file "$report_dir/impl_worst_hold_paths.rpt"
check_timing          -verbose -file "$report_dir/impl_check_timing.rpt"
report_clocks                  -file "$report_dir/impl_clocks.rpt"
report_utilization             -file "$report_dir/impl_utilization.rpt"
report_utilization -hierarchical -file "$report_dir/impl_utilization_hier.rpt"
report_drc                     -file "$report_dir/impl_drc.rpt"
report_methodology             -file "$report_dir/impl_methodology.rpt"

# ---------------- one-line summary ----------------
set setup_path [lindex [get_timing_paths -delay_type max -max_paths 1] 0]
set hold_path  [lindex [get_timing_paths -delay_type min -max_paths 1] 0]
set wns [get_property SLACK $setup_path]
set whs [get_property SLACK $hold_path]
set wns_clk [get_property ENDPOINT_CLOCK $setup_path]
set wns_req [get_property REQUIREMENT $setup_path]

set fh [open "$report_dir/summary.txt" w]
puts $fh "top:                 $top ($part)"
puts $fh "primitive cells:     $synth_cells (post-synthesis)"
puts $fh "worst setup slack:   $wns ns  (clock $wns_clk, requirement $wns_req ns)"
puts $fh "worst setup path:    [get_property STARTPOINT_PIN $setup_path] -> [get_property ENDPOINT_PIN $setup_path]"
puts $fh "worst hold slack:    $whs ns"
close $fh

puts "CHECKPOINT_WNS_NS: $wns"
puts "CHECKPOINT_WHS_NS: $whs"
puts "CHECKPOINT_REPORTS: $report_dir"
