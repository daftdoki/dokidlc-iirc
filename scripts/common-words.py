#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["wordfreq==3.1.1"]
# ///
"""scripts/common-words.py bin/iirc_words.txt: writes wordfreq's top English words, letters only, proper nouns removed, first 1,000."""
import re, sys, importlib.metadata as md
import wordfreq

# names, places, months (but "may"), days, deities, and the adjectives of nations, as wordfreq lowercases them
PROPER = set("""john york london america david england james china michael washington australia europe george india
paul california jesus canada san uk al la god
january february march april june july august september october november december friday
american english british french european chinese russian german""".split())
words = [w for w in wordfreq.top_n_list("en", 1500) if re.fullmatch(r"[a-z]+", w) and w not in PROPER][:1000]
assert len(words) == 1000
header = f"""# The 1,000 most frequent English words, lowercase, one per line. iirc never counts one as a strong term.
# Source: wordfreq {md.version('wordfreq')} by Robyn Speer, https://github.com/rspeer/wordfreq, top_n_list("en", 1500),
# keeping words of letters a to z only, with proper nouns, month names (but "may"), and nationality words removed.
# wordfreq's data is licensed CC-BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/); so is this file,
# a derived work. Its data includes SUBTLEX word lists by Marc Brysbaert et al., freely available at
# http://crr.ugent.be/programs-data/subtitle-frequencies, and Google Books Ngrams, http://books.google.com/ngrams.
"""
open(sys.argv[1], "w").write(header + "\n".join(words) + "\n")
