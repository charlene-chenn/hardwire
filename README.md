# HARDWIRE: Multi-Agent Hardware Design Pipeline

### Solution Overview
HARDWIRE is an end-to-end autonomous platform designed to transform natural language product concepts into production-ready hardware designs. By leveraging a sophisticated multi-agent AI architecture, the system bridges the "complexity gap" between high-level creative intent and technical engineering implementation. For amateur builders and professional engineers alike, HARDWIRE eliminates the friction of manual component selection, circuit routing, firmware drafting, and enclosure design, providing a unified path from a single text prompt to a complete design package.

### Key Features
- **Intelligent Spec Generation:** Automatically translates ambiguous user requests into rigorous technical specifications and viable part lists by extracting data from real-world component datasheets.
- **Electronics & HDL Synthesis:** Features a specialized Electronics Agent that writes syntactically correct Verilog-2001 code. It integrates directly with the Yosys Open SYnthesis Suite to produce RTL gate-level schematics and netlists, ensuring the design is technically valid.
- **Automated Firmware Development:** Generates complete, compilable Arduino/C++ firmware tailored specifically to the synthesized circuit, including pin mapping, control logic, and interrupt handling.
- **Generative Mechanical Assembly:** Uses an Assembly Agent to measure 3D component models (STLs), calculate non-overlapping placements, and generate custom OpenSCAD scripts for 3D-printable housings with mounting standoffs and ventilation.
- **Verification & Coaching:** An integrated verification engine scores designs against the original prompt using LLM-based evaluation, providing syntax checks and five actionable "next steps" to guide users through iterative improvements.

### How It Works
The HARDWIRE pipeline operates through a coordinated hierarchy of agents powered by advanced models like Claude and Nemotron. 

1. **Extraction & Planning:** Upon receiving a prompt, the **Data Extraction** and **Spec Generator** agents work in parallel to identify necessary components and define the system architecture.
2. **Circuit & Logic Design:** The **Electronics Agent** fetches technical datasheets from a Supabase-backed library to inform the generation of a unified Verilog module. This code is then synthesized using Yosys to verify logic and generate a visual RTL schematic.
3. **Mechanical Synthesis:** Simultaneously, the **Assembly Agent** retrieves STL models of the selected parts. It performs geometric analysis to determine the optimal bounding box and generates an OpenSCAD assembly script that places components and wraps them in a precision-fitted enclosure.
4. **Final Packaging:** The system outputs a comprehensive result set: 3D models (housing + assembly), functional Verilog code, a gate-level schematic, and ready-to-flash firmware.

### Technology Stack
Built on a modern stack of FastAPI, React, and OpenSCAD, HARDWIRE represents a paradigm shift in generative engineering, making hardware development as agile as software.
