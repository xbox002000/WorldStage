"""The producer: the one place that reads the story and then makes things happen in the world.

In The Truman Show the showrunner arranges circumstances; Truman's reactions are his own. This package is that arranger,
kept apart from `narrative/` (which only reads) so that the rule that matters can be tested: the producer changes the world
through exactly one door, the seed layer (world/seeds.py, contracts/seed.py), whose vocabulary is closed and names no action,
feeling, relationship or verdict. It never writes world.db itself, never imports `apply_event`, and never decides what a
character does. Nothing below `channel/` imports it. tests/test_layers.py enforces all of this.
"""
