from typing import Protocol

class AgentApi(Protocol):
    """The offline demo's agent. HttpAgentApi talks to the backend instead, where a conversation
    is a thread on the server: respond(conversation, message, language, progress)."""
    def respond(self, message, requirements, preferences, history): ...
