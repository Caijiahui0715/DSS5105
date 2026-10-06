import re
from dataclasses import replace
from domain.models import AgentResponse
from data.demo_enrichment import RELIABILITY_REPLY, MISSING_BUDGET_QUESTION, MISSING_SCOPE_QUESTION, INVALID_BUDGET_REPLY, agent_summary

class MockAgentApi:
    def __init__(self, rental_api):
        self.rental_api = rental_api

    def respond(self, message, requirements, preferences, history):
        text = message.lower()
        req, pref = replace(requirements), replace(preferences, districts=list(preferences.districts))
        if 'reliable' in text or 'trustworthy' in text:
            return AgentResponse(RELIABILITY_REPLY, req, pref, [])
        budget = re.search(r'(?:sgd\s*|\$\s*|budget(?:\s+of)?\s*|under\s*|below\s*)([\d,]+(?:\.\d+)?)', text)
        if budget:
            amount = float(budget.group(1).replace(',', ''))
            if amount <= 0:
                return AgentResponse(INVALID_BUDGET_REPLY, req, pref, [], MISSING_BUDGET_QUESTION)
            req.max_budget = amount
        if re.search(r'\b(room|shared|sharing)\b', text):
            req.rental_scope = 'room'
        if re.search(r'\b(entire|whole)\b', text):
            req.rental_scope = 'entire_unit'
        beds = re.search(r'\b(\d+|one|two|three)[ -]bedroom', text)
        if beds:
            value = beds.group(1)
            req.min_bedrooms = {'one':1,'two':2,'three':3}.get(value) or int(value)
            if not re.search(r'\b(room|shared)\b', text):
                req.rental_scope = None
        commute = re.search(r'(\d+)\s*(?:min|minutes)', text)
        if commute:
            pref.commute_minutes = max(1, int(commute.group(1)))
        if 'near nus' in text:
            pref.districts = ['D05']
        if 'furnished' in text:
            pref.furnishing = 'fully_furnished'
        districts = re.findall(r'\bd(?:0[1-9]|1[0-9]|2[0-8])\b', text)
        if districts:
            pref.districts = [code.upper() for code in districts]
        clarification = None
        if not budget and not history:
            clarification = MISSING_BUDGET_QUESTION
        if req.rental_scope is None:
            clarification = MISSING_SCOPE_QUESTION
        results = self.rental_api.recommendations(req, pref)
        reply = agent_summary(len(results))
        return AgentResponse(reply, req, pref, results, clarification)
