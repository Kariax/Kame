"""Pruebas del servicio de clasificación."""
from kame.services import characters, ranking


def _make(conn, content, discord_id=1, name="Aldric", class_id="guerrero"):
    return characters.create_character(conn, content, discord_id, name, class_id)


def test_recompute_ranking_populates_scores(conn, content):
    c1 = _make(conn, content, 1, "Aldric")
    c2 = _make(conn, content, 2, "Mira", "mago")
    c3 = _make(conn, content, 3, "Rico", "picaro")
    # El mago sube de nivel (inteligencia -> poder mágico).
    characters.grant_xp(conn, content.config.progression, c2.id, 5000, "test")
    updated = ranking.recompute_ranking(conn, content)
    assert updated == 3
    entries = ranking.get_ranking(conn, content, limit=3)
    assert {e.name for e in entries} == {"Aldric", "Mira", "Rico"}
    assert entries[0].rank == 1
    scores = [e.score for e in entries]
    assert scores == sorted(scores, reverse=True)


def test_get_ranking_respects_limit(conn, content):
    names = ["Artha", "Brana", "Cesia", "Dario", "Elena"]
    for i, n in enumerate(names):
        _make(conn, content, i + 1, n)
    ranking.recompute_ranking(conn, content)
    entries = ranking.get_ranking(conn, content, limit=3)
    assert len(entries) == 3
    assert [e.rank for e in entries] == [1, 2, 3]


def test_ranking_empty_when_no_characters(conn, content):
    assert ranking.get_ranking(conn, content) == ()


def test_update_character_score_after_xp(conn, content):
    c = _make(conn, content)
    ranking.recompute_ranking(conn, content)
    before = ranking.get_ranking(conn, content)[0].score
    # Subir de nivel eleva la puntuación.
    characters.grant_xp(conn, content.config.progression, c.id, 10000, "test")
    ranking.update_character_score(conn, content, c.id)
    after = ranking.get_ranking(conn, content)[0].score
    assert after > before
