# subword-tokenizers

Companion code for the dataa.dev article *Tokenization for LLM Engineers: BPE, WordPiece, Unigram and What They Cost You* (6 April 2024).

| File | What it does |
| :--- | :--- |
| `bpe_minimal.py` | Byte Pair Encoding in about 60 lines of plain Python: training from word counts and encoding with the learned merges. For reading, not production. |
| `compare.py` | Trains BPE, WordPiece and Unigram tokenizers on the same local corpus with the Hugging Face `tokenizers` library (nothing is downloaded) and reports tokens per word and the unknown-token rate for each test text. |

## Use

```bash
pip install tokenizers==0.15.2
python compare.py corpus.txt --vocab 8000 \
  --text "The pharmacist dispensed the prescription." \
  --text "Der Apotheker gab das Rezept aus."
```

Use a corpus that looks like your production text. Tokens per word is the number that moves your context-window use and your per-token bill.

## Tests

```bash
pip install tokenizers==0.15.2 pytest==8.1.1
python -m pytest -q
```

9 tests: the classic merge order from Sennrich et al. (2016) on the `low/lower/newest/widest` example, encoding unseen words, deterministic training, in-domain vs out-of-domain token counts, NFKC making composed and decomposed accents tokenize identically (and differing without it), and reserved special-token IDs. Tested with Python 3.13.
