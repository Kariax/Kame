import dataclasses
import json
import math

import pytest

from kame.engine import combat
from kame.engine.combat import Combatant
from kame.engine.dungeon import (
    BossMove,
    _spawn_stage,
    _target_count,
    auto_action,
    describe_intents,
    estimate_dps,
    living,
    make_hero,
    new_state,
    resolve_round,
    roll_intents,
    simulate_auto,
    state_from_dict,
    state_to_dict,
    validate_action,
)
from kame.engine.skills import SkillDef


@pytest.fixture
def D(content):
    return content.dungeons["cripta_del_rey_hueco"]


@pytest.fixture
def defs(content):
    return content.dungeon_enemies


def combatant(power=80.0, hp=400, defense=20.0, **kw):
    base = dict(name="x", max_hp=hp, power=power, damage_type="physical", defense=defense, resistance=defense)
    base.update(kw)
    return Combatant(**base)


def party(D, n, **kw):
    return [make_hero(f"h{i}", f"Heroe{i}", combatant(**kw), D.hero_rating_cap) for i in range(n)]


def state(D, defs, n=3, seed=1, **kw):
    return new_state(D, party(D, n, **kw), defs, seed)


def S(skill_id="s", **kw):
    base = dict(id=skill_id, name=skill_id, description="", class_id="guerrero", ultimate=False,
                cooldown=3, unlock_level=1, multiplier=1.0)
    base.update(kw)
    return SkillDef(**base)


@pytest.fixture
def no_variance(monkeypatch):
    monkeypatch.setattr(combat, "DAMAGE_VARIANCE", 0.0)


# ---------- escalado ----------

def test_enemy_count_grows_with_party_but_hp_per_enemy_does_not(D, defs):
    counts, hps = [], []
    for n in (2, 3, 4, 6):
        st = state(D, defs, n)
        counts.append(len(st.enemies))
        hps.append({round(e.c.max_hp, -1) for e in st.enemies if not e.c.is_elite})
    assert counts == sorted(counts) and counts[-1] > counts[0]
    assert all(hps[0] == h for h in hps)  # la vida de cada enemigo no depende del nº de jugadores


def test_boss_hp_scales_with_party_damage_and_boss_hits_more_targets(D, defs):
    hp = {}
    for n in (2, 3, 4, 6):
        st = state(D, defs, n)
        _spawn_stage(st, D, defs, 2)
        hp[n] = st.enemies[0].c.max_hp
    assert hp[2] < hp[3] < hp[4] < hp[6]
    for kind in ("attack", "heavy"):
        move = BossMove("m", kind, 0.2)
        targets = [_target_count(move, n) for n in (2, 3, 4, 5, 6)]
        assert targets == sorted(targets) and targets[-1] > targets[0]


def test_enemy_damage_follows_party_health_not_a_fixed_number(D, defs):
    free = dataclasses.replace(D, hero_rating_cap=1e9, hero_rating_floor=0.0)  # sin tope ni mínimo
    weak = new_state(free, party(free, 3, hp=200), defs, 1)
    sturdy = new_state(free, party(free, 3, hp=400), defs, 1)
    assert sturdy.enemies[0].c.power == pytest.approx(weak.enemies[0].c.power * 2, rel=0.01)


def test_rating_cap_limits_very_strong_heroes(D, defs):
    giant = make_hero("g", "Gigante", combatant(power=500, hp=3000, defense=300), D.hero_rating_cap)
    normal = make_hero("n", "Normal", combatant(power=80, hp=400), D.hero_rating_cap)
    rating = lambda u: math.sqrt(u.c.power * u.c.max_hp)
    assert rating(giant) == pytest.approx(D.hero_rating_cap, rel=0.01)
    assert rating(normal) == pytest.approx(math.sqrt(80 * 400), rel=0.01)  # el normal no se toca
    # los enemigos se generan con el héroe ya recortado, no con sus números reales
    with_giant = new_state(D, [giant, normal], defs, 1)
    capped_pair = new_state(D, [make_hero("a", "A", combatant(power=500, hp=3000, defense=300), D.hero_rating_cap),
                                make_hero("b", "B", combatant(power=80, hp=400), D.hero_rating_cap)], defs, 1)
    assert with_giant.scale == capped_pair.scale
    assert with_giant.scale["H"] < 2000


