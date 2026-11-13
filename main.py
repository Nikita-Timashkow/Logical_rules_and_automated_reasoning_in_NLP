import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import product

from engine import explain, forward_chain, prove
from logic import parse_query, parse_rules, show, unify
from morphology import sentence_to_facts
from rules import RULES_TEXT
from thesaurus import PROBLEM

RULES = parse_rules(RULES_TEXT)

@dataclass
class Reading:
    subjects: dict            # глагол → выбранное подлежащее
    facts: list               # факты этого прочтения
    known: list               # все выведенные факты
    why: dict                 # обоснования
    contradictions: list      # нарушенные запреты


def readings(facts):
    """Все прочтения: сначала непротиворечивые, затем отброшенные."""
    known, why, contradictions = forward_chain(RULES, facts)
    unsplit = Reading({}, facts, known, why, contradictions)
    candidates = defaultdict(set)
    for f in known:
        if f[0] == "подлежащее":
            candidates[f[1]].add(f[2])
    if not candidates:
        return [unsplit]
    verbs = sorted(candidates)
    result = []
    position = lambda word: int(word.rsplit("_", 1)[1])     # номер слова в предложении
    for choice in product(*(sorted(candidates[v], key=position) for v in verbs)):
        chosen = dict(zip(verbs, choice))
        subjects = set(chosen.values())
        drop = set()
        for verb, subject in chosen.items():
            # им. п. убираем только у слова, которое не подлежащее НИ при каком глаголе
            # (раньше убиралось и у подлежащего соседней клаузы)
            drop |= {(other, "им") for other in candidates[verb] if other not in subjects}
            drop.add((subject, "вин"))        # подлежащее не может быть и дополнением
        reading_facts = [f for f in facts if not (f[0] == "сущ" and (f[1], f[5]) in drop)]
        known, why, contradictions = forward_chain(RULES, reading_facts)
        # прочтение допустимо, только если у каждого глагола ровно выбранное подлежащее
        got = defaultdict(set)
        for f in known:
            if f[0] == "подлежащее":
                got[f[1]].add(f[2])
        if any(got[v] != {s} for v, s in chosen.items()):
            continue
        result.append(Reading(chosen, reading_facts, known, why, contradictions))
    if not result:
        return [unsplit]
    result.sort(key=lambda r: bool(r.contradictions))
    return result


def entity_facts(known, entity):
    """Только факты о выбранной сущности: где она упомянута сама, и о событиях,
    в которых она — агент (действие, пациенс, место этого события).
    Факты о других людях и их действиях сюда не попадают."""
    events = {f[1] for f in known if f[0] == "агент" and f[2] == entity}
    result = []
    for f in known:
        if f[0] in HIDDEN_FACTS:
            continue
        if entity in f[1:] or (f[0] in ("действие", "пациенс", "место") and f[1] in events):
            result.append(f)
    return result


HIDDEN_FACTS = {"разные", "перед", "клауза", "общее_подлежащее"}


def consistent(all_readings):
    """Непротиворечивые прочтения; если таких нет — все (ошибка в любом случае)."""
    good = [r for r in all_readings if not r.contradictions]
    return good or all_readings


# Анализ и вопросы
def _subject_text(r):
    return ", ".join(f"подлежащее {s} при {v}" for v, s in r.subjects.items())


def print_reading(r):
    derived = lambda name: [f for f in r.known if f[0] == name]
    print("  Выведено — синтаксис:")
    for name in ("подлежащее", "дополнение", "определение"):
        for f in derived(name):
            print(f"    {show(f)}")
    if not derived("подлежащее"):
        print("    ✗ ни одного подлежащего, согласованного со сказуемым — предложение неправильное")
    print("  Выведено — смысл:")
    for name in ("действие", "агент", "пациенс", "место", "находится", "это", "свойство"):
        items = [show(f) for f in derived(name)]
        if items:
            print("    " + ", ".join(items))
    if r.contradictions:
        print("  ✗ СМЫСЛОВАЯ ОШИБКА — нарушен запрет:")
        rule, premises = r.contradictions[0]
        print(f"    {rule.text}")
        shown = set()
        for p in premises:
            print(explain(p, r.why, "      ", shown))
    else:
        print("  ✓ противоречий со знаниями нет")


