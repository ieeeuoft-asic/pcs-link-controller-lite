import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, with_timeout, SimTimeoutError
from cocotb.queue import Queue
import random

# Constrained-randomized full bidirectional data test
class GoldenEncoder8b10b:
    def __init__(self):
        self.rd = 0  # 0 = Negative (RD-), 1 = Positive (RD+)
        self.lut_5b6b = {
            0: ("100111", "011000", True),  1: ("011101", "100010", True),
            2: ("101101", "010010", True),  3: ("110001", "110001", False),
            4: ("110101", "001010", True),  5: ("101001", "101001", False),
            6: ("011001", "011001", False), 7: ("111000", "000111", True),
            8: ("111001", "000110", True),  9: ("100101", "100101", False),
            10:("010101", "010101", False), 11:("110100", "110100", False),
            12:("001101", "001101", False), 13:("101100", "101100", False),
            14:("011100", "011100", False), 15:("010111", "101000", True),
            16:("011011", "100100", True),  17:("100011", "100011", False),
            18:("010011", "010011", False), 19:("110010", "110010", False),
            20:("001011", "001011", False), 21:("101010", "101010", False),
            22:("011010", "011010", False), 23:("111010", "000101", True),
            24:("110011", "001100", True),  25:("100110", "100110", False),
            26:("010110", "010110", False), 27:("110110", "001001", True),
            28:("001110", "001110", False), 29:("101110", "010001", True),
            30:("011110", "100001", True),  31:("101011", "010100", True)
        }
        self.lut_3b4b = {
            0: ("1011", "0100", True),  1: ("1001", "1001", False),
            2: ("0101", "0101", False), 3: ("1100", "0011", True),
            4: ("1101", "0010", True),  5: ("1010", "1010", False),
            6: ("0110", "0110", False)
        }

    def encode(self, byte_val):
        val5 = byte_val & 0x1F
        val3 = (byte_val >> 5) & 0x07
        
        rd_minus_6b, rd_plus_6b, flips_6b = self.lut_5b6b[val5]
        str_6b = rd_minus_6b if self.rd == 0 else rd_plus_6b
        rd_mid = (1 - self.rd) if flips_6b else self.rd
        
        if val3 == 7:
            str_4b = "1110" if rd_mid == 0 else "0001"
            flips_4b = True
        else:
            rd_minus_4b, rd_plus_4b, flips_4b = self.lut_3b4b[val3]
            str_4b = rd_minus_4b if rd_mid == 0 else rd_plus_4b
            
        self.rd = (1 - rd_mid) if flips_4b else rd_mid
        
        bits_6b = [int(str_6b[5-i]) for i in range(6)]
        bits_4b = [int(str_4b[3-i]) for i in range(4)]
        
        return bits_6b + bits_4b

async def serial_tx_driver(dut, tx_queue):
    # Drive serial_in with either idle commas or queued symbols
    idle_comma = [int(b) for b in "0011111010"] # K28.5 RD-
    while True:
        symbol = idle_comma if tx_queue.empty() else tx_queue.get_nowait()
        for bit in symbol:
            dut.serial_in.value = bit  
            await RisingEdge(dut.clk)

async def tx_serial_monitor(dut, scoreboard):
    # Monitors TX output and compares against scoreboard
    comma_n = [int(b) for b in "0011111010"]
    comma_p = [int(b) for b in "1100000101"]
    
    history = []
    # 1. Sync Loop
    while True:
        await RisingEdge(dut.clk)
        try:
            history.append(int(dut.serial_out.value))
        except ValueError:
            continue
        if len(history) > 10:
            history.pop(0)
        if history in [comma_n, comma_p]:
            break
            
    dut._log.info("TX MONITOR: Aligned to ASIC's serial output stream.")

    while True:
        symbol = []
        for _ in range(10):
            await RisingEdge(dut.clk) 
            try:
                symbol.append(int(dut.serial_out.value))
            except ValueError:
                symbol.append(0)
                
        if symbol in [comma_n, comma_p]:
            continue 
            
        if not scoreboard.empty():
            expected_sym, tx_val = scoreboard.get_nowait()
            match = (symbol == expected_sym)
            if match:
                dut._log.info(f"[TX CAPTURE] Serial Out: {symbol} matches Expected 0x{tx_val:02X}")
            else:
                dut._log.error(f"[TX ERROR] Sent: 0x{tx_val:02X} | Captured: {symbol} | Expected: {expected_sym}")
            assert match, f"TX Serialization Mismatch on 0x{tx_val:02X}!"

