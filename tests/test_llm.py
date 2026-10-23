
import sys
from pathlib import Path

# Add the project root so Python can find the app package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.llm import generate_qa_cases


source_sections = [
    {
        "section_number": "2.1",
        "heading": "Specifications",
    },
    {
        "section_number": "4.2",
        "heading": "Error Codes",
    },
]

source_text = """
Section 2.1 - Specifications:
The pressure measurement range is 0-299 mmHg.

Section 4.2 - Error Codes:
If pressure exceeds 299 mmHg at any point, emergency deflation
must occur. If pressure exceeds 300 mmHg for more than 3 seconds
due to a sensor fault, the device must vent within 2 seconds.
"""


def main():
    try:
        result = generate_qa_cases(
            section_text=source_text,
            section_metadata=source_sections,
            count=4,
        )

        print("Model:", result["model_name"])
        print("Generated cases:", len(result["test_cases"]))

        for index, case in enumerate(result["test_cases"], start=1):
            print()
            print("Case", index)
            print("Question:", case["question"])
            print("Expected answer:", case["expected_answer"])
            print("Type:", case["test_type"])
            print("Sources:", case["source_sections"])

    except Exception as error:
        print("Generation failed:", error)


if __name__ == "__main__":
    main()
