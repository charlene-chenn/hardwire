import os
import anthropic
from dotenv import load_dotenv
from backend.schemas.agent_schemas import SpecGeneratorOutput

load_dotenv()

class SpecGeneratorAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-6"

    async def generate_spec(self, user_prompt: str) -> SpecGeneratorOutput:
        """
        Interprets the design from the user prompt and generates a spec summary,
        parts required, and evaluates viability.
        """
        system_prompt = (
            "You are an expert electronics engineer and system designer. "
            "Interpret the user's design goal and evaluate viability based on their description. "
            "Be precise and technical."
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
            tools=[
                {
                    "name": "output_spec",
                    "description": "Output the generated specification, required parts, and viability evaluation.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "design_spec_summary": {"type": "string", "description": "A concise summary of the intended design."},
                            "parts_required": {"type": "array", "items": {"type": "string"}, "description": "List of parts needed for the design."},
                            "viable": {"type": "boolean", "description": "Whether the design is viable with the current parts."},
                            "reasoning": {"type": "string", "description": "Detailed reasoning for the spec and viability."}
                        },
                        "required": ["design_spec_summary", "parts_required", "viable", "reasoning"]
                    }
                }
            ],
            tool_choice={"type": "tool", "name": "output_spec"}
        )

        # Extract the tool use from the response
        tool_use = next(block for block in response.content if block.type == "tool_use")
        data = tool_use.input

        return SpecGeneratorOutput(**data)
