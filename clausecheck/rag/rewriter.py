from clausecheck.prompts.loader import Prompt
from clausecheck.services.sessions import Turn


class Rewriter:
    def __init__(self, client, prompt: Prompt) -> None:
        self.client = client
        self.prompt = prompt

    def rewrite(self, question: str, history: list[Turn]) -> str:
        if not history:
            return question
        history_lines = []
        for turn in history:
            history_lines.append(f"User: {turn.question}")
            history_lines.append(f"Assistant: {turn.answer}")
        history_text = "\n".join(history_lines)
        filled = self.prompt.text.replace("{{history}}", history_text).replace(
            "{{question}}", question
        )
        result = self.client.complete(filled, temperature=0.0).strip()
        return result if result else question

    @classmethod
    def from_settings(cls, settings) -> "Rewriter":
        from clausecheck.llm.client import LLMClient
        from clausecheck.prompts.loader import load_prompt

        client = LLMClient.from_settings(settings)
        prompt = load_prompt("rewrite")
        return cls(client, prompt)
