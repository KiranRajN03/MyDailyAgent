"""
LangGraph Multi-Agent Orchestration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
This module compiles and orchestrates the LangGraph-based multi-agent workflow
with intelligent routing between the supervisor (EM Agent) and specialist agents.

Architecture:
  User Request → EM Agent (Router/Supervisor)
                  ├── Data Analyst Agent → analytics, insights
                  ├── Jira Agent → sprint data, velocity
                  └── Automation Agent → emails, reports
"""

from __future__ import annotations

import logging
from typing import Any, Dict
from sqlalchemy.orm import Session

# LangGraph Orchestration
from langgraph.graph import END, StateGraph

from daily_agents.agents.state import AgentState
from daily_agents.agents.agents import (
    automation_agent_node,
    data_analyst_node,
    em_agent_node,
    jira_agent_node,
    transcription_agent_node,
)
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


async def run_agent_workflow(
    project_id: int,
    user_id: int,
    message: str,
    db: Session
) -> Dict[str, Any]:
    """
    Compiles the multi-agent graph dynamically and executes the workflow asynchronously.
    Dynamically binds the active DB session request into the nodes to ensure transactional isolation.
    """
    logger.info("Initializing multi-agent graph execution for project_id=%d", project_id)

    # 1. Initialize State
    initial_state = {
        "messages": [HumanMessage(content=message)],
        "user_id": user_id,
        "project_id": project_id,
        "completed_agents": [],
        "next_agent": "em_agent",
        "status": "pending",
    }

    # 2. Build StateGraph
    workflow = StateGraph(AgentState)

    # Add agent nodes (passing thread-safe db session via closure)
    workflow.add_node("em_agent", lambda state: em_agent_node(state, db))
    workflow.add_node("jira_agent", lambda state: jira_agent_node(state, db))
    workflow.add_node("data_analyst", lambda state: data_analyst_node(state, db))
    workflow.add_node("automation_agent", lambda state: automation_agent_node(state, db))
    workflow.add_node("transcription_agent", lambda state: transcription_agent_node(state, db))

    # Set Graph Entrypoint
    workflow.set_entry_point("em_agent")

    # Define Conditional Routing from EM Supervisor
    def route_from_supervisor(state: AgentState) -> str:
        next_agent = state.get("next_agent")
        if next_agent == "jira_agent":
            return "jira_agent"
        elif next_agent == "data_analyst":
            return "data_analyst"
        elif next_agent == "automation_agent":
            return "automation_agent"
        elif next_agent == "transcription_agent":
            return "transcription_agent"
        return END

    workflow.add_conditional_edges(
        "em_agent",
        route_from_supervisor,
        {
            "jira_agent": "jira_agent",
            "data_analyst": "data_analyst",
            "automation_agent": "automation_agent",
            "transcription_agent": "transcription_agent",
            END: END,
        }
    )

    # Add return edges back to supervisor
    workflow.add_edge("jira_agent", "em_agent")
    workflow.add_edge("data_analyst", "em_agent")
    workflow.add_edge("automation_agent", "em_agent")
    workflow.add_edge("transcription_agent", "em_agent")

    # 3. Compile Graph
    compiled_graph = workflow.compile()

    # 4. Invoke Graph Workflow
    logger.info("Executing LangGraph multi-agent flow...")
    final_state = await compiled_graph.ainvoke(initial_state)
    logger.info("LangGraph execution completed with status=%s", final_state.get("status"))

    return final_state