@cocotb.test()
async def test_pcs_bidirectional(dut):
    dut._log.info("Starting PCS Lite Full Bidirectional Test")

    # Start Clocks & Background Agents
    cocotb.start_soon(Clock(dut.clk, 15.15, unit="ns").start())     
    cocotb.start_soon(Clock(dut.clk_sys, 100, unit="ns").start())   

    rx_driver_queue = Queue()
    tx_scoreboard_queue = Queue()
    
    cocotb.start_soon(serial_tx_driver(dut, rx_driver_queue))
    cocotb.start_soon(tx_serial_monitor(dut, tx_scoreboard_queue))

    tx_predictor = GoldenEncoder8b10b()
    rx_predictor = GoldenEncoder8b10b()

    # Reset Sequence
    dut._log.info("Resetting DUT...")
    dut.ena.value = 1
    dut.rst_n.value = 0
    dut.rx_req.value = 0     
    dut.tx_valid.value = 0   
    await ClockCycles(dut.clk_sys, 10)
    dut.rst_n.value = 1
    dut._log.info("Reset released.")

    # PHASE 1: TX Mode
    dut._log.info("--- Phase 1: TX Mode ---")
    num_tx_tests = 50
    
    for i in range(num_tx_tests):
        tx_val = random.randint(0, 255)
        
        expected_10b = tx_predictor.encode(tx_val)
        tx_scoreboard_queue.put_nowait((expected_10b, tx_val))
        
        dut._log.info(f"[{i+1}/{num_tx_tests}] [TX DRIVE] Queueing Parallel Data In: 0x{tx_val:02X}")
        dut.uio_in.value = tx_val
        dut.tx_valid.value = 1
        await RisingEdge(dut.clk_sys)
        dut.tx_valid.value = 0
        
        await ClockCycles(dut.clk_sys, 5) 
        
    dut._log.info(f"--- Phase 1 Passed: {num_tx_tests} Random Bytes Transmitted! ---")

    # PHASE 2: Switch to RX Mode
    dut._log.info("--- Phase 2: Transition to RX Mode ---")
    dut.tx_valid.value = 0   
    dut.rx_req.value = 1     
    
    try:
        await with_timeout(RisingEdge(dut.rx_ack), 2000, "ns") 
        dut._log.info("HANDSHAKE: RX Acknowledge received.")
    except SimTimeoutError:
        raise RuntimeError("TIMEOUT: Failed to switch to RX mode!")

    await ClockCycles(dut.clk, 20) 

    # PHASE 3: Link Training
    dut._log.info("TRAINING: Background driver is streaming Commas...")
    if int(dut.link_lock_out.value) == 1:
        dut._log.info(">>> LINK ALREADY LOCKED <<<")
    else:
        try:
            await with_timeout(RisingEdge(dut.link_lock_out), 5000, "ns") 
            dut._log.info(">>> LINK LOCK ACHIEVED <<<")
        except SimTimeoutError:
            raise RuntimeError("TIMEOUT: Link Lock failed!")

    # PHASE 4: RX Mode
    dut._log.info("--- Phase 4: RX Mode---")
    num_rx_tests = 50 
    
    for i in range(num_rx_tests):
        val5 = random.randint(0, 31)
        val3 = random.randint(0, 6)
        sent_val = (val3 << 5) | val5
        
        symbol = rx_predictor.encode(sent_val)

        dut._log.info(f"[{i+1}/{num_rx_tests}] [RX DRIVE] Streaming Serial Pattern for Expected 0x{sent_val:02X}")
        rx_driver_queue.put_nowait(symbol)
        
        try:
            await with_timeout(RisingEdge(dut.rx_valid), 15000, "ns") 
            received_val = dut.uio_out.value.to_unsigned()
            
            dut._log.info(f"[{i+1}/{num_rx_tests}] [RX CAPTURE] Parallel Data Out: 0x{received_val:02X} | Match: {received_val == sent_val}")
            assert received_val == sent_val, f"RX Mismatch: Expected 0x{sent_val:02X}, got 0x{received_val:02X}"
        except SimTimeoutError:
            raise RuntimeError(f"DEADLOCK on RX 0x{sent_val:02X}.")
        
    dut._log.info(f"--- Phase 4 Passed: {num_rx_tests} Random Bytes Decoded! ---")
    dut._log.info("--- VERIFICATION COMPLETE: ALL TESTS PASSED! ---")