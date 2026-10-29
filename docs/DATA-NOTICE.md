# Data and model attribution

The MIT license covers this benchmark's code. It does not replace the following data/model terms. Source URLs, archive checksums, licenses, transformations, and cache hashes are retained in each dataset manifest and the experiment provenance.

## Natural Questions

Natural Questions was created by Tom Kwiatkowski and colleagues at Google: [Natural Questions: a Benchmark for Question Answering Research](https://aclanthology.org/Q19-1026/), TACL 2019. It includes questions and content from Wikipedia contributors. This benchmark uses the [BEIR NQ distribution](https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nq.zip).

The original project states that its data is available under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/); see the [upstream notice](https://github.com/google-research-datasets/natural-questions/blob/master/nq_open/README.md). The redistributed transformed NQ subset and its derived data retain that license. Changes: deterministic query/document sampling, title/text truncation, normalized vector encoding, and simulated mutation assignments. Neither original authors nor Wikipedia contributors endorse these benchmark results.

## SciFact

SciFact was created by David Wadden and colleagues at the Allen Institute for AI and the University of Washington: [Fact or Fiction: Verifying Scientific Claims](https://arxiv.org/abs/2004.14974), EMNLP 2020. This benchmark uses the [BEIR SciFact distribution](https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip).

The [upstream license](https://github.com/allenai/scifact/blob/master/LICENSE.md) specifies [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) for claims/evidence annotations and [ODC-By 1.0](https://opendatacommons.org/licenses/by/1-0/) for the abstract corpus, sourced from [S2ORC](https://github.com/allenai/s2orc). Credit the SciFact creators, S2ORC creators, and authors of the underlying research articles. The transformed subset retains these applicable data terms. Changes: selected test claims, title/text truncation, vector encoding, and simulated mutations.

## BEIR and embeddings

Dataset formatting and retrieval judgments come from [BEIR](https://github.com/beir-cellar/beir), Nandan Thakur and colleagues, NeurIPS Datasets and Benchmarks 2021. The benchmark code does not relabel the data as MIT or claim the subset scores are full BEIR results.

Embeddings use [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), under Apache-2.0, at the pinned revision in the manifests. Model weights are downloaded from the model publisher rather than bundled in the data archive. The release includes the exact normalized vectors used for measurement and preserves the source data notices.