def test_estimate_dps_is_stable_and_rewards_better_kits():
    base = combatant(power=80)
    assert estimate_dps(base) == estimate_dps(base)
    kit = dataclasses.replace(base, skills=(S(multiplier=3.0, cooldown=1),))
    assert estimate_dps(kit) > estimate_dps(base)


# ---------- serialización y determinismo ----------

def test_state_survives_json_roundtrip_and_continues_identically(D, defs, content):
    st = state(D, defs, 3)
    for _ in range(3):
        resolve_round(st, D, defs, {h.uid: ("attack", 1) for h in living(st.heroes)})
    restored = state_from_dict(json.loads(json.dumps(state_to_dict(st))), content.skills)
    assert state_to_dict(restored) == state_to_dict(st)
    acts = {h.uid: ("attack", 1) for h in living(st.heroes)}
    r1 = resolve_round(st, D, defs, acts)
    r2 = resolve_round(restored, D, defs, acts)
    assert r1.events == r2.events and state_to_dict(st) == state_to_dict(restored)


def test_same_seed_same_fight_and_different_seed_differs(D, defs):
    def play(seed):
        st = state(D, defs, 3, seed=seed)
        log = []
        for _ in range(4):
            log += resolve_round(st, D, defs, {h.uid: ("attack", 1) for h in living(st.heroes)}).events
        return log

    assert play(5) == play(5)
    assert play(5) != play(6)


# ---------- acciones ----------

def test_validate_action_rules(D, defs):
    st = state(D, defs, 3)
    hero = st.heroes[0]
    assert validate_action(st, hero, "volar", None)
    assert validate_action(st, hero, "attack", 99)
    assert validate_action(st, hero, "attack", 1) is None
    assert validate_action(st, hero, "skill1", None)              # sin habilidades equipadas
    assert validate_action(st, hero, "ultimate", None)            # sin definitiva
    assert validate_action(st, hero, "protect", None)
    assert validate_action(st, hero, "protect", 1)                # a sí mismo
    assert validate_action(st, hero, "protect", 99)
    assert validate_action(st, hero, "protect", 2) is None
    st.heroes[1].hp = 0
    assert validate_action(st, hero, "protect", 2)                # aliado caído
    st.heroes[0].hp = 0
    assert validate_action(st, st.heroes[0], "attack", 1)         # el caído no actúa


def test_cooldowns_block_actions_until_ready(D, defs, content):
    kit = dataclasses.replace(combatant(), skills=(S(multiplier=2.0, cooldown=3),))
    st = new_state(D, [make_hero("h0", "A", kit, 1e9), make_hero("h1", "B", combatant(), 1e9)], defs, 1)
    assert validate_action(st, st.heroes[0], "skill1", 1) is None
    resolve_round(st, D, defs, {"h0": ("skill1", 1), "h1": ("defend", None)})
    assert "estará lista" in validate_action(st, st.heroes[0], "skill1", 1)


def test_defend_halves_the_damage(D, defs, no_variance):
    def damage(action):
        st = state(D, defs, 3)
        st.enemies = st.enemies[:1]
        st.intents = [{"unit": st.enemies[0].uid, "kind": "attack", "mult": 1.0,
                       "targets": ["h0"], "name": "x"}]
        resolve_round(st, D, defs, {"h0": (action, None if action == "defend" else 1),
                                    "h1": ("defend", None), "h2": ("defend", None)})
        return st.heroes[0].c.max_hp - st.heroes[0].hp

    assert damage("defend") * 2 == pytest.approx(damage("attack"), abs=1)


def test_protect_redirects_a_hit_with_a_small_discount(D, defs, no_variance):
    st = state(D, defs, 3)
    st.enemies = st.enemies[:1]
    st.intents = [{"unit": st.enemies[0].uid, "kind": "heavy", "mult": 1.8, "targets": ["h0"], "name": "x"}]
    base = state(D, defs, 3)
    base.enemies, base.intents = base.enemies[:1], list(st.intents)
    resolve_round(base, D, defs, {"h0": ("attack", 1), "h1": ("attack", 1), "h2": ("attack", 1)})
    hit = base.heroes[0].c.max_hp - base.heroes[0].hp
    resolve_round(st, D, defs, {"h0": ("attack", 1), "h1": ("protect", 1), "h2": ("attack", 1)})
    assert st.heroes[0].hp == st.heroes[0].c.max_hp                    # el objetivo no recibe daño
    assert st.heroes[1].c.max_hp - st.heroes[1].hp == pytest.approx(hit * 0.75, abs=1)


