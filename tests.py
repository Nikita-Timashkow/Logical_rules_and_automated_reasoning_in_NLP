from engine import prove
from logic import parse_atom, parse_query, unify
from main import RULES, consistent, entity_facts, readings
from morphology import sentence_to_facts
from thesaurus import AVAILABLE


def facts_of(sentence):
    """Факты первого непротиворечивого прочтения (или первого, если все с ошибкой)."""
    _, facts = sentence_to_facts(sentence)
    r = consistent(readings(facts))[0]
    return set(r.known), r.contradictions


def test_unification():
    s = unify(parse_atom("P(x1, f(Y), g(X))"), parse_atom("P(x1, f(a), g(h(Y)))"))
    assert s == {"Y": "a", "X": ("h", "a")}
    assert unify(parse_atom("P(X, f(X))"), parse_atom("P(Y, Y)")) is None   # проверка вхождения
    assert unify(parse_atom("P(a)"), parse_atom("P(b)")) is None


def test_agreement():
    known, _ = facts_of("Кошка спит")
    assert ("подлежащее", "спит_2", "кошка_1") in known
    known, _ = facts_of("Кошка спят")                       # не согласовано по числу
    assert not any(f[0] == "подлежащее" for f in known)
    known, _ = facts_of("Черный кошка спит")                # прилагательное не согласовано
    assert not any(f[0] == "определение" for f in known)


def test_homonym_and_person():
    known, _ = facts_of("Мама мыла раму")             # «мыла» — глагол, а не «мыло»
    assert ("действие", "мыла_2", "мыть") in known
    assert not any(f[0] == "это" and f[1] == "мыла_2" for f in known)
    known, _ = facts_of("Я съела рыбу")
    assert ("подлежащее", "съела_2", "я_1") in known
    known, _ = facts_of("Я ест рыбу")                 # не согласовано по лицу
    assert not any(f[0] == "подлежащее" for f in known)


def test_word_order():
    known, _ = facts_of("Рыбу съела кошка")
    assert ("агент", "съела_2", "кошка_3") in known
    assert ("пациенс", "съела_2", "рыбу_1") in known


def test_knowledge():
    known, contradictions = facts_of("Черная кошка съела свежую рыбу")
    assert ("свойство", "кошка_2", "сытый") in known
    assert ("это", "рыбу_5", "еда") in known
    assert not contradictions


def test_anomalies():
    for sentence in ["Камень ест рыбу", "Кошка лает", "Кошка читает книгу", "Стол съел девочку"]:
        _, contradictions = facts_of(sentence)
        assert contradictions, sentence


def test_animacy_from_morphology():
    # слов «стул» и «суп» нет в правилах — одушевлённость берётся из pymorphy3
    _, contradictions = facts_of("Стул ест суп")
    assert contradictions
    known, contradictions = facts_of("Кошки едят суп")
    assert ("это", "кошки_1", "одушевленный") in known and not contradictions


def test_readings_disambiguation():
    # «мясо» может быть и подлежащим, но прочтение «мясо ест тигра» противоречит знаниям
    _, facts = sentence_to_facts("Тигр ест мясо")
    good = [r for r in readings(facts) if not r.contradictions]
    assert len(good) == 1 and good[0].subjects == {"ест_2": "тигр_1"}
    # «Мать любит дочь» — оба прочтения непротиворечивы: настоящая неоднозначность
    _, facts = sentence_to_facts("Мать любит дочь")
    assert len([r for r in readings(facts) if not r.contradictions]) == 2


def test_thesaurus():
    if not AVAILABLE:
        print("  (RuWordNet не установлен — проверка пропущена)")
        return
    known, contradictions = facts_of("Тигр ест мясо")
    assert ("это", "тигр_1", "животное") in known and ("это", "мясо_3", "еда") in known
    assert not contradictions
    known, _ = facts_of("Врач читает книгу")
    assert ("это", "врач_1", "человек") in known
    known, _ = facts_of("Егор читает книгу")                # имя — человек
    assert ("это", "егор_1", "человек") in known
    _, contradictions = facts_of("Машина ест суп")          # машина — предмет
    assert contradictions


# ---------------------------------------------------------------------------
# Регрессия: несколько клауз, разные подлежащие, сытость
# ---------------------------------------------------------------------------

