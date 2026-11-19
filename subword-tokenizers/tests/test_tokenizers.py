import unicodedata

import pytest

import bpe_minimal as bpe
import compare

SENNRICH = {"low": 5, "lower": 2, "newest": 6, "widest": 3}


def test_bpe_learns_the_classic_merges_in_order():
    merges = bpe.train(SENNRICH, 5)
    assert merges == [("e", "s"), ("es", "t"), ("est", "</w>"), ("l", "o"), ("lo", "w")]


def test_bpe_encodes_unseen_words_from_known_pieces():
    merges = bpe.train(SENNRICH, 10)
    assert bpe.encode_word("lowest", merges) == ["low", "est</w>"]
    assert bpe.encode("newest low", merges)[-1] == "low</w>"


def test_bpe_stops_when_no_pair_repeats():
    assert bpe.train({"ab": 1}, 10) == []


CORPUS = [
    "The quick brown fox jumps over the lazy dog.",
    "Tokenizers split text into subword units that models can embed.",
    "Prescriptions are dispensed by community pharmacies and hospital pharmacies.",
    "The pharmacist checked the prescription and dispensed the medicine.",
    "Café, naïve and résumé are common loanwords in English text.",
] * 40


@pytest.fixture(scope="module")
def trained():
    return compare.train_all(CORPUS, vocab_size=300)


def test_all_three_train_and_are_deterministic(trained):
    again = compare.train_all(CORPUS, vocab_size=300)
    text = "The pharmacist dispensed prescriptions."
    for kind, tok in trained.items():
        assert tok.encode(text).tokens == again[kind].encode(text).tokens, kind
        assert tok.get_vocab_size() <= 300


def test_in_domain_text_needs_fewer_tokens_than_out_of_domain(trained):
    for tok in trained.values():
        assert compare.tokens_per_word(tok, "the pharmacist dispensed the prescription") < \
               compare.tokens_per_word(tok, "zygomorphic xylographers quixotically juxtapose")


def test_nfkc_makes_composed_and_decomposed_text_identical(trained):
    composed = unicodedata.normalize("NFC", "Café résumé")
    decomposed = unicodedata.normalize("NFD", "Café résumé")
    assert composed != decomposed
    for tok in trained.values():
        assert tok.encode(composed).tokens == tok.encode(decomposed).tokens


def test_without_normalizer_decomposed_text_tokenizes_differently():
    raw = compare.train_all(CORPUS, vocab_size=300, normalize=False)["bpe"]
    composed = unicodedata.normalize("NFC", "résumé")
    decomposed = unicodedata.normalize("NFD", "résumé")
    assert raw.encode(composed).tokens != raw.encode(decomposed).tokens


def test_special_tokens_reserved(trained):
    for tok in trained.values():
        for i, s in enumerate(compare.SPECIALS):
            assert tok.token_to_id(s) == i


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        compare.build("sentencepiece", 100)
