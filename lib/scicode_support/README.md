# Vendored from SciCode

`scicode/parse/parse.py`, `scicode/compare/cmp.py` and `steps/*.txt` come from
[scicode-bench/SciCode](https://github.com/scicode-bench/SciCode) at commit
`e3158ea`, under the Apache License 2.0 in `LICENSE`.

They are here because SciCode's test cases import them by name
(`from scicode.parse.parse import process_hdf5_to_tuple`,
`from scicode.compare.cmp import ...`), so the generated code is checked by
the benchmark's own comparison functions, unchanged.

Changes to `parse.py`: the Hugging Face `datasets` import and
`read_from_hf_dataset` are removed (the plugin fetches the problems itself),
and the test-data path is read from `SCICODE_H5`.

`steps/` holds the three steps the official harness never asks a model for
(13.6, 62.1, 76.3): their code is given, as `gencode.py` does.

`sitecustomize.py` is not SciCode's; it is the plugin's. Python imports it at
startup in every step script, and it puts back names newer numpy and scipy
removed (`scipy.integrate.simps`, `np.trapz`, ...), each as its documented
replacement: two SciCode problems import `simps` in their own dependency line
and could not pass on current scipy otherwise.
