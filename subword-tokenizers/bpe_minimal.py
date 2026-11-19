"""Byte Pair Encoding in about 60 lines, for reading rather than production.

Training starts from characters and repeatedly merges the most frequent
adjacent pair across the corpus. Encoding replays the learned merges in the
order they were learned. Words end with "</w>" so that a suffix such as
"est</w>" is a different token from "est" inside a word, as in Sennrich et
al. (2016). Production tokenizers (GPT-2 style byte-level BPE, the Hugging
Face `tokenizers` library) work on bytes and are far faster, but follow the
same idea.
"""
from __future__ import annotations

from collections import Counter

EOW = "</w>"


def _words(corpus: dict[str, int]) -> dict[tuple[str, ...], int]:
    return {tuple(w) + (EOW,): n for w, n in corpus.items()}


def _pair_counts(vocab: dict[tuple[str, ...], int]) -> Counter:
    pairs: Counter = Counter()
    for symbols, n in vocab.items():
        for a, b in zip(symbols, symbols[1:]):
            pairs[(a, b)] += n
    return pairs


def _merge(vocab: dict[tuple[str, ...], int], pair: tuple[str, str]) -> dict[tuple[str, ...], int]:
    merged = {}
    for symbols, n in vocab.items():
        out, i = [], 0
        while i < len(symbols):
            if i + 1 < len(symbols) and (symbols[i], symbols[i + 1]) == pair:
                out.append(symbols[i] + symbols[i + 1])
                i += 2
            else:
                out.append(symbols[i])
                i += 1
        merged[tuple(out)] = merged.get(tuple(out), 0) + n
    return merged


def train(corpus: dict[str, int], num_merges: int) -> list[tuple[str, str]]:
    """Learn up to `num_merges` merges from word frequencies.

    Ties go to the alphabetically smallest pair, so training is deterministic.
    """
    vocab = _words(corpus)
    merges: list[tuple[str, str]] = []
    for _ in range(num_merges):
        pairs = _pair_counts(vocab)
        if not pairs:
            break
        best = min(pairs.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if pairs[best] < 2:
            break                       # merging a pair seen once teaches nothing
        vocab = _merge(vocab, best)
        merges.append(best)
    return merges


def encode_word(word: str, merges: list[tuple[str, str]]) -> list[str]:
    symbols = list(word) + [EOW]
    for pair in merges:
        i, out = 0, []
        while i < len(symbols):
            if i + 1 < len(symbols) and (symbols[i], symbols[i + 1]) == pair:
                out.append(symbols[i] + symbols[i + 1])
                i += 2
            else:
                out.append(symbols[i])
                i += 1
        symbols = out
    return symbols


def encode(text: str, merges: list[tuple[str, str]]) -> list[str]:
    return [tok for word in text.split() for tok in encode_word(word, merges)]
