"""Insights page: usage figures from the query log."""

from components.insights import render_insights
from components.state import init_state

render_insights(init_state())
