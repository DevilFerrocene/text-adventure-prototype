"""苍穹回廊 · Skybound Spire — 日式异世界逐层攻略。

内容拆成包：canon（世界观+规则书）/ enemies / skills / rooms / objects / state。
register() 把它们组装进 GameWorld。引擎只认 register 这个入口，拆包对引擎透明。
"""
from .canon import SPIRE_CANON, RULEBOOK
from .enemies import ENEMIES
from .skills import SKILLS
from . import rooms, objects
from .state import build_initial_state


def register(world):
    world.set_world_canon(SPIRE_CANON)
    world.register_enemies(ENEMIES)
    world.register_skills(SKILLS)
    world.rulebook = RULEBOOK
    rooms.add_all(world)
    objects.add_all(world)
    world.initial_state = build_initial_state()
