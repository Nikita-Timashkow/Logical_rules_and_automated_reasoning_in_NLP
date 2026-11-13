import re

import pymorphy3

from thesaurus import categories

_morph = pymorphy3.MorphAnalyzer()

РОДА = ["муж", "жен", "ср"]
_GENDER = {"masc": ["муж"], "femn": ["жен"], "neut": ["ср"], "ms-f": ["муж", "жен"]}
_CASE = {"nomn": "им", "gent": "род", "datv": "дат", "accs": "вин", "ablt": "твор",
         "loct": "пред", "gen2": "род", "acc2": "вин", "loc2": "пред", "voct": "им"}
MIN_SCORE = 0.05          # отбрасываем совсем маловероятные разборы
OTHER_POS_SCORE = 0.2     # разбор другой части речи, чем у лучшего, нужен вероятнее 0.2
                          # («свежую» — прилагательное, а не «я свежую» от «свежевать»)


def _genders(tag):
    if tag.number == "plur":
        return ["-"]
    return _GENDER.get(tag.gender, РОДА)


def _numbers(tag, pos):
    n = "мн" if tag.number == "plur" else "ед"
    if pos == "VERB" and tag.tense == "past":
        return [n, n + ",1л", n + ",2л"]
    if tag.person in ("1per", "2per"):
        return [n + "," + tag.person[0] + "л"]
    return [n]


_TENSE = {"past": "прош", "pres": "наст", "futr": "буд"}
CONJUNCTIONS = {"а", "но", "и", "однако", "зато"}   # союзы, которые могут начать клаузу


def tokenize(sentence):
    return re.findall(r"[а-яё]+", sentence.lower())


def _clause_numbers(sentence, has_verb):
    """Номер клаузы для каждого слова (1, 2, ...).

    Граница — запятая/точка с запятой или сочинительный союз. Кусок без
    глагола («Кошка и собака спят» → «кошка») не клауза: он присоединяется
    к следующему куску с глаголом (или к предыдущему, если он последний)."""
    segment, current, pending = [], 0, False
    for token in re.findall(r"[а-яё]+|[,;:]", sentence.lower()):
        if token in ",;:":
            pending = True
            continue
        if (pending or token in CONJUNCTIONS) and segment:
            current += 1
        pending = False
        segment.append(current)
    order = sorted(set(segment))
    with_verb = [k for k in order if any(has_verb[i] for i, s in enumerate(segment) if s == k)]
    if not with_verb:
        return [1] * len(segment)
    target = {}
    for k in order:
        later = [v for v in with_verb if v >= k]
        target[k] = later[0] if later else with_verb[-1]
    number = {k: i + 1 for i, k in enumerate(with_verb)}
    return [number[target[s]] for s in segment]


def sentence_to_facts(sentence):
    """Предложение → (список имён слов, факты)."""
    words = tokenize(sentence)
    ids = [f"{w.replace('ё', 'е')}_{i + 1}" for i, w in enumerate(words)]
    facts = []
    after_prep = False     # существительное после предлога («на ковре») —
                           # не подлежащее и не дополнение: помечаем падеж «предл»
    prep = None
    names = {}             # имя → сущность: второе «Вася» — та же сущность вася_1
    has_verb, has_nominative = [], []
    for i, w in enumerate(words):
        parses = _morph.parse(w)
        best = parses[0]
        if best.tag.POS == "NOUN" and "Name" in best.tag:
            ids[i] = names.setdefault(best.normal_form, ids[i])
        wid = ids[i]
        found_noun = False
        is_prep = False
        seen = set()
        best_pos = parses[0].tag.POS
        for p in parses:
            if p.score < MIN_SCORE:
                continue
            if p.tag.POS != best_pos and p.score < OTHER_POS_SCORE:
                continue
            tag, lemma = p.tag, p.normal_form.replace("ё", "е")
            pos = tag.POS
            if pos == "PREP":
                is_prep = True
                prep = lemma
                continue
            if pos in ("NOUN", "NPRO", "ADJF"):
                case = _CASE.get(tag.case, tag.case)
                if after_prep:
                    case = "предл"
                kind = "прил" if pos == "ADJF" else "сущ"
                found_noun |= kind == "сущ"
                for g in _genders(tag):
                    for n in _numbers(tag, pos):
                        seen.add((kind, wid, lemma, g, n, case))
            elif pos == "VERB":
                trans = "перех" if "tran" in tag else "неперех"
                for g in _genders(tag):
                    for n in _numbers(tag, pos):
                        seen.add(("глаг", wid, lemma, g, n, trans))
                if tag.tense:
                    seen.add(("время", wid, _TENSE[tag.tense]))
        facts += sorted(seen)
        has_verb.append(any(f[0] == "глаг" for f in seen))
        has_nominative.append(any(f[0] == "сущ" and f[5] == "им" for f in seen))
        if found_noun and after_prep:
            facts.append(("предлог", wid, prep))
        # одушевлённость — из самого вероятного разбора существительного
        best_noun = next((p for p in parses if p.tag.POS == "NOUN" and p.tag.animacy), None)
        if best_noun is not None and found_noun:   # «по» — предлог, а не существительное
            anim = "одуш" if best_noun.tag.animacy == "anim" else "неодуш"
            facts.append(("одушевленность", wid, anim))
            lemma = best_noun.normal_form.replace("ё", "е")
            cats = set(categories(lemma, anim == "одуш"))
            if "Name" in best_noun.tag:         # имя человека: Егор, Маша
                cats.add("человек")
            facts += [("тезаурус", wid, c) for c in sorted(cats)]
        if is_prep:
            after_prep = True
        elif found_noun:
            after_prep = False
    # клаузы: какое слово к какому простому предложению относится
    clause = _clause_numbers(sentence, has_verb)
    facts += sorted({("клауза", wid, str(k)) for wid, k in zip(ids, clause)})
    for k in range(2, max(clause) + 1):
        own_subject = any(n for n, c in zip(has_nominative, clause) if c == k)
        if not own_subject:            # «Вася пришел и поел»: «поел» без подлежащего
            facts.append(("общее_подлежащее", str(k), str(k - 1)))
    facts += [("перед", a, b) for a, b in zip(ids, ids[1:])]
    unique = list(dict.fromkeys(ids))
    facts += [("разные", a, b) for a in unique for b in unique if a != b]
    return unique, facts
