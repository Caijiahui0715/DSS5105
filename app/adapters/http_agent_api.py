"""The agent backend's replies, in the app's domain objects."""
from adapters.backend_client import BackendError
from domain.criteria import from_backend
from domain.models import AgentResponse, ConstraintEvaluation, Recommendation

STATUS = {'match': 'pass', 'needs_confirmation': 'needs_confirmation'}


class HttpAgentApi:
    def __init__(self, client):
        self.client = client

    def respond(self, conversation, message, language, progress=lambda text: None):
        """One turn in a conversation; creates it on the backend at its first message.
        progress(text) is called with each progress line while the agent works."""
        if conversation.get('thread_id') is None:
            conversation['thread_id'] = self.client.new_conversation()
        reply = None
        for event, data in self.client.send(conversation['thread_id'], message, language):
            if event == 'progress':
                progress(data.get(language) or data.get('en', ''))
            elif event == 'reply':
                reply = data
            elif event == 'error':
                raise BackendError(data.get('message', ''), 500)
        if reply is None:
            raise BackendError('The reply stream ended without a reply.', 502)
        requirements, preferences = from_backend(reply.get('preferences') or {})
        found = reply.get('recommendations')
        return AgentResponse(
            reply['text'], requirements, preferences, recommendations(found), steps=reply.get('steps') or [],
            shortlist=reply.get('shortlist'), preview=bool(found and found.get('preview')),
        )


def recommendations(found):
    """The listings a search showed, in its order; None when there was no search."""
    if found is None:
        return None
    return [
        Recommendation(
            item['listing_id'], item.get('position') or rank, None, item['status'],
            ConstraintEvaluation(STATUS.get(item['status'], 'needs_confirmation'), {}),
            [], [], list(item.get('unknown_condition_labels') or []), {}, is_demo_score=False, facts=item,
        )
        for rank, item in enumerate(found.get('listings') or [], 1)
    ]
