"""Tests for world_state rendering into a prompt block."""
from metahuman_actor.game_driven.world_state import render_world_state


def test_empty_dict_renders_empty_string():
    assert render_world_state({}) == ""


def test_none_renders_empty_string():
    assert render_world_state(None) == ""


def test_single_scalar():
    assert render_world_state({"time_of_day": "night"}) == "time_of_day: night"


def test_multiple_scalars_one_per_line_insertion_order():
    out = render_world_state({"time_of_day": "night", "reputation": "hostile"})
    assert out == "time_of_day: night\nreputation: hostile"


def test_bool_and_number_values():
    out = render_world_state({"armed": True, "gold": 5})
    assert out == "armed: True\ngold: 5"


def test_list_value_is_comma_joined():
    out = render_world_state({"recent_actions": ["stole gold", "killed guard"]})
    assert out == "recent_actions: stole gold, killed guard"
