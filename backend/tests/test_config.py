"""Tests for Settings AI-related fields."""

from app.core.config import Settings


def test_rag_enabled_parses_string_flags() -> None:
    assert Settings(rag_enabled="1").rag_enabled is True
    assert Settings(rag_enabled="0").rag_enabled is False
    assert Settings(rag_enabled="true").rag_enabled is True
    assert Settings(rag_enabled="off").rag_enabled is False


def test_ai_context_log_parses_string_flags() -> None:
    assert Settings(ai_context_log="1").ai_context_log is True
    assert Settings(ai_context_log="0").ai_context_log is False


def test_ai_context_stamps_parses_string_flags() -> None:
    assert Settings(ai_context_stamps="1").ai_context_stamps is True
    assert Settings(ai_context_stamps="0").ai_context_stamps is False


def test_rag_query_rewrite_on_miss_parses_string_flags() -> None:
    assert Settings(rag_query_rewrite_on_miss="1").rag_query_rewrite_on_miss is True
    assert Settings(rag_query_rewrite_on_miss="0").rag_query_rewrite_on_miss is False


def test_rag_l0_enabled_parses_string_flags() -> None:
    assert Settings(rag_l0_enabled="1").rag_l0_enabled is True
    assert Settings(rag_l0_enabled="0").rag_l0_enabled is False


def test_rag_escalate_on_miss_parses_string_flags() -> None:
    assert Settings(rag_escalate_on_miss="1").rag_escalate_on_miss is True
    assert Settings(rag_escalate_on_miss="0").rag_escalate_on_miss is False


def test_rag_tier_b_enabled_parses_string_flags() -> None:
    assert Settings(rag_tier_b_enabled="1").rag_tier_b_enabled is True
    assert Settings(rag_tier_b_enabled="0").rag_tier_b_enabled is False
    assert Settings().rag_tier_b_enabled is False


def test_rag_mode_defaults_and_accepts_valid_values() -> None:
    assert Settings().rag_mode == "off"
    assert Settings(rag_mode="flat").rag_mode == "flat"
    assert Settings(rag_mode="agentic").rag_mode == "agentic"
    assert Settings(rag_mode="auto").rag_mode == "auto"


def test_rag_agent_max_steps_default() -> None:
    assert Settings().rag_agent_max_steps == 4


def test_rag_agent_max_vision_default() -> None:
    assert Settings().rag_agent_max_vision == 2


def test_rag_agent_planning_mode_default() -> None:
    assert Settings().rag_agent_planning_mode == "auto"


def test_rag_agent_plan_alignment_llm_parses_string_flags() -> None:
    assert Settings(rag_agent_plan_alignment_llm="1").rag_agent_plan_alignment_llm is True
    assert Settings(rag_agent_plan_alignment_llm="0").rag_agent_plan_alignment_llm is False
    assert Settings().rag_agent_plan_alignment_llm is False


def test_rag_intent_routing_enabled_parses_string_flags() -> None:
    assert Settings(rag_intent_routing_enabled="1").rag_intent_routing_enabled is True
    assert Settings(rag_intent_routing_enabled="0").rag_intent_routing_enabled is False


def test_rag_scope_bias_default() -> None:
    assert Settings().rag_scope_bias == 0.04


def test_agent_runtime_defaults() -> None:
    settings = Settings()
    assert settings.agent_runtime_engine == "langgraph"
    assert settings.rag_l2_engine == "langgraph"
    assert settings.agent_actions_enabled is False
    assert settings.agent_media_enabled is False


def test_agent_feature_flags_parse_strings() -> None:
    assert Settings(agent_actions_enabled="1").agent_actions_enabled is True
    assert Settings(agent_media_enabled="true").agent_media_enabled is True


def test_provider_keys_default_empty() -> None:
    settings = Settings()
    assert settings.openai_api_key == ""
    assert settings.deepseek_api_key == ""