def test_intents_are_announced_and_name_their_targets(D, defs):
    st = state(D, defs, 3)
    lines = describe_intents(st)
    assert len(lines) == len(st.enemies) and all("Heroe" in line for line in lines)


def test_gone_and_dead_heroes_are_never_targeted(D, defs):
    st = state(D, defs, 4)
    st.heroes[0].gone = True
    st.heroes[1].hp = 0
    for round_number in range(1, 15):
        st.round = round_number
        roll_intents(st, D)
        targeted = {t for it in st.intents for t in it.get("targets", [])}
        assert targeted <= {"h2", "h3"}


# ---------- jefe: fases, coraza, estados ----------

def boss_state(D, defs, n=3, phase=1, hp_fraction=1.0):
    st = state(D, defs, n)
    _spawn_stage(st, D, defs, 2)
    st.phase = phase
    boss = st.enemies[0]
    boss.hp = round(boss.c.max_hp * hp_fraction)
    roll_intents(st, D)
    return st, boss


def test_boss_changes_phase_when_its_health_drops(D, defs):
    st, boss = boss_state(D, defs, hp_fraction=0.60)
    report = resolve_round(st, D, defs, {h.uid: ("defend", None) for h in st.heroes})
    assert st.phase == 2 and any("Nueva fase" in e for e in report.events)
    boss.hp = round(boss.c.max_hp * 0.2)
    report = resolve_round(st, D, defs, {h.uid: ("defend", None) for h in st.heroes})
    assert st.phase == 3 and any("Furia" in e for e in report.events)


def test_each_boss_phase_has_its_own_moves(D):
    boss = D.stages[-1]
    assert len(boss.phases) == 3
    kinds = [{m.kind for m in p.moves} for p in boss.phases]
    assert "bone_shield" in kinds[1] and "bone_shield" not in kinds[0] and "aoe" in kinds[2]


def test_bone_shield_unbroken_explodes_and_broken_staggers_the_boss(D, defs, no_variance):
    def play(break_shield):
        st, boss = boss_state(D, defs, phase=2)
        st.phase_round = 3  # el escudo toca en la ronda 4 de la fase
        roll_intents(st, D)
        assert any(i["kind"] == "shield" for i in st.intents)
        resolve_round(st, D, defs, {h.uid: ("defend", None) for h in st.heroes})
        assert boss.shield > 0 and st.shield_pending
        assert any(i["kind"] == "burst" for i in st.intents) and "estallará" in " ".join(describe_intents(st))
        for h in st.heroes:
            h.hp = h.c.max_hp
        if break_shield:
            boss.shield = 1  # casi rota: cualquier golpe la termina
        before = [h.hp for h in st.heroes]
        report = resolve_round(st, D, defs, {h.uid: ("attack", 1) for h in st.heroes})
        return before, [h.hp for h in st.heroes], report

    before, after, report = play(break_shield=True)
    assert after == before and any("se ha roto" in e for e in report.events)
    before, after, report = play(break_shield=False)
    assert all(a < b for a, b in zip(after, before)) and any("estalla" in e for e in report.events)


def test_shield_absorbs_damage_before_health(D, defs, no_variance):
    st, boss = boss_state(D, defs, phase=2)
    boss.shield = 10_000
    hp = boss.hp
    resolve_round(st, D, defs, {h.uid: ("attack", 1) for h in st.heroes})
    assert boss.hp == hp and boss.shield < 10_000


def test_phase_three_hits_everyone_every_round(D, defs):
    st, boss = boss_state(D, defs, n=4, phase=3, hp_fraction=0.2)
    assert any(i["kind"] == "aoe" for i in st.intents)
    before = [h.hp for h in st.heroes]
    resolve_round(st, D, defs, {h.uid: ("attack", 1) for h in st.heroes})
    assert all(h.hp < b for h, b in zip(st.heroes, before))


def test_bosses_and_elites_resist_chained_stuns(D, defs, no_variance):
    stunner = S("stun", stun_turns=1, cooldown=1)
    heroes = [make_hero("h0", "A", dataclasses.replace(combatant(), skills=(stunner,)), 1e9),
              make_hero("h1", "B", combatant(), 1e9)]
    st = new_state(D, heroes, defs, 1)
    _spawn_stage(st, D, defs, 2)
    boss = st.enemies[0]
    roll_intents(st, D)
    resolve_round(st, D, defs, {"h0": ("skill1", 1), "h1": ("defend", None)})
    assert boss.stun_immunity > 0
    resolve_round(st, D, defs, {"h0": ("skill1", 1), "h1": ("defend", None)})
    report = resolve_round(st, D, defs, {"h0": ("skill1", 1), "h1": ("defend", None)})
    assert boss.stun == 0 and any("resiste" in e for e in report.events)