def analyze(sentence):
    print(f"\n▶ «{sentence}»")
    ids, facts = sentence_to_facts(sentence)

    print("  Факты от морфологии (варианты разбора слов):")
    for wid in ids:
        parses = sorted({f"{f[0]} {f[2]}, {f[4]}, {f[5]}" for f in facts
                         if f[0] in ("сущ", "прил", "глаг") and f[1] == wid})
        extra = [f"{f[0]}: {f[2]}" for f in facts
                 if f[0] in ("одушевленность", "тезаурус") and f[1] == wid]
        print(f"    {wid:14} " + ("; ".join(parses) if parses else "—")
              + (f"   [{', '.join(extra)}]" if extra else ""))

    all_readings = readings(facts)
    good = consistent(all_readings)
    rejected = [r for r in all_readings if r not in good]
    for r in rejected:
        rule, _ = r.contradictions[0]
        print(f"  ✂ прочтение «{_subject_text(r)}» отброшено: нарушен запрет {rule.text}")
    if all(r.contradictions for r in good):
        if len(good) > 1:
            print(f"  ✗ все прочтения ({len(good)}) противоречат знаниям, показано первое")
        good = good[:1]
    elif len(good) > 1:
        print(f"  ⚠ неоднозначность: {len(good)} непротиворечивых прочтения")
    for i, r in enumerate(good, 1):
        if len(good) > 1:
            print(f"  — Прочтение {i}: {_subject_text(r)}")
        print_reading(r)
    return good


def ask(sentence, query_text):
    print(f"\n▶ «{sentence}»   вопрос: {query_text}")
    _, facts = sentence_to_facts(sentence)
    query = parse_query(query_text)
    found = None
    for r in consistent(readings(facts)):
        answer, protocol = prove(RULES, r.facts, query)
        if answer is not None:
            found = answer
            visible = {k: v for k, v in answer.items() if not k.startswith("_")}
            print("  ✓ доказано. Ответ:", ", ".join(f"{k} = {v}" for k, v in visible.items()))
            print("  Вывод методом резолюций:")
            print("\n".join("    " + line for line in protocol.splitlines()))
            break
    if found is None:
        print("  ✗ не доказывается: пустой дизъюнкт не выводится")
    return found


def about(sentence, entity):
    print(f"\n▶ «{sentence}»   факты о {entity}:")
    _, facts = sentence_to_facts(sentence)
    for r in consistent(readings(facts)):
        items = entity_facts(r.known, entity)
        print("    " + (", ".join(show(f) for f in items) if items else "нет фактов"))


def demo():
    print("═══ 1. Унификация (алгоритм Робинсона) ═══")
    log = []
    unify(("сущ", "N", "L", "G", "Num", "им"), ("сущ", "кошка_1", "кошка", "жен", "ед", "им"),
          log=log)
    print("  сущ(N, L, G, Num, им)  и  сущ(кошка_1, кошка, жен, ед, им)")
    print("\n".join("   " + line for line in log))

    print("\n═══ 2. Прямой вывод: анализ предложений ═══")
    analyze("Черная кошка съела свежую рыбу")
    analyze("Рыбу съела кошка")              # другой порядок слов — тот же смысл
    analyze("Мама мыла раму")                # «мыла» — глагол или «мыло»?
    analyze("Кошка спят")                    # нет согласования
    analyze("Мать любит дочь")               # неоднозначность
    analyze("Тигр ест мясо")                 # смысл снимает неоднозначность (RuWordNet)
    analyze("Камень ест рыбу")               # смысловая ошибка
    analyze("Стул ест суп")                  # ошибка для слов, которых нет в правилах

    print("\n═══ 3. Объяснение вывода: почему кошка сыта? ═══")
    _, facts = sentence_to_facts("Черная кошка съела свежую рыбу")
    known, why, _ = forward_chain(RULES, facts)
    print(explain(("свойство", "кошка_2", "сытый"), why, "  "))

    print("\n═══ 4. Вопрос: метод резолюций ═══")
    ask("Черная кошка съела свежую рыбу", "это(X, животное) & агент(E, X) & действие(E, есть)")
    ask("Тигр ест мясо", "это(X, животное) & агент(E, X) & пациенс(E, Y) & это(Y, еда)")
    ask("Черная кошка съела свежую рыбу", "это(X, собака)")


if __name__ == "__main__":
    if PROBLEM:
        print(f"⚠ Внимание: {PROBLEM}.\n  Без него «тигр — животное» и т. п. известно только для слов из rules.py.")
    if len(sys.argv) == 4 and sys.argv[2] == "--about":
        about(sys.argv[1], sys.argv[3])
    elif len(sys.argv) == 2:
        analyze(sys.argv[1])
    elif len(sys.argv) == 3:
        ask(sys.argv[1], sys.argv[2])
    else:
        demo()
