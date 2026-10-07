from domain.models import ApiError

class HttpAgentApi:
    def __init__(self, base_url=None):
        self.base_url = base_url

    def respond(self, message, requirements, preferences, history):
        raise ApiError('Agent API is not connected. Use the demo Agent until an endpoint and contract are agreed.')
