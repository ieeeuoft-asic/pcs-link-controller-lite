# Shared constants, copied from base.sdc
set_max_fanout $::env(MAX_FANOUT_CONSTRAINT) [ current_design ]
set cap_load [ expr $::env(OUTPUT_CAP_LOAD) / 1000.0 ] ;# fF -> pF

# Remove clock nets from the standard input list so they aren't treated as data
set idx [ lsearch [ all_inputs ] "clk" ]
set all_inputs_wo_clk [ lreplace [ all_inputs ] $idx $idx ]
set idx [ lsearch $all_inputs_wo_clk "ui_in\[0\]" ]
set all_inputs_wo_clk [ lreplace $all_inputs_wo_clk $idx $idx ]

# -------------------------------------------------------------------------
# 1. Main Link Clock (clk) - 66 MHz (15.15 ns)
# -------------------------------------------------------------------------
set clk_link_period 15.15
set clk_link_delay [ expr $clk_link_period * $::env(IO_PCT) ]

create_clock [ get_ports "clk" ] -name clk_link -period $clk_link_period
set_input_delay $clk_link_delay -clock [ get_clocks clk_link ] $all_inputs_wo_clk
set_output_delay $clk_link_delay -clock [ get_clocks clk_link ] [ all_outputs ]
set_clock_uncertainty $::env(SYNTH_CLOCK_UNCERTAINTY) [ get_clocks clk_link ]
set_clock_transition $::env(SYNTH_CLOCK_TRANSITION) [ get_clocks clk_link ]

# -------------------------------------------------------------------------
# 2. System Clock (ui_in) - 10 MHz (100.00 ns)
# -------------------------------------------------------------------------
set clk_sys_period 100.00
set clk_sys_delay [ expr $clk_sys_period * $::env(IO_PCT) ]

create_clock [ get_ports "ui_in\[0\]" ] -name clk_sys -period $clk_sys_period

# Note the -add_delay flag. Without this, it overwrites the 66MHz constraints
set_input_delay $clk_sys_delay -clock [ get_clocks clk_sys ] -add_delay $all_inputs_wo_clk
set_output_delay $clk_sys_delay -clock [ get_clocks clk_sys ] -add_delay [ all_outputs ]
set_clock_uncertainty $::env(SYNTH_CLOCK_UNCERTAINTY) [ get_clocks clk_sys ]
set_clock_transition $::env(SYNTH_CLOCK_TRANSITION) [ get_clocks clk_sys ]

# -------------------------------------------------------------------------
# 3. Asynchronous Crossing Definition
# -------------------------------------------------------------------------
set_clock_groups -asynchronous -group { clk_link } -group { clk_sys }

# Miscellanea (Required for OpenLane to synthesize standard cells correctly)
set_driving_cell -lib_cell $::env(SYNTH_DRIVING_CELL) -pin $::env(SYNTH_DRIVING_CELL_PIN) $all_inputs_wo_clk
set_load $cap_load [ all_outputs ]
set_timing_derate -early [ expr {1-$::env(SYNTH_TIMING_DERATE)} ]
set_timing_derate -late [ expr {1+$::env(SYNTH_TIMING_DERATE)} ]