# ---------- salas, derrota, victoria ----------

def test_clearing_a_room_heals_revives_and_advances(D, defs):
    st = state(D, defs, 3)
    st.heroes[2].hp = 0
    st.heroes[0].hp = 10
    st.enemies = st.enemies[:2]
    for e in st.enemies:
        e.hp = 1
    report = resolve_round(st, D, defs, {h.uid: ("attack", 1) for h in living(st.heroes)})
    assert st.stage == 1 and 0 in report.cleared_stages and report.outcome is None
    assert st.heroes[2].hp == round(st.heroes[2].c.max_hp * D.revive_hp)
    assert st.heroes[0].hp >= 10 + round(st.heroes[0].c.max_hp * D.stage_heal) - 1
    assert len(st.enemies) > 0 and all(e.hp == e.c.max_hp for e in st.enemies)


def test_killing_the_boss_wins_the_dungeon(D, defs):
    st, boss = boss_state(D, defs, phase=3, hp_fraction=0.01)
    boss.hp = 1
    report = resolve_round(st, D, defs, {h.uid: ("attack", 1) for h in st.heroes})
    assert report.outcome == "win" and 2 in report.cleared_stages


def test_wiping_the_party_loses(D, defs):
    st = state(D, defs, 3, hp=1, defense=0.0)
    st.intents = [{"unit": e.uid, "kind": "attack", "mult": 1.0, "targets": [h.uid], "name": "x"}
                  for e, h in zip(st.enemies, st.heroes)]
    report = resolve_round(st, D, defs, {h.uid: ("defend", None) for h in st.heroes})
    assert report.outcome == "loss"


def test_exhaustion_ends_the_dungeon(D, defs):
    short = dataclasses.replace(D, max_rounds=3)
    st = new_state(short, party(short, 3, power=1.0, hp=100_000, defense=10_000.0), defs, 1)
    outcomes = []
    for _ in range(5):
        outcomes.append(resolve_round(st, short, defs, {h.uid: ("defend", None) for h in st.heroes}).outcome)
        if outcomes[-1]:
            break
    assert outcomes[-1] == "loss"


# ---------- IA automática ----------

def test_auto_action_defends_against_a_deadly_telegraphed_hit(D, defs):
    st = state(D, defs, 3)
    st.enemies = st.enemies[:1]
    st.intents = [{"unit": st.enemies[0].uid, "kind": "heavy", "mult": 50.0, "targets": ["h0"], "name": "x"}]
    assert auto_action(st, st.heroes[0]) == ("defend", None)
    st.intents = [{"unit": st.enemies[0].uid, "kind": "heavy", "mult": 0.01, "targets": ["h0"], "name": "x"}]
    assert auto_action(st, st.heroes[0])[0] == "attack"


def test_sturdiest_healthy_hero_protects_a_threatened_ally(D, defs):
    heroes = [make_hero("tank", "Tanque", combatant(hp=900, defense=60.0, power=50.0), 1e9),
              make_hero("mage", "Mago", combatant(hp=150, defense=5.0), 1e9)]
    st = new_state(D, heroes, defs, 1)
    st.enemies = st.enemies[:1]
    st.intents = [{"unit": st.enemies[0].uid, "kind": "heavy", "mult": 5.0, "targets": ["mage"], "name": "x"}]
    assert auto_action(st, st.heroes[0]) == ("protect", 2)
    assert auto_action(st, st.heroes[1]) == ("defend", None)


# ---------- simulaciones completas con contenido real ----------

def test_dungeon_terminates_for_every_party_size_and_mix(content, D, defs):
    from kame.engine.build import build_combatant
    from kame.engine.simulation import TEAM_LOADOUT, standard_build

    mixes = {
        2: ["guerrero", "mago"], 3: ["guerrero", "mago", "picaro"], 4: ["mago", "mago", "picaro", "picaro"],
        5: ["guerrero", "guerrero", "mago", "picaro", "picaro"], 6: ["guerrero"] * 3 + ["mago", "picaro", "picaro"],
    }
    for n, classes in mixes.items():
        heroes = [make_hero(f"h{i}", f"{c}{i}", build_combatant(standard_build(content, c, 8, True,
                  loadout=TEAM_LOADOUT[c])), D.hero_rating_cap) for i, c in enumerate(classes)]
        outcome, rounds, cleared = simulate_auto(D, heroes, defs, seed=n)
        assert outcome in ("win", "loss") and 3 <= rounds <= D.max_rounds + 1


