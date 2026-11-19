"""Train BPE, WordPiece and Unigram tokenizers on the same corpus and compare them.

Uses the Hugging Face `tokenizers` library, so nothing is downloaded: the
tokenizers are trained locally from your own text. The report shows how many
tokens each one needs per word for each test text, which is what drives
context-window use and per-token cost.

Usage:
    python compare.py corpus.txt --vocab 8000 --text "Some English text" --text "Ein deutscher Text"
"""
from __future__ import annotations

import argparse
import unicodedata

from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, trainers

SPECIALS = ["[UNK]", "[PAD]", "[BOS]", "[EOS]"]


def build(kind: str, vocab_size: int, normalize: bool = True) -> tuple[Tokenizer, object]:
    if kind == "bpe":
        tok = Tokenizer(models.BPE(unk_token="[UNK]"))
        trainer = trainers.BpeTrainer(vocab_size=vocab_size, special_tokens=SPECIALS, min_frequency=2)
    elif kind == "wordpiece":
        tok = Tokenizer(models.WordPiece(unk_token="[UNK]"))
        trainer = trainers.WordPieceTrainer(vocab_size=vocab_size, special_tokens=SPECIALS, min_frequency=2)
    elif kind == "unigram":
        tok = Tokenizer(models.Unigram())
        trainer = trainers.UnigramTrainer(vocab_size=vocab_size, special_tokens=SPECIALS, unk_token="[UNK]")
    else:
        raise ValueError(f"unknown tokenizer kind: {kind}")
    if normalize:
        # NFKC folds visually identical forms (composed/decomposed accents,
        # full-width letters) into one, so they tokenize the same way.
        tok.normalizer = normalizers.NFKC()
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    return tok, trainer


def train_all(lines: list[str], vocab_size: int, normalize: bool = True) -> dict[str, Tokenizer]:
    out = {}
    for kind in ("bpe", "wordpiece", "unigram"):
        tok, trainer = build(kind, vocab_size, normalize)
        tok.train_from_iterator(lines, trainer=trainer)
        out[kind] = tok
    return out


def tokens_per_word(tok: Tokenizer, text: str) -> float:
    words = len(text.split())
    return len(tok.encode(text).tokens) / words if words else 0.0


def unknown_rate(tok: Tokenizer, text: str) -> float:
    toks = tok.encode(text).tokens
    return toks.count("[UNK]") / len(toks) if toks else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corpus")
    ap.add_argument("--vocab", type=int, default=8000)
    ap.add_argument("--text", action="append", required=True)
    args = ap.parse_args()
    with open(args.corpus, encoding="utf-8") as fh:
        lines = [unicodedata.normalize("NFC", l) for l in fh if l.strip()]
    toks = train_all(lines, args.vocab)
    for text in args.text:
        print(text[:60])
        for kind, tok in toks.items():
            print(f"  {kind:<10} tokens/word={tokens_per_word(tok, text):.2f} "
                  f"unknown={unknown_rate(tok, text):.1%} {tok.encode(text).tokens[:12]}")


if __name__ == "__main__":
    main()
