from typing import Protocol

class AgentApi(Protocol):
    def respond(self, message, requirements, preferences, history): ...