def _win_rate(content, D, classes, levels=None, absent=(), runs=60, defs=None):
    from kame.engine.build import build_combatant
    from kame.engine.simulation import TEAM_LOADOUT, standard_build

    defs = defs or content.dungeon_enemies
    wins = 0
    for seed in range(runs):
        heroes = [make_hero(f"h{i}", f"{c}{i}", build_combatant(standard_build(
            content, c, (levels or [8] * len(classes))[i], True, loadout=TEAM_LOADOUT[c])), D.hero_rating_cap)
            for i, c in enumerate(classes)]
        outcome, _, _ = simulate_auto(D, heroes, defs, seed=seed, absent={f"h{i}" for i in absent})
        wins += outcome == "win"
    return wins / runs


@pytest.mark.parametrize("classes", [
    ["guerrero", "mago"], ["guerrero", "picaro"], ["mago", "picaro"],
    ["guerrero", "mago", "picaro"], ["guerrero", "guerrero", "mago", "picaro"],
    ["mago", "mago", "picaro", "picaro"],
])
def test_parties_of_two_to_four_can_win_without_any_required_class(content, D, classes):
    assert _win_rate(content, D, classes) >= 0.4


def test_difficulty_is_similar_for_two_three_and_four_players(content, D):
    two = _win_rate(content, D, ["guerrero", "picaro"])
    three = _win_rate(content, D, ["guerrero", "mago", "picaro"])
    four = _win_rate(content, D, ["guerrero", "guerrero", "mago", "picaro"])
    assert max(two, three, four) - min(two, three, four) <= 0.35


def test_preparation_matters_underleveled_groups_face_a_harder_dungeon(content, D):
    mix = ["guerrero", "mago", "picaro"]
    rates = {lvl: _win_rate(content, D, mix, levels=[lvl] * 3, runs=80) for lvl in (6, 7, 8, 10)}
    assert rates[6] < rates[7] < rates[8] - 0.05 or rates[7] < rates[8] - 0.05
    assert rates[6] <= 0.7 and rates[8] >= 0.8 and rates[10] >= 0.8


def test_an_absent_player_hurts_but_does_not_doom_the_group(content, D):
    full = _win_rate(content, D, ["guerrero", "mago", "picaro"])
    one_absent = _win_rate(content, D, ["guerrero", "mago", "picaro"], absent=(2,))
    assert one_absent >= full - 0.25   # los enemigos se reajustan: la ausencia pesa poco
    assert _win_rate(content, D, ["guerrero", "mago", "picaro"], absent=(0,)) >= 0.25


def test_a_far_stronger_hero_cannot_trivialize_the_dungeon_for_the_others(content, D):
    base = _win_rate(content, D, ["guerrero", "mago", "picaro"], levels=[8, 8, 8])
    carried = _win_rate(content, D, ["guerrero", "mago", "picaro"], levels=[30, 8, 8])
    assert carried <= base + 0.2


def test_rescale_after_departure_shrinks_the_fight_for_the_remaining_group(D, defs):
    from kame.engine.dungeon import rescale_after_departure

    st = state(D, defs, 4)
    count = len(st.enemies)
    st.heroes[3].gone = True
    rescale_after_departure(st, D)
    assert len(st.enemies) < count and st.scale["n"] == 3
    boss_state_ = state(D, defs, 4)
    _spawn_stage(boss_state_, D, defs, 2)
    hp = boss_state_.enemies[0].c.max_hp
    boss_state_.heroes[3].gone = True
    rescale_after_departure(boss_state_, D)
    assert boss_state_.enemies[0].c.max_hp < hp
    # sin cambios si nadie se ha ido
    other = state(D, defs, 3)
    before = state_to_dict(other)
    rescale_after_departure(other, D)
    assert state_to_dict(other) == before


def test_unprepared_groups_get_tougher_enemies_and_prepared_ones_do_not(D, defs):
    weak = new_state(D, party(D, 3, power=40.0, hp=200), defs, 1)
    ready = new_state(D, party(D, 3, power=100.0, hp=300), defs, 1)
    assert weak.scale["deficit"] > 1.0 and ready.scale["deficit"] == 1.0