def good_readings(sentence):
    _, facts = sentence_to_facts(sentence)
    return [r for r in readings(facts) if not r.contradictions]


def test_case1_two_subjects_not_mixed():
    # «Вася пришел на кухню, а Артем уже ел еду» — два простых предложения
    good = good_readings("Вася пришел на кухню, а Артем уже ел еду")
    assert len(good) == 1, "должно быть одно прочтение"
    known = set(good[0].known)
    for fact in [("подлежащее", "пришел_2", "вася_1"), ("подлежащее", "ел_8", "артем_6"),
                 ("агент", "пришел_2", "вася_1"), ("агент", "ел_8", "артем_6"),
                 ("пациенс", "ел_8", "еду_9"), ("место", "пришел_2", "кухню_4"),
                 ("находится", "вася_1", "кухню_4"), ("свойство", "артем_6", "сытый")]:
        assert fact in known, fact
    for fact in [("агент", "ел_8", "вася_1"),          # Вася не ест
                 ("агент", "пришел_2", "артем_6"),     # Артем не приходил
                 ("находится", "артем_6", "кухню_4"),  # Артем не на кухне
                 ("пациенс", "ел_8", "артем_6"),       # Артема не едят
                 ("свойство", "вася_1", "сытый")]:
        assert fact not in known, fact


def test_case2_entities_are_separate():
    good = good_readings("Вася пришел на кухню, а Артем уже ел еду")
    vasya = entity_facts(good[0].known, "вася_1")
    assert ("находится", "вася_1", "кухню_4") in vasya
    assert not any("артем_6" in f or "ел_8" in f for f in vasya)      # чужих фактов нет
    people = {f[1] for f in good[0].known if f[0] == "это" and f[2] == "человек"}
    assert people == {"вася_1", "артем_6"}                              # без фантомов
    # одно имя — одна сущность: второе «Вася» — тот же вася_1
    ids, _ = sentence_to_facts("Вася пришел, и Вася поел")
    assert ids.count("вася_1") == 1 and "вася_4" not in ids
    known = set(good_readings("Вася пришел, и Вася поел")[0].known)
    assert {("агент", "пришел_2", "вася_1"), ("агент", "поел_5", "вася_1"),
            ("свойство", "вася_1", "сытый")} <= known


def test_case3_shared_subject_and_satiety():
    # «Вася пришел на кухню и поел фруктов» — «поел» наследует подлежащее
    good = good_readings("Вася пришел на кухню и поел фруктов")
    assert len(good) == 1
    known = set(good[0].known)
    for fact in [("агент", "пришел_2", "вася_1"), ("агент", "поел_6", "вася_1"),
                 ("пациенс", "поел_6", "фруктов_7"), ("находится", "вася_1", "кухню_4"),
                 ("свойство", "вася_1", "сытый")]:
        assert fact in known, fact


def test_case4_satiety_without_object():
    known = set(good_readings("Вася поел")[0].known)
    assert ("свойство", "вася_1", "сытый") in known
    # настоящее время — ещё не сыт (поведение «Кошка ест рыбу» не меняется)
    known = set(good_readings("Кошка ест рыбу")[0].known)
    assert ("свойство", "кошка_1", "сытый") not in known


def test_shared_subject_keeps_ambiguity_consistent():
    # «Мать любит дочь и спит»: у «спит» то же подлежащее, что у «любит»
    for r in good_readings("Мать любит дочь и спит"):
        subj = {f[1]: f[2] for f in r.known if f[0] == "подлежащее"}
        assert subj["любит_2"] == subj["спит_5"]


def test_resolution():
    _, facts = sentence_to_facts("Черная кошка съела свежую рыбу")
    facts = consistent(readings(facts))[0].facts
    answer, _ = prove(RULES, facts, parse_query("это(X, животное) & агент(E, X)"))
    assert answer == {"E": "съела_3", "X": "кошка_2"}
    answer, _ = prove(RULES, facts, parse_query("это(X, собака)"))
    assert answer is None


if __name__ == "__main__":
    tests = [f for name, f in list(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print("✓", t.__name__)
    print(f"Все проверки пройдены: {len(tests)}")
