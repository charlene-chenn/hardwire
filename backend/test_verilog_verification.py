import asyncio
import os
import tempfile
from agents.electronics_agent import ElectronicsAgent

async def test_verification():
    agent = ElectronicsAgent()
    
    # 1. Correct Verilog and matching prompt (using verilog_code)
    verilog_ok = """
module simple_and(input a, input b, output y);
  assign y = a & b;
endmodule
"""
    prompt_ok = "A simple 2-input AND gate module named simple_and."
    
    print("\n>>> Testing correct Verilog and matching prompt (code)")
    result_ok = await agent.verify_verilog(prompt=prompt_ok, verilog_code=verilog_ok)
    print(f"Score: {result_ok['score']}")
    print(f"Syntactically correct: {result_ok['is_syntactically_correct']}")
    print(f"Explanation: {result_ok['explanation']}")
    
    # 2. Using default path (after creating file there)
    print("\n>>> Testing using default path (/tmp/unified_circuit.txt)")
    default_path = agent.DEFAULT_VERILOG_PATH
    with open(default_path, "w") as f:
        f.write(verilog_ok)
    
    try:
        # Note: no verilog_code or verilog_path passed here
        result_default = await agent.verify_verilog(prompt=prompt_ok)
        print(f"Score: {result_default['score']}")
        print(f"Syntactically correct: {result_default['is_syntactically_correct']}")
        print(f"Explanation: {result_default['explanation']}")
    finally:
        if os.path.exists(default_path):
            os.remove(default_path)

    # 3. Syntax error
    verilog_err = """
module bad_syntax(input a, input b, output y)
  assign y = a & b
endmodule
"""
    prompt_err = "A simple 2-input AND gate."
    
    print("\n>>> Testing Verilog with syntax error")
    result_err = await agent.verify_verilog(prompt=prompt_err, verilog_code=verilog_err)
    print(f"Score: {result_err['score']}")
    print(f"Syntactically correct: {result_err['is_syntactically_correct']}")
    print(f"Explanation: {result_err['explanation']}")

if __name__ == "__main__":
    asyncio.run(test_verification())
