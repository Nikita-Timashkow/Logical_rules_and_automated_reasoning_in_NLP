"""
Если пакет ruwordnet не установлен, модуль просто ничего не добавляет.
Установка:  pip install ruwordnet  и затем  ruwordnet download
"""
from collections import Counter
from functools import lru_cache

from logic import is_var, parse_rules
from rules import RULES_TEXT

CATEGORIES = {
    "ЖИВОТНОЕ": "животное",
    "ЧЕЛОВЕК": "человек",
    "ЕДА, ПИЩА": "еда",
    "ПРОДУКТЫ ПИТАНИЯ": "еда",
    "ПРОДОВОЛЬСТВИЕ": "еда",
    "НАПИТОК": "еда",
    "ПРЕДМЕТ, ВЕЩЬ": "предмет",
    "РАСТЕНИЕ": "растение",
}
LIVING = {"животное", "человек"}
CONFLICTS = [("животное", "человек"), ("предмет", "еда")]

# слова, для которых в rules.py уже есть правило вида это(X, слово) -> ...
MANUAL = {r.body[0][2] for r in parse_rules(RULES_TEXT)
          if len(r.body) == 1 and r.body[0][0] == "это" and not is_var(r.body[0][2])}

try:
    from ruwordnet import RuWordNet
    _wn = RuWordNet()
    AVAILABLE = True
    PROBLEM = ""
except ImportError:
    _wn, AVAILABLE = None, False
    PROBLEM = "RuWordNet не установлен: выполните  pip install ruwordnet  и  ruwordnet download"
except Exception:                     # пакет есть, а база не скачана
    _wn, AVAILABLE = None, False
    PROBLEM = "база RuWordNet не скачана: выполните  ruwordnet download"


def _sense_categories(synset):
    """Категории, встречающиеся в цепочке гиперонимов одного значения."""
    found, stack, seen = set(), [synset], set()
    while stack:
        s = stack.pop()
        if s.id in seen:
            continue
        seen.add(s.id)
        if s.title in CATEGORIES:
            found.add(CATEGORIES[s.title])
        stack.extend(s.hypernyms)
    if "еда" in found:                # пища — особый вид вещей, «предмет» не нужен
        found.discard("предмет")
    return found


@lru_cache(maxsize=None)
def categories(lemma, animate):
    """Категории слова. animate: True / False / None (неизвестно)."""
    if not AVAILABLE or lemma in MANUAL:
        return ()
    senses = []
    for sense in _wn.get_senses(lemma):
        if sense.synset.part_of_speech != "N":
            continue
        cats = _sense_categories(sense.synset)
        if animate is True and not cats & LIVING:
            continue
        if animate is False and cats & LIVING:
            continue
        senses.append(cats)
    votes = Counter(c for cats in senses for c in cats)
    for a, b in CONFLICTS:
        if votes[a] and votes[b]:
            if votes[a] > votes[b]:
                del votes[b]
            elif votes[b] > votes[a]:
                del votes[a]
            else:
                del votes[a], votes[b]
    return tuple(sorted(votes))